import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from maki.activity.routes import router as activity_router
from maki.app_config.routes import router as app_config_router
from maki.auth import BearerAuthMiddleware
from maki.aws.errors import register_aws_error_handlers
from maki.health_check import router as health_router
from maki.history.routes import router as history_router
from maki.identity.routes import router as identity_router
from maki.ingest import build_ingester, ingest_loop
from maki.inventory.routes import router as inventory_router
from maki.logs.routes import router as logs_router
from maki.metrics.routes import router as metrics_router
from maki.rollback.routes import router as rollback_router
from maki.rollout_status.routes import router as rollout_status_router
from maki.run_task.routes import router as run_task_router
from maki.service_env.routes import router as service_env_router
from maki.settings import settings
from maki.task_history.routes import router as task_history_router
from maki.timeline.routes import router as timeline_router
from maki.version.routes import router as version_router
from maki.watches.routes import router as watches_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background deploy-events ingester for the lifetime of the ASGI server.

    Importing this module must NOT touch AWS or the database: the ingester is built and the loop
    is scheduled only here, when a real server runs the lifespan. Tests that don't run the
    lifespan (or set ``ingest_enabled=False``) never start it and never call AWS.
    """
    stop = asyncio.Event()
    task: asyncio.Task | None = None
    if settings.ingest_enabled:
        ingester = build_ingester()
        task = asyncio.create_task(ingest_loop(ingester, settings.ingest_interval_seconds, stop))
        logger.info("deploy-events ingester started")
    try:
        yield
    finally:
        # Cancel rather than await: a cycle already running on the worker thread can take a long
        # time (the first one is a full backfill), and awaiting it would wedge shutdown/--reload.
        # cancel() unblocks the await immediately; the detached thread dies with the process.
        stop.set()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            logger.info("deploy-events ingester stopped")


# Logging-hygiene invariant: maki never logs request/response bodies or secrets. The access log is
# method/path/status only; the bearer token, GITHUB_TOKEN, and env-var values must never reach a
# log. Guarded by tests/test_logging_hygiene.py — do not add body-logging middleware.
app = FastAPI(title=settings.config.branding.appName, version="0.0.1", lifespan=lifespan)

# Missing/expired AWS creds → typed 503 instead of an opaque 500, so the SPA can prompt a re-assume.
register_aws_error_handlers(app)

# Reject requests whose Host header isn't loopback (or an explicitly-allowed proxy host). Defends
# against DNS-rebinding, where a malicious site resolves to 127.0.0.1 to bypass the same-origin
# policy. Loopback hosts are always allowed; MAKI_ALLOWED_HOSTS adds proxy hostnames.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

# Optional shared-token gate. Off unless MAKI_AUTH_TOKEN is set (laptop default = no auth).
if settings.auth_token:
    app.add_middleware(BearerAuthMiddleware, token=settings.auth_token)

app.include_router(health_router)
app.include_router(app_config_router)
app.include_router(identity_router)
app.include_router(inventory_router)
app.include_router(history_router)
app.include_router(activity_router)
app.include_router(rollback_router)
app.include_router(rollout_status_router)
app.include_router(run_task_router)
app.include_router(metrics_router)
app.include_router(timeline_router)
app.include_router(task_history_router)
app.include_router(service_env_router)
app.include_router(logs_router)
app.include_router(version_router)
app.include_router(watches_router)


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built SPA with history fallback.

    Real files (e.g. /assets/*.js) are served as-is; any other GET path falls back to
    index.html so client-side routes like /services/<name> survive a reload. Registered
    AFTER the API routers, so /api/* and /health match first.
    """
    index = static_dir / "index.html"
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    static_root = static_dir.resolve()

    @app.get("/{full_path:path}")
    def _spa(full_path: str) -> FileResponse:
        candidate = (static_root / full_path).resolve()
        within_root = candidate == static_root or static_root in candidate.parents
        if full_path and within_root and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


# Built SPA is served only when STATIC_DIR points at an existing dir (container/demo).
# In local dev it's unset → use the Vite dev server instead.
_static = Path(settings.static_dir) if settings.static_dir else None
if _static and _static.is_dir():
    mount_spa(app, _static)
