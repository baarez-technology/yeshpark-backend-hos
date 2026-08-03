"""Add Revenue AI models - PricingRecommendationRecord, RateChangeAudit, AutoPricingConfig, AIInsightRecord, CompetitorScrapeLog, EventRecord

Revision ID: 5175cfb06aed
Revises: 8eb737cedc30
Create Date: 2026-01-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = '5175cfb06aed'
down_revision = '8eb737cedc30'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### Create pricing_recommendation_records table ###
    op.create_table('pricing_recommendation_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('room_type_id', sa.Integer(), nullable=False),
        sa.Column('current_rate', sa.Float(), nullable=False),
        sa.Column('recommended_rate', sa.Float(), nullable=False),
        sa.Column('change_percent', sa.Float(), nullable=False),
        sa.Column('demand_level', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('reasoning', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('priority', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('actioned_at', sa.DateTime(), nullable=True),
        sa.Column('actioned_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['room_type_id'], ['room_types.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pricing_recommendation_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_date'), ['date'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_room_type_id'), ['room_type_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_demand_level'), ['demand_level'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_priority'), ['priority'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_actioned_at'), ['actioned_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_pricing_recommendation_records_actioned_by'), ['actioned_by'], unique=False)
        batch_op.create_index('ix_pricing_rec_date_room', ['date', 'room_type_id'], unique=False)
        batch_op.create_index('ix_pricing_rec_status_priority', ['status', 'priority'], unique=False)

    # ### Create rate_change_audit table ###
    op.create_table('rate_change_audit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_type_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('old_rate', sa.Float(), nullable=False),
        sa.Column('new_rate', sa.Float(), nullable=False),
        sa.Column('change_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('rule_id', sa.Integer(), nullable=True),
        sa.Column('recommendation_id', sa.Integer(), nullable=True),
        sa.Column('changed_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['room_type_id'], ['room_types.id'], ),
        sa.ForeignKeyConstraint(['rule_id'], ['rms_pricing_rules.id'], ),
        sa.ForeignKeyConstraint(['recommendation_id'], ['pricing_recommendation_records.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('rate_change_audit', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rate_change_audit_room_type_id'), ['room_type_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_change_audit_date'), ['date'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_change_audit_change_reason'), ['change_reason'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_change_audit_rule_id'), ['rule_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_change_audit_recommendation_id'), ['recommendation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_change_audit_changed_by'), ['changed_by'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_change_audit_changed_at'), ['changed_at'], unique=False)
        batch_op.create_index('ix_rate_audit_room_date', ['room_type_id', 'date'], unique=False)
        batch_op.create_index('ix_rate_audit_changed_at_reason', ['changed_at', 'change_reason'], unique=False)

    # ### Create auto_pricing_config table ###
    op.create_table('auto_pricing_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_type_id', sa.Integer(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('min_rate', sa.Float(), nullable=False),
        sa.Column('max_rate', sa.Float(), nullable=False),
        sa.Column('max_daily_change_percent', sa.Float(), nullable=False),
        sa.Column('competitor_tracking_enabled', sa.Boolean(), nullable=False),
        sa.Column('demand_pricing_enabled', sa.Boolean(), nullable=False),
        sa.Column('last_auto_update', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['room_type_id'], ['room_types.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auto_pricing_config', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auto_pricing_config_room_type_id'), ['room_type_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_auto_pricing_config_is_enabled'), ['is_enabled'], unique=False)
        batch_op.create_index(batch_op.f('ix_auto_pricing_config_last_auto_update'), ['last_auto_update'], unique=False)
        batch_op.create_index('ix_auto_pricing_enabled_room', ['is_enabled', 'room_type_id'], unique=False)

    # ### Create ai_insight_records table ###
    op.create_table('ai_insight_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('insight_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('revenue_impact', sa.Float(), nullable=True),
        sa.Column('priority', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('action_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('is_dismissed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ai_insight_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_insight_records_insight_type'), ['insight_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_insight_records_priority'), ['priority'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_insight_records_is_read'), ['is_read'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_insight_records_is_dismissed'), ['is_dismissed'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_insight_records_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_insight_records_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index('ix_ai_insights_unread_active', ['is_read', 'is_dismissed', 'expires_at'], unique=False)
        batch_op.create_index('ix_ai_insights_type_priority', ['insight_type', 'priority'], unique=False)

    # ### Create competitor_scrape_logs table ###
    op.create_table('competitor_scrape_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('competitor_id', sa.Integer(), nullable=False),
        sa.Column('scrape_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('rates_found', sa.Integer(), nullable=False),
        sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['competitor_id'], ['rms_competitors.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('competitor_scrape_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_competitor_scrape_logs_competitor_id'), ['competitor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_competitor_scrape_logs_scrape_status'), ['scrape_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_competitor_scrape_logs_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_competitor_scrape_logs_completed_at'), ['completed_at'], unique=False)
        batch_op.create_index('ix_scrape_logs_competitor_status', ['competitor_id', 'scrape_status'], unique=False)
        batch_op.create_index('ix_scrape_logs_status_started', ['scrape_status', 'started_at'], unique=False)

    # ### Create event_records table ###
    op.create_table('event_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('event_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('venue', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('expected_attendance', sa.Integer(), nullable=True),
        sa.Column('distance_km', sa.Float(), nullable=True),
        sa.Column('impact_score', sa.Float(), nullable=False),
        sa.Column('demand_lift_percent', sa.Float(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('external_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('event_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_event_records_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_records_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_records_venue'), ['venue'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_records_start_date'), ['start_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_records_end_date'), ['end_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_records_source'), ['source'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_records_external_id'), ['external_id'], unique=False)
        batch_op.create_index('ix_event_records_date_range', ['start_date', 'end_date'], unique=False)
        batch_op.create_index('ix_event_records_type_dates', ['event_type', 'start_date', 'end_date'], unique=False)
        batch_op.create_index('ix_event_records_impact', ['impact_score', 'demand_lift_percent'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### Drop event_records table ###
    with op.batch_alter_table('event_records', schema=None) as batch_op:
        batch_op.drop_index('ix_event_records_impact')
        batch_op.drop_index('ix_event_records_type_dates')
        batch_op.drop_index('ix_event_records_date_range')
        batch_op.drop_index(batch_op.f('ix_event_records_external_id'))
        batch_op.drop_index(batch_op.f('ix_event_records_source'))
        batch_op.drop_index(batch_op.f('ix_event_records_end_date'))
        batch_op.drop_index(batch_op.f('ix_event_records_start_date'))
        batch_op.drop_index(batch_op.f('ix_event_records_venue'))
        batch_op.drop_index(batch_op.f('ix_event_records_event_type'))
        batch_op.drop_index(batch_op.f('ix_event_records_name'))

    op.drop_table('event_records')

    # ### Drop competitor_scrape_logs table ###
    with op.batch_alter_table('competitor_scrape_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_scrape_logs_status_started')
        batch_op.drop_index('ix_scrape_logs_competitor_status')
        batch_op.drop_index(batch_op.f('ix_competitor_scrape_logs_completed_at'))
        batch_op.drop_index(batch_op.f('ix_competitor_scrape_logs_started_at'))
        batch_op.drop_index(batch_op.f('ix_competitor_scrape_logs_scrape_status'))
        batch_op.drop_index(batch_op.f('ix_competitor_scrape_logs_competitor_id'))

    op.drop_table('competitor_scrape_logs')

    # ### Drop ai_insight_records table ###
    with op.batch_alter_table('ai_insight_records', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_insights_type_priority')
        batch_op.drop_index('ix_ai_insights_unread_active')
        batch_op.drop_index(batch_op.f('ix_ai_insight_records_expires_at'))
        batch_op.drop_index(batch_op.f('ix_ai_insight_records_created_at'))
        batch_op.drop_index(batch_op.f('ix_ai_insight_records_is_dismissed'))
        batch_op.drop_index(batch_op.f('ix_ai_insight_records_is_read'))
        batch_op.drop_index(batch_op.f('ix_ai_insight_records_priority'))
        batch_op.drop_index(batch_op.f('ix_ai_insight_records_insight_type'))

    op.drop_table('ai_insight_records')

    # ### Drop auto_pricing_config table ###
    with op.batch_alter_table('auto_pricing_config', schema=None) as batch_op:
        batch_op.drop_index('ix_auto_pricing_enabled_room')
        batch_op.drop_index(batch_op.f('ix_auto_pricing_config_last_auto_update'))
        batch_op.drop_index(batch_op.f('ix_auto_pricing_config_is_enabled'))
        batch_op.drop_index(batch_op.f('ix_auto_pricing_config_room_type_id'))

    op.drop_table('auto_pricing_config')

    # ### Drop rate_change_audit table ###
    with op.batch_alter_table('rate_change_audit', schema=None) as batch_op:
        batch_op.drop_index('ix_rate_audit_changed_at_reason')
        batch_op.drop_index('ix_rate_audit_room_date')
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_changed_at'))
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_changed_by'))
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_recommendation_id'))
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_rule_id'))
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_change_reason'))
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_date'))
        batch_op.drop_index(batch_op.f('ix_rate_change_audit_room_type_id'))

    op.drop_table('rate_change_audit')

    # ### Drop pricing_recommendation_records table ###
    with op.batch_alter_table('pricing_recommendation_records', schema=None) as batch_op:
        batch_op.drop_index('ix_pricing_rec_status_priority')
        batch_op.drop_index('ix_pricing_rec_date_room')
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_actioned_by'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_actioned_at'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_created_at'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_status'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_priority'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_demand_level'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_room_type_id'))
        batch_op.drop_index(batch_op.f('ix_pricing_recommendation_records_date'))

    op.drop_table('pricing_recommendation_records')

    # ### end Alembic commands ###
