"""Migrate cashback system to Milo Points

Revision ID: 044
Revises: 043_add_post_url_to_drawings
Create Date: 2026-03-13

Changes:
- Add Milo Points fields to cashback_balances
- Add points/spin_type fields to cashback_transactions
- Add points/spin_type fields to spin_transactions
- Add points/spin_type/streak_level fields to streak_rewards
- Add TierLevel, SpinType enums to PostgreSQL
- Convert existing euro balances to points (1 EUR = 1000 pts)
- Migrate existing spins to standard_spins
- Set all existing users as kickstart_completed (skip kickstart)
- Reset all streaks to 0, level 1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision = '044'
down_revision = '043_add_post_url'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create new PostgreSQL ENUMs ──────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tierlevel AS ENUM ('bronze', 'silver', 'gold');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE spintype AS ENUM ('standard', 'premium');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # ── Update StreakRewardType enum to add 'points' value ───────────────
    op.execute("""
        ALTER TYPE streakrewardtype ADD VALUE IF NOT EXISTS 'points';
    """)

    # ── cashback_balances: add new columns ───────────────────────────────
    op.add_column('cashback_balances',
        sa.Column('points_balance', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('total_points_earned', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('total_points_paid_out', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('standard_spins', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('premium_spins', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('tier_level',
                  sa.Enum('bronze', 'silver', 'gold', name='tierlevel',
                          create_type=False),
                  nullable=False, server_default='bronze'))
    op.add_column('cashback_balances',
        sa.Column('tier_calculated_month', sa.String(7), nullable=True))
    op.add_column('cashback_balances',
        sa.Column('kickstart_tickets', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('kickstart_completed', sa.Boolean(), nullable=False,
                  server_default='false'))
    op.add_column('cashback_balances',
        sa.Column('grote_kar_count_this_month', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_balances',
        sa.Column('grote_kar_month', sa.String(7), nullable=True))
    op.add_column('cashback_balances',
        sa.Column('streak_level', sa.Integer(), nullable=False,
                  server_default='1'))
    op.add_column('cashback_balances',
        sa.Column('streak_cycle_start_week', sa.String(8), nullable=True))

    # ── Convert existing euro balances to points (1 EUR = 1000 pts) ─────
    op.execute("""
        UPDATE cashback_balances SET
            points_balance       = ROUND(current_balance * 1000)::integer,
            total_points_earned  = ROUND(total_earned * 1000)::integer,
            total_points_paid_out = ROUND(total_paid_out * 1000)::integer,
            standard_spins       = spins_available,
            premium_spins        = 0,
            tier_level           = 'bronze',
            kickstart_completed  = true,
            streak_level         = 1,
            streak_week_count    = 0,
            streak_last_qualified_at = NULL
    """)

    # ── cashback_transactions: add new columns ───────────────────────────
    op.add_column('cashback_transactions',
        sa.Column('points_total', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_transactions',
        sa.Column('fixed_points', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_transactions',
        sa.Column('grote_kar_points', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_transactions',
        sa.Column('kickstart_bonus_points', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('cashback_transactions',
        sa.Column('is_kickstart', sa.Boolean(), nullable=False,
                  server_default='false'))
    op.add_column('cashback_transactions',
        sa.Column('is_streak_saver', sa.Boolean(), nullable=False,
                  server_default='false'))
    op.add_column('cashback_transactions',
        sa.Column('spin_type',
                  sa.Enum('standard', 'premium', name='spintype',
                          create_type=False),
                  nullable=True))

    # Convert existing transactions' cashback_amount to points
    op.execute("""
        UPDATE cashback_transactions SET
            points_total = ROUND(cashback_amount * 1000)::integer
        WHERE cashback_amount > 0
    """)

    # ── spin_transactions: add new columns ───────────────────────────────
    op.add_column('spin_transactions',
        sa.Column('points_value', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('spin_transactions',
        sa.Column('spin_type',
                  sa.Enum('standard', 'premium', name='spintype',
                          create_type=False),
                  nullable=True))

    # Convert existing spin cash_value to points
    op.execute("""
        UPDATE spin_transactions SET
            points_value = ROUND(cash_value * 1000)::integer,
            spin_type    = 'standard'
        WHERE cash_value IS NOT NULL
    """)

    # ── streak_rewards: add new columns ─────────────────────────────────
    op.add_column('streak_rewards',
        sa.Column('points_amount', sa.Integer(), nullable=False,
                  server_default='0'))
    op.add_column('streak_rewards',
        sa.Column('spin_type',
                  sa.Enum('standard', 'premium', name='spintype',
                          create_type=False),
                  nullable=True))
    op.add_column('streak_rewards',
        sa.Column('streak_level', sa.Integer(), nullable=False,
                  server_default='1'))

    # Convert existing streak rewards cash_amount to points
    op.execute("""
        UPDATE streak_rewards SET
            points_amount = ROUND(cash_amount * 1000)::integer,
            spin_type     = CASE WHEN spins_amount > 0 THEN 'standard'::spintype ELSE NULL END,
            streak_level  = 1
    """)


def downgrade() -> None:
    # Remove streak_rewards columns
    op.drop_column('streak_rewards', 'streak_level')
    op.drop_column('streak_rewards', 'spin_type')
    op.drop_column('streak_rewards', 'points_amount')

    # Remove spin_transactions columns
    op.drop_column('spin_transactions', 'spin_type')
    op.drop_column('spin_transactions', 'points_value')

    # Remove cashback_transactions columns
    op.drop_column('cashback_transactions', 'spin_type')
    op.drop_column('cashback_transactions', 'is_streak_saver')
    op.drop_column('cashback_transactions', 'is_kickstart')
    op.drop_column('cashback_transactions', 'kickstart_bonus_points')
    op.drop_column('cashback_transactions', 'grote_kar_points')
    op.drop_column('cashback_transactions', 'fixed_points')
    op.drop_column('cashback_transactions', 'points_total')

    # Remove cashback_balances columns
    op.drop_column('cashback_balances', 'streak_cycle_start_week')
    op.drop_column('cashback_balances', 'streak_level')
    op.drop_column('cashback_balances', 'grote_kar_month')
    op.drop_column('cashback_balances', 'grote_kar_count_this_month')
    op.drop_column('cashback_balances', 'kickstart_completed')
    op.drop_column('cashback_balances', 'kickstart_tickets')
    op.drop_column('cashback_balances', 'tier_calculated_month')
    op.drop_column('cashback_balances', 'tier_level')
    op.drop_column('cashback_balances', 'premium_spins')
    op.drop_column('cashback_balances', 'standard_spins')
    op.drop_column('cashback_balances', 'total_points_paid_out')
    op.drop_column('cashback_balances', 'total_points_earned')
    op.drop_column('cashback_balances', 'points_balance')
