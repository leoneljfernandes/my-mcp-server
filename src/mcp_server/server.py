"""FastMCP v4 server exposing DevTeam Skills tools, resources, prompts, and /health."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastmcp import FastMCP, Skill
from fastmcp.skills.provider import SkillCatalogProvider
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.auth import ConstantTimeBearerVerifier
from mcp_server.config import Settings, get_settings
from mcp_server.models import (
    RoleSummary,
    SearchHit,
    SkillSummary,
    SourceName,
    WebGuideSummary,
)
from mcp_server.registry import SkillRegistry

LOGGER = logging.getLogger(__name__)

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


class InsecureConfigError(RuntimeError):
    """Raised when the HTTP transport would start without authentication by accident."""


def ensure_auth_configured(cfg: Settings) -> None:
    """Fail closed: streamable-http requires MCP_API_KEY unless explicitly opted out."""
    if cfg.api_key_value is not None:
        return
    if cfg.mcp_allow_unauthenticated:
        LOGGER.warning(
            "MCP_ALLOW_UNAUTHENTICATED is enabled: streamable-http is running WITHOUT "
            "authentication. Use only for local development."
        )
        return
    raise InsecureConfigError(
        "MCP_API_KEY es obligatoria en streamable-http. Definila o, solo para desarrollo "
        "local, MCP_ALLOW_UNAUTHENTICATED=true."
    )


def _build_native_skills_provider(registry: SkillRegistry) -> SkillCatalogProvider | None:
    """Build optional FastMCP v4.2+ SkillCatalogProvider with graceful degradation per skill."""
    loaded_skills: list[Skill] = []
    seen_names: set[str] = set()

    for skill_dir in registry.get_native_skill_directories():
        try:
            skill = Skill.from_directory(skill_dir)
        except Exception as exc:
            LOGGER.warning("Skipping native FastMCP skill at %s: %s", skill_dir, exc)
            continue
        if skill.name in seen_names:
            LOGGER.warning("Skipping duplicate native skill name '%s' at %s", skill.name, skill_dir)
            continue
        seen_names.add(skill.name)
        loaded_skills.append(skill)

    if not loaded_skills:
        return None
    LOGGER.info("Mounted FastMCP native SkillCatalogProvider with %d skills", len(loaded_skills))
    return SkillCatalogProvider(loaded_skills)


def create_server(
    settings: Settings | None = None,
    registry: SkillRegistry | None = None,
) -> FastMCP:
    """Construct and wire the FastMCP v4 server instance."""
    cfg = settings or get_settings()
    reg = registry or SkillRegistry(
        skills_dir=cfg.skills_dir,
        roles_config_path=cfg.roles_config_path,
    )

    auth_provider = None
    api_key = cfg.api_key_value
    if api_key is not None:
        auth_provider = ConstantTimeBearerVerifier(api_key)
        LOGGER.info("Bearer token authentication enabled for MCP endpoints")

    providers: list[Any] = []
    if cfg.mcp_enable_native_skills:
        native_provider = _build_native_skills_provider(reg)
        if native_provider is not None:
            providers.append(native_provider)

    mcp = FastMCP(
        name="DevTeam Skills MCP",
        instructions=(
            "Fuente única de verdad de estándares y skills de desarrollo "
            "(obra/superpowers, my_skills, modern-web-guidance). "
            "Usá `list_roles` y `get_role_skills` para cargar el contexto base del rol, "
            "`get_skill` para skills `on_demand` o archivos `references/*.md`, "
            "y `search_modern_web_guidance` + `retrieve_modern_web_guidance` antes de implementar UI/web."
        ),
        auth=auth_provider,
        providers=providers or None,
    )

    # ------------------------------------------------------------------
    # Public health endpoint (unauthenticated by design in FastMCP)
    # ------------------------------------------------------------------
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        del request
        return JSONResponse(reg.get_health_info())

    # ------------------------------------------------------------------
    # MCP Tools (all read-only, idempotent, closed-world, Pydantic typed)
    # ------------------------------------------------------------------
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def list_roles() -> list[RoleSummary]:
        """List all configured agent roles with core/on-demand skill counts."""
        return reg.list_roles()

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def list_skills(
        source: SourceName | None = None,
    ) -> list[SkillSummary]:
        """List available skills across all sources or filtered by a specific source."""
        return reg.list_skills(source=source)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def get_role_skills(role: str, include_on_demand: bool = False) -> str:
        """Return precedence rules, role instructions, core skills, and on-demand catalog for a role."""
        return reg.get_role_skills(role, include_on_demand=include_on_demand)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def get_skill(source: SourceName, skill_name: str) -> str:
        """Return the exact Markdown content of a skill or auxiliary reference file."""
        return reg.get_skill(source, skill_name)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def search_skills(
        query: str,
        source: SourceName | None = None,
        limit: int = 10,
        role: str | None = None,
    ) -> list[SearchHit]:
        """Search skills and guides using SQLite FTS5 BM25 ranking.

        `role` scopes the search to that role's skills (core, on-demand and shared;
        modern-web-guidance guides only for web roles). Recommended for agents with an
        assigned role. Without `role`, all sources are searched.
        """
        return reg.search_skills(query, source=source, limit=limit, role=role)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def search_modern_web_guidance(query: str, limit: int = 10) -> list[WebGuideSummary]:
        """Search compiled Modern Web Guidance entries and return matching guide IDs and summaries."""
        return reg.search_modern_web_guidance(query, limit=limit)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def retrieve_modern_web_guidance(guide_id: str) -> str:
        """Retrieve full compiled Markdown for one or more comma-separated Modern Web Guidance IDs (max 5)."""
        return reg.retrieve_modern_web_guidance(guide_id)

    # ------------------------------------------------------------------
    # MCP Resources (read-only)
    # ------------------------------------------------------------------
    @mcp.resource("skills://roles/{role}", mime_type="text/markdown")
    def role_skills_resource(role: str) -> str:
        """Read-only resource exposing the core skills bundle and on-demand catalog for a role."""
        return reg.get_role_skills(role)

    @mcp.resource("skills://{source}/{skill_name*}", mime_type="text/markdown")
    def single_skill_resource(source: str, skill_name: str) -> str:
        """Read-only resource exposing an individual skill or nested reference file."""
        return reg.get_skill(source, skill_name)

    # ------------------------------------------------------------------
    # MCP Prompts
    # ------------------------------------------------------------------
    @mcp.prompt()
    def bootstrap_agent(
        role: Literal["supervisor", "db", "backend", "frontend", "qa", "security", "observability"] | str,
        task: str,
        include_on_demand: bool = False,
    ) -> str:
        """Build a ready-to-use system prompt injecting precedence rules, role skills, and the task."""
        return reg.bootstrap_agent_prompt(role, task, include_on_demand=include_on_demand)

    return mcp


def create_http_app(
    settings: Settings | None = None,
    registry: SkillRegistry | None = None,
) -> Any:
    """Build the stateless Streamable HTTP ASGI app (usable by uvicorn or tests)."""
    cfg = settings or get_settings()
    ensure_auth_configured(cfg)
    mcp = create_server(settings=cfg, registry=registry)
    return mcp.http_app(
        path=cfg.mcp_path,
        transport="streamable-http",
        stateless_http=True,
        allowed_origins=cfg.allowed_origins_list or None,
    )


def main() -> None:
    """CLI entrypoint supporting both `stdio` and stateless `streamable-http` transports."""
    cfg = get_settings()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if cfg.mcp_transport == "streamable-http":
        ensure_auth_configured(cfg)
    mcp = create_server(settings=cfg)
    if cfg.mcp_transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
        return

    mcp.run(
        transport="streamable-http",
        host=cfg.mcp_host,
        port=cfg.port,
        path=cfg.mcp_path,
        stateless_http=True,
        allowed_origins=cfg.allowed_origins_list or None,
        show_banner=False,
    )


if __name__ == "__main__":
    main()
