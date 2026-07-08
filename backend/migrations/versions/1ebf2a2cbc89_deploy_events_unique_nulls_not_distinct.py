"""deploy_events unique nulls not distinct

Revision ID: 1ebf2a2cbc89
Revises: dc453b33e84b
Create Date: 2026-06-01 22:22:14.279911

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ebf2a2cbc89'
down_revision: Union[str, Sequence[str], None] = 'dc453b33e84b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rebuild the unique constraint as NULLS NOT DISTINCT (PG 15+).

    Amplify rows carry revision=NULL with one row per service. Under the default
    NULLS DISTINCT, two (service, NULL) rows don't collide, so the ingester's
    ON CONFLICT never fires for Amplify and would append a duplicate every cycle.
    """
    op.execute(
        "ALTER TABLE deploy_events DROP CONSTRAINT uq_deploy_event_service_revision"
    )
    op.execute(
        "ALTER TABLE deploy_events ADD CONSTRAINT uq_deploy_event_service_revision "
        "UNIQUE NULLS NOT DISTINCT (service, revision)"
    )


def downgrade() -> None:
    """Restore the default NULLS DISTINCT unique constraint."""
    op.execute(
        "ALTER TABLE deploy_events DROP CONSTRAINT uq_deploy_event_service_revision"
    )
    op.execute(
        "ALTER TABLE deploy_events ADD CONSTRAINT uq_deploy_event_service_revision "
        "UNIQUE (service, revision)"
    )
