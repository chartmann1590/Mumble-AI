-- Create conversation history table
CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    user_session INTEGER NOT NULL,
    message_type VARCHAR(10) NOT NULL CHECK (message_type IN ('voice', 'text')),
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    message TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_conversation_timestamp ON conversation_history(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_user ON conversation_history(user_name);

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
    ('silero_voice', 'en_0')
ON CONFLICT (key) DO NOTHING;

COMMENT ON TABLE conversation_history IS 'Stores all conversation history between users and the AI bot';
COMMENT ON COLUMN conversation_history.message_type IS 'Type of message: voice or text';
COMMENT ON COLUMN conversation_history.role IS 'Role: user or assistant';
COMMENT ON TABLE bot_config IS 'Stores bot configuration settings';
