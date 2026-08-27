"""Add assignment_templates.is_ai_generated for AI-copilot auto-grading routing.

The AI weekly planner creates templates on the student's behalf; submissions
against those templates are auto-graded by the same copilot instead of
waiting on manual parent review. Existing/manually-authored templates default
to False so they keep going through the normal grading-assist flow.

Revision ID: add_ai_generated_templates
Revises: add_point_tx_actor_name
Create Date: 2026-08-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_ai_generated_templates"
down_revision: Union[str, None] = "add_point_tx_actor_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assignment_templates",
        sa.Column(
            "is_ai_generated", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("assignment_templates", "is_ai_generated")
