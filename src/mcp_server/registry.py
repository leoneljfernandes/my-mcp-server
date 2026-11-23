"""Skill discovery, role resolution, path-traversal guards, and SQLite FTS5 BM25 indexing."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from mcp_server.models import (
    VALID_SOURCES,
    InputValidationError,
    PathTraversalError,
    RoleConfig,
    RoleNotFoundError,
    RolesFileConfig,
    RoleSummary,
    SearchHit,
    SkillNotFoundError,
    SkillSummary,
    SourceName,
    WebGuideSummary,
)

LOGGER = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 200
MAX_SEARCH_LIMIT = 25
MAX_GUIDE_IDS = 5

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "before",
        "by",
        "con",
        "de",
        "del",
        "el",
        "en",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "la",
        "las",
        "los",
        "of",
        "on",
        "or",
        "para",
        "por",
        "que",
        "the",
        "to",
        "un",
        "una",
        "with",
    }
)

DEFAULT_PRECEDENCE_RULES = (
    "### Jerarquía de Precedencia entre Fuentes\n"
    "1. **obra/superpowers (Proceso e ingeniería):** gobierna *cómo* trabajás "
    "(brainstorming, planificación, TDD, debugging sistemático, verificación antes de cerrar y code review).\n"
    "2. **my_skills (Arquitectura y decisiones de stack):** gobierna *con qué y cómo* se construye el proyecto "
    "(scaffolding, FastAPI, PostgreSQL/SQLAlchemy/Alembic, React, observabilidad y testing).\n"
    "3. **modern-web-guidance (Plataforma web moderna):** gobierna *qué APIs nativas* de HTML/CSS/JS usar en el navegador, "
    "adaptándolas al stack de `my_skills` sin degradar a patrones o librerías obsoletas."
)


@dataclass(frozen=True, slots=True)
class IndexedSkill:
    """Internal representation of an indexed Markdown skill or compiled web guide."""

    source: SourceName
    id: str
    name: str
    relative_path: str
    absolute_path: Path
    description: str
    category: str | None = None
    references: tuple[str, ...] = ()
    features_used: tuple[str, ...] = ()
    token_count: int | None = None
    content: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedRole:
    """Resolved skill entries for a single configured role."""

    name: str
    config: RoleConfig
    core: tuple[IndexedSkill, ...]
    on_demand: tuple[IndexedSkill, ...]
    missing_patterns: tuple[str, ...] = field(default_factory=tuple)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract optional YAML frontmatter from Markdown text."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_yaml = match.group(1)
    body = text[match.end() :]
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        LOGGER.warning("Ignoring malformed YAML frontmatter: %s", exc)
        return {}, body
    if not isinstance(parsed, dict):
        return {}, body
    return cast(dict[str, Any], parsed), body


def _first_heading_or_summary(body: str) -> str:
    """Fallback summary from the first non-heading paragraph when frontmatter is absent."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped[:240]
    return ""


def _extract_query_tokens(query: str) -> list[str]:
    """Extract deduplicated lowercase search tokens, filtering stopwords when content words exist."""
    raw = [tok.lower() for tok in _TOKEN_RE.findall(query)]
    if not raw:
        return []
    filtered = [tok for tok in raw if tok not in _STOPWORDS and len(tok) > 1]
    chosen = filtered if filtered else raw
    seen: set[str] = set()
    unique: list[str] = []
    for tok in chosen:
        if tok not in seen:
            seen.add(tok)
            unique.append(tok)
    return unique


def _build_fts_query(tokens: list[str]) -> str | None:
    """Build a safe FTS5 OR prefix query from sanitized tokens."""
    if not tokens:
        return None
    return " OR ".join(f'"{tok}"*' for tok in tokens)


def _token_overlap_count(query_tokens: list[str], target_text: str) -> int:
    """Count how many distinct query tokens match (by prefix) tokens in target_text."""
    if not target_text:
        return 0
    target_tokens = {tok.lower() for tok in _TOKEN_RE.findall(target_text)}
    matched = 0
    for q_tok in query_tokens:
        if any(t.startswith(q_tok) or q_tok.startswith(t) for t in target_tokens if len(t) > 2):
            matched += 1
    return matched


def _validate_search_args(query: str, limit: int) -> tuple[str, int]:
    cleaned = query.strip()
    if not cleaned:
        raise InputValidationError("query must not be empty")
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise InputValidationError(
            f"query exceeds maximum allowed length of {MAX_QUERY_LENGTH} characters"
        )
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise InputValidationError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    return cleaned, limit


class SkillRegistry:
    """Loads, validates, resolves, and indexes skills across all configured sources."""

    def __init__(self, skills_dir: Path, roles_config_path: Path) -> None:
        self._skills_dir = skills_dir.resolve()
        self._roles_config_path = roles_config_path.resolve()

        self._roles_file = self._load_roles_config()
        self._skills_by_path: dict[Path, IndexedSkill] = {}
        self._skills_by_source: dict[SourceName, list[IndexedSkill]] = {
            source: [] for source in VALID_SOURCES
        }
        self._skills_by_source_and_id: dict[tuple[SourceName, str], IndexedSkill] = {}
        self._web_guides_by_id: dict[str, IndexedSkill] = {}
        self._resolved_roles: dict[str, ResolvedRole] = {}

        self._fts_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._fts_conn.row_factory = sqlite3.Row

        self._index_all_sources()
        self._build_fts_index()
        self._resolve_all_roles()

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    @property
    def precedence_rules(self) -> str:
        rules = self._roles_file.precedence_rules.strip()
        return rules if rules else DEFAULT_PRECEDENCE_RULES

    def close(self) -> None:
        """Close the in-memory SQLite FTS5 connection."""
        self._fts_conn.close()

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------
    def _resolve_within_root(self, relative_path: str | Path, *, root: Path | None = None) -> Path:
        """Resolve a relative path and enforce strict containment inside ``root``."""
        base = (root or self._skills_dir).resolve()
        raw_str = str(relative_path)
        if "\x00" in raw_str:
            raise PathTraversalError("Null byte detected in path")

        candidate_rel = Path(raw_str)
        if candidate_rel.is_absolute() or ".." in candidate_rel.parts:
            raise PathTraversalError(f"Path traversal or absolute path blocked: {raw_str!r}")

        resolved = (base / candidate_rel).resolve()
        if not resolved.is_relative_to(base):
            raise PathTraversalError(f"Resolved path escapes allowed root: {raw_str!r}")
        return resolved

    # ------------------------------------------------------------------
    # Config & indexing
    # ------------------------------------------------------------------
    def _load_roles_config(self) -> RolesFileConfig:
        if not self._roles_config_path.is_file():
            LOGGER.warning("Roles config file not found at %s", self._roles_config_path)
            return RolesFileConfig()
        raw = yaml.safe_load(self._roles_config_path.read_text(encoding="utf-8"))
        if raw is None:
            return RolesFileConfig()
        return RolesFileConfig.model_validate(raw)

    def _register_skill(self, skill: IndexedSkill) -> None:
        if skill.absolute_path in self._skills_by_path:
            return
        self._skills_by_path[skill.absolute_path] = skill
        self._skills_by_source[skill.source].append(skill)
        key = (skill.source, skill.id)
        if key not in self._skills_by_source_and_id:
            self._skills_by_source_and_id[key] = skill
        if skill.source == "modern-web-guidance":
            self._web_guides_by_id[skill.id] = skill

    def _read_skill_markdown(
        self,
        source: SourceName,
        md_path: Path,
        *,
        category: str | None = None,
        explicit_id: str | None = None,
        explicit_description: str | None = None,
        features_used: tuple[str, ...] = (),
        token_count: int | None = None,
        references: tuple[str, ...] = (),
    ) -> IndexedSkill:
        resolved = md_path.resolve()
        if not resolved.is_relative_to(self._skills_dir):
            raise PathTraversalError(f"Skill file outside skills_dir: {md_path}")

        content = resolved.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)

        rel_posix = resolved.relative_to(self._skills_dir).as_posix()
        default_slug = resolved.parent.name if resolved.name in {"SKILL.md", "guide.md"} else resolved.stem
        skill_id = explicit_id or str(frontmatter.get("name") or default_slug).strip()
        skill_name = str(frontmatter.get("name") or skill_id).strip()
        description = (
            explicit_description
            or str(frontmatter.get("description") or "").strip()
            or _first_heading_or_summary(body)
        )

        return IndexedSkill(
            source=source,
            id=skill_id,
            name=skill_name,
            relative_path=rel_posix,
            absolute_path=resolved,
            description=description,
            category=category,
            references=references,
            features_used=features_used,
            token_count=token_count,
            content=content,
        )

    def _discover_references(self, source_root: Path, skill_dir: Path) -> tuple[str, ...]:
        refs_dir = skill_dir / "references"
        if not refs_dir.is_dir():
            return ()
        refs: list[str] = []
        for md_file in sorted(refs_dir.rglob("*.md")):
            resolved = md_file.resolve()
            if resolved.is_relative_to(source_root):
                refs.append(resolved.relative_to(source_root).as_posix())
        return tuple(refs)

    def _index_standard_source(self, source: SourceName) -> None:
        source_root = self._skills_dir / source
        if not source_root.is_dir():
            LOGGER.warning("Source directory not found for '%s': %s", source, source_root)
            return

        skills_root = source_root / "skills"
        scan_root = skills_root if skills_root.is_dir() else source_root

        for skill_md in sorted(scan_root.rglob("SKILL.md")):
            skill_dir = skill_md.parent
            rel_from_scan = skill_dir.relative_to(scan_root)
            category = rel_from_scan.parts[0] if len(rel_from_scan.parts) > 1 else None
            refs = self._discover_references(source_root, skill_dir)
            indexed = self._read_skill_markdown(
                source,
                skill_md,
                category=category,
                references=refs,
            )
            self._register_skill(indexed)

    def _index_modern_web_guidance(self) -> None:
        source: SourceName = "modern-web-guidance"
        source_root = self._skills_dir / source
        if not source_root.is_dir():
            LOGGER.warning("Source directory not found for '%s': %s", source, source_root)
            return

        # Compiled npm layout: skills/modern-web-guidance/{guides,gen/guides.json}
        npm_skill_dir = source_root / "skills" / "modern-web-guidance"
        guides_root = npm_skill_dir / "guides"
        if not guides_root.is_dir():
            # Fallback layout (e.g. test fixtures): <source>/guides
            guides_root = source_root / "guides"
        if not guides_root.is_dir():
            LOGGER.warning("Modern Web Guidance guides directory not found under %s", source_root)
            return

        guides_meta_by_id: dict[str, dict[str, Any]] = {}
        guides_json = npm_skill_dir / "gen" / "guides.json"
        if not guides_json.is_file():
            guides_json = source_root / "gen" / "guides.json"
        if guides_json.is_file():
            try:
                raw_entries = json.loads(guides_json.read_text(encoding="utf-8"))
                if isinstance(raw_entries, list):
                    for item in raw_entries:
                        if isinstance(item, dict) and "id" in item:
                            guides_meta_by_id[str(item["id"])] = item
            except (OSError, json.JSONDecodeError) as exc:
                LOGGER.warning("Failed to parse %s: %s", guides_json, exc)

        for md_file in sorted(guides_root.rglob("*.md")):
            rel_parts = md_file.relative_to(guides_root).parts
            if md_file.name == "guide.md" and len(rel_parts) >= 2:
                guide_id = md_file.parent.name
                category = rel_parts[0] if len(rel_parts) >= 3 else "general"
            else:
                guide_id = md_file.stem
                category = rel_parts[0] if len(rel_parts) >= 2 else "general"

            meta = guides_meta_by_id.get(guide_id, {})
            meta_category = str(meta.get("category") or category)
            meta_desc = str(meta.get("description") or "").strip() or None
            raw_features = meta.get("featuresUsed") or []
            features = tuple(str(f) for f in raw_features) if isinstance(raw_features, list) else ()
            raw_tokens = meta.get("tokenCount")
            token_count = int(raw_tokens) if isinstance(raw_tokens, int) else None

            indexed = self._read_skill_markdown(
                source,
                md_file,
                category=meta_category,
                explicit_id=guide_id,
                explicit_description=meta_desc,
                features_used=features,
                token_count=token_count,
            )
            self._register_skill(indexed)

    def _index_all_sources(self) -> None:
        self._index_standard_source("superpowers")
        self._index_standard_source("my_skills")
        self._index_modern_web_guidance()

    def _build_fts_index(self) -> None:
        cur = self._fts_conn.cursor()
        cur.execute(
            """
            CREATE VIRTUAL TABLE skills_fts USING fts5(
                source UNINDEXED,
                skill_id UNINDEXED,
                name,
                category,
                description,
                relative_path UNINDEXED,
                content,
                tokenize = 'porter unicode61'
            )
            """
        )
        rows = [
            (
                skill.source,
                skill.id,
                skill.name,
                skill.category or "",
                " ".join(filter(None, [skill.description, " ".join(skill.features_used)])),
                skill.relative_path,
                skill.content,
            )
            for skill in self._skills_by_path.values()
        ]
        cur.executemany(
            "INSERT INTO skills_fts (source, skill_id, name, category, description, relative_path, content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._fts_conn.commit()

    # ------------------------------------------------------------------
    # Role resolution
    # ------------------------------------------------------------------
    def _load_or_lookup_md(self, md_path: Path) -> IndexedSkill | None:
        resolved = md_path.resolve()
        if not resolved.is_relative_to(self._skills_dir):
            raise PathTraversalError(f"Configured file escapes skills_dir: {md_path}")
        if resolved in self._skills_by_path:
            return self._skills_by_path[resolved]
        if not resolved.is_file():
            return None

        rel_parts = resolved.relative_to(self._skills_dir).parts
        if not rel_parts or rel_parts[0] not in VALID_SOURCES:
            LOGGER.warning("Ignoring file outside known sources: %s", resolved)
            return None
        source: SourceName = rel_parts[0]
        return self._read_skill_markdown(source, resolved)

    def _expand_pattern(self, pattern: str) -> list[IndexedSkill]:
        cleaned = pattern.strip()
        if not cleaned:
            return []
        if "\x00" in cleaned or cleaned.startswith("/") or ".." in Path(cleaned).parts:
            raise PathTraversalError(f"Unsafe pattern in roles.yaml: {pattern!r}")

        has_glob = any(ch in cleaned for ch in "*?[")
        candidates: list[Path]
        if has_glob:
            candidates = sorted(self._skills_dir.glob(cleaned))
        else:
            single = self._resolve_within_root(cleaned)
            candidates = [single] if single.exists() else []

        resolved_skills: list[IndexedSkill] = []
        for candidate in candidates:
            resolved_cand = candidate.resolve()
            if not resolved_cand.is_relative_to(self._skills_dir):
                raise PathTraversalError(f"Matched path escapes skills_dir: {candidate}")

            if resolved_cand.is_file() and resolved_cand.suffix.lower() == ".md":
                item = self._load_or_lookup_md(resolved_cand)
                if item is not None:
                    resolved_skills.append(item)
            elif resolved_cand.is_dir():
                for entry_name in ("SKILL.md", "guide.md"):
                    entry_file = resolved_cand / entry_name
                    if entry_file.is_file():
                        item = self._load_or_lookup_md(entry_file)
                        if item is not None:
                            resolved_skills.append(item)
                        break
        return resolved_skills

    def _resolve_all_roles(self) -> None:
        for role_name, role_cfg in self._roles_file.roles.items():
            seen_paths: set[Path] = set()
            missing: list[str] = []
            core_items: list[IndexedSkill] = []
            on_demand_items: list[IndexedSkill] = []

            for pattern in role_cfg.core:
                try:
                    matched = self._expand_pattern(pattern)
                except PathTraversalError as exc:
                    LOGGER.warning("Skipping unsafe core pattern %r in role %r: %s", pattern, role_name, exc)
                    missing.append(pattern)
                    continue
                if not matched:
                    LOGGER.warning("Role '%s': core pattern matched no skills: %s", role_name, pattern)
                    missing.append(pattern)
                    continue
                for skill in matched:
                    if skill.absolute_path not in seen_paths:
                        seen_paths.add(skill.absolute_path)
                        core_items.append(skill)

            for pattern in role_cfg.on_demand:
                try:
                    matched = self._expand_pattern(pattern)
                except PathTraversalError as exc:
                    LOGGER.warning(
                        "Skipping unsafe on_demand pattern %r in role %r: %s",
                        pattern,
                        role_name,
                        exc,
                    )
                    missing.append(pattern)
                    continue
                if not matched:
                    LOGGER.warning(
                        "Role '%s': on_demand pattern matched no skills: %s",
                        role_name,
                        pattern,
                    )
                    missing.append(pattern)
                    continue
                for skill in matched:
                    if skill.absolute_path not in seen_paths:
                        seen_paths.add(skill.absolute_path)
                        on_demand_items.append(skill)

            self._resolved_roles[role_name] = ResolvedRole(
                name=role_name,
                config=role_cfg,
                core=tuple(core_items),
                on_demand=tuple(on_demand_items),
                missing_patterns=tuple(missing),
            )

    # ------------------------------------------------------------------
    # Public query methods (used by MCP tools, resources, prompts)
    # ------------------------------------------------------------------
    def list_roles(self) -> list[RoleSummary]:
        return [
            RoleSummary(
                name=resolved.name,
                description=resolved.config.description,
                core_count=len(resolved.core),
                on_demand_count=len(resolved.on_demand),
                missing_patterns=list(resolved.missing_patterns),
            )
            for resolved in self._resolved_roles.values()
        ]

    def list_skills(self, source: SourceName | None = None) -> list[SkillSummary]:
        if source is not None and source not in VALID_SOURCES:
            raise InputValidationError(f"Unknown source {source!r}; valid sources: {VALID_SOURCES}")
        sources: tuple[SourceName, ...] = (source,) if source is not None else VALID_SOURCES
        results: list[SkillSummary] = []
        for src in sources:
            for item in self._skills_by_source[src]:
                results.append(
                    SkillSummary(
                        source=item.source,
                        id=item.id,
                        name=item.name,
                        relative_path=item.relative_path,
                        description=item.description,
                        category=item.category,
                        references=list(item.references),
                    )
                )
        return results

    def get_role_skills(self, role: str, *, include_on_demand: bool = False) -> str:
        resolved = self._resolved_roles.get(role)
        if resolved is None:
            available = ", ".join(sorted(self._resolved_roles))
            raise RoleNotFoundError(f"Unknown role {role!r}. Available roles: {available}")

        sections: list[str] = [
            f"# Role Bundle: `{resolved.name}`",
            "",
            self.precedence_rules,
        ]
        if resolved.config.description:
            sections.extend(["", f"## Descripción del Rol\n{resolved.config.description}"])
        if resolved.config.instructions:
            sections.extend(["", f"## Instrucciones Obligatorias del Rol\n{resolved.config.instructions}"])

        sections.append("\n## Skills Core (Obligatorias)")
        if not resolved.core:
            sections.append("_No se cargaron skills core para este rol._")
        for skill in resolved.core:
            sections.append(self._format_skill_block(skill))

        if resolved.on_demand:
            if include_on_demand:
                sections.append("\n## Skills On-Demand (Incluidas Completas)")
                for skill in resolved.on_demand:
                    sections.append(self._format_skill_block(skill))
            else:
                sections.append(
                    "\n## Catálogo de Skills On-Demand (Cargar bajo demanda con `get_skill`)"
                )
                for skill in resolved.on_demand:
                    desc = skill.description or "Sin descripción"
                    sections.append(
                        f"- **`{skill.source}` / `{skill.id}`** (`{skill.relative_path}`): {desc}"
                    )

        return "\n\n".join(sections).strip() + "\n"

    def _format_skill_block(self, skill: IndexedSkill) -> str:
        header = f"### [{skill.source}] {skill.name} (`{skill.relative_path}`)"
        parts = [header]
        if skill.references:
            refs_formatted = ", ".join(f"`{r}`" for r in skill.references)
            parts.append(
                f"> Referencias auxiliares disponibles vía `get_skill('{skill.source}', '<ruta>')`: {refs_formatted}"
            )
        parts.append(skill.content.strip())
        return "\n\n".join(parts)

    def get_skill(self, source: str, skill_name: str) -> str:
        if source not in VALID_SOURCES:
            raise InputValidationError(f"Unknown source {source!r}; valid sources: {VALID_SOURCES}")
        typed_source: SourceName = source

        cleaned = skill_name.strip().lstrip("/")
        if not cleaned:
            raise InputValidationError("skill_name must not be empty")
        if "\x00" in cleaned or ".." in Path(cleaned).parts:
            raise PathTraversalError(f"Invalid skill_name (path traversal blocked): {skill_name!r}")

        # 1. Exact ID lookup (frontmatter name / guide id)
        direct = self._skills_by_source_and_id.get((typed_source, cleaned))
        if direct is not None:
            return direct.content

        # 2. Candidate path lookup within source root (supports references/*.md & category/skill paths)
        source_root = self._resolve_within_root(typed_source)
        candidates: list[str] = [
            cleaned,
            f"skills/{cleaned}",
            f"{cleaned}/SKILL.md",
            f"skills/{cleaned}/SKILL.md",
            f"{cleaned}.md",
            f"skills/{cleaned}.md",
        ]
        if typed_source == "modern-web-guidance":
            candidates.extend(
                [
                    f"skills/modern-web-guidance/guides/{cleaned}",
                    f"skills/modern-web-guidance/guides/{cleaned}.md",
                    f"guides/{cleaned}",
                    f"guides/{cleaned}.md",
                ]
            )

        for rel_candidate in candidates:
            resolved = self._resolve_within_root(rel_candidate, root=source_root)
            if resolved.is_file() and resolved.suffix.lower() == ".md":
                return resolved.read_text(encoding="utf-8")

        raise SkillNotFoundError(
            f"Skill {skill_name!r} not found in source {source!r}"
        )

    def _run_fts_query(
        self,
        query: str,
        *,
        source: SourceName | None,
        limit: int,
    ) -> list[tuple[sqlite3.Row, float]]:
        tokens = _extract_query_tokens(query)
        fts_expr = _build_fts_query(tokens)
        if fts_expr is None:
            return []

        candidate_limit = max(limit * 6, 30)
        sql_base = (
            "SELECT source, skill_id, name, relative_path, "
            "-bm25(skills_fts, 0.0, 0.0, 8.0, 3.0, 5.0, 0.0, 1.0) AS score, "
            "snippet(skills_fts, 6, '[', ']', '...', 24) AS snippet "
            "FROM skills_fts "
            "WHERE skills_fts MATCH ? "
        )
        source_clause = "AND source = ? " if source is not None else ""
        sql = sql_base + source_clause + "ORDER BY score DESC LIMIT ?"

        params: list[Any] = [fts_expr]
        if source is not None:
            params.append(source)
        params.append(candidate_limit)
        candidates = list(self._fts_conn.execute(sql, params).fetchall())

        # Re-rank candidates adding non-saturating metadata (name/id + description/features) boosts
        reranked: list[tuple[sqlite3.Row, float]] = []
        for row in candidates:
            base_score = float(row["score"])
            src = cast(SourceName, str(row["source"]))
            sid = str(row["skill_id"])
            skill = self._skills_by_source_and_id.get((src, sid))
            if skill is not None:
                name_hits = _token_overlap_count(tokens, f"{skill.id} {skill.name}")
                desc_text = " ".join(filter(None, [skill.description, " ".join(skill.features_used)]))
                desc_hits = _token_overlap_count(tokens, desc_text)
                final_score = base_score + (name_hits * 6.0) + (desc_hits * 3.0)
            else:
                final_score = base_score
            reranked.append((row, final_score))

        reranked.sort(key=lambda item: item[1], reverse=True)
        return reranked[:limit]

    def search_skills(
        self,
        query: str,
        *,
        source: SourceName | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        cleaned, valid_limit = _validate_search_args(query, limit)
        if source is not None and source not in VALID_SOURCES:
            raise InputValidationError(f"Unknown source {source!r}; valid sources: {VALID_SOURCES}")

        scored_rows = self._run_fts_query(cleaned, source=source, limit=valid_limit)
        return [
            SearchHit(
                source=cast(SourceName, str(row["source"])),
                id=str(row["skill_id"]),
                name=str(row["name"]),
                relative_path=str(row["relative_path"]),
                score=round(score, 4),
                snippet=str(row["snippet"]),
            )
            for row, score in scored_rows
        ]

    def search_modern_web_guidance(self, query: str, *, limit: int = 10) -> list[WebGuideSummary]:
        cleaned, valid_limit = _validate_search_args(query, limit)
        scored_rows = self._run_fts_query(cleaned, source="modern-web-guidance", limit=valid_limit)
        results: list[WebGuideSummary] = []
        for row, _score in scored_rows:
            guide_id = str(row["skill_id"])
            guide = self._web_guides_by_id.get(guide_id)
            if guide is None:
                continue
            results.append(
                WebGuideSummary(
                    id=guide.id,
                    category=guide.category or "general",
                    description=guide.description,
                    features_used=list(guide.features_used),
                    token_count=guide.token_count,
                )
            )
        return results

    def retrieve_modern_web_guidance(self, guide_id: str) -> str:
        raw_ids = [part.strip() for part in guide_id.split(",") if part.strip()]
        if not raw_ids:
            raise InputValidationError("guide_id must not be empty")
        if len(raw_ids) > MAX_GUIDE_IDS:
            raise InputValidationError(
                f"At most {MAX_GUIDE_IDS} guide IDs may be retrieved per call (received {len(raw_ids)})"
            )

        blocks: list[str] = []
        missing: list[str] = []
        for gid in raw_ids:
            if "\x00" in gid or "/" in gid or "\\" in gid or ".." in gid:
                raise PathTraversalError(f"Invalid guide_id: {gid!r}")
            guide = self._web_guides_by_id.get(gid)
            if guide is None:
                missing.append(gid)
                continue
            blocks.append(
                f"# Modern Web Guidance: `{guide.id}` (category: `{guide.category}`)\n\n"
                f"{guide.content.strip()}"
            )

        if missing:
            raise SkillNotFoundError(
                f"Modern Web Guidance guide ID(s) not found: {', '.join(missing)}"
            )
        return "\n\n---\n\n".join(blocks) + "\n"

    def bootstrap_agent_prompt(
        self,
        role: str,
        task: str,
        *,
        include_on_demand: bool = False,
    ) -> str:
        cleaned_task = task.strip()
        if not cleaned_task:
            raise InputValidationError("task must not be empty")
        bundle = self.get_role_skills(role, include_on_demand=include_on_demand)
        return (
            f"Actuá como el agente especializado **`{role}`** del equipo de desarrollo.\n"
            "Seguí estrictamente la jerarquía de precedencia, las instrucciones del rol y las skills cargadas abajo.\n"
            "Si necesitás una skill adicional del catálogo `on_demand`, una referencia auxiliar (`references/*.md`) "
            "o una guía web moderna, consultala usando las tools MCP antes de implementar.\n\n"
            f"{bundle}\n"
            "---\n\n"
            f"## Tarea Asignada\n{cleaned_task}\n"
        )

    def get_native_skill_directories(self) -> list[Path]:
        """Return skill directories compatible with FastMCP v4.2+ `Skill.from_directory`."""
        dirs: list[Path] = []
        for source in ("superpowers", "my_skills"):
            for item in self._skills_by_source[source]:
                if item.absolute_path.name == "SKILL.md":
                    dirs.append(item.absolute_path.parent)
        return dirs

    def get_health_info(self) -> dict[str, Any]:
        """Return operational health metadata and sync provenance for `/health`."""
        sync_meta: dict[str, Any] | None = None
        meta_file = self._skills_dir / ".sync_meta.json"
        if meta_file.is_file():
            try:
                loaded = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    sync_meta = loaded
            except (OSError, json.JSONDecodeError):
                sync_meta = None

        return {
            "status": "healthy",
            "service": "devteam-skills-mcp",
            "roles_count": len(self._resolved_roles),
            "skills_by_source": {
                src: len(items) for src, items in self._skills_by_source.items()
            },
            "total_indexed_documents": len(self._skills_by_path),
            "sync_meta": sync_meta,
        }
