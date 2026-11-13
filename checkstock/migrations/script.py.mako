# -*- coding: utf-8 -*-
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: Optional[str] = ${repr(down_revision)}
branch_labels: Optional[Union[str, Sequence[str]]] = ${repr(branch_labels)}
depends_on: Optional[Union[str, Sequence[str]]] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
