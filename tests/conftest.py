"""Shared pytest fixtures building an isolated synthetic skills_store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.config import Settings
from mcp_server.registry import SkillRegistry


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def sample_skills_dir(tmp_path: Path) -> Path:
    """Create a synthetic multi-source skills_store matching real repo layouts."""
    root = tmp_path / "skills_store"

    # 1. superpowers
    _write(
        root / "superpowers/skills/brainstorming/SKILL.md",
        "---\nname: brainstorming\ndescription: Explore requirements before writing code.\n---\n"
        "# Brainstorming\nAlways align on design before coding.\n",
    )
    _write(
        root / "superpowers/skills/test-driven-development/SKILL.md",
        "---\nname: test-driven-development\ndescription: Enforce red-green-refactor TDD cycles.\n---\n"
        "# TDD\nWrite a failing test first, watch it fail, then implement minimal code.\n",
    )

    # 2. my_skills (2-level nested categories + references/*.md)
    _write(
        root / "my_skills/skills/backend/layering-fastapi-apps/SKILL.md",
        "---\nname: layering-fastapi-apps\ndescription: Separate routers, services, and repositories in FastAPI.\n---\n"
        "# Layering FastAPI Apps\nKeep HTTP routers thin and business logic in services.\n",
    )
    _write(
        root / "my_skills/skills/backend/scaffolding-fastapi-backends/SKILL.md",
        "---\nname: scaffolding-fastapi-backends\ndescription: Orchestrate FastAPI backend project setup.\n---\n"
        "# Scaffolding FastAPI\nSee references/security.md for JWT and cookie rules.\n",
    )
    _write(
        root / "my_skills/skills/backend/scaffolding-fastapi-backends/references/security.md",
        "# Backend Security Reference\nEnforce HttpOnly Secure refresh cookies, RBAC, and anti-IDOR ownership checks.\n",
    )
    _write(
        root / "my_skills/skills/database/migrating-with-alembic/SKILL.md",
        "---\nname: migrating-with-alembic\ndescription: Safe PostgreSQL migrations with Alembic lock and statement timeouts.\n---\n"
        "# Migrating with Alembic\nOverride statement_timeout to 0 in env.py and set lock_timeout.\n",
    )
    _write(
        root / "my_skills/skills/observability/exposing-prometheus-metrics/SKILL.md",
        "---\nname: exposing-prometheus-metrics\ndescription: Expose Prometheus HTTP and custom metrics in FastAPI.\n---\n"
        "# Prometheus Metrics\nUse multiprocess directory with Gunicorn workers.\n",
    )
    # Intentionally mismatched name/dir to verify SkillCatalogProvider graceful degradation
    _write(
        root / "my_skills/skills/testing/bad-native-skill/SKILL.md",
        "---\nname: wrong-name-mismatch\ndescription: Tests graceful skip in native provider.\n---\n"
        "# Testing\nSample test guidance.\n",
    )

    # 3. modern-web-guidance (compiled npm layout)
    mwg_root = root / "modern-web-guidance/skills/modern-web-guidance"
    guides_index = [
        {
            "id": "animate-to-from-top-layer",
            "description": "Animate dialogs and popovers entering/exiting the top layer with @starting-style.",
            "category": "ui-behaviors",
            "featuresUsed": ["@starting-style", "transition-behavior"],
            "tokenCount": 1200,
        },
        {
            "id": "client-side-encryption",
            "description": "Encrypt sensitive data in the browser using WebCrypto AEAD and KEM.",
            "category": "security",
            "featuresUsed": ["Web Cryptography API"],
            "tokenCount": 1800,
        },
        {
            "id": "responsive-table",
            "description": "Keep sticky headers and adapt tables on narrow viewports with container queries.",
            "category": "ui-atoms",
            "featuresUsed": ["container-queries", "css-sticky"],
            "tokenCount": 950,
        },
    ]
    _write(mwg_root / "gen/guides.json", json.dumps(guides_index, indent=2))
    _write(
        mwg_root / "guides/ui-behaviors/animate-to-from-top-layer.md",
        "# Animate to and from top layer\nUse `@starting-style` and `transition-behavior: allow-discrete` for modal dialog backdrops.\n",
    )
    _write(
        mwg_root / "guides/security/client-side-encryption.md",
        "# Encrypt data client-side with WebCrypto\nUse crypto.subtle AEAD encryption.\n",
    )
    _write(
        mwg_root / "guides/ui-atoms/responsive-table.md",
        "# Responsive Data Table\nUse CSS container queries and sticky headers.\n",
    )

    _write(
        root / ".sync_meta.json",
        json.dumps(
            {
                "synced_at": "2026-11-23T00:00:00+00:00",
                "sources": {
                    "superpowers": {"type": "git", "commit": "abc1234"},
                    "my_skills": {"type": "git", "commit": "def5678"},
                    "modern-web-guidance": {"type": "npm", "version": "1.0.1"},
                },
            }
        ),
    )
    return root


@pytest.fixture()
def sample_roles_yaml(tmp_path: Path) -> Path:
    cfg = tmp_path / "roles.yaml"
    cfg.write_text(
        """
precedence_rules: |
  1. superpowers (process)
  2. my_skills (architecture)
  3. modern-web-guidance (web platform)

shared_on_demand:
  - superpowers/skills/brainstorming
  - superpowers/skills/test-driven-development

roles:
  backend:
    description: Backend FastAPI engineer
    instructions: Always enforce anti-IDOR and Pydantic validation.
    core:
      - superpowers/skills/test-driven-development
      - my_skills/skills/backend/layering-fastapi-apps
      - my_skills/skills/backend/scaffolding-fastapi-backends/references/security.md
    on_demand:
      - my_skills/skills/backend/*
      - my_skills/skills/observability/*
      - my_skills/skills/security/*
  db:
    description: Database engineer
    core:
      - my_skills/skills/database/*
      - my_skills/skills/nonexistent-folder
    on_demand: []
  frontend:
    description: Frontend engineer
    web_guidance: true
    core:
      - superpowers/skills/brainstorming
    on_demand: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture()
def registry(sample_skills_dir: Path, sample_roles_yaml: Path) -> SkillRegistry:
    reg = SkillRegistry(skills_dir=sample_skills_dir, roles_config_path=sample_roles_yaml)
    yield reg
    reg.close()


@pytest.fixture()
def base_settings(sample_skills_dir: Path, sample_roles_yaml: Path) -> Settings:
    return Settings(
        MCP_TRANSPORT="streamable-http",
        SKILLS_DIR=sample_skills_dir,
        ROLES_CONFIG_PATH=sample_roles_yaml,
        MCP_ENABLE_NATIVE_SKILLS=True,
    )
