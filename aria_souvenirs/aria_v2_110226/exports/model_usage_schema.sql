-- Model Usage Tracking Schema
-- Part of M3: Model Strategy Enforcement
-- Created: 2026-02-09

-- Table: model_usage_tracking
-- Tracks which models are used for different tasks to enable optimization

CREATE TABLE IF NOT EXISTS model_usage_tracking (
    id SERIAL PRIMARY KEY,
    session_key VARCHAR(64) NOT NULL,
    model_alias VARCHAR(64) NOT NULL,
    model_full_name VARCHAR(128),
    task_type VARCHAR(64), -- e.g., 'code', 'research', 'social', 'analysis'
    agent_id VARCHAR(64), -- e.g., 'aria', 'devops', 'analyst', 'creator'
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    cost_usd DECIMAL(10, 6) DEFAULT 0.0,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_model_usage_session ON model_usage_tracking(session_key);
CREATE INDEX IF NOT EXISTS idx_model_usage_model ON model_usage_tracking(model_alias);
CREATE INDEX IF NOT EXISTS idx_model_usage_task ON model_usage_tracking(task_type);
CREATE INDEX IF NOT EXISTS idx_model_usage_agent ON model_usage_tracking(agent_id);
CREATE INDEX IF NOT EXISTS idx_model_usage_created ON model_usage_tracking(created_at);

-- Materialized view: Daily model usage summary
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_model_usage AS
SELECT 
    DATE(created_at) as date,
    model_alias,
    agent_id,
    COUNT(*) as invocation_count,
    SUM(tokens_input) as total_input_tokens,
    SUM(tokens_output) as total_output_tokens,
    SUM(cost_usd) as total_cost,
    AVG(duration_ms) as avg_duration_ms,
    SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as success_rate
FROM model_usage_tracking
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at), model_alias, agent_id;

-- Index on materialized view
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_usage 
ON mv_daily_model_usage(date, model_alias, agent_id);

-- Function to refresh materialized view
CREATE OR REPLACE FUNCTION refresh_daily_model_usage()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_model_usage;
END;
$$ LANGUAGE plpgsql;

-- View: Cost analysis by model tier
CREATE OR REPLACE VIEW v_model_tier_costs AS
SELECT 
    CASE 
        WHEN model_alias LIKE '%-mlx' THEN 'local_free'
        WHEN model_alias LIKE '%-free' THEN 'cloud_free'
        WHEN model_alias LIKE 'litellm/kimi' THEN 'paid'
        ELSE 'unknown'
    END as tier,
    DATE(created_at) as date,
    COUNT(*) as invocations,
    SUM(cost_usd) as daily_cost,
    SUM(tokens_input + tokens_output) as daily_tokens
FROM model_usage_tracking
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY tier, DATE(created_at)
ORDER BY date DESC, daily_cost DESC;

-- Sample query for cost optimization:
-- SELECT * FROM v_model_tier_costs WHERE date = CURRENT_DATE;

COMMENT ON TABLE model_usage_tracking IS 'Tracks LLM model usage for cost optimization and strategy enforcement';
