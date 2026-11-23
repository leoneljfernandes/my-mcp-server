Actuá como un Arquitecto de Software Senior especialista en Python, Model Context Protocol (FastMCP v4) y Developer Experience (DevEx).

Tu objetivo es diseñar e implementar un **MCP Server completo ("DevTeam Skills MCP")** en Python con **FastMCP** que actúe como la **fuente única de verdad** de estándares y skills de desarrollo para un equipo de agentes especializados (consumido desde LangGraph v1 vía `langchain-mcp-adapters` o desde IDEs/clientes MCP como Cursor, OpenCode, Claude Desktop o Antigravity).

### Principios de Arquitectura
- **Desacoplado de LLMs:** Este servidor NO ejecuta modelos de lenguaje ni contiene lógica de agentes. Solo gestiona, sincroniza, indexa y expone skills (archivos Markdown), prompts base y herramientas de consulta.
- **Configuración declarativa y carga progresiva (*progressive disclosure*):** El mapeo entre roles y skills se define en `config/roles.yaml` separando skills **`core`** (siempre inyectadas al iniciar el rol) y **`on_demand`** (listadas como catálogo con nombre y descripción para que el agente las cargue con `get_skill` solo cuando la subtarea las requiera). Esto evita saturar la ventana de contexto y permite evolucionar `my_skills` sin tocar código Python.
- **Complementariedad y jerarquía de precedencia:** Las 3 fuentes cumplen roles distintos y se complementan. Tanto `get_role_skills` como `bootstrap_agent` deben incluir una regla de precedencia explícita:
  1. **`obra/superpowers` (Proceso e ingeniería):** gobierna *cómo* trabaja el agente (brainstorming, planificación, TDD, debugging sistemático, verificación antes de cerrar y code review).
  2. **`my_skills` (Arquitectura y decisiones de stack):** gobierna *con qué y cómo* se construye el proyecto (scaffolding, FastAPI, PostgreSQL/SQLAlchemy/Alembic, React, observabilidad y testing).
  3. **`modern-web-guidance` (Plataforma web moderna):** gobierna *qué APIs nativas* de HTML/CSS/JS usar en el navegador, adaptándolas al stack de `my_skills` sin degradar a patrones o librerías obsoletas.

### Fuentes de Skills a Integrar
El servidor carga skills locales almacenadas en `./skills_store/` (excluida en `.gitignore`) provenientes de 3 fuentes:
1. `superpowers` (`https://github.com/obra/superpowers`): metodología de ingeniería (`skills/<nombre>/SKILL.md`).
2. `modern-web-guidance` (paquete npm `modern-web-guidance`, descargado como tarball `.tgz` desde `https://registry.npmjs.org/modern-web-guidance/latest` en Python puro con `urllib`/`tarfile`): contiene las guías **ya compiladas** (sin macros de transclusión sin expandir como `{{ FEATURE_FALLBACKS(...) }}` del repo `-src`) y su índice de búsqueda, sin requerir Node.js ni `npx` en el servidor ni en el contenedor Docker.
3. `my_skills` (`https://github.com/leoneljfernandes/my_skills`): decisiones de arquitectura, scaffolding, backend, frontend, bases de datos, observabilidad y testing (`skills/<categoria>/<nombre>/SKILL.md` y sus archivos auxiliares bajo `references/*.md`).

Creá un script `scripts/sync_skills.py` idempotente y resiliente que:
- Para los repos git (`superpowers` y `my_skills`): clone con `--depth 1` si no existen, o actualice con `git fetch --depth 1 origin && git reset --hard FETCH_HEAD` (evita fallos de `--ff-only` ante historiales shallow/rebased). Si `GITHUB_TOKEN` está definido (útil si `my_skills` pasa a privado), pasarlo sin grabarlo en `.git/config` ni loguearlo.
- Para `modern-web-guidance`: descargue y extraiga el tarball npm compilado validando los miembros del tar contra *tar slip* (*path traversal*) antes de escribir en `./skills_store/modern-web-guidance/`.
- Genere un archivo `./skills_store/.sync_meta.json` con timestamp UTC y commit SHA / versión de cada fuente para exponerlo en `/health` y trazabilidad.

### Mapeo Inicial de Roles (`config/roles.yaml`)
Definí la estructura declarativa para los siguientes roles combinando las 3 fuentes. El cargador (`SkillRegistry`) debe soportar:
- Rutas a archivos `.md` específicos (incluyendo `references/*.md` dentro de una skill).
- Carpetas de una skill que contengan `SKILL.md` (cargando únicamente `SKILL.md` por defecto; sus archivos bajo `references/*.md` se listan/exponen bajo demanda vía `get_skill` y Resources para no inflar el contexto).
- **Carpetas de categoría / globs** (por ejemplo `my_skills/skills/database/*`) que expandan automáticamente todas las subskills contenidas, **deduplicando por ruta canónica resuelta** para evitar repeticiones.
- **Separación `core` vs `on_demand`** por rol (con `instructions` opcionales específicas del rol).
- **Degradación segura:** si una ruta o glob configurado no coincide con ningún archivo, registrar un warning claro en logs y continuar cargando el resto sin romper el servidor.

Mapeo inicial sugerido (aplicando seguridad *shift-left* en diseño, implementación y auditoría):
- `supervisor`:
  - `core`:
    - `superpowers/skills/brainstorming`
    - `superpowers/skills/writing-plans`
    - `superpowers/skills/dispatching-parallel-agents`
    - `my_skills/skills/backend/scaffolding-fastapi-backends`
    - `my_skills/skills/backend/scaffolding-fastapi-backends/references/security.md`
  - `on_demand`:
    - `my_skills/skills/frontend/choosing-ssr-or-spa`
    - `my_skills/skills/frontend/architecting-react-apps`
    - `my_skills/skills/security/*`
  - `instructions`: definir explícitamente en el plan los requisitos de auth/RBAC, protección contra IDOR y manejo de datos sensibles/PII antes de delegar.
- `db`:
  - `core`:
    - `superpowers/skills/test-driven-development`
    - `superpowers/skills/verification-before-completion`
    - `superpowers/skills/receiving-code-review`
    - `my_skills/skills/database/*`
- `backend`:
  - `core`:
    - `superpowers/skills/test-driven-development`
    - `superpowers/skills/systematic-debugging`
    - `superpowers/skills/verification-before-completion`
    - `superpowers/skills/receiving-code-review`
    - `my_skills/skills/backend/layering-fastapi-apps`
    - `my_skills/skills/backend/handling-fastapi-errors`
    - `my_skills/skills/backend/scaffolding-fastapi-backends/references/security.md`
  - `on_demand`:
    - `my_skills/skills/backend/*`
    - `my_skills/skills/observability/*`
    - `my_skills/skills/security/*`
- `frontend`:
  - `core`:
    - `superpowers/skills/test-driven-development`
    - `superpowers/skills/systematic-debugging`
    - `superpowers/skills/verification-before-completion`
    - `superpowers/skills/receiving-code-review`
    - `my_skills/skills/frontend/architecting-react-apps`
    - `my_skills/skills/frontend/handling-react-errors`
  - `on_demand`:
    - `my_skills/skills/frontend/*`
  - `instructions`: usar obligatoriamente `search_modern_web_guidance` y `retrieve_modern_web_guidance` (incluyendo guías de `security`) antes de implementar UI/HTML/CSS/JS.
- `qa`:
  - `core`:
    - `superpowers/skills/requesting-code-review`
    - `superpowers/skills/systematic-debugging`
    - `superpowers/skills/verification-before-completion`
    - `my_skills/skills/testing/*`
    - `my_skills/skills/backend/scaffolding-fastapi-backends/references/security.md`
  - `on_demand`:
    - `my_skills/skills/security/*`
  - `instructions`: consultar `modern-web-guidance` al auditar frontend y verificar tests de auth/permisos y ausencia de filtración de stacktraces o secretos.
- `security` *(AppSec Reviewer — pensado para correr en paralelo con `qa` como gate obligatorio previo al PR)*:
  - `core`:
    - `superpowers/skills/requesting-code-review`
    - `superpowers/skills/systematic-debugging`
    - `superpowers/skills/verification-before-completion`
    - `my_skills/skills/backend/scaffolding-fastapi-backends/references/security.md`
    - `my_skills/skills/security/*`
  - `instructions`: auditar OWASP API Top 10, auth/RBAC/IDOR, cookies/headers/CORS, exposición de secretos/PII, consultar guías `security` de `modern-web-guidance` y exigir validación con `bandit`, `pip-audit`, `npm audit` y `gitleaks`.

### Primitivas MCP a Exponer (`src/mcp_server/server.py`)
Todas las tools son **solo lectura** y deben declararse con **Tool Annotations** de MCP (`annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}`) para evitar prompts innecesarios de confirmación en clientes MCP, y devolver **modelos Pydantic v2 tipados** (generando `outputSchema` automático y compatibilidad estricta con `mypy`).

1. **Tools (`@mcp.tool`)**:
   - `list_roles() -> list[RoleSummary]`: devuelve los roles configurados en `roles.yaml` con su descripción y cantidad de skills `core` y `on_demand`.
   - `list_skills(source: Literal["superpowers", "modern-web-guidance", "my_skills"] | None = None) -> list[SkillSummary]`: lista todas las skills disponibles leyendo su `id`/`slug`, ruta relativa, nombre, `description` del frontmatter YAML y archivos `references` asociados si existen.
   - `get_role_skills(role: str, include_on_demand: bool = False) -> str`: devuelve las reglas de precedencia, instrucciones del rol, el contenido completo de las skills `core` y el catálogo indexado de las `on_demand` (o su contenido completo si `include_on_demand=True`).
   - `get_skill(source: str, skill_name: str) -> str`: devuelve el contenido exacto de una skill puntual o de un archivo auxiliar dentro de ella (soportando slug único del frontmatter y rutas relativas como `backend/layering-fastapi-apps` o `backend/scaffolding-fastapi-backends/references/security.md`).
   - `search_skills(query: str, source: str | None = None, limit: int = 10) -> list[SearchHit]`: busca con ranking BM25 (vía índice **SQLite FTS5** en memoria usando `sqlite3` de stdlib, sin dependencias externas) sobre todos los `.md` de `./skills_store/` y devuelve los fragmentos más relevantes con ruta y puntaje.
   - `search_modern_web_guidance(query: str, limit: int = 10) -> list[WebGuideSummary]`: busca en Python puro (FTS5/índice compilado) sobre las guías compiladas de `modern-web-guidance` devolviendo `[{id, category, description}]`.
   - `retrieve_modern_web_guidance(guide_id: str) -> str`: devuelve el contenido completo y ya compilado de la guía correspondiente a un `guide_id` (acepta varios IDs separados por coma, con tope máximo ej. 5 por llamada).
2. **Resources (`@mcp.resource`)**:
   - `skills://roles/{role}`: expone el bundle de skills del rol como recurso de solo lectura.
   - `skills://{source}/{skill_name*}`: expone una skill individual (o archivo en `references/`) usando wildcard RFC 6570 `{skill_name*}` para soportar subcategorías con `/`.
3. **Prompts (`@mcp.prompt`)**:
   - `bootstrap_agent(role: str, task: str, include_on_demand: bool = False)`: genera un prompt de sistema listo para usar que inyecta la jerarquía de precedencia, las instrucciones del rol, las skills `core` (+ catálogo `on_demand`) y la tarea asignada.
4. **Native Skills Provider de FastMCP v4.2+ (en paralelo a las tools/resources estándar)**:
   - Montar opcionalmente `SkillCatalogProvider` (configurable vía `MCP_ENABLE_NATIVE_SKILLS=true`) alimentado con los directorios de skills válidos (`SKILL.md` con frontmatter compatible) de `superpowers` y `my_skills`, con degradación segura si alguna skill individual no cumple la validación estricta de FastMCP. Así el servidor soporta tanto clientes universales (LangGraph, Cursor, OpenCode) como clientes con la extensión nativa `skills/list` / `read_skill` / `download_skill`.

### Stack Técnico, Seguridad y Despliegue (Local y Cloud Gratuito)
- **Python y dependencias:** `requires-python = ">=3.12"` (objetivo recomendado Python 3.13/3.14 con **`uv`**), **`fastmcp>=4.2.4,<5`** (fijado a la rama v4 estable con los últimos parches de seguridad; no cruzar majors v3/v4), `pydantic>=2`, `pydantic-settings>=2`, `pyyaml>=6`.
- **Transportes configurables mediante `MCP_TRANSPORT`:**
  - `stdio`: para uso local en IDEs/CLIs.
  - `streamable-http`: escucha en `0.0.0.0`, puerto tomado de `PORT` (default `8000`, compatible con Google Cloud Run, Render y Hugging Face Spaces) y path `/mcp`.
  - **Importante en FastMCP v4:** pasar `stateless_http=True` a `mcp.run(transport="streamable-http", host=..., port=..., stateless_http=True)` o `mcp.http_app(stateless_http=True)` (nunca en el constructor `FastMCP(...)`, donde fue removido), garantizando tolerancia a cold starts, reinicios y escalado serverless sin errores de `Mcp-Session-Id`.
- **Seguridad de conexión y hardening del MCP Server:**
  - **En tránsito:** asumir terminación TLS/HTTPS en el hosting (Google Cloud Run, FastMCP Cloud o Render); nunca exponer HTTP sin cifrar en internet.
  - **Autenticación Bearer Token (`MCP_API_KEY`):** si `MCP_API_KEY` está definida en modo `streamable-http`, proteger `/mcp` mediante un `TokenVerifier` de FastMCP (o middleware ASGI) que valide el token en tiempo constante con `hmac.compare_digest`, rechazando con `401` sin loguear nunca el token ni el header `Authorization`. Exponer `/health` mediante `@mcp.custom_route("/health", methods=["GET"])` (público por diseño en FastMCP) devolviendo estado + metadatos de `.sync_meta.json` (versiones/SHAs y conteo de skills). *(Compatible a futuro con OAuth 2.1 o Cloud Run IAM).*
  - **Anti DNS-rebinding y CORS:** soportar `ALLOWED_ORIGINS` (lista explícita, sin `*` abierto por defecto) y aprovechar la validación de `Host`/`Origin` de FastMCP.
  - **Prevención de abuso y *path traversal*:** validación estricta `Path.resolve().is_relative_to(...)` en toda lectura de archivos y extracción de tarballs; límites máximos en `query` (`<= 200` caracteres), `limit` (`<= 25`) y cantidad de IDs en `retrieve_modern_web_guidance` (`<= 5`).
  - **Contenedor mínimo y solo lectura:** sin ejecución de subprocesos de shell/Node en runtime y corriendo con **usuario no-root** (`USER appuser`) en el `Dockerfile`.
- **Empaquetado, CI/CD y tests:**
  - `pyproject.toml` (con `uv`, configuración de `mypy --strict` y `ruff`), `.env.example`, `.gitignore` (incluyendo `skills_store/`), `Dockerfile` multi-stage con `uv` (usuario no-root) que ejecute `scripts/sync_skills.py` en build time (horneando las skills en la imagen para despliegue serverless), y `docker-compose.yml` para desarrollo local (permitiendo montar `./skills_store` como volumen opcional).
  - **GitHub Actions (`.github/workflows/ci-deploy.yml`):**
    - Job de CI en `push` y `pull_request`: `ruff check`, `mypy --strict`, `pytest`.
    - Job de auto-redeploy disparado por `schedule` semanal, `workflow_dispatch` manual y `repository_dispatch` (evento `skills-updated`, listo para dispararse desde un push en `my_skills`), que reconstruye y despliega la imagen (plantilla lista para Google Cloud Run o webhook de Render).
  - **Tests unitarios + evals de recuperación (`pytest`):**
    - Unitarios cubriendo `SkillRegistry` (globs, deduplicación, `core`/`on_demand`, `SKILL.md` + `references/*.md`, rutas faltantes, protección contra *path traversal* y *tar slip*), búsqueda FTS5, tools MCP (structured output, annotations, límites de `query`/`limit`), recursos `{skill_name*}`, `SkillCatalogProvider` y autenticación Bearer (`401` sin token / token inválido, `200` con token válido, `/health` público).
    - **Retrieval evals (`tests/test_retrieval_evals.py`, marcados con `@pytest.mark.eval`):** batería de 10–15 consultas reales sobre el corpus sincronizado (ej. `"alembic timeout"`, `"fastapi error handling"`, `"prometheus metrics"`, `"tdd red green refactor"`, `"animate dialog backdrop"`, `"responsive table"`) que verifique que `search_skills` y `search_modern_web_guidance` devuelvan la skill/guía esperada dentro del **Top-3**.

### Entregables (Paso a Paso)
Aplicá Clean Architecture, tipado estricto (`mypy --strict` / modelos Pydantic v2) y manejo explícito de errores.
Empezá generando:
1. El árbol de directorios completo del proyecto.
2. `pyproject.toml`, `.env.example`, `.gitignore` y `config/roles.yaml`.
3. `scripts/sync_skills.py` y el núcleo de carga/indexación FTS5 (`src/mcp_server/config.py`, `src/mcp_server/models.py`, `src/mcp_server/registry.py`).
4. El servidor FastMCP v4 completo (`src/mcp_server/server.py`, incluyendo `TokenVerifier` en tiempo constante, `@mcp.custom_route("/health")`, Tool Annotations, `SkillCatalogProvider` opcional y `stateless_http=True` en `.run()`/`.http_app()`) y un ejemplo corto actualizado de cómo conectarlo desde LangGraph v1 con `langchain-mcp-adapters>=0.1.0` (`MultiServerMCPClient` sin `async with` + `from langchain.agents import create_agent`).
5. `Dockerfile`, `docker-compose.yml` y la suite de tests unitarios con `pytest` (`tests/`).
6. `.github/workflows/ci-deploy.yml` (CI + auto-redeploy programado/por `repository_dispatch`) y `tests/test_retrieval_evals.py` (evals Top-3 de recuperación).
