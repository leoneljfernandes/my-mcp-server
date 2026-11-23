# DevTeam Skills MCP

Servidor MCP que le da a un equipo de agentes de desarrollo una **fuente única de verdad** para trabajar: cómo trabajar (proceso), cómo encaja cada cosa en el stack (arquitectura) y qué APIs nativas de la web usar (plataforma). Cada agente recibe por rol solo las skills que necesita, y puede buscar o pedir el resto a demanda.

## Índice

1. [Qué problema resuelve](#qué-problema-resuelve)
2. [Tecnologías](#tecnologías)
3. [Las tres fuentes de skills](#las-tres-fuentes-de-skills)
4. [Roles y qué skills recibe cada uno](#roles-y-qué-skills-recibe-cada-uno)
5. [Decisiones técnicas y de arquitectura](#decisiones-técnicas-y-de-arquitectura)
6. [Cómo consumir el servidor, paso a paso](#cómo-consumir-el-servidor-paso-a-paso)
7. [Referencia de tools, resources y prompt](#referencia-de-tools-resources-y-prompt)
8. [Configuración](#configuración)
9. [Actualizar skills](#actualizar-skills)
10. [Docker y despliegue](#docker-y-despliegue)
11. [Desarrollo y tests](#desarrollo-y-tests)

## Qué problema resuelve

Un agente de código que trabaja sin guías mezcla criterios: usa APIs web obsoletas, elige otra arquitectura en cada tarea, se salta tests o verificación. Este servidor entrega, según el rol del agente, un paquete de instrucciones curadas y coherentes entre sí, y reglas explícitas de **quién decide qué** cuando dos fuentes tocan el mismo tema.

El servidor no ejecuta nada ni modifica datos: todas sus tools son de solo lectura.

## Tecnologías

| Capa | Tecnología | Para qué |
|---|---|---|
| Lenguaje y entorno | Python 3.14, [uv](https://docs.astral.sh/uv/) | Código del servidor y gestión de dependencias con `uv.lock` |
| Protocolo | [FastMCP](https://gofastmcp.com) v4 (`fastmcp>=4.2.4,<5`) | Tools, resources, prompts y transportes `stdio` y `streamable-http` |
| Búsqueda | SQLite FTS5 con ranking BM25 | Búsqueda de texto completo en memoria, sin servicios externos |
| Modelos y config | Pydantic v2, pydantic-settings | Salidas tipadas de las tools y configuración por variables de entorno |
| Roles | YAML (`config/roles.yaml`) | Mapeo declarativo de rol a skills |
| Autenticación | Bearer token con comparación en tiempo constante | Protege el modo HTTP |
| Calidad | pytest, ruff, mypy (estricto) | Tests, estilo y tipos |
| Contenedor | Docker multi-stage, usuario no root | Imagen con las skills horneadas |
| CI/CD | GitHub Actions | Tests, evals de recuperación, deploy y actualización semanal |
| Despliegue | Google Cloud Run o Render | Destinos soportados por el workflow de deploy |

## Las tres fuentes de skills

Cada fuente responde una pregunta distinta. Se complementan, no compiten.

| Fuente | Responde | Origen |
|---|---|---|
| `superpowers` | **Cómo trabajás**: brainstorming, planes, TDD, debugging, verificación, code review | [obra/superpowers](https://github.com/obra/superpowers) |
| `my_skills` | **Cómo encaja en el stack**: arquitectura y decisiones de FastAPI, PostgreSQL, React 19 y observabilidad | [leoneljfernandes/my_skills](https://github.com/leoneljfernandes/my_skills) |
| `modern-web-guidance` | **Qué API nativa usar** en el navegador: 210 guías de HTML, CSS, JS, accesibilidad, rendimiento y seguridad | paquete npm `modern-web-guidance` |

### Skills de `superpowers` (proceso)

| Skill | Cuándo se usa |
|---|---|
| `brainstorming` | Antes de cualquier trabajo creativo: aclarar intención y diseño |
| `writing-plans` | Convertir una especificación en un plan de tareas |
| `dispatching-parallel-agents` | Repartir tareas independientes entre agentes |
| `executing-plans`, `subagent-driven-development` | Ejecutar un plan, inline o con un subagente por tarea |
| `using-git-worktrees` | Aislar el trabajo en un worktree |
| `test-driven-development` | Escribir primero el test que falla |
| `systematic-debugging` | Diagnosticar antes de proponer un arreglo |
| `verification-before-completion` | Correr la verificación antes de decir "listo" |
| `requesting-code-review`, `receiving-code-review` | Pedir y recibir revisión con rigor técnico |
| `finishing-a-development-branch` | Decidir cómo integrar el trabajo terminado |
| `writing-skills` | Crear o editar skills |

`using-superpowers` y `diagnosing-superpowers` están en el almacén pero no se anuncian a los roles.

### Skills de `my_skills` (stack)

| Categoría | Skill | Decisión que fija |
|---|---|---|
| Backend | `scaffolding-fastapi-backends` | Orden de construcción, JWT, Docker, CI y referencias de seguridad |
| | `layering-fastapi-apps` | Capas api, schemas, services, repositorios; inyección con `Depends` |
| | `handling-fastapi-errors` | Excepciones de dominio y respuestas RFC 9457 `problem+json` |
| | `configuring-fastapi-settings` | `pydantic-settings`, secretos y configuración por entorno |
| Base de datos | `modeling-postgres-with-sqlalchemy` | Modelos SQLAlchemy 2.0, índices, restricciones, transacciones |
| | `configuring-sqlalchemy-sessions` | Engine, pool y sesiones async |
| | `migrating-with-alembic` | Migraciones seguras y reversibles |
| Frontend | `architecting-react-apps` | Estructura por features, hooks, composición |
| | `routing-with-react-router` | React Router en modo data (loaders, actions, rutas protegidas) |
| | `using-react-19-actions` | Formularios y mutaciones con Actions de React 19 |
| | `building-axios-clients` | Cliente HTTP, refresh de tokens, reintentos, errores tipados |
| | `handling-react-errors` | Error Boundaries y reporte de errores |
| | `optimizing-react-renders` | Cuándo memoizar y cuándo no |
| | `choosing-ssr-or-spa` | SPA contra SSR |
| | `vercel-index` | Elegir skills oficiales de Vercel |
| Observabilidad | `exposing-prometheus-metrics` | Métricas RED y de negocio, cardinalidad de labels |
| | `logging-json-to-loki` | Logs JSON correlacionados con trazas |
| | `tracing-with-opentelemetry` | Trazas distribuidas hacia Tempo |
| | `defining-grafana-slos` | SLOs, alertas multi-ventana y dashboards como código |
| Testing | `testing-fastapi-endpoints` | Tests de integración con base real y rollback por test |
| | `unit-testing-fastapi-services` | Tests unitarios; mocks solo en bordes externos |

### `modern-web-guidance` (plataforma web)

Guías compiladas por categoría (accesibilidad, formularios, rendimiento, seguridad, CSS, APIs del navegador, entre otras). Se consultan con `search_modern_web_guidance` y `retrieve_modern_web_guidance` antes de escribir código de cliente.

## Roles y qué skills recibe cada uno

Cada rol tiene `core` (se inyecta siempre) y `on_demand` (se anuncia como catálogo y se pide con `get_skill`). Además, `shared_on_demand` se anuncia a todos los roles.

| Rol | Foco | Skills `core` principales | `modern-web-guidance` |
|---|---|---|---|
| `supervisor` | Arquitectura, planes, requisitos de seguridad antes de delegar | brainstorming, writing-plans, dispatching-parallel-agents, scaffolding-fastapi-backends | No |
| `db` | PostgreSQL, SQLAlchemy, Alembic | TDD, verification, todas las de `database/*` | No |
| `backend` | FastAPI seguro por defecto | TDD, debugging, layering, errores, seguridad | No |
| `frontend` | React y plataforma web | TDD, debugging, architecting-react-apps, handling-react-errors | **Sí** |
| `qa` | Testing y revisión | requesting-code-review, `testing/*`, seguridad | **Sí** |
| `security` | Auditoría AppSec previa al PR | code review, debugging, referencia de seguridad | **Sí** |
| `observability` | Métricas, logs, trazas, SLOs | TDD, debugging, `observability/*` | No |

El flag `web_guidance: true` decide si las guías de `modern-web-guidance` entran en la búsqueda por rol.

## Decisiones técnicas y de arquitectura

**Tres fuentes, una jerarquía de precedencia.** Se inyecta en cada bundle de rol. En código de cliente, `modern-web-guidance` es la fuente principal y decide la API de plataforma; `my_skills` decide cómo se integra en la arquitectura; `superpowers` gobierna el proceso. Desempates:

| Tema | Decide la plataforma (`modern-web-guidance`) | Decide el stack (`my_skills`) |
|---|---|---|
| Formularios | Validación nativa: `required`, `pattern`, `:user-invalid` | Errores 422/409 como estado de la action (`using-react-19-actions`) |
| Rendimiento | Carga, prioridad de recursos, INP | Re-renders y memoización (`optimizing-react-renders`) |
| Seguridad del cliente | CSP, Trusted Types, sanitización, passkeys | Tokens en memoria y refresh en cookie httpOnly (`building-axios-clients`) |
| Navegación | View Transitions | Se activan desde el router (`routing-with-react-router`) |

Si no se pueden conciliar, se anota en el plan y se escala al supervisor.

**Roles declarativos en YAML.** Cambiar qué recibe un rol no requiere tocar código. Acepta carpetas de skill, archivos puntuales y globs (`my_skills/skills/database/*`). Una ruta inexistente genera un warning, no una caída.

**Integridad de roles verificada en CI.** `check_role_integrity` falla si un rol referencia una ruta que no existe, o si una skill del rol exige (`REQUIRED`) otra que ese rol no puede ver.

**Búsqueda con alcance por rol.** `search_skills(query, role=...)` busca solo dentro de lo que ese rol puede ver, sin tope de candidatos, para que el ruido de otras áreas (por ejemplo 210 guías web en una consulta de base de datos) no desplace resultados. Sin `role`, busca en las tres fuentes.

**Costo de contexto visible.** Cada skill reporta `token_estimate` y cada rol `core_tokens`, para decidir qué cargar sin sorpresas.

**Skills horneadas en la imagen.** El sync ocurre al construir la imagen, no al arrancar. El arranque es rápido (serverless) y no depende de internet. El costo: para servir contenido nuevo hay que reconstruir y redesplegar.

**Fuentes fijadas en `config/sources.lock.json`.**
- `superpowers`: commit exacto.
- `modern-web-guidance`: versión exacta, con verificación de integridad del tarball.
- `my_skills`: sigue la rama `main`, por decisión del equipo (se actualiza en cuanto se publica). Si falta una entrada en el lock, el sync falla en lugar de traer lo último.

**Falla cerrada en autenticación.** En modo HTTP el servidor no arranca sin `MCP_API_KEY`. La comparación del token es en tiempo constante. Desactivarlo exige `MCP_ALLOW_UNAUTHENTICATED=true` y deja un warning.

**Solo lectura.** Todas las tools declaran `read_only`, `idempotent` y `closed_world`.

**Doble acceso a las skills.** Además de las tools propias, se monta el proveedor nativo de skills de FastMCP (`MCP_ENABLE_NATIVE_SKILLS`), para clientes que ya lo soportan.

**Imagen mínima.** Build multi-stage: git y herramientas de sync solo en el primer stage; el runtime es `python:3.14-slim`, sin Node.js ni git, con usuario no root. El build usa `uv sync --locked`, así que un `uv.lock` desactualizado rompe el build.

**Evals de recuperación.** Tests sobre el corpus real que verifican que cada rol encuentra lo esperado en las primeras posiciones y que no entra ruido de otras áreas.

## Cómo consumir el servidor, paso a paso

### Opción A: local por stdio (IDE o CLI)

No necesita clave.

1. Instalá [uv](https://docs.astral.sh/uv/) y cloná el repo:
   ```bash
   git clone https://github.com/leoneljfernandes/my-mcp-server.git
   cd my-mcp-server
   ```
2. Instalá dependencias y descargá las skills:
   ```bash
   uv sync
   uv run python scripts/sync_skills.py     # deja las tres fuentes en ./skills_store
   ```
3. Registralo en tu cliente. Con Claude Code:
   ```bash
   claude mcp add devteam-skills -- uv --directory /ruta/absoluta/a/my-mcp-server run devteam-skills-mcp
   ```
   Para otros clientes, el comando a ejecutar es `uv --directory /ruta/a/my-mcp-server run devteam-skills-mcp`.
4. Verificá: pedile al agente `list_roles`. Debe devolver los 7 roles.

### Opción B: remoto por HTTP (Docker, Cloud Run, Render)

1. Generá una clave:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Levantá el servidor (local con Docker):
   ```bash
   cp .env.example .env        # pegá la clave en MCP_API_KEY
   docker compose up --build
   ```
   En Cloud Run o Render, definí `MCP_API_KEY` como secreto del servicio.
3. Comprobá que responde (el endpoint de salud es público y muestra las versiones sincronizadas):
   ```bash
   curl http://localhost:8000/health
   ```
4. Registralo en el cliente. Con Claude Code:
   ```bash
   claude mcp add --transport http devteam-skills http://localhost:8000/mcp \
     --header "Authorization: Bearer <TU_CLAVE>"
   ```
5. Para agentes en código, ver [`examples/langgraph_client.py`](examples/langgraph_client.py): usa `langchain-mcp-adapters` con transporte `streamable_http`, el header `Authorization` y variables `DEVTEAM_MCP_URL` y `MCP_API_KEY`.

### Flujo recomendado para un agente

1. **Cargar el rol:** `get_role_skills(role="backend")` devuelve reglas de precedencia, instrucciones, skills `core` y catálogo `on_demand`. O usá el prompt `bootstrap_agent(role, task)`, que arma el system prompt completo.
2. **Pedir lo que falte:** `get_skill(source, skill_name)` para una skill `on_demand` o un archivo `references/*.md`.
3. **Buscar:** `search_skills("migración sin bloqueo", role="db")`.
4. **En trabajo de UI:** `search_modern_web_guidance("form validation")` y luego `retrieve_modern_web_guidance("<id>")` antes de escribir código.

## Referencia de tools, resources y prompt

| Elemento | Qué hace |
|---|---|
| `list_roles` | Roles con cantidad de skills `core` y `on_demand` y `core_tokens` |
| `list_skills(source?)` | Skills disponibles, con `token_estimate` |
| `get_role_skills(role, include_on_demand=False)` | Bundle del rol: precedencia, instrucciones, `core` y catálogo |
| `get_skill(source, skill_name)` | Contenido exacto de una skill o referencia |
| `search_skills(query, source?, limit=10, role?)` | Búsqueda BM25; `role` restringe al alcance del rol |
| `search_modern_web_guidance(query, limit=10)` | Busca guías web y devuelve ids y resúmenes |
| `retrieve_modern_web_guidance(guide_id)` | Texto completo de hasta 5 guías (ids separados por coma) |
| Resource `skills://roles/{role}` | Mismo bundle que `get_role_skills` |
| Resource `skills://{source}/{skill}` | Una skill o archivo de referencia |
| Prompt `bootstrap_agent(role, task, include_on_demand)` | System prompt listo para usar |
| `GET /health` | Versiones sincronizadas (sin autenticación) |

## Configuración

Variables de entorno (ver [`.env.example`](.env.example)):

| Variable | Default | Descripción |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` o `streamable-http` |
| `MCP_HOST`, `PORT`, `MCP_PATH` | `0.0.0.0`, `8000`, `/mcp` | Solo modo HTTP |
| `MCP_API_KEY` | vacío | Obligatoria en HTTP; vacío o solo espacios cuenta como ausente |
| `MCP_ALLOW_UNAUTHENTICATED` | `false` | Solo desarrollo local: permite HTTP sin clave |
| `ALLOWED_ORIGINS` | vacío | Orígenes permitidos, separados por coma |
| `SKILLS_DIR`, `ROLES_CONFIG_PATH` | `./skills_store`, `./config/roles.yaml` | Rutas locales |
| `MCP_ENABLE_NATIVE_SKILLS` | `true` | Monta el proveedor nativo de skills de FastMCP |
| `GITHUB_TOKEN` | vacío | Opcional: solo si alguna fuente pasa a ser privada |
| `LOG_LEVEL` | `INFO` | Nivel de logs |

## Actualizar skills

Las skills viajan dentro de la imagen: para servir una versión nueva se reconstruye y redespliega.

- `uv run python scripts/sync_skills.py` sincroniza exactamente lo que dice `config/sources.lock.json` (`--lock PATH` para otro archivo).
- `uv run python scripts/sync_skills.py --update-lock` trae lo último de cada fuente y reescribe el lock.
- **PR semanal:** `.github/workflows/update-skills.yml` corre cada lunes 06:00 UTC (y a mano), ejecuta los evals y abre o actualiza el PR `bot/update-skills` con links de comparación. El deploy ocurre al mergearlo.
- **Aviso desde `my_skills`:** un push a `skills/**` en `my_skills` dispara el redeploy mediante `repository_dispatch` (`skills-updated`). Requiere el secret `MCP_DISPATCH_TOKEN` en el repo `my_skills` (un PAT con *Contents: Read and write* sobre este repo).
- **Aviso sobre la caché:** como `my_skills` sigue `main`, un servicio de build que reutilice la caché de capas puede servir contenido anterior. Forzá un build sin caché (`docker build --no-cache`, o la opción equivalente del servicio) si no ves los cambios.

## Docker y despliegue

Todos los repos de fuentes son públicos: no hace falta ningún token.

```bash
docker build -t devteam-skills-mcp .
docker compose up --build       # lee MCP_API_KEY de .env
```

El workflow `.github/workflows/ci-deploy.yml` corre tests y evals, y despliega a Cloud Run o Render al pushear a `main` o al recibir `skills-updated`. Secrets necesarios según el destino: `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `GCP_PROJECT_ID` (Cloud Run) o `RENDER_DEPLOY_HOOK_URL` (Render).

## Desarrollo y tests

```bash
uv run ruff check . && uv run mypy src scripts && uv run pytest -q
uv run pytest -m eval -v     # evals de recuperación sobre el corpus real (requiere sync)
```

La especificación original está en [`instructions.md`](instructions.md).
