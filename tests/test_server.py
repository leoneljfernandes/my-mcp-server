"""Integration tests for FastMCP v4 server primitives, annotations, /health, and Bearer auth."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastmcp import Client
from pydantic import SecretStr

from mcp_server.config import Settings
from mcp_server.registry import SkillRegistry
from mcp_server.server import InsecureConfigError, create_http_app, create_server


@pytest.mark.asyncio
async def test_mcp_tools_annotations_resources_and_prompts(
    base_settings: Settings,
    registry: SkillRegistry,
) -> None:
    server = create_server(settings=base_settings, registry=registry)

    async with Client(server) as client:
        tools = await client.list_tools()
        tool_by_name = {t.name: t for t in tools}

        expected_tools = {
            "list_roles",
            "list_skills",
            "get_role_skills",
            "get_skill",
            "search_skills",
            "search_modern_web_guidance",
            "retrieve_modern_web_guidance",
        }
        assert expected_tools.issubset(tool_by_name)

        for name in expected_tools:
            annotations = tool_by_name[name].annotations
            assert annotations is not None
            assert annotations.read_only_hint is True
            assert annotations.idempotent_hint is True
            assert annotations.open_world_hint is False

        # Tool calls with structured output
        roles_res = await client.call_tool("list_roles", {})
        assert roles_res.structured_content is not None

        mwg_search = await client.call_tool(
            "search_modern_web_guidance",
            {"query": "WebCrypto encryption"},
        )
        assert "client-side-encryption" in str(mwg_search.content)

        scoped = await client.call_tool(
            "search_skills", {"query": "animate dialog top layer", "role": "backend"}
        )
        assert "animate-to-from-top-layer" not in str(scoped.content)
        skills_res = await client.call_tool("list_skills", {})
        assert "token_estimate" in str(skills_res.content)

        # Resource templates (including wildcard {skill_name*} with slashes)
        role_resource = await client.read_resource("skills://roles/backend")
        assert "Keep HTTP routers thin" in str(role_resource)

        nested_resource = await client.read_resource(
            "skills://my_skills/backend/scaffolding-fastapi-backends/references/security.md"
        )
        assert "HttpOnly Secure" in str(nested_resource)

        # Prompt
        prompt_res = await client.get_prompt(
            "bootstrap_agent",
            {"role": "backend", "task": "Crear servicio de pagos"},
        )
        assert "Crear servicio de pagos" in str(prompt_res.messages)


@pytest.mark.asyncio
async def test_streamable_http_bearer_auth_and_public_health(
    sample_skills_dir: object,
    sample_roles_yaml: object,
    registry: SkillRegistry,
) -> None:
    token = "super-secret-test-bearer-token"
    settings = Settings(
        MCP_TRANSPORT="streamable-http",
        MCP_API_KEY=SecretStr(token),
        SKILLS_DIR=registry.skills_dir,
        ROLES_CONFIG_PATH=sample_roles_yaml,  # type: ignore[arg-type]
        MCP_ENABLE_NATIVE_SKILLS=True,
    )
    app = create_http_app(settings=settings, registry=registry)

    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest-client", "version": "1.0.0"},
        },
    }
    mcp_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as http,
    ):
        # 1. /health must be public without Authorization header
        health = await http.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "healthy"
        assert body["roles_count"] == 3
        assert body["sync_meta"]["sources"]["modern-web-guidance"]["version"] == "1.0.1"

        # 2. /mcp without token -> 401
        unauth = await http.post("/mcp", json=init_payload, headers=mcp_headers)
        assert unauth.status_code == 401

        # 3. /mcp with invalid token -> 401
        wrong = await http.post(
            "/mcp",
            json=init_payload,
            headers={**mcp_headers, "Authorization": "Bearer wrong-token"},
        )
        assert wrong.status_code == 401

        # 4. /mcp with valid Bearer token -> 200 (stateless!)
        ok = await http.post(
            "/mcp",
            json=init_payload,
            headers={**mcp_headers, "Authorization": f"Bearer {token}"},
        )
        assert ok.status_code == 200
        assert "DevTeam Skills MCP" in ok.text


def _http_settings(registry: SkillRegistry, sample_roles_yaml, **extra) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        MCP_TRANSPORT="streamable-http",
        SKILLS_DIR=registry.skills_dir,
        ROLES_CONFIG_PATH=sample_roles_yaml,
        **extra,
    )


def test_http_app_refuses_to_start_without_api_key(sample_roles_yaml, registry) -> None:  # type: ignore[no-untyped-def]
    cfg = _http_settings(registry, sample_roles_yaml)
    with pytest.raises(InsecureConfigError, match="MCP_API_KEY"):
        create_http_app(settings=cfg, registry=registry)


def test_http_app_refuses_whitespace_only_api_key(sample_roles_yaml, registry) -> None:  # type: ignore[no-untyped-def]
    cfg = _http_settings(registry, sample_roles_yaml, MCP_API_KEY=SecretStr("   "))
    with pytest.raises(InsecureConfigError, match="MCP_API_KEY"):
        create_http_app(settings=cfg, registry=registry)


def test_http_app_allows_explicit_unauthenticated_opt_out(  # type: ignore[no-untyped-def]
    sample_roles_yaml, registry, caplog
) -> None:
    cfg = _http_settings(registry, sample_roles_yaml, MCP_ALLOW_UNAUTHENTICATED=True)
    with caplog.at_level(logging.WARNING):
        assert create_http_app(settings=cfg, registry=registry) is not None
    assert any(r.levelno == logging.WARNING and "MCP_ALLOW_UNAUTHENTICATED" in r.message for r in caplog.records)
