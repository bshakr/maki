# maki — Phase 1 (Read-Only Visibility) Plan

**Goal:** A local dashboard that shows every prod ECS service + the Amplify web app with its
current git SHA, deploy time, running/desired counts, and rollout status. No DB, no auth.

**Architecture:** FastAPI backend live-queries AWS (ECS + Amplify) per request with a short
in-process TTL cache, exposes `GET /api/services`, and serves a React+Vite SPA. Standalone repo,
plain venv + npm. boto3 uses the developer's AWS credentials.

**Decisions baked in:** single cluster `production`, region `eu-west-1`, account `123456789012`.
Image git SHA = `image.rsplit(":", 1)[-1]`; one container per task def → `containerDefinitions[0]`.
Amplify app `dexampleapp123`, branch `master`. Service→repo for commit links: default
`acme/platform`, `middleware`→`acme/middleware`, `web-app`→`acme/web-app`.

## Repo layout

The repo has two top-level subfolders: `backend/` and `frontend/`. All backend paths below are
relative to `backend/`; **run all backend commands (`pytest`, `uvicorn`, `ruff`) from `backend/`.**
The `Dockerfile` lives at repo root (it builds both).

```
backend/
  pyproject.toml          # ruff + pytest (pythonpath=["src"], testpaths=["tests"])
  requirements.txt  requirements-dev.txt
  src/maki/
    __init__.py
    api.py                # FastAPI app; routers; StaticFiles mount (guarded)
    main.py               # from maki.api import app
    settings.py           # pydantic-settings
    health_check.py       # GET /health
    schemas.py            # DeployedService, ServicesResponse
    aws/
      __init__.py
      clients.py          # boto3 client factories
      ecs_registry.py     # ECSDeployRegistry.list_deployed_services()
      amplify_registry.py # AmplifyDeployRegistry.get_deployed_web_app()
    inventory/
      __init__.py
      service.py          # InventoryService.get_inventory() (combine + commit urls + cache)
      routes.py           # GET /api/services
  tests/
    __init__.py
    test_health.py
    test_static_serving.py
    aws/{__init__.py,test_ecs_registry.py,test_amplify_registry.py}
    inventory/{__init__.py,test_service.py,test_routes.py}
frontend/                 # Vite + React + TS (package.json, src/App.tsx, etc.)
Dockerfile                # multi-stage (optional; for later demo/deploy)
```

Run commands (backend from `backend/`): `pytest` (backend tests),
`uvicorn maki.main:app --reload --port 8787 --app-dir src` (serve); frontend from `frontend/`:
`npm test`, `npm run dev`.

---

## Task 1 — backend skeleton + health

Create `src/maki/__init__.py` (empty), `settings.py`, `health_check.py`, `api.py`, `main.py`,
`tests/__init__.py`, `tests/test_health.py`. TDD: write `test_health` first.

`tests/test_health.py`:
```python
from fastapi.testclient import TestClient

from maki.main import app


def test_health_returns_ok():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

`src/maki/settings.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "eu-west-1"
    ecs_cluster: str = "production"
    amplify_app_id: str = "dexampleapp123"
    amplify_branch: str = "master"

    default_github_repo: str = "acme/platform"
    github_repo_overrides: dict[str, str] = {
        "middleware": "acme/middleware",
        "web-app": "acme/web-app",
    }
    inventory_cache_ttl_seconds: int = 20
    static_dir: str | None = None  # set when serving the built SPA; unset in dev

    def repo_for(self, service_name: str) -> str:
        return self.github_repo_overrides.get(service_name, self.default_github_repo)


settings = Settings()
```

`src/maki/health_check.py`:
```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

`src/maki/api.py` (no telemetry/sentry — standalone):
```python
from fastapi import FastAPI

from maki.health_check import router as health_router

app = FastAPI(title="maki — Nory Deploy Console", version="0.0.1")

app.include_router(health_router)
```

`src/maki/main.py`:
```python
from maki.api import app  # noqa: F401
```

Verify: `pytest tests/test_health.py` PASS. Commit.

---

## Task 2 — ECS registry + schemas

Create `schemas.py`, `aws/__init__.py`, `aws/clients.py`, `aws/ecs_registry.py`,
`tests/aws/__init__.py`, `tests/aws/test_ecs_registry.py`. TDD first.

`tests/aws/test_ecs_registry.py`:
```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from maki.aws.ecs_registry import ECSDeployRegistry


def _client_with(services, task_defs):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"serviceArns": [s["serviceArn"] for s in services]}
    ]
    client.describe_services.return_value = {"services": services}
    client.describe_task_definition.side_effect = lambda taskDefinition: {
        "taskDefinition": task_defs[taskDefinition]
    }
    return client


def test_returns_deployed_service_with_git_sha_and_counts():
    deployed_at = datetime(2026, 5, 29, 9, 0, tzinfo=timezone.utc)
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/newsfeed",
            "serviceName": "newsfeed",
            "runningCount": 2,
            "desiredCount": 2,
            "taskDefinition": "arn:td:newsfeed:5",
            "deployments": [
                {"rolloutState": "COMPLETED", "updatedAt": deployed_at,
                 "taskDefinition": "arn:td:newsfeed:5"}
            ],
        }
    ]
    task_defs = {
        "arn:td:newsfeed:5": {
            "containerDefinitions": [
                {"image": "527.dkr.ecr.eu-west-1.amazonaws.com/newsfeed:abc123sha"}
            ]
        }
    }
    registry = ECSDeployRegistry(_client_with(services, task_defs), cluster="production")
    result = registry.list_deployed_services()
    assert len(result) == 1
    svc = result[0]
    assert svc.name == "newsfeed"
    assert svc.platform == "ecs"
    assert svc.git_sha == "abc123sha"
    assert svc.running_count == 2
    assert svc.desired_count == 2
    assert svc.status == "COMPLETED"
    assert svc.deployed_at == deployed_at


def test_describe_services_is_batched_in_tens():
    arns = [f"arn:svc-{i}" for i in range(23)]
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"serviceArns": arns}]
    client.describe_services.return_value = {"services": []}
    client.describe_task_definition.return_value = {"taskDefinition": {"containerDefinitions": []}}
    registry = ECSDeployRegistry(client, cluster="production")
    registry.list_deployed_services()
    assert client.describe_services.call_count == 3
```

`src/maki/schemas.py`:
```python
from datetime import datetime

from pydantic import BaseModel


class DeployedService(BaseModel):
    name: str
    platform: str  # "ecs" | "amplify"
    env: str = "production"
    git_sha: str | None = None
    image: str | None = None
    deployed_at: datetime | None = None
    running_count: int | None = None
    desired_count: int | None = None
    status: str | None = None
    commit_url: str | None = None


class ServicesResponse(BaseModel):
    services: list[DeployedService]
    generated_at: datetime
```

`src/maki/aws/clients.py`:
```python
import boto3

from maki.settings import settings


def ecs_client():
    return boto3.client("ecs", region_name=settings.aws_region)


def amplify_client():
    return boto3.client("amplify", region_name=settings.aws_region)
```

`src/maki/aws/ecs_registry.py`:
```python
from maki.schemas import DeployedService

_DESCRIBE_BATCH = 10


class ECSDeployRegistry:
    """Live, read-only view of currently-deployed ECS services in one cluster."""

    def __init__(self, client, cluster: str):
        self._client = client
        self._cluster = cluster

    def list_deployed_services(self) -> list[DeployedService]:
        arns = self._list_service_arns()
        services = self._describe_services(arns)
        cache: dict[str, str | None] = {}
        return [self._to_deployed_service(svc, cache) for svc in services]

    def _list_service_arns(self) -> list[str]:
        arns: list[str] = []
        for page in self._client.get_paginator("list_services").paginate(cluster=self._cluster):
            arns.extend(page["serviceArns"])
        return arns

    def _describe_services(self, arns: list[str]) -> list[dict]:
        services: list[dict] = []
        for start in range(0, len(arns), _DESCRIBE_BATCH):
            batch = arns[start : start + _DESCRIBE_BATCH]
            if not batch:
                continue
            services.extend(
                self._client.describe_services(cluster=self._cluster, services=batch)["services"]
            )
        return services

    def _image_for_task_def(self, arn: str, cache: dict[str, str | None]) -> str | None:
        if arn not in cache:
            containers = self._client.describe_task_definition(taskDefinition=arn)[
                "taskDefinition"
            ]["containerDefinitions"]
            cache[arn] = containers[0]["image"] if containers else None
        return cache[arn]

    def _to_deployed_service(self, svc: dict, cache: dict[str, str | None]) -> DeployedService:
        primary = self._primary_deployment(svc)
        td_arn = (primary or {}).get("taskDefinition") or svc.get("taskDefinition")
        image = self._image_for_task_def(td_arn, cache) if td_arn else None
        return DeployedService(
            name=svc["serviceName"],
            platform="ecs",
            git_sha=self._sha_from_image(image),
            image=image,
            deployed_at=(primary or {}).get("updatedAt"),
            running_count=svc.get("runningCount"),
            desired_count=svc.get("desiredCount"),
            status=(primary or {}).get("rolloutState"),
        )

    @staticmethod
    def _primary_deployment(svc: dict) -> dict | None:
        deployments = svc.get("deployments", [])
        return deployments[0] if deployments else None

    @staticmethod
    def _sha_from_image(image: str | None) -> str | None:
        if not image or ":" not in image:
            return None
        return image.rsplit(":", 1)[-1]
```

Verify: `pytest tests/aws/test_ecs_registry.py` PASS. Commit.

---

## Task 3 — Amplify registry

`tests/aws/test_amplify_registry.py`:
```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from maki.aws.amplify_registry import AmplifyDeployRegistry


def test_returns_web_app_with_active_commit():
    end_time = datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc)
    client = MagicMock()
    client.get_branch.return_value = {"branch": {"activeJobId": "42"}}
    client.get_job.return_value = {
        "job": {"summary": {"commitId": "deadbeefsha", "status": "SUCCEED", "endTime": end_time}}
    }
    registry = AmplifyDeployRegistry(client, app_id="dexampleapp123", branch="master")
    svc = registry.get_deployed_web_app()
    assert svc.name == "web-app"
    assert svc.platform == "amplify"
    assert svc.git_sha == "deadbeefsha"
    assert svc.status == "SUCCEED"
    assert svc.deployed_at == end_time


def test_returns_none_when_no_active_job():
    client = MagicMock()
    client.get_branch.return_value = {"branch": {}}
    registry = AmplifyDeployRegistry(client, app_id="x", branch="master")
    assert registry.get_deployed_web_app() is None
```

`src/maki/aws/amplify_registry.py`:
```python
from maki.schemas import DeployedService


class AmplifyDeployRegistry:
    """Live, read-only view of the currently-deployed Amplify web app."""

    def __init__(self, client, app_id: str, branch: str):
        self._client = client
        self._app_id = app_id
        self._branch = branch

    def get_deployed_web_app(self) -> DeployedService | None:
        branch = self._client.get_branch(appId=self._app_id, branchName=self._branch)["branch"]
        active_job_id = branch.get("activeJobId")
        if not active_job_id:
            return None
        summary = self._client.get_job(
            appId=self._app_id, branchName=self._branch, jobId=active_job_id
        )["job"]["summary"]
        return DeployedService(
            name="web-app",
            platform="amplify",
            git_sha=summary.get("commitId"),
            deployed_at=summary.get("endTime"),
            status=summary.get("status"),
        )
```

Verify: `pytest tests/aws/test_amplify_registry.py` PASS. Commit.

---

## Task 4 — inventory service (combine + commit urls + TTL cache)

`tests/inventory/test_service.py`:
```python
from unittest.mock import MagicMock

from maki.inventory.service import InventoryService
from maki.schemas import DeployedService


def _svc(name, platform="ecs"):
    return DeployedService(name=name, platform=platform, git_sha="sha1")


def _repo_for(name: str) -> str:
    return {"middleware": "acme/middleware", "web-app": "acme/web-app"}.get(
        name, "acme/platform"
    )


def test_combines_ecs_and_amplify_and_adds_commit_urls():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed"), _svc("middleware")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = _svc("web-app", platform="amplify")
    svc = InventoryService(ecs, amplify, repo_for=_repo_for, ttl_seconds=0)
    result = svc.get_inventory()
    by_name = {s.name: s for s in result.services}
    assert by_name["newsfeed"].commit_url == "https://github.com/acme/platform/commit/sha1"
    assert by_name["middleware"].commit_url == "https://github.com/acme/middleware/commit/sha1"
    assert by_name["web-app"].commit_url == "https://github.com/acme/web-app/commit/sha1"


def test_caches_within_ttl():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = None
    svc = InventoryService(ecs, amplify, repo_for=_repo_for, ttl_seconds=60)
    svc.get_inventory()
    svc.get_inventory()
    assert ecs.list_deployed_services.call_count == 1
```

`src/maki/inventory/service.py`:
```python
import time
from collections.abc import Callable
from datetime import datetime, timezone

from maki.aws.amplify_registry import AmplifyDeployRegistry
from maki.aws.ecs_registry import ECSDeployRegistry
from maki.schemas import DeployedService, ServicesResponse


class InventoryService:
    def __init__(
        self,
        ecs: ECSDeployRegistry,
        amplify: AmplifyDeployRegistry,
        repo_for: Callable[[str], str],
        ttl_seconds: int,
    ):
        self._ecs = ecs
        self._amplify = amplify
        self._repo_for = repo_for
        self._ttl = ttl_seconds
        self._cached: ServicesResponse | None = None
        self._cached_at: float = 0.0

    def get_inventory(self) -> ServicesResponse:
        if self._fresh():
            return self._cached
        services = self._ecs.list_deployed_services()
        web = self._amplify.get_deployed_web_app()
        if web is not None:
            services.append(web)
        for svc in services:
            svc.commit_url = self._commit_url(svc)
        response = ServicesResponse(
            services=sorted(services, key=lambda s: s.name),
            generated_at=datetime.now(timezone.utc),
        )
        self._cached = response
        self._cached_at = time.monotonic()
        return response

    def _fresh(self) -> bool:
        if self._cached is None or self._ttl <= 0:
            return False
        return (time.monotonic() - self._cached_at) < self._ttl

    def _commit_url(self, svc: DeployedService) -> str | None:
        if not svc.git_sha:
            return None
        return f"https://github.com/{self._repo_for(svc.name)}/commit/{svc.git_sha}"
```

Verify: `pytest tests/inventory/test_service.py` PASS. Commit.

---

## Task 5 — `GET /api/services` route

`tests/inventory/test_routes.py`:
```python
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import DeployedService, ServicesResponse


def test_get_services_returns_inventory():
    fake = ServicesResponse(
        services=[DeployedService(name="newsfeed", platform="ecs", git_sha="abc")],
        generated_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = fake
        client = TestClient(app)
        r = client.get("/api/services")
    assert r.status_code == 200
    assert r.json()["services"][0]["name"] == "newsfeed"
    assert r.json()["services"][0]["git_sha"] == "abc"
```

`src/maki/inventory/routes.py`:
```python
from functools import cache

from fastapi import APIRouter

from maki.aws.amplify_registry import AmplifyDeployRegistry
from maki.aws.clients import amplify_client, ecs_client
from maki.aws.ecs_registry import ECSDeployRegistry
from maki.inventory.service import InventoryService
from maki.schemas import ServicesResponse
from maki.settings import settings

router = APIRouter(prefix="/api")


@cache
def get_inventory_service() -> InventoryService:
    return InventoryService(
        ecs=ECSDeployRegistry(ecs_client(), cluster=settings.ecs_cluster),
        amplify=AmplifyDeployRegistry(
            amplify_client(), app_id=settings.amplify_app_id, branch=settings.amplify_branch
        ),
        repo_for=settings.repo_for,
        ttl_seconds=settings.inventory_cache_ttl_seconds,
    )


@router.get("/services", response_model=ServicesResponse)
def list_services() -> ServicesResponse:
    return get_inventory_service().get_inventory()
```

Wire into `api.py` (add import + `app.include_router(inventory_router)` AFTER health, BEFORE any
static mount). Verify: `pytest` (whole suite) PASS. Commit.

---

> **NOTE (2026-05-29): frontend Tasks 6-9 below are SUPERSEDED** by the
> "## Revised UI Plan (shadcn + sidebar)" section at the bottom of this file. The original bare-grid
> tasks shipped (commits 910ca79, 513db9a, a957cc0) but are being re-architected onto shadcn/ui +
> react-router. Backend Tasks 1-5 are unchanged. Read the revised section for current frontend work.

## Task 6 — React + Vite frontend scaffold

Create `frontend/` with `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`,
`src/main.tsx`, `src/api.ts`. (Same content as the original plan; module fetches `/api/services`,
dev proxy `/api → http://localhost:8787`, vitest + jsdom configured.)

Key bits — `frontend/src/api.ts`:
```typescript
export interface DeployedService {
  name: string;
  platform: "ecs" | "amplify";
  env: string;
  git_sha: string | null;
  image: string | null;
  deployed_at: string | null;
  running_count: number | null;
  desired_count: number | null;
  status: string | null;
  commit_url: string | null;
}
export interface ServicesResponse {
  services: DeployedService[];
  generated_at: string;
}
export async function fetchServices(): Promise<ServicesResponse> {
  const r = await fetch("/api/services");
  if (!r.ok) throw new Error(`Failed to load services: ${r.status}`);
  return r.json();
}
```

`frontend/vite.config.ts` proxy + vitest:
```typescript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
  server: { proxy: { "/api": "http://localhost:8787" } },
  test: { globals: true, environment: "jsdom", setupFiles: ["@testing-library/jest-dom/vitest"] },
});
```

`npm install` to generate the lockfile. Commit.

---

## Task 7 — frontend grid component (vitest TDD)

`frontend/src/App.test.tsx` asserts a row per service, short 7-char sha, `running / desired`, and
a commit link. `frontend/src/App.tsx` fetches on mount, auto-refreshes every 20s, renders a table
(columns: Service, Platform, SHA(link), Deployed(relative), Running/Desired, Status). Same code as
the original plan's App.tsx. Verify `npm test` PASS, `npm run build` emits `dist/`. Commit.

---

## Task 8 — serve built SPA from FastAPI (guarded)

`tests/test_static_serving.py` ensures `/health` and `/api/services` still resolve (no catch-all
shadowing). In `api.py`, after routers, mount only when `settings.static_dir` is set and exists:
```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from maki.settings import settings

_static = Path(settings.static_dir) if settings.static_dir else None
if _static and _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
```
Local dev: leave `static_dir` unset, use the Vite dev server. Commit.

---

## Task 9 — Dockerfile (optional; for later demo/deploy)

Multi-stage: node:20 builds `frontend/dist`, python:3.11-slim installs `requirements.txt`, copies
`src/` + `dist`, sets `STATIC_DIR=/app/static`, runs `uvicorn maki.main:app`. Low priority — only
needed when we want to host it. Not required to run locally. Commit when added.

---

## Verification (end)

- `pytest` → all green.
- `cd frontend && npm test` → all green.
- `ruff check src tests` → clean.
- Manual: `AWS_PROFILE=<prod> uvicorn maki.main:app --port 8787 --app-dir src`, then
  `curl localhost:8787/api/services` returns real services; `npm run dev` grid shows real SHAs.
  Cross-check 2–3 SHAs against the ECS console / GitHub.

## Risks / notes

- **No auth, real prod reads.** Local only. Never expose publicly without auth.
- **Amplify `get_job` summary field names** (`commitId`, `endTime`, `status`) — verify against a
  live response; adjust mapping if they differ.
- boto3 needs working AWS creds with the read perms listed in the README.

---

# Revised UI Plan (shadcn + sidebar)

**Decided 2026-05-29.** Frontend uses **shadcn/ui** (Tailwind v4) with a **sidebar-08** style layout
and **react-router-dom**. Supersedes original frontend Tasks 6-9. Backend Tasks 1-5 unchanged.

## Information architecture

```
maki
├── /                  Services overview (grid)           phase 1
├── /services/:name    Service detail (CURRENT now;       phase 1 (CURRENT)
│                       HISTORY/ACTIONS later)             phase 2-4
├── /activity          Global deploy + action feed        phase 2 / 4   (stub in p1)
└── /metrics           DORA charts                         phase 5        (stub in p1)
   dialogs/sheets: Rollback confirm (p3), Run-task (p4)
```

Sidebar nav: Services / Activity / Metrics, collapsible to an icon rail (sidebar-08), user+env in
the footer. Content renders in `SidebarInset` with a breadcrumb header. See ASCII wireframes in the
chat design exploration (sidebar overview, service detail, rollback dialog, run-task sheet, activity
feed, metrics).

## Frontend stack

- Tailwind v4 via `@tailwindcss/vite`; shadcn/ui (`components.json`, `src/components/ui/*`,
  `src/lib/utils.ts` `cn()`); `react-router-dom` v6; `lucide-react` icons.
- `@/` path alias → `frontend/src` (vite `resolve.alias` + tsconfig `paths`).
- shadcn components: `sidebar button table badge breadcrumb dropdown-menu input separator tooltip
  sheet skeleton avatar`.

## Frontend structure (target)

```
frontend/
  components.json
  tailwind / index.css (theme tokens)
  vite.config.ts            # @tailwindcss/vite, @ alias, vitest jsdom
  tsconfig.json             # paths @/*
  src/
    main.tsx                # <BrowserRouter><App/></BrowserRouter>
    App.tsx                 # <Routes> → Layout-wrapped pages
    index.css               # tailwind + shadcn theme vars
    lib/utils.ts            # cn()
    api.ts                  # fetchServices() (unchanged)
    components/
      ui/*                  # shadcn-generated primitives
      app-sidebar.tsx       # sidebar-08 nav (Services/Activity/Metrics + footer)
      layout.tsx            # SidebarProvider + AppSidebar + SidebarInset + breadcrumb header
    pages/
      ServicesPage.tsx      # grid (shadcn Table)
      ServiceDetailPage.tsx # CURRENT block stub + disabled history/actions
      ActivityPage.tsx      # stub
      MetricsPage.tsx       # stub
```

## Revised tasks

### T6 — re-scaffold frontend (Tailwind v4 + shadcn + router + alias)
Add Tailwind v4 (`@tailwindcss/vite`), run `shadcn init` (creates `components.json`, `lib/utils.ts`,
theme CSS), add `react-router-dom`, configure `@/`→`src` in `vite.config.ts` + `tsconfig.json`.
`main.tsx` wraps `<App/>` in `<BrowserRouter>`. Verify `npm run build` + one trivial vitest render.
Reuse the existing `api.ts`. Commit.

### T7 — app shell (sidebar-08) + routes
`npx shadcn add sidebar button breadcrumb dropdown-menu separator tooltip sheet avatar`. Build
`components/app-sidebar.tsx` (brand header, nav: Services/Activity/Metrics with lucide icons,
collapsible icon rail, footer user/env menu) and `components/layout.tsx`
(`SidebarProvider`+`AppSidebar`+`SidebarInset` with breadcrumb header reflecting the route). Wire
`App.tsx` routes: `/` ServicesPage, `/services/:name` ServiceDetailPage, `/activity` + `/metrics`
stubs. vitest: nav renders, clicking a nav item routes. Commit.

### T8 — Services page (shadcn Table grid)
`npx shadcn add table badge input skeleton`. `pages/ServicesPage.tsx`: fetch via `fetchServices()`,
render shadcn `Table`; columns Service / Platform(`Badge`) / SHA(link) / Deployed(relative) /
Run·Des / Status(`Badge` colored by state); a filter `Input`; fleet summary counts
(healthy/deploying/error derived from status + running<desired); 20s auto-refresh; rows link to
`/services/:name`; `Skeleton` while loading; error alert. Port the `shortSha`/`ago` helpers. vitest:
renders a row, short sha link, counts, filter narrows rows. Commit.

### T9 — Service-detail stub page
`pages/ServiceDetailPage.tsx`: read `:name`, fetch the inventory, find the matching service
client-side; render CURRENT block (status badge, sha→commit link, deployed-ago, running/desired,
image, CloudWatch logs deep-link built from name+region); HISTORY + RECENT ACTIONS as disabled
"coming in a later phase" cards; `Roll back` / `Run task` buttons present but `disabled`. Breadcrumb
`Services / :name`. vitest: renders CURRENT for a known service, buttons disabled, 404-ish state for
unknown name. Commit.

### T10 — backend SPA history fallback
The StaticFiles mount (commit a957cc0) serves `/` but 404s deep links like `/services/x`. Add an
SPA fallback so any non-`/api`, non-`/health` GET returns `index.html` when `static_dir` is set
(e.g. mount assets under their hashed paths via StaticFiles, plus a catch-all route returning
`FileResponse(index.html)`; keep `/api/*` and `/health` resolving first). Add a test:
`GET /services/anything` returns 200 + the SPA HTML when `STATIC_DIR` is set, and `/api/services`
still routes. Commit.

### T11 — Dockerfile
Already shipped (commit d1b2112), unchanged. The multi-stage build runs `npm ci && npm run build`,
which now includes Tailwind/shadcn — re-verify the image build after T6-T9.

## Verification (revised)
- `cd backend && pytest` all green (14+).
- `cd frontend && npm test` all green; `npm run build` succeeds (Tailwind + shadcn compile).
- Manual: `npm run dev` → sidebar shell, grid, click row → detail; deep-link `/services/<name>`
  reload works once T10 lands (or always in dev via Vite).

---

# Phase 2 Plan — deploy history + Activity feed

**Decided 2026-05-31.** Source = **ECS task-def revisions + GitHub enrich** (live, no DB).

## Backend

- **Deploy history (ECS):** a service's current task-def ARN (`arn:…:task-definition/<family>:<rev>`,
  already available from `describe_services`) yields its **family**. `list_task_definitions(
  familyPrefix=<family>, sort="DESC", status="ACTIVE")` → revisions; `describe_task_definition` per
  revision → `registeredAt` + container image SHA. Produces a backfilled per-service timeline.
  Schema `DeployRecord { sha, image, revision, registered_at, author?, message?, commit_url? }`.
- **GitHub enrich (optional):** `GITHUB_TOKEN` env (`export GITHUB_TOKEN=$(gh auth token)`). Per SHA →
  `GET /repos/{owner}/{repo}/commits/{sha}` → author login/name, commit message. Repo via the existing
  `settings.repo_for(name)`. If no token or lookup fails → skip enrichment, keep sha+time. httpx client,
  small in-process cache (sha→commit).
- **Endpoints:**
  - `GET /api/services/{name}/deployments` → `{ service, deployments: DeployRecord[] }` (newest first, capped e.g. 30).
  - `GET /api/activity` → recent deploys across all services, merged + sorted by `registered_at` desc, capped (e.g. 50). `ActivityItem { service, sha, registered_at, author?, status? }`.
- TTL cache like P1. New dep: `httpx` in `requirements.txt` (already a dev dep for TestClient).

## Frontend

- **Service detail HISTORY card** — fetch `/deployments`; rows: SHA→commit link, registered-ago,
  author, revision; replace the disabled placeholder. (A "roll back to" affordance is wired but
  disabled until P3.)
- **Activity page** — fetch `/activity`; chronological feed (time, service, sha, author); replace the stub.
  Filter by service (client-side) for now.

## Out of scope (P2)
- "Who triggered the deploy" beyond commit author; GitHub Actions **run link** (needs Actions-run
  correlation) — deferred. Duration/rollout success (would need the snapshot ledger) — deferred.
- RECENT ACTIONS card + action events → P4.

## Tasks
- P2.1 backend: ECS deploy-history registry + `DeployRecord` schema (TDD, mocked boto3).
- P2.2 backend: GitHub enrich client (httpx, token-optional, cached; TDD mocked).
- P2.3 backend: history service + `GET /api/services/{name}/deployments` (TDD).
- P2.4 backend: `GET /api/activity` aggregation (TDD).
- P2.5 frontend: service-detail HISTORY card (vitest).
- P2.6 frontend: Activity page real feed (vitest).
