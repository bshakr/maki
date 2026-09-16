"""The opt-in set of services that produce deploy notifications."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from fastapi import HTTPException
from sqlalchemy.orm import Session

from maki.db.repository import DeployEventRepository, ServiceWatchRepository
from maki.schemas import WatchedService, WatchesResponse


class WatchesService:
    def __init__(
        self,
        *,
        watches: ServiceWatchRepository,
        deploys: DeployEventRepository,
        session_factory: Callable[[], AbstractContextManager[Session]],
    ):
        self._watches = watches
        self._deploys = deploys
        self._session_factory = session_factory

    def list(self) -> WatchesResponse:
        with self._session_factory() as session:
            rows = self._watches.list_all(session)
            return WatchesResponse(
                watches=[WatchedService(service=r.service, created_at=r.created_at) for r in rows]
            )

    def add(self, service: str) -> WatchedService:
        with self._session_factory() as session:
            if service not in set(self._deploys.list_services(session)):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"unknown service {service!r} — it must appear in maki's deploy history "
                        "before it can be watched"
                    ),
                )
            row = self._watches.add(session, service)
            return WatchedService(service=row.service, created_at=row.created_at)

    def remove(self, service: str) -> None:
        with self._session_factory() as session:
            if not self._watches.remove(session, service):
                raise HTTPException(status_code=404, detail=f"{service!r} is not watched")
