from fastapi import APIRouter
from pydantic import BaseModel

from maki.schemas import RunTaskPreview

router = APIRouter(prefix="/api")


class RunTaskRequest(BaseModel):
    command: str
    task_def: str | None = None


@router.post("/services/{name}/run-task", response_model=RunTaskPreview)
def run_task(name: str, body: RunTaskRequest) -> RunTaskPreview:
    # SAFETY: UI-ONLY PREVIEW. This endpoint intentionally performs NO action:
    # no ECS run_task, no GitHub dispatch, no subprocess, no AWS call, no side effect of any kind.
    # Real run-task execution is deliberately not implemented.
    return RunTaskPreview(
        service=name,
        command=body.command,
        task_def=body.task_def,
        executed=False,
        message=(
            "Preview only — run-task execution is not implemented. No production change was made."
        ),
    )
