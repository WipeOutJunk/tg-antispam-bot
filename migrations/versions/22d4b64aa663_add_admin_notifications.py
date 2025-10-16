"""Add admin_notifications and admin_notification_messages tables

Revision ID: 20251016_01
Revises: <previous_revision>
Create Date: 2025-10-16 19:35:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251016_01'
down_revision = '<previous_revision>'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'admin_notifications',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('original_chat_id', sa.BigInteger, nullable=False),
        sa.Column('original_message_id', sa.BigInteger, nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('event_data', sa.Text),
        sa.Column('is_processed', sa.Boolean, nullable=False, server_default=sa.text('FALSE')),
        sa.Column('processed_by', sa.BigInteger),
        sa.Column('processed_at', sa.DateTime),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now())
    )
    op.create_table(
        'admin_notification_messages',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('admin_notification_id', sa.Integer, sa.ForeignKey('admin_notifications.id'), nullable=False),
        sa.Column('admin_id', sa.BigInteger, nullable=False),
        sa.Column('message_id', sa.BigInteger, nullable=False),
        sa.Column('chat_id', sa.BigInteger, nullable=False),
        sa.Column('is_deleted', sa.Boolean, nullable=False, server_default=sa.text('FALSE')),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now())
    )

def downgrade():
    op.drop_table('admin_notification_messages')
    op.drop_table('admin_notifications')
