#!/bin/bash
# Initialize app DB with schema
# This script is run by Docker on app_db startup

set -e

# Execute the app schema SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- App Database Schema
    CREATE TABLE IF NOT EXISTS conversations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,
        title VARCHAR(500),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        archived BOOLEAN DEFAULT FALSE
    );

    CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
    CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at DESC);

    CREATE TABLE IF NOT EXISTS messages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);

    CREATE TABLE IF NOT EXISTS query_log (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        user_question TEXT NOT NULL,
        generated_sql TEXT,
        validation_status VARCHAR(50),
        validation_reason TEXT,
        execution_status VARCHAR(50),
        execution_error TEXT,
        result_row_count INTEGER,
        result_summary TEXT,
        latency_ms INTEGER,
        token_count INTEGER,
        cost_usd NUMERIC(10, 6),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_query_log_conversation_id ON query_log(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_query_log_created_at ON query_log(created_at DESC);

    CREATE TABLE IF NOT EXISTS eval_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        dataset_version VARCHAR(100) NOT NULL,
        eval_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        total_items INTEGER,
        successful_executions INTEGER,
        accuracy_percentage NUMERIC(5, 2),
        schema_retrieval_recall NUMERIC(5, 2),
        unsafe_query_block_rate NUMERIC(5, 2),
        avg_latency_ms NUMERIC(10, 2),
        total_tokens INTEGER,
        total_cost_usd NUMERIC(10, 6),
        notes TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_eval_runs_timestamp ON eval_runs(eval_timestamp DESC);

    -- Grant appropriate permissions to app user
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_user;
    GRANT USAGE, CREATE ON SCHEMA public TO app_user;
EOSQL

echo "App DB schema initialized successfully"
