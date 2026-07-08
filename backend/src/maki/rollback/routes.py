from fastapi import APIRouter
from pydantic import BaseModel

from maki.schemas import RollbackPreview

router = APIRouter(prefix="/api")


class RollbackRequest(BaseModel):
    target_sha: str


@router.post("/services/{name}/rollback", response_model=RollbackPreview)
def rollback(name: str, body: RollbackRequest) -> RollbackPreview:
    # SAFETY: UI-ONLY PREVIEW. This endpoint intentionally performs NO action:
    # no GitHub dispatch, no ECS/AWS call, no deploy, no side effect of any kind.
    # Real rollback execution is deliberately not implemented.
    return RollbackPreview(
        service=name,
        target_sha=body.target_sha,
        executed=False,
        message=(
            "Preview only — rollback execution is not implemented. No production change was made."
        ),
    )
