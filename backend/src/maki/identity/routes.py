from functools import cache

from fastapi import APIRouter

from maki.aws.clients import sts_client
from maki.identity.service import IdentityService
from maki.schemas import IdentityResponse
from maki.settings import settings

router = APIRouter(prefix="/api")


@cache
def get_identity_service() -> IdentityService:
    return IdentityService(sts_client(), region=settings.aws_region)


@router.get("/identity", response_model=IdentityResponse)
def get_identity() -> IdentityResponse:
    return get_identity_service().get_identity()
