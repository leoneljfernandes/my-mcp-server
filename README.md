# DevTeam Skills MCP

Servidor MCP (FastMCP v4) que sirve a agentes de desarrollo tres fuentes de skills que se complementan:

| Fuente | Responde | Origen |
|---|---|---|
| `superpowers` | cómo trabajar (brainstorming, planes, TDD, debugging, verificación, review) | [obra/superpowers](https://github.com/obra/superpowers) |
| `my_skills` | decisiones de arquitectura y stack (FastAPI, PostgreSQL/SQLAlchemy/Alembic, React 19, observabilidad, testing) | [leoneljfernandes/my_skills](https://github.com/leoneljfernandes/my_skills) |
| `modern-web-guidance` | qué APIs nativas de la plataforma web usar en el cliente | paquete npm `modern-web-guidance` |

Los roles (`config/roles.yaml`) definen qué skills se inyectan siempre (`core`) y cuáles se ofrecen como catálogo (`on_demand`). Todas las skills siguen accesibles con `get_skill` y `search_skills`.

## Uso rápido

```bash
uv sync
uv run python scripts/sync_skills.py      # descarga las tres fuentes a ./skills_store
uv run devteam-skills-mcp                 # stdio (IDE / CLI)
```

En modo HTTP (`MCP_TRANSPORT=streamable-http`) definí `MCP_API_KEY`; ver `.env.example`. Docker: `docker compose up --build`. Cliente LangGraph de ejemplo en `examples/langgraph_client.py`.

## Tools

`list_roles`, `list_skills`, `get_role_skills`, `get_skill`, `search_skills`, `search_modern_web_guidance`, `retrieve_modern_web_guidance`; recursos `skills://roles/{role}` y `skills://{source}/{skill}`; prompt `bootstrap_agent`; `GET /health` con las versiones sincronizadas.

## Actualizar skills

Las skills se hornean en la imagen al construirla: para servir una versión nueva se reconstruye y redespliega. En local alcanza con volver a correr `scripts/sync_skills.py` y reiniciar el proceso.

## Desarrollo

```bash
uv run ruff check . && uv run mypy src scripts && uv run pytest -q
uv run pytest -m eval -v   # evals de recuperación sobre el corpus real (requiere sync)
```

La especificación original está en `instructions.md`.
