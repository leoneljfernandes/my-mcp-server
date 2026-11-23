"""Retrieval quality evaluations against the real synced `./skills_store/` corpus.

Run with:
    uv run pytest -m eval -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.registry import SkillRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_SKILLS_DIR = REPO_ROOT / "skills_store"
REAL_ROLES_YAML = REPO_ROOT / "config" / "roles.yaml"

pytestmark = pytest.mark.eval


@pytest.fixture(scope="module")
def real_registry() -> SkillRegistry:
    if not (REAL_SKILLS_DIR / "superpowers").is_dir():
        pytest.skip("skills_store not synced yet; run `uv run python scripts/sync_skills.py` first")
    reg = SkillRegistry(skills_dir=REAL_SKILLS_DIR, roles_config_path=REAL_ROLES_YAML)
    yield reg
    reg.close()


def test_all_six_roles_loaded_from_real_corpus(real_registry: SkillRegistry) -> None:
    roles = {r.name: r for r in real_registry.list_roles()}
    assert set(roles) == {"supervisor", "db", "backend", "frontend", "qa", "security"}
    for name, role in roles.items():
        assert role.core_count >= 1, f"Role {name} has no core skills loaded"


@pytest.mark.parametrize(
    ("query", "source", "expected_id"),
    [
        # superpowers
        ("red green refactor failing test", "superpowers", "test-driven-development"),
        ("root cause trace bug before fixing", "superpowers", "systematic-debugging"),
        ("verify tests pass before claiming completion", "superpowers", "verification-before-completion"),
        ("creative work building components new feature", "superpowers", "brainstorming"),
        # my_skills
        ("alembic migration statement_timeout lock_timeout", "my_skills", "migrating-with-alembic"),
        ("fastapi error handling HTTPException problem details", "my_skills", "handling-fastapi-errors"),
        ("prometheus metrics gunicorn multiprocess", "my_skills", "exposing-prometheus-metrics"),
        ("sqlalchemy async session pool pgbouncer", "my_skills", "configuring-sqlalchemy-sessions"),
        ("react router data mode loader", "my_skills", "routing-with-react-router"),
        ("opentelemetry tracing spans fastapi", "my_skills", "tracing-with-opentelemetry"),
    ],
)
def test_search_skills_top3_retrieval(
    real_registry: SkillRegistry,
    query: str,
    source: str,
    expected_id: str,
) -> None:
    hits = real_registry.search_skills(query, source=source, limit=3)  # type: ignore[arg-type]
    top3_ids = [h.id for h in hits]
    assert expected_id in top3_ids, f"Query {query!r}: expected {expected_id!r} in Top-3 {top3_ids}"


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("animate dialog modal backdrop top layer", "animate-to-from-top-layer"),
        ("encrypt data client side WebCrypto", "client-side-encryption"),
        ("passkey webauthn authentication", "passkey-authentication"),
        ("accessible error announcement aria invalid", "accessible-error-announcement"),
    ],
)
def test_search_modern_web_guidance_top3_retrieval(
    real_registry: SkillRegistry,
    query: str,
    expected_id: str,
) -> None:
    hits = real_registry.search_modern_web_guidance(query, limit=3)
    top3_ids = [h.id for h in hits]
    assert expected_id in top3_ids, f"Query {query!r}: expected {expected_id!r} in Top-3 {top3_ids}"
