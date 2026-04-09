"""Initial platform tables — all models from Phase 0-7.

Revision ID: 001
Revises: None
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON, ARRAY

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── Users (Phase 1) ──────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('supabase_uid', sa.String(255), unique=True, index=True, nullable=False),
        sa.Column('email', sa.String(255), unique=True, index=True, nullable=False),
        sa.Column('name', sa.String(255), server_default='', nullable=False),
        sa.Column('plan', sa.String(20), server_default='free', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'user_preferences',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('language', sa.String(10), server_default='en', nullable=False),
        sa.Column('confidence_level', sa.String(10), server_default='95', nullable=False),
        sa.Column('default_prompt', sa.Text(), nullable=True),
    )

    # ─── Teams (Phase 6) ─────────────────────────────────────────────
    op.create_table(
        'teams',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('owner_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'team_members',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('team_id', UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('role', sa.String(20), server_default='viewer', nullable=False),
        sa.UniqueConstraint('team_id', 'user_id', name='uq_team_members_team_user'),
    )

    # ─── Projects (Phase 2) ──────────────────────────────────────────
    op.create_table(
        'projects',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_type', sa.String(20), server_default='user', nullable=False),
        sa.Column('owner_id', UUID(as_uuid=True), index=True, nullable=False),
        sa.Column('status', sa.String(20), server_default='processing', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('study_objective', sa.Text(), nullable=True),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('target_audience', sa.Text(), nullable=True),
        sa.Column('brands', ARRAY(sa.String()), nullable=True),
        sa.Column('methodology', sa.String(100), nullable=True),
        sa.Column('study_date', sa.Date(), nullable=True),
        sa.Column('is_tracking', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('report_language', sa.String(10), server_default='en', nullable=False),
        sa.Column('low_base_threshold', sa.Integer(), server_default='20', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'project_files',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('file_type', sa.String(30), nullable=False),
        sa.Column('storage_path', sa.String(512), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'dataset_metadata',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('n_cases', sa.Integer(), nullable=False),
        sa.Column('n_variables', sa.Integer(), nullable=False),
        sa.Column('variables', JSON, server_default='[]', nullable=False),
        sa.Column('basic_frequencies', JSON, server_default='{}', nullable=False),
        sa.Column('basic_stats', JSON, server_default='{}', nullable=False),
        sa.Column('variable_profiles', JSON, server_default='[]', nullable=False),
        sa.Column('user_metadata_overrides', JSON, server_default='{}', nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── Conversations (Phase 3) ─────────────────────────────────────
    op.create_table(
        'conversations',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('title', sa.String(255), server_default='New conversation', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'messages',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), server_default='', nullable=False),
        sa.Column('analyses_performed', JSON, nullable=True),
        sa.Column('charts', JSON, nullable=True),
        sa.Column('variables_used', JSON, nullable=True),
        sa.Column('python_code', sa.Text(), nullable=True),
        sa.Column('warnings', JSON, nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── Data Prep (Phase 4) ─────────────────────────────────────────
    op.create_table(
        'data_prep_rules',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('rule_type', sa.String(20), nullable=False),
        sa.Column('name', sa.String(255), server_default='', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('config', JSON, server_default='{}', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('order_index', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'variable_groups',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('group_type', sa.String(50), server_default='mrs', nullable=False),
        sa.Column('variables', ARRAY(sa.String()), server_default='{}', nullable=False),
        sa.Column('parent_group_id', UUID(as_uuid=True), nullable=True),
        sa.Column('hidden_by_group', JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'project_waves',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('wave_name', sa.String(255), nullable=False),
        sa.Column('wave_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('file_id', UUID(as_uuid=True), sa.ForeignKey('project_files.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'explore_bookmarks',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('config', JSON, server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'segments',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('conditions', JSON, server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── Exports & Reports (Phase 5) ─────────────────────────────────
    op.create_table(
        'exports',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('export_type', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('file_path', sa.String(512), nullable=True),
        sa.Column('download_url', sa.String(1024), nullable=True),
        sa.Column('config', JSON, server_default='{}', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'table_templates',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('config', JSON, server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'reports',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('title', sa.String(255), server_default='Report', nullable=False),
        sa.Column('status', sa.String(20), server_default='generating', nullable=False),
        sa.Column('progress', sa.Integer(), server_default='0', nullable=False),
        sa.Column('content', JSON, nullable=True),
        sa.Column('file_path', sa.String(512), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── Dashboards & Sharing (Phase 6) ──────────────────────────────
    op.create_table(
        'dashboards',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('widgets', JSON, server_default='[]', nullable=False),
        sa.Column('filters', JSON, server_default='{}', nullable=False),
        sa.Column('is_published', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('share_token', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'share_links',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('token', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('view_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=True),
        sa.Column('details', JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('share_links')
    op.drop_table('dashboards')
    op.drop_table('reports')
    op.drop_table('table_templates')
    op.drop_table('exports')
    op.drop_table('segments')
    op.drop_table('explore_bookmarks')
    op.drop_table('project_waves')
    op.drop_table('variable_groups')
    op.drop_table('data_prep_rules')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('dataset_metadata')
    op.drop_table('project_files')
    op.drop_table('projects')
    op.drop_table('team_members')
    op.drop_table('teams')
    op.drop_table('user_preferences')
    op.drop_table('users')
