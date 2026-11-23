# DevTeam Skills MCP

Servidor MCP (FastMCP v4) que sirve a agentes de desarrollo tres fuentes de skills que se complementan:

| Fuente | Responde | Origen |
|---|---|---|
| `superpowers` | cómo trabajar (brainstorming, planes, TDD, debugging, verificación, review) | [obra/superpowers](https://github.com/obra/superpowers) |
| `my_skills` | decisiones de arquitectura y stack (FastAPI, PostgreSQL/SQLAlchemy/Alembic, React 19, observabilidad, testing) | [leoneljfernandes/my_skills](https://github.com/leoneljfernandes/my_skills) |
| `modern-web-guidance` | qué APIs nativas de la plataforma web usar en el cliente | paquete npm `modern-web-guidance` |

Los roles (`config/roles.yaml`) definen qué skills se inyectan siempre (`core`) y cuáles se ofrecen como catálogo (`on_demand`). Roles: `supervisor`, `db`, `backend`, `frontend`, `qa`, `security`, `observability`. Todas las skills siguen accesibles con `get_skill` y `search_skills`; `search_skills(query, role=...)` restringe la búsqueda a las skills del rol (las guías de `modern-web-guidance` solo para los roles con `web_guidance: true`: frontend, qa, security). El catálogo `shared_on_demand` aparece en el bundle de todos los roles.

## Uso rápido

```bash
uv sync
uv run python scripts/sync_skills.py      # descarga las tres fuentes a ./skills_store
uv run devteam-skills-mcp                 # stdio (IDE / CLI)
```

En modo HTTP (`MCP_TRANSPORT=streamable-http`: Docker, compose, Render, Cloud Run) el servidor **no arranca sin `MCP_API_KEY`** (un valor solo con espacios cuenta como ausente). Solo para desarrollo local se puede desactivar con `MCP_ALLOW_UNAUTHENTICATED=true`; stdio no necesita clave. Ver `.env.example`. Docker: `docker compose up --build`. Cliente LangGraph de ejemplo en `examples/langgraph_client.py`.

## Tools

`list_roles`, `list_skills`, `get_role_skills`, `get_skill`, `search_skills`, `search_modern_web_guidance`, `retrieve_modern_web_guidance`; recursos `skills://roles/{role}` y `skills://{source}/{skill}`; prompt `bootstrap_agent`; `GET /health` con las versiones sincronizadas.

## Actualizar skills

Las skills se hornean en la imagen al construirla: para servir una versión nueva se reconstruye y redespliega.

- `config/sources.lock.json` fija las fuentes: SHA de `superpowers`, `my_skills` sigue `main` y versión exacta de `modern-web-guidance`. `scripts/sync_skills.py` sincroniza exactamente lo que dice el lock (`--lock PATH` para otro archivo).
- `uv run python scripts/sync_skills.py --update-lock` sincroniza lo último de cada fuente y reescribe el lock.
- `.github/workflows/update-skills.yml` corre cada lunes 06:00 UTC (y a mano), ejecuta los evals y abre/actualiza el PR `bot/update-skills` con links de comparación. El deploy ocurre al mergear ese PR (push a `main`); el workflow de deploy ya no tiene schedule.
- Un push a `my_skills` puede disparar un redeploy vía `repository_dispatch` (`skills-updated`), una vez configurado el secret `MCP_DISPATCH_TOKEN` en el repo `my_skills`.

## Docker

Mientras `my_skills` sea privado, el build necesita el token como secret:

```bash
GITHUB_TOKEN=... docker build --secret id=github_token,env=GITHUB_TOKEN -t devteam-skills-mcp .
```

## Desarrollo

```bash
uv run ruff check . && uv run mypy src scripts && uv run pytest -q
uv run pytest -m eval -v   # evals de recuperación sobre el corpus real (requiere sync)
```

La especificación original está en `instructions.md`.
