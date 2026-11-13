# -*- coding: utf-8 -*-
"""operation_log is append-only

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence
from typing import Optional, Union

from alembic import op

revision: str = "0002"
down_revision: Optional[str] = "0001"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION operation_log_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'operation_log is append-only' USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER operation_log_append_only
        BEFORE UPDATE OR DELETE ON operation_log
        FOR EACH ROW EXECUTE FUNCTION operation_log_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER operation_log_append_only ON operation_log")
    op.execute("DROP FUNCTION operation_log_append_only()")
