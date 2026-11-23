"""Unit tests for SkillRegistry: globs, deduplication, security guards, FTS5 search."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.models import (
    InputValidationError,
    PathTraversalError,
    RoleNotFoundError,
    SkillNotFoundError,
)
from mcp_server.registry import MAX_GUIDE_IDS, MAX_QUERY_LENGTH, MAX_SEARCH_LIMIT, SkillRegistry


def test_list_roles_deduplicates_core_from_on_demand_and_tracks_missing(
    registry: SkillRegistry,
) -> None:
    roles = {r.name: r for r in registry.list_roles()}
    assert set(roles) == {"backend", "db", "frontend"}

    # backend core has 3 items (tdd, layering-fastapi-apps, security.md).
    # on_demand globs backend/* (contains layering-fastapi-apps already in core + scaffolding)
    # + observability/* (prometheus) + security/* (missing).
    backend = roles["backend"]
    assert backend.core_count == 3
    assert backend.on_demand_count == 2  # scaffolding + prometheus (layering deduplicated!)
    assert backend.missing_patterns == ["my_skills/skills/security/*"]

    # db has 1 valid glob match and 1 nonexistent path (graceful degradation)
    db = roles["db"]
    assert db.core_count == 1
    assert db.missing_patterns == ["my_skills/skills/nonexistent-folder"]


def test_get_role_skills_progressive_disclosure_and_full_mode(registry: SkillRegistry) -> None:
    compact = registry.get_role_skills("backend", include_on_demand=False)
    assert "superpowers (process)" in compact
    assert "Always enforce anti-IDOR" in compact
    assert "Keep HTTP routers thin" in compact
    assert "Enforce HttpOnly Secure refresh cookies" in compact
    # On-demand skill appears in catalog, NOT full body
    assert "exposing-prometheus-metrics" in compact
    assert "Use multiprocess directory with Gunicorn workers." not in compact

    full = registry.get_role_skills("backend", include_on_demand=True)
    assert "Use multiprocess directory with Gunicorn workers." in full


def test_get_role_skills_unknown_role_raises(registry: SkillRegistry) -> None:
    with pytest.raises(RoleNotFoundError):
        registry.get_role_skills("unknown-role")


def test_get_skill_supports_slug_category_and_nested_references(registry: SkillRegistry) -> None:
    by_slug = registry.get_skill("my_skills", "layering-fastapi-apps")
    assert "Keep HTTP routers thin" in by_slug

    by_category_path = registry.get_skill("my_skills", "backend/layering-fastapi-apps")
    assert by_category_path == by_slug

    nested_ref = registry.get_skill(
        "my_skills",
        "backend/scaffolding-fastapi-backends/references/security.md",
    )
    assert "HttpOnly Secure" in nested_ref


def test_list_skills_exposes_references_and_filters_by_source(registry: SkillRegistry) -> None:
    my_skills = registry.list_skills(source="my_skills")
    scaffolding = next(s for s in my_skills if s.id == "scaffolding-fastapi-backends")
    assert scaffolding.category == "backend"
    assert "skills/backend/scaffolding-fastapi-backends/references/security.md" in scaffolding.references

    mwg = registry.list_skills(source="modern-web-guidance")
    assert len(mwg) == 3
    assert {g.id for g in mwg} == {
        "animate-to-from-top-layer",
        "client-side-encryption",
        "responsive-table",
    }


@pytest.mark.parametrize(
    "malicious",
    [
        "../roles.yaml",
        "../../etc/passwd",
        "backend/../../../etc/passwd",
        "foo\x00bar",
    ],
)
def test_path_traversal_blocked_in_get_skill(registry: SkillRegistry, malicious: str) -> None:
    with pytest.raises(PathTraversalError):
        registry.get_skill("my_skills", malicious)


def test_symlink_escape_blocked(
    sample_skills_dir: Path,
    sample_roles_yaml: Path,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "outside_secret.md"
    secret_file.write_text("TOP SECRET", encoding="utf-8")
    evil_link = sample_skills_dir / "my_skills/skills/backend/escape.md"
    evil_link.symlink_to(secret_file)

    reg = SkillRegistry(skills_dir=sample_skills_dir, roles_config_path=sample_roles_yaml)
    try:
        with pytest.raises(PathTraversalError):
            reg.get_skill("my_skills", "backend/escape.md")
    finally:
        reg.close()


def test_fts5_search_skills_and_modern_web_guidance(registry: SkillRegistry) -> None:
    hits = registry.search_skills("alembic statement timeout")
    assert hits
    assert hits[0].id == "migrating-with-alembic"
    assert hits[0].source == "my_skills"

    # Special FTS5 operators in query must not crash SQLite
    safe_hits = registry.search_skills('NOT (OR "alembic" *)')
    assert any(h.id == "migrating-with-alembic" for h in safe_hits)

    mwg_hits = registry.search_modern_web_guidance("animate dialog backdrop")
    assert mwg_hits
    assert mwg_hits[0].id == "animate-to-from-top-layer"

    retrieved = registry.retrieve_modern_web_guidance("animate-to-from-top-layer,responsive-table")
    assert "@starting-style" in retrieved
    assert "CSS container queries" in retrieved


def test_input_validation_limits(registry: SkillRegistry) -> None:
    with pytest.raises(InputValidationError):
        registry.search_skills("   ")
    with pytest.raises(InputValidationError):
        registry.search_skills("a" * (MAX_QUERY_LENGTH + 1))
    with pytest.raises(InputValidationError):
        registry.search_skills("alembic", limit=0)
    with pytest.raises(InputValidationError):
        registry.search_skills("alembic", limit=MAX_SEARCH_LIMIT + 1)

    too_many_ids = ",".join(f"id-{i}" for i in range(MAX_GUIDE_IDS + 1))
    with pytest.raises(InputValidationError):
        registry.retrieve_modern_web_guidance(too_many_ids)

    with pytest.raises(SkillNotFoundError):
        registry.retrieve_modern_web_guidance("does-not-exist")


def test_bootstrap_agent_prompt_includes_precedence_skills_and_task(
    registry: SkillRegistry,
) -> None:
    prompt = registry.bootstrap_agent_prompt("backend", "Implementar endpoint /orders")
    assert "superpowers (process)" in prompt
    assert "Implementar endpoint /orders" in prompt
    assert "Keep HTTP routers thin" in prompt


def test_shared_on_demand_listed_in_every_role_and_deduplicated(registry: SkillRegistry) -> None:
    for role in ("backend", "db"):
        shared = registry.get_role_skills(role).split("## Catálogo Compartido")[1]
        assert "`superpowers` / `brainstorming`" in shared
    backend_shared = registry.get_role_skills("backend").split("## Catálogo Compartido")[1]
    assert "`superpowers` / `test-driven-development`" not in backend_shared  # ya es core
    db_shared = registry.get_role_skills("db").split("## Catálogo Compartido")[1]
    assert "`superpowers` / `test-driven-development`" in db_shared


def test_shared_catalog_stays_catalog_with_include_on_demand(registry: SkillRegistry) -> None:
    bundle = registry.get_role_skills("db", include_on_demand=True)
    shared = bundle.split("## Catálogo Compartido")[1]
    assert "`superpowers` / `brainstorming`" in shared
    assert "Always align on design before coding." not in bundle


def test_allowed_skill_ids_union(registry: SkillRegistry) -> None:
    ids = registry.allowed_skill_ids("backend")
    assert ("superpowers", "brainstorming") in ids
    assert ("my_skills", "layering-fastapi-apps") in ids
    assert not any(source == "modern-web-guidance" for source, _ in ids)


def test_web_guidance_flag_adds_catalog_line_and_allows_guides(registry: SkillRegistry) -> None:
    assert "Modern Web Guidance" not in registry.get_role_skills("backend")
    bundle = registry.get_role_skills("frontend")
    assert "Modern Web Guidance" in bundle
    assert "3 guías" in bundle
    assert "security, ui-atoms, ui-behaviors" in bundle
    ids = registry.allowed_skill_ids("frontend")
    assert ("modern-web-guidance", "client-side-encryption") in ids


def test_check_role_integrity_reports_kinds(registry: SkillRegistry) -> None:
    found = {(i.role, i.kind, i.target) for i in registry.check_role_integrity()}
    assert ("backend", "unknown_reference", "no-existe") in found
    assert ("backend", "unassigned_reference", "writing-plans") in found
    assert ("backend", "unassigned_reference", "brainstorming") not in found  # está en shared
    assert ("db", "missing_pattern", "my_skills/skills/nonexistent-folder") in found


def test_search_without_role_keeps_all_sources(registry: SkillRegistry) -> None:
    hits = registry.search_skills("animate dialog top layer")
    assert hits[0].id == "animate-to-from-top-layer"


def test_role_with_web_guidance_includes_guides(registry: SkillRegistry) -> None:
    hits = registry.search_skills("animate dialog top layer", role="frontend")
    assert hits[0].id == "animate-to-from-top-layer"
    assert all(
        h.source != "modern-web-guidance"
        for h in registry.search_skills("animate dialog top layer", role="backend")
    )


def test_search_scoped_to_role(registry: SkillRegistry) -> None:
    backend_ids = [h.id for h in registry.search_skills("prometheus metrics", role="backend")]
    assert "exposing-prometheus-metrics" in backend_ids
    db_hits = registry.search_skills("prometheus metrics", role="db")
    assert "exposing-prometheus-metrics" not in [h.id for h in db_hits]
    assert all((h.source, h.id) in registry.allowed_skill_ids("db") for h in db_hits)


def test_search_unknown_role_raises(registry: SkillRegistry) -> None:
    with pytest.raises(RoleNotFoundError):
        registry.search_skills("x", role="nope")


def test_token_estimates_exposed(registry: SkillRegistry) -> None:
    assert all(s.token_estimate > 0 for s in registry.list_skills())
    assert all(r.core_tokens > 0 for r in registry.list_roles() if r.core_count)


def test_role_search_not_starved_by_out_of_role_candidates(
    sample_skills_dir: Path, sample_roles_yaml: Path
) -> None:
    for i in range(230):
        noise = sample_skills_dir / f"my_skills/skills/noise/noise-{i}/SKILL.md"
        noise.parent.mkdir(parents=True)
        noise.write_text(
            f"---\nname: noise-{i}\ndescription: prometheus metrics prometheus metrics.\n---\n"
            "# Noise\nprometheus metrics prometheus metrics prometheus metrics.\n",
            encoding="utf-8",
        )
    reg = SkillRegistry(skills_dir=sample_skills_dir, roles_config_path=sample_roles_yaml)
    try:
        hits = reg.search_skills("prometheus metrics", role="backend", limit=1)
        assert len(hits) == 1
        assert (hits[0].source, hits[0].id) in reg.allowed_skill_ids("backend")
    finally:
        reg.close()
