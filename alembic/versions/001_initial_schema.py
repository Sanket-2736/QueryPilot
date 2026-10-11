"""Initial schema: conversations, messages, query_log, eval_runs.

Revision ID: 001
Revises: 
Create Date: 2024-10-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create conversations, messages, query_log, eval_runs tables."""
    # Conversations table
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Index('idx_conversations_user_id', 'user_id'),
    )

    # Messages table (tracks each turn in a conversation)
    op.create_table(
        'messages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('turn_number', sa.Integer, nullable=False),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('plan', sa.JSON, nullable=True),
        sa.Column('sql', sa.Text, nullable=True),
        sa.Column('status', sa.String(50), nullable=False),  # answered, rejected, failed, needs_clarification
        sa.Column('answer', sa.Text, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('iterations_used', sa.Integer, nullable=False),
        sa.Column('retries_used', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Index('idx_messages_conversation_id', 'conversation_id'),
        sa.Index('idx_messages_turn_number', 'conversation_id', 'turn_number'),
    )

    # Query log table (tracks SQL execution details)
    op.create_table(
        'query_log',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sql', sa.Text, nullable=False),
        sa.Column('result_summary', sa.JSON, nullable=True),  # {columns, row_count, sample_rows}
        sa.Column('success', sa.Boolean, nullable=False),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('latency_ms', sa.Integer, nullable=False),  # Query execution time
        sa.Column('tokens_used', sa.Integer, nullable=True),  # LLM tokens for turn
        sa.Column('cost_cents', sa.Float, nullable=True),  # Cost in cents for turn
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Index('idx_query_log_conversation_id', 'conversation_id'),
        sa.Index('idx_query_log_success', 'success'),
    )

    # Eval runs table (tracks evaluation experiments)
    op.create_table(
        'eval_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('config', sa.JSON, nullable=True),  # eval config (thresholds, flags, etc.)
        sa.Column('total_questions', sa.Integer, nullable=False),
        sa.Column('succeeded_count', sa.Integer, nullable=False),
        sa.Column('failed_count', sa.Integer, nullable=False),
        sa.Column('accuracy', sa.Float, nullable=True),
        sa.Column('avg_latency_ms', sa.Float, nullable=True),
        sa.Column('total_tokens', sa.Integer, nullable=True),
        sa.Column('total_cost_cents', sa.Float, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Long-term memory table (successful question-SQL pairs with embeddings)
    op.create_table(
        'long_term_memory',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('sql', sa.Text, nullable=False),
        sa.Column('embedding', sa.LargeBinary, nullable=True),  # Vector embedding (binary)
        sa.Column('category', sa.String(100), nullable=True),  # aggregation, join, time_comparison, etc.
        sa.Column('success_rate', sa.Float, nullable=False, default=1.0),
        sa.Column('usage_count', sa.Integer, nullable=False, default=1),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Index('idx_long_term_memory_user', 'conversation_id'),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('long_term_memory')
    op.drop_table('eval_runs')
    op.drop_table('query_log')
    op.drop_table('messages')
    op.drop_table('conversations')
