"""Drop budget AI insight tables

Revision ID: 015_drop_ai_tables
Revises: 014_fix_parents
Create Date: 2026-02-11

Removes the budget_ai_insights and ai_insight_feedback tables.
AI-powered budget suggestions have been replaced with a simpler
manual budget setup (Option A: category targets as guardrails).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '015_drop_ai_tables'
down_revision: Union[str, None] = '014_fix_parents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop ai_insight_feedback first (has FK to budget_ai_insights)
    op.drop_table('ai_insight_feedback')
    op.drop_table('budget_ai_insights')


def downgrade() -> None:
    # Recreate budget_ai_insights
    op.create_table(
        'budget_ai_insights',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('insight_type', sa.String(length=50), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=True),
        sa.Column('input_data', postgresql.JSONB(), nullable=True),
        sa.Column('ai_response', postgresql.JSONB(), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=True),
        sa.Column('receipt_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Recreate ai_insight_feedback
    op.create_table(
        'ai_insight_feedback',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('insight_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('feedback_type', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['insight_id'], ['budget_ai_insights.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
