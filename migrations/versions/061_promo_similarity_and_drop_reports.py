"""promo similarity infra + drop weekly-report tables

Revision ID: 061_promo_similarity_and_drop_reports
Revises: 060_promo_folder_url_not_null
Create Date: 2026-04-17

Changes
-------
1. Enable pg_trgm and add a GIN trigram index on promo_items.display_name.
   Enables fast similarity() scoring for the tier-based "similar promos" ranker.
2. Create promo_interaction_events: telemetry for folder/hotspot/carousel
   interactions. Decoupled from promo reports — user_id is nullable so
   logged-out folder browsers can still emit events.
3. Drop promo_report_events and promo_candidates: the weekly personalized
   promo report feature is being retired in favour of the folder + similar
   recommendation flow.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '061_promo_similarity_and_drop_reports'
down_revision: Union[str, None] = '060_promo_folder_url_not_null'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_items_display_name_trgm "
        "ON promo_items USING gin (display_name gin_trgm_ops)"
    )

    op.create_table(
        'promo_interaction_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column(
            'user_id', sa.String(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('promo_item_id', sa.String(), nullable=True),
        sa.Column('source_item_id', sa.String(), nullable=True),
        sa.Column('store_name', sa.String(length=255), nullable=True),
        sa.Column('metadata_json', JSONB(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        'ix_promo_interaction_events_user_id',
        'promo_interaction_events', ['user_id'],
    )
    op.create_index(
        'ix_promo_interaction_events_promo_item_id',
        'promo_interaction_events', ['promo_item_id'],
    )
    op.create_index(
        'ix_promo_interaction_events_event_created',
        'promo_interaction_events', ['event_type', 'created_at'],
    )

    op.execute("DROP TABLE IF EXISTS promo_report_events")
    op.execute("DROP TABLE IF EXISTS promo_candidates")


def downgrade() -> None:
    op.create_table(
        'promo_candidates',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column(
            'user_id', sa.String(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False, index=True,
        ),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('candidates_json', JSONB(), nullable=False),
        sa.Column('closing_nudge', sa.Text(), nullable=False, server_default=''),
        sa.Column('smart_switch_json', JSONB(), nullable=True),
        sa.Column('store_tips_json', JSONB(), nullable=True),
        sa.Column('interest_item_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_matches', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('user_id', name='uq_promo_candidates_user_id'),
    )

    op.create_table(
        'promo_report_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column(
            'report_id', sa.String(),
            sa.ForeignKey('promo_candidates.id', ondelete='CASCADE'),
            nullable=False, index=True,
        ),
        sa.Column(
            'user_id', sa.String(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False, index=True,
        ),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('item_key', sa.String(length=64), nullable=True, index=True),
        sa.Column('store_name', sa.String(length=255), nullable=True, index=True),
        sa.Column('metadata_json', JSONB(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False, index=True,
        ),
    )

    op.drop_index('ix_promo_interaction_events_event_created', table_name='promo_interaction_events')
    op.drop_index('ix_promo_interaction_events_promo_item_id', table_name='promo_interaction_events')
    op.drop_index('ix_promo_interaction_events_user_id', table_name='promo_interaction_events')
    op.drop_table('promo_interaction_events')

    op.execute("DROP INDEX IF EXISTS ix_promo_items_display_name_trgm")
