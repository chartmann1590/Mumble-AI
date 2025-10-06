-- Create conversation sessions table for tracking conversation state
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id SERIAL PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL UNIQUE,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    state VARCHAR(20) DEFAULT 'active' CHECK (state IN ('active', 'idle', 'closed')),
    message_count INTEGER DEFAULT 0,
    UNIQUE(user_name, session_id)
);

-- Create conversation history table with semantic memory support
CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    user_session INTEGER NOT NULL,
    session_id VARCHAR(255),
    message_type VARCHAR(10) NOT NULL CHECK (message_type IN ('voice', 'text')),
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    message TEXT NOT NULL,
    embedding FLOAT8[],
    importance_score FLOAT DEFAULT 0.5,
    summary TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(session_id) ON DELETE SET NULL
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_conversation_timestamp ON conversation_history(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_user ON conversation_history(user_name);
CREATE INDEX IF NOT EXISTS idx_conversation_session ON conversation_history(session_id);
CREATE INDEX IF NOT EXISTS idx_conversation_role ON conversation_history(role);
CREATE INDEX IF NOT EXISTS idx_session_user ON conversation_sessions(user_name);
CREATE INDEX IF NOT EXISTS idx_session_activity ON conversation_sessions(last_activity DESC);

-- Create a view for recent conversations
CREATE OR REPLACE VIEW recent_conversations AS
SELECT
    id,
    user_name,
    message_type,
    role,
    message,
    timestamp
FROM conversation_history
ORDER BY timestamp DESC
LIMIT 100;

-- Create bot configuration table
CREATE TABLE IF NOT EXISTS bot_config (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default configuration values
INSERT INTO bot_config (key, value) VALUES
    ('ollama_url', 'http://host.docker.internal:11434'),
    ('ollama_model', 'llama3.2:latest'),
    ('piper_voice', 'en_US-lessac-medium'),
    ('bot_persona', ''),
    ('whisper_language', 'auto'),
    ('tts_engine', 'piper'),
    ('silero_voice', 'en_0'),
    ('embedding_model', 'nomic-embed-text:latest'),
    ('short_term_memory_limit', '3'),
    ('long_term_memory_limit', '3'),
    ('semantic_similarity_threshold', '0.7'),
    ('session_timeout_minutes', '30'),
    ('session_reactivation_minutes', '10')
ON CONFLICT (key) DO NOTHING;

-- Function to calculate cosine similarity between two embedding vectors
CREATE OR REPLACE FUNCTION cosine_similarity(vec1 FLOAT8[], vec2 FLOAT8[])
RETURNS FLOAT8 AS $$
DECLARE
    dot_product FLOAT8 := 0;
    magnitude1 FLOAT8 := 0;
    magnitude2 FLOAT8 := 0;
    i INTEGER;
BEGIN
    -- Handle null or empty arrays
    IF vec1 IS NULL OR vec2 IS NULL OR array_length(vec1, 1) IS NULL OR array_length(vec2, 1) IS NULL THEN
        RETURN 0;
    END IF;

    -- Calculate dot product and magnitudes
    FOR i IN 1..array_length(vec1, 1) LOOP
        dot_product := dot_product + (vec1[i] * vec2[i]);
        magnitude1 := magnitude1 + (vec1[i] * vec1[i]);
        magnitude2 := magnitude2 + (vec2[i] * vec2[i]);
    END LOOP;

    -- Avoid division by zero
    IF magnitude1 = 0 OR magnitude2 = 0 THEN
        RETURN 0;
    END IF;

    RETURN dot_product / (sqrt(magnitude1) * sqrt(magnitude2));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Create persistent memories table for important notes and information
CREATE TABLE IF NOT EXISTS persistent_memories (
    id SERIAL PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL CHECK (category IN ('schedule', 'fact', 'preference', 'task', 'reminder', 'other')),
    content TEXT NOT NULL,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(255),
    importance INTEGER DEFAULT 5 CHECK (importance >= 1 AND importance <= 10),
    tags TEXT[],
    active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(session_id) ON DELETE SET NULL
);

-- Create indexes for memories
CREATE INDEX IF NOT EXISTS idx_memories_user ON persistent_memories(user_name);
CREATE INDEX IF NOT EXISTS idx_memories_category ON persistent_memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_active ON persistent_memories(active);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON persistent_memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON persistent_memories USING GIN(tags);

-- Create a view for active memories
CREATE OR REPLACE VIEW active_memories AS
SELECT
    id,
    user_name,
    category,
    content,
    extracted_at,
    importance,
    tags
FROM persistent_memories
WHERE active = TRUE
ORDER BY importance DESC, extracted_at DESC;

-- Create email settings table for daily summary emails
CREATE TABLE IF NOT EXISTS email_settings (
    id SERIAL PRIMARY KEY,
    smtp_host VARCHAR(255) NOT NULL DEFAULT 'localhost',
    smtp_port INTEGER NOT NULL DEFAULT 25,
    smtp_username VARCHAR(255),
    smtp_password VARCHAR(255),
    smtp_use_tls BOOLEAN DEFAULT FALSE,
    smtp_use_ssl BOOLEAN DEFAULT FALSE,
    from_email VARCHAR(255) NOT NULL DEFAULT 'mumble-ai@localhost',
    recipient_email VARCHAR(255),
    daily_summary_enabled BOOLEAN DEFAULT FALSE,
    summary_time TIME DEFAULT '22:00:00',  -- 10pm
    timezone VARCHAR(50) DEFAULT 'America/New_York',  -- EST
    last_sent TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default email settings
INSERT INTO email_settings (id, smtp_host, smtp_port, from_email, daily_summary_enabled)
VALUES (1, 'localhost', 25, 'mumble-ai@localhost', FALSE)
ON CONFLICT (id) DO NOTHING;

-- Create index for email settings
CREATE INDEX IF NOT EXISTS idx_email_last_sent ON email_settings(last_sent DESC);

COMMENT ON TABLE conversation_history IS 'Stores all conversation history between users and the AI bot';
COMMENT ON COLUMN conversation_history.message_type IS 'Type of message: voice or text';
COMMENT ON COLUMN conversation_history.role IS 'Role: user or assistant';
COMMENT ON TABLE bot_config IS 'Stores bot configuration settings';
COMMENT ON TABLE persistent_memories IS 'Stores important extracted memories like schedules, facts, preferences, and tasks';
COMMENT ON TABLE email_settings IS 'Stores email configuration for daily summary emails';
