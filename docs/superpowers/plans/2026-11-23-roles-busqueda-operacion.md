# Roles, búsqueda y operación — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que las tres fuentes de skills se complementen de verdad por rol (sin referencias colgantes ni ruido cruzado) y cerrar los riesgos operativos del servidor (auth, cadena de suministro, lockfile, redeploy).

**Architecture:** Los cambios de complementariedad son declarativos (`config/roles.yaml` + un nuevo bloque `shared_on_demand`) más dos capacidades del `SkillRegistry`: verificar integridad de roles y filtrar la búsqueda por rol. Los cambios operativos mueven la versión de cada fuente a un lockfile revisable (`config/sources.lock.json`) que un workflow semanal propone actualizar por PR, en lugar de redeployar `HEAD` sin revisión.

**Tech Stack:** Python 3.14, FastMCP v4, pydantic v2, SQLite FTS5, uv, GitHub Actions, Docker.

**Spec:** `instructions.md` + análisis del 2026-11-23 (puntos 1–4 de "Qué haría" y sección "4. Riesgos y operación").

## Global Constraints

- Todas las tools MCP siguen siendo read-only con `READ_ONLY_ANNOTATIONS`.
- `ruff check .`, `mypy src scripts` (strict) y `pytest` deben quedar verdes al cierre de cada tarea.
- Los tests que necesitan el corpus real van marcados `@pytest.mark.eval` en `tests/test_retrieval_evals.py`; el resto usa los fixtures sintéticos de `tests/conftest.py`.
- Nunca loguear `MCP_API_KEY`, `GITHUB_TOKEN` ni el header `Authorization`.
- Prosa de roles y mensajes al agente en español; identificadores de código en inglés.
- Límite de línea de ruff: el configurado en `pyproject.toml`.

## Review Focus

1. Un `roles.yaml` con un rol cuyo `shared_on_demand` o `core` repite una skill: la skill aparece una sola vez en el bundle (dedup por ruta absoluta, como hoy).
2. `search_skills(role="inexistente")` → `RoleNotFoundError` con la lista de roles, no una lista vacía silenciosa.
3. Servidor `streamable-http` sin `MCP_API_KEY` y sin `MCP_ALLOW_UNAUTHENTICATED=true` → no arranca, con mensaje claro; `stdio` sin key sigue arrancando.
4. Lockfile con un SHA que el remoto ya no tiene (force-push upstream) → `sync_skills.py` falla con exit 1 y mensaje que nombra la fuente, nunca cae silenciosamente a `HEAD`.
5. Skill de superpowers que referencia `superpowers:<x>` donde `<x>` no existe en el corpus → el test de integridad lo reporta como inexistente (distinto de "no asignado al rol").

---

## Parte A — Complementariedad, integridad y búsqueda (puntos 1–3)

### Task 1: Catálogo compartido `shared_on_demand` y ajuste de roles

Responde también a "¿se puede dejar disponible el resto?": todo ya es accesible por `get_skill`/`search_skills`, pero el agente no sabe que existe. Este bloque lo anuncia en todos los roles como catálogo (nombre + descripción, ~1 línea por skill), sin cargar contenido.

**Files:**
- Modify: `src/mcp_server/models.py` (`RolesFileConfig`)
- Modify: `src/mcp_server/registry.py` (`ResolvedRole`, `_resolve_all_roles`, `get_role_skills`)
- Modify: `config/roles.yaml`
- Modify: `src/mcp_server/server.py:163` (Literal de roles del prompt)
- Test: `tests/test_registry.py`, `tests/conftest.py` (fixture `sample_roles_yaml`), `tests/test_retrieval_evals.py`

**Interfaces:**
- Produces: `RolesFileConfig.shared_on_demand: list[str]` (default `[]`); `RoleConfig.web_guidance: bool` (default `False`); `ResolvedRole.shared: tuple[IndexedSkill, ...]` (excluye lo que ya está en core/on_demand del rol); `SkillRegistry.allowed_skill_ids(role: str) -> frozenset[tuple[SourceName, str]]` = core ∪ on_demand ∪ shared del rol, más todas las guías de modern-web-guidance si `web_guidance` es `True`. Tasks 2 y 3 lo consumen.

- [ ] **Step 1: Tests que fallan**

En `conftest.py` agregar a `sample_roles_yaml` `shared_on_demand: [superpowers/skills/brainstorming, superpowers/skills/test-driven-development]` (el fixture tiene roles `backend` —con TDD en core— y `db`).

```python
def test_shared_on_demand_listed_in_every_role_and_deduplicated(registry: SkillRegistry) -> None:
    for role in ("backend", "db"):
        shared = registry.get_role_skills(role).split("## Catálogo Compartido")[1]
        assert "`superpowers` / `brainstorming`" in shared
    backend_shared = registry.get_role_skills("backend").split("## Catálogo Compartido")[1]
    assert "`superpowers` / `test-driven-development`" not in backend_shared  # ya es core
    db_shared = registry.get_role_skills("db").split("## Catálogo Compartido")[1]
    assert "`superpowers` / `test-driven-development`" in db_shared

def test_allowed_skill_ids_union(registry: SkillRegistry) -> None:
    ids = registry.allowed_skill_ids("backend")
    assert ("superpowers", "brainstorming") in ids
    assert ("my_skills", "layering-fastapi-apps") in ids
```

- [ ] **Step 2:** `uv run pytest tests/test_registry.py -k "shared or allowed" -v` → FAIL (`shared_on_demand` desconocido / atributo inexistente).

- [ ] **Step 3: Implementar.** `_resolve_all_roles` expande `shared_on_demand` una vez con `_expand_pattern` (mismas reglas de missing/unsafe, los patrones faltantes van a `missing_patterns` de cada rol) y por rol filtra los que ya están en `seen_paths`. `get_role_skills` agrega después del catálogo on_demand:
  `## Catálogo Compartido (disponible para todos los roles vía \`get_skill\`)` con el mismo formato de línea que el catálogo on_demand, siempre como catálogo (también con `include_on_demand=True`), y una línea final:
  `- **Modern Web Guidance** (<N> guías, fuente principal para código de cliente): categorías <lista de categorías ordenadas>. Usá \`search_modern_web_guidance\` + \`retrieve_modern_web_guidance\`.` — N y categorías calculados desde el índice; esta línea solo aparece en roles con `web_guidance: true`. Test adicional: el bundle de `backend` (sin flag) no contiene "Modern Web Guidance"; con el flag en un rol sintético, sí.

- [ ] **Step 4: Actualizar `config/roles.yaml`:**

```yaml
shared_on_demand:
  - superpowers/skills/executing-plans
  - superpowers/skills/subagent-driven-development
  - superpowers/skills/using-git-worktrees
  - superpowers/skills/finishing-a-development-branch
  - superpowers/skills/test-driven-development
  - superpowers/skills/systematic-debugging
  - superpowers/skills/writing-skills
```
  No se incluyen `using-superpowers` (instruye a invocar la tool `Skill` de Claude Code, no aplica a agentes MCP) ni `diagnosing-superpowers` (depura el harness de superpowers). Siguen accesibles por `get_skill`.

  Reemplazar `precedence_rules` por este texto (y sincronizar `DEFAULT_PRECEDENCE_RULES` en `registry.py` con el mismo contenido):

```markdown
### Jerarquía de Precedencia entre Fuentes
Cada fuente responde una pregunta distinta; se complementan, no compiten.
1. **obra/superpowers — cómo trabajás:** brainstorming, planes, TDD, debugging sistemático, verificación y code review. Aplica a todos los roles.
2. **modern-web-guidance — fuente principal en código de cliente:** para HTML, CSS, JS de navegador, formularios, accesibilidad, rendimiento web y seguridad de cliente, la guía decide la API o el patrón de plataforma. Se consulta antes de implementar.
3. **my_skills — cómo encaja en el stack:** decide la arquitectura (React 19 + React Router data mode + Axios, FastAPI, PostgreSQL/SQLAlchemy/Alembic, observabilidad, testing). En el cliente integra el patrón de modern-web-guidance en esa arquitectura; fuera del navegador es la autoridad técnica.

Desempates en el cliente:
- **Formularios:** formato y obligatoriedad con validación nativa (`required`, `type`, `pattern`, `:user-invalid` + puente a `aria-invalid`) según modern-web-guidance; errores de negocio (422/409) como estado de la action según `using-react-19-actions`, pintados en el mismo lugar del campo.
- **Rendimiento:** carga, prioridad de recursos, INP y long tasks según modern-web-guidance; re-renders, memoización y virtualización de listas interactivas según `optimizing-react-renders`.
- **Seguridad:** CSP, Trusted Types, sanitización de HTML y passkeys según modern-web-guidance; tokens (access en memoria, refresh en cookie httpOnly) y refresh según `building-axios-clients`.
- **Navegación:** View Transitions según modern-web-guidance, activadas desde el router de `routing-with-react-router`.
- Si no se pueden conciliar: la API de plataforma la decide modern-web-guidance y la estructura my_skills; si aun así chocan, anotalo en el plan y escalalo al supervisor.
```

  Flag `web_guidance: true` en `frontend`, `qa` y `security`.

  Cambios por rol:
  - `backend.on_demand` += `my_skills/skills/testing/*`; `backend.instructions` += "Al escribir tests cargá `testing-fastapi-endpoints` (integración) o `unit-testing-fastapi-services` (lógica de servicio)."
  - `db.on_demand` = `[my_skills/skills/testing/testing-fastapi-endpoints]`.
  - Nuevo rol `observability` — description: "SRE/Observabilidad: métricas Prometheus, logs JSON a Loki, trazas OpenTelemetry/Tempo, SLOs y alertas en Grafana, más contenedores y CI."; core: `superpowers/skills/test-driven-development`, `superpowers/skills/systematic-debugging`, `superpowers/skills/verification-before-completion`, `my_skills/skills/observability/*`; on_demand: `my_skills/skills/backend/scaffolding-fastapi-backends/references/docker.md`, `.../references/ci.md`, `my_skills/skills/backend/configuring-fastapi-settings`; instructions: "Toda métrica/log/span nuevo se verifica contra el stack real (Prometheus/Loki/Tempo) antes de cerrar; sin PII en labels ni logs; cardinalidad de labels acotada."
  - `frontend`: sin cambios de roles (no hay skills de testing frontend en `my_skills`; queda como gap de contenido, fuera de este plan).

- [ ] **Step 5:** Actualizar el Literal de `bootstrap_agent` en `server.py` agregando `"observability"`, y en `test_retrieval_evals.py` renombrar a `test_all_roles_loaded_from_real_corpus` con el set de 7 roles.

- [ ] **Step 6:** `uv run pytest -q && uv run pytest -m eval -q` → PASS. `uv run ruff check . && uv run mypy src scripts` → limpio.

- [ ] **Step 7: Commit** `feat(roles): shared_on_demand catalog, testing skills per role, observability role`

### Task 2: Test de integridad de roles en CI

**Files:**
- Modify: `src/mcp_server/registry.py`
- Modify: `src/mcp_server/models.py`
- Test: `tests/test_registry.py`, `tests/test_retrieval_evals.py`

**Interfaces:**
- Consumes: `allowed_skill_ids(role)` (Task 1).
- Produces: `RoleIntegrityIssue(BaseModel)`: `role: str`, `skill: str`, `kind: Literal["missing_pattern", "unknown_reference", "unassigned_reference"]`, `target: str`; `SkillRegistry.check_role_integrity() -> list[RoleIntegrityIssue]`.

- [ ] **Step 1: Tests que fallan** (fixtures sintéticos: crear `superpowers/skills/writing-plans/SKILL.md` sin asignarla a ningún rol ni a `shared_on_demand`, y agregar al TDD sintético —core de `backend`— el texto `REQUIRED: superpowers:writing-plans, superpowers:brainstorming, superpowers:no-existe`).

```python
def test_check_role_integrity_reports_kinds(registry: SkillRegistry) -> None:
    found = {(i.role, i.kind, i.target) for i in registry.check_role_integrity()}
    assert ("backend", "unknown_reference", "no-existe") in found
    assert ("backend", "unassigned_reference", "writing-plans") in found
    assert ("backend", "unassigned_reference", "brainstorming") not in found  # está en shared
    assert ("db", "missing_pattern", "my_skills/skills/nonexistent-folder") in found
```

  Y en evals (corpus real):

```python
def test_real_roles_have_no_integrity_issues(real_registry: SkillRegistry) -> None:
    assert real_registry.check_role_integrity() == []
```

- [ ] **Step 2:** Correr ambos → FAIL (método inexistente).

- [ ] **Step 3: Implementar.** Regex `superpowers:([a-z0-9-]+)` sobre el contenido de cada skill en core ∪ on_demand del rol (no sobre `shared`: las skills compartidas no se inyectan). Si el id no existe en `superpowers` → `unknown_reference`; si existe pero no está en `allowed_skill_ids(role)` → `unassigned_reference`. Cada `missing_patterns` → `missing_pattern`. Orden determinista (role, skill, target).

- [ ] **Step 4:** `uv run pytest -q && uv run pytest -m eval -q` → PASS (con el `roles.yaml` de Task 1 el corpus real no debe tener issues; si aparece alguno, se corrige `roles.yaml`, no el test).

- [ ] **Step 5: Commit** `test(roles): fail CI on missing patterns and unresolved superpowers cross-refs`

### Task 3: Búsqueda con alcance por rol y costo en tokens

**Decisión del usuario (2026-11-23):** modern-web-guidance es la fuente principal en código de cliente; no se excluye de la búsqueda. El ruido observado era de ranking (guías de UI apareciendo en consultas de backend/db/observabilidad), no de contenido, y se resuelve con el alcance por rol: en roles con `web_guidance: true` las guías entran; en los demás, no. Sin `role`, `search_skills` se comporta como hoy (todas las fuentes, según `instructions.md`).

**Files:**
- Modify: `src/mcp_server/registry.py` (`search_skills`, `_run_fts_query`, `list_skills`, `list_roles`)
- Modify: `src/mcp_server/models.py` (`SkillSummary`, `RoleSummary`)
- Modify: `src/mcp_server/server.py` (firma de `search_skills`)
- Test: `tests/test_registry.py`, `tests/test_server.py`, `tests/test_retrieval_evals.py`

**Interfaces:**
- Consumes: `allowed_skill_ids(role)` (Task 1).
- Produces: `search_skills(query: str, source: SourceName | None = None, limit: int = 10, role: str | None = None) -> list[SearchHit]`; `SkillSummary.token_estimate: int`; `RoleSummary.core_tokens: int`; helper `_estimate_tokens(skill: IndexedSkill) -> int` = `skill.token_count` si existe, si no `ceil(len(content) / 4)`.

- [ ] **Step 1: Tests que fallan**

```python
def test_search_without_role_keeps_all_sources(registry: SkillRegistry) -> None:
    hits = registry.search_skills("animate dialog top layer")
    assert hits[0].id == "animate-to-from-top-layer"

def test_role_with_web_guidance_includes_guides(registry: SkillRegistry) -> None:
    # fixture: agregar rol sintético `frontend` con web_guidance: true
    hits = registry.search_skills("animate dialog top layer", role="frontend")
    assert hits[0].id == "animate-to-from-top-layer"
    assert all(h.source != "modern-web-guidance"
               for h in registry.search_skills("animate dialog top layer", role="backend"))

def test_search_scoped_to_role(registry: SkillRegistry) -> None:
    backend_ids = [h.id for h in registry.search_skills("prometheus metrics", role="backend")]
    assert "exposing-prometheus-metrics" in backend_ids  # on_demand de backend
    db_hits = registry.search_skills("prometheus metrics", role="db")
    assert "exposing-prometheus-metrics" not in [h.id for h in db_hits]
    assert all((h.source, h.id) in registry.allowed_skill_ids("db") for h in db_hits)

def test_search_unknown_role_raises(registry: SkillRegistry) -> None:
    with pytest.raises(RoleNotFoundError):
        registry.search_skills("x", role="nope")

def test_token_estimates_exposed(registry: SkillRegistry) -> None:
    assert all(s.token_estimate > 0 for s in registry.list_skills())
    assert all(r.core_tokens > 0 for r in registry.list_roles() if r.core_count)
```

  En evals, regresión del ruido observado y del rol principal:

```python
@pytest.mark.parametrize(("query", "role"), [
    ("migración sin downtime alembic", "db"),
    ("alertas burn rate slo", "observability"),
])
def test_role_search_has_no_web_guidance_noise(real_registry, query, role) -> None:
    hits = real_registry.search_skills(query, role=role, limit=3)
    assert hits and all(h.source != "modern-web-guidance" for h in hits)

def test_frontend_form_validation_surfaces_web_guidance(real_registry) -> None:
    ids = [h.id for h in real_registry.search_skills("validate input after interaction form", role="frontend", limit=3)]
    assert "validate-input-after-interaction" in ids
```

- [ ] **Step 2:** Correr → FAIL.

- [ ] **Step 3: Implementar.** Con `role`, filtrar los candidatos reordenados por `allowed_skill_ids(role)` antes de cortar a `limit` (el pool de candidatos ya es `max(limit*6, 30)`; si con rol queda corto, subir el pool a 200 solo en ese caso). Validar rol con el mismo `RoleNotFoundError` de `get_role_skills`. Actualizar el docstring de la tool: `role` acota la búsqueda a las skills del rol (incluye modern-web-guidance solo en roles web) y es lo recomendado para agentes con rol asignado.

- [ ] **Step 4:** `uv run pytest -q && uv run pytest -m eval -q` → PASS; ruff + mypy limpios.

- [ ] **Step 5: Commit** `feat(search): role-scoped search and token estimates`

---

## Parte B — Riesgos y operación (punto 4)

Análisis por riesgo, con la decisión tomada:

| Riesgo | Impacto | Decisión |
|---|---|---|
| Auth fail-open en `streamable-http` sin `MCP_API_KEY` | Servidor público sin auth en Cloud Run (`--allow-unauthenticated`) si falta el secreto | Fail-closed con opt-out explícito (Task 4) |
| `HEAD` sin fijar en superpowers + redeploy semanal | Un cambio upstream se vuelve instrucción de agente sin revisión | Lockfile + PR semanal de actualización (Task 5) |
| `repository_dispatch` nunca disparado | Cambios en `my_skills` no llegan hasta el lunes | Workflow en `my_skills` (Task 6) |
| `uv sync --frozen \|\| uv sync` | Si el lock no coincide se resuelve de nuevo y se ignora el lock | `--locked` sin fallback (Task 7) |
| Servidor sin recarga | Actualizar skills exige reiniciar | **No se implementa:** las skills van horneadas en la imagen (inmutable, reproducible); en local, el IDE reinicia el proceso stdio. Un reload en caliente rompería la trazabilidad `/health` ↔ imagen. Se documenta en README. |

### Task 4: Auth fail-closed

**Files:**
- Modify: `src/mcp_server/config.py`, `src/mcp_server/server.py`
- Modify: `.env.example`, `docker-compose.yml`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `Settings.mcp_allow_unauthenticated: bool` (alias `MCP_ALLOW_UNAUTHENTICATED`, default `False`); `class InsecureConfigError(RuntimeError)`; `ensure_auth_configured(cfg: Settings) -> None` en `server.py`, llamada al inicio de `create_http_app` y en `main()` cuando `mcp_transport == "streamable-http"`.

- [ ] **Step 1: Tests que fallan**

```python
def test_http_app_refuses_to_start_without_api_key(sample_roles_yaml, registry) -> None:
    cfg = Settings(MCP_TRANSPORT="streamable-http", SKILLS_DIR=registry.skills_dir,
                   ROLES_CONFIG_PATH=sample_roles_yaml)
    with pytest.raises(InsecureConfigError, match="MCP_API_KEY"):
        create_http_app(settings=cfg, registry=registry)

def test_http_app_allows_explicit_unauthenticated_opt_out(sample_roles_yaml, registry) -> None:
    cfg = Settings(MCP_TRANSPORT="streamable-http", MCP_ALLOW_UNAUTHENTICATED=True,
                   SKILLS_DIR=registry.skills_dir, ROLES_CONFIG_PATH=sample_roles_yaml)
    assert create_http_app(settings=cfg, registry=registry) is not None
```

- [ ] **Step 2:** `uv run pytest tests/test_server.py -v` → FAIL.
- [ ] **Step 3:** Implementar. Mensaje: `"MCP_API_KEY es obligatoria en streamable-http. Definila o, solo para desarrollo local, MCP_ALLOW_UNAUTHENTICATED=true."` Con opt-out activo, loguear WARNING una vez. En `.env.example` documentar la variable (default `false`); en `docker-compose.yml` agregar `MCP_ALLOW_UNAUTHENTICATED: ${MCP_ALLOW_UNAUTHENTICATED:-false}`.
- [ ] **Step 4:** Tests + ruff + mypy → PASS.
- [ ] **Step 5: Commit** `fix(auth): fail closed when streamable-http has no MCP_API_KEY`

### Task 5: Fijar versiones de las fuentes y PR semanal de actualización

**Files:**
- Create: `config/sources.lock.json`
- Modify: `scripts/sync_skills.py`
- Modify: `Dockerfile` (quitar `ARG MODERN_WEB_GUIDANCE_VERSION=latest`)
- Modify: `.github/workflows/ci-deploy.yml` (quitar `schedule` del deploy)
- Create: `.github/workflows/update-skills.yml`
- Test: `tests/test_sync_skills.py`

**Interfaces:**
- Produces: formato del lock:
  ```json
  {"superpowers": {"ref": "<sha40>"}, "my_skills": {"ref": "main"}, "modern-web-guidance": {"version": "1.0.1"}}
  ```
  `my_skills` sigue `main` (repo propio, ya revisado al hacer push); superpowers y mwg fijados.
  `load_lock(path: Path) -> dict[str, dict[str, str]]`; `sync_git_repo(..., ref: str | None = None)`; `sync_all(..., lock: dict[str, dict[str, str]] | None = None)`; CLI `--lock PATH` (default `config/sources.lock.json`) y `--update-lock` (sincroniza a lo último y reescribe el lock con los SHAs/versión resueltos).

- [ ] **Step 1: Tests que fallan** (sin red: repo git local creado en `tmp_path` con dos commits, URL `file://`; `GIT_SOURCES` parcheado con `monkeypatch`)

```python
def test_sync_git_repo_checks_out_pinned_sha(tmp_path, local_repo_two_commits) -> None:
    first_sha, _ = local_repo_two_commits.shas
    meta = sync_git_repo("x", local_repo_two_commits.url, tmp_path / "x", ref=first_sha)
    assert meta["commit"] == first_sha

def test_sync_git_repo_unknown_sha_fails_naming_source(tmp_path, local_repo_two_commits) -> None:
    with pytest.raises(RuntimeError, match="x"):
        sync_git_repo("x", local_repo_two_commits.url, tmp_path / "x", ref="0" * 40)

def test_update_lock_writes_resolved_refs(tmp_path, local_repo_two_commits, monkeypatch) -> None:
    ...  # --update-lock con fuente git parcheada → lock contiene el SHA del último commit
```

- [ ] **Step 2:** `uv run pytest tests/test_sync_skills.py -v` → FAIL.
- [ ] **Step 3: Implementar.** Con `ref`: `git fetch --depth 1 origin <ref>` + `reset --hard FETCH_HEAD` (también en el primer clone: `git init` + `remote add` + fetch, en lugar de `clone`). Si `ref` es SHA de 40 hex, verificar `rev-parse HEAD == ref`, si no `RuntimeError` con el nombre de la fuente. mwg usa `lock["modern-web-guidance"]["version"]`; `--mwg-version` y `MODERN_WEB_GUIDANCE_VERSION` se eliminan (una sola fuente de verdad). `.sync_meta.json` guarda también el `ref` pedido.
- [ ] **Step 4:** `update-skills.yml`: `schedule` lunes 06:00 UTC + `workflow_dispatch`; corre `uv run python scripts/sync_skills.py --update-lock`, luego `uv run pytest -m eval -q`, y abre/actualiza un PR con `peter-evans/create-pull-request@v7` (branch `bot/update-skills`). El cuerpo del PR incluye, por fuente git cuyo SHA cambió, el link `https://github.com/<owner>/<repo>/compare/<old>...<new>`, y para mwg la versión vieja → nueva. Permisos del workflow: `contents: write`, `pull-requests: write`. En `ci-deploy.yml` quitar el `schedule` (el deploy pasa a ocurrir al mergear el PR, vía `push` a main).
- [ ] **Step 5:** Tests + ruff + mypy → PASS; `uv run python scripts/sync_skills.py` local reproduce los SHAs de `.sync_meta.json` actual.
- [ ] **Step 6: Commit** `feat(sync): pin skill sources in sources.lock.json and propose updates via weekly PR`

### Task 6: Disparo de redeploy desde `my_skills`

Repo: `/home/leonel/my_skills` (remoto `leoneljfernandes/my_skills`). Requiere que `my-mcp-server` ya esté pusheado (remoto `leoneljfernandes/my-mcp-server`, hoy sin commits).

**Files:**
- Create (en `my_skills`): `.github/workflows/notify-mcp-server.yml`

- [ ] **Step 1:** Workflow `on: push: branches: [main], paths: ["skills/**"]`, un job que usa `peter-evans/repository-dispatch@v3` con `repository: leoneljfernandes/my-mcp-server`, `event-type: skills-updated`, `token: ${{ secrets.MCP_DISPATCH_TOKEN }}`.
- [ ] **Step 2 (manual, usuario):** crear un fine-grained PAT con acceso solo a `my-mcp-server`, permiso *Contents: Read and write*, y guardarlo como secret `MCP_DISPATCH_TOKEN` en `my_skills`.
- [ ] **Step 3: Verificación:** push de un cambio trivial en `skills/` → en `my-mcp-server` aparece un run `repository_dispatch` de `ci-deploy.yml` que pasa `ci`, `evals` y `deploy`.
- [ ] **Step 4: Commit (en my_skills)** `ci: notify my-mcp-server on skills changes`

### Task 7: Dockerfile reproducible

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1:** `COPY pyproject.toml uv.lock ./` (sin glob) y `RUN uv sync --no-dev --locked` (sin fallback). Copiar `config/sources.lock.json` antes del sync de skills y pasar `--lock /app/config/sources.lock.json`.
- [ ] **Step 2: Verificación:** `docker build -t devteam-skills-mcp:test .` termina OK; `docker run --rm -e MCP_API_KEY=x -p 127.0.0.1:8000:8000 devteam-skills-mcp:test` y `curl -s localhost:8000/health` muestra en `sync_meta` los mismos SHAs que el lock. Con un `uv.lock` desactualizado a propósito (en un scratch), el build falla.
- [ ] **Step 3: Commit** `build: enforce uv.lock in Docker image and use pinned skill sources`

---

## Fuera de este plan

- Skills nuevas en `my_skills` (testing frontend, contrato OpenAPI→cliente, UI/a11y, seguridad, jobs/caché): son trabajo de contenido en el otro repo.
- Primer commit, README y `.gitignore` (`graphify-out/`, quitar `mis_skills/`): se hacen como Task 0 al iniciar la ejecución, antes de la Task 1, porque el repo no tiene commits y todos los pasos "Commit" lo presuponen.
