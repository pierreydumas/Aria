-- Agent Performance (Pheromone) Tracking Schema
-- Week 1 of Orchestrator Mindset v2 - Metrics Foundation
-- Created: 2026-02-09
-- 
-- Pheromone reinforcement tracks agent success metrics to enable
-- dynamic agent selection based on historical performance.

-- ============================================
-- Main Table: agent_performance (Pheromone Trail)
-- ============================================
CREATE TABLE IF NOT EXISTS agent_performance (
    id SERIAL PRIMARY KEY,
    
    -- Agent identification
    agent_id VARCHAR(64) NOT NULL,           -- e.g., 'devops', 'analyst', 'creator', 'memory'
    agent_focus VARCHAR(32),                  -- e.g., 'devsecops', 'data', 'social'
    session_key VARCHAR(64),                  -- Link to agent session
    
    -- Task classification
    task_type VARCHAR(64) NOT NULL,           -- e.g., 'code_review', 'security_scan', 'data_analysis'
    task_complexity VARCHAR(16),              -- 'simple', 'medium', 'complex'
    skill_used VARCHAR(64),                   -- Which skill was invoked
    
    -- Performance metrics (pheromone components)
    success BOOLEAN DEFAULT true,             -- Did the task complete successfully?
    completion_rate DECIMAL(5,2),             -- 0.00 - 1.00 (partial completion tracking)
    
    -- Token efficiency metrics
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    tokens_total INTEGER GENERATED ALWAYS AS (tokens_input + tokens_output) STORED,
    cost_usd DECIMAL(10, 6) DEFAULT 0.0,
    
    -- Time metrics
    duration_ms INTEGER,                      -- Time to complete
    time_to_first_token_ms INTEGER,           -- Latency perception
    
    -- Quality signals (implicit user satisfaction)
    retry_count INTEGER DEFAULT 0,            -- How many retries needed
    error_count INTEGER DEFAULT 0,            -- Errors encountered
    was_escalated BOOLEAN DEFAULT false,      -- Required human intervention
    
    -- Pheromone score (calculated)
    pheromone_score DECIMAL(6, 3),            -- Composite score (see calculation below)
    
    -- Metadata
    model_used VARCHAR(64),                   -- Which model the agent used
    metadata JSONB DEFAULT '{}',              -- Extra context
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- Indexes for Efficient Querying
-- ============================================
CREATE INDEX IF NOT EXISTS idx_agent_perf_agent ON agent_performance(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_perf_task ON agent_performance(task_type);
CREATE INDEX IF NOT EXISTS idx_agent_perf_skill ON agent_performance(skill_used);
CREATE INDEX IF NOT EXISTS idx_agent_perf_success ON agent_performance(success);
CREATE INDEX IF NOT EXISTS idx_agent_perf_pheromone ON agent_performance(pheromone_score DESC);
CREATE INDEX IF NOT EXISTS idx_agent_perf_created ON agent_performance(created_at);

-- Composite index for agent+task lookups (common query pattern)
CREATE INDEX IF NOT EXISTS idx_agent_perf_agent_task 
ON agent_performance(agent_id, task_type, created_at DESC);

-- ============================================
-- Pheromone Score Calculation Function
-- ============================================
-- Higher score = better agent for this task type
-- Factors:
--   - Success rate (40% weight)
--   - Token efficiency (30% weight) - lower is better
--   - Speed (20% weight) - faster is better  
--   - Quality signals (10% weight) - fewer retries/errors

CREATE OR REPLACE FUNCTION calculate_pheromone_score(
    p_success BOOLEAN,
    p_completion_rate DECIMAL,
    p_tokens_total INTEGER,
    p_duration_ms INTEGER,
    p_retry_count INTEGER,
    p_error_count INTEGER,
    p_was_escalated BOOLEAN
) RETURNS DECIMAL(6, 3) AS $$
DECLARE
    v_success_weight DECIMAL := 0.40;
    v_efficiency_weight DECIMAL := 0.30;
    v_speed_weight DECIMAL := 0.20;
    v_quality_weight DECIMAL := 0.10;
    
    v_success_score DECIMAL;
    v_efficiency_score DECIMAL;
    v_speed_score DECIMAL;
    v_quality_score DECIMAL;
    v_final_score DECIMAL;
BEGIN
    -- Success score (0-100 base, scaled to weight)
    IF p_success AND p_completion_rate >= 1.0 THEN
        v_success_score := 100 * v_success_weight;
    ELSIF p_success THEN
        v_success_score := (p_completion_rate * 100) * v_success_weight;
    ELSE
        v_success_score := 0;
    END IF;
    
    -- Efficiency score (assume 10k tokens is baseline "average")
    -- Lower tokens = higher score, max 100
    v_efficiency_score := GREATEST(0, LEAST(100, (10000.0 / NULLIF(p_tokens_total, 0)) * 100)) * v_efficiency_weight;
    
    -- Speed score (assume 30s is baseline "average")
    -- Faster = higher score, max 100
    v_speed_score := GREATEST(0, LEAST(100, (30000.0 / NULLIF(p_duration_ms, 0)) * 100)) * v_speed_weight;
    
    -- Quality score (penalties for issues)
    v_quality_score := 100 * v_quality_weight;
    v_quality_score := v_quality_score - (p_retry_count * 5);     -- -5 per retry
    v_quality_score := v_quality_score - (p_error_count * 10);    -- -10 per error
    IF p_was_escalated THEN
        v_quality_score := v_quality_score - 25;                   -- -25 if escalated
    END IF;
    v_quality_score := GREATEST(0, v_quality_score);
    
    v_final_score := v_success_score + v_efficiency_score + v_speed_score + v_quality_score;
    
    RETURN ROUND(v_final_score, 3);
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Trigger: Auto-calculate pheromone score on insert/update
-- ============================================
CREATE OR REPLACE FUNCTION trigger_calc_pheromone()
RETURNS TRIGGER AS $$
BEGIN
    NEW.pheromone_score := calculate_pheromone_score(
        NEW.success,
        COALESCE(NEW.completion_rate, CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END),
        COALESCE(NEW.tokens_total, 0),
        COALESCE(NEW.duration_ms, 30000),
        COALESCE(NEW.retry_count, 0),
        COALESCE(NEW.error_count, 0),
        COALESCE(NEW.was_escalated, false)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_calc_pheromone ON agent_performance;
CREATE TRIGGER trg_calc_pheromone
    BEFORE INSERT OR UPDATE ON agent_performance
    FOR EACH ROW
    EXECUTE FUNCTION trigger_calc_pheromone();

-- ============================================
-- Views for Orchestrator Decision-Making
-- ============================================

-- View: Agent Pheromone Rankings by Task Type
-- Use this to select the best agent for a task
CREATE OR REPLACE VIEW v_agent_pheromone_rankings AS
SELECT 
    agent_id,
    agent_focus,
    task_type,
    task_complexity,
    COUNT(*) as task_count,
    AVG(pheromone_score) as avg_pheromone_score,
    AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate,
    AVG(tokens_total) as avg_tokens,
    AVG(duration_ms) as avg_duration_ms,
    MAX(created_at) as last_used
FROM agent_performance
WHERE created_at >= NOW() - INTERVAL '30 days'  -- Recent performance only
GROUP BY agent_id, agent_focus, task_type, task_complexity
ORDER BY task_type, avg_pheromone_score DESC;

-- View: Best Agent per Task Type (for quick lookup)
CREATE OR REPLACE VIEW v_best_agent_per_task AS
SELECT DISTINCT ON (task_type, task_complexity)
    task_type,
    task_complexity,
    agent_id as best_agent,
    avg_pheromone_score,
    success_rate,
    task_count
FROM v_agent_pheromone_rankings
WHERE task_count >= 3  -- Minimum sample size
ORDER BY task_type, task_complexity, avg_pheromone_score DESC;

-- View: Agent Health Dashboard
CREATE OR REPLACE VIEW v_agent_health_dashboard AS
SELECT 
    agent_id,
    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') as tasks_24h,
    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as tasks_7d,
    AVG(pheromone_score) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') as pheromone_24h,
    AVG(pheromone_score) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as pheromone_7d,
    AVG(CASE WHEN success THEN 1 ELSE 0 END) as overall_success_rate,
    SUM(cost_usd) as total_cost,
    MAX(created_at) as last_active
FROM agent_performance
GROUP BY agent_id
ORDER BY pheromone_24h DESC NULLS LAST;

-- ============================================
-- Materialized View: Daily Pheromone Trends
-- ============================================
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_pheromone_trends AS
SELECT 
    DATE(created_at) as date,
    agent_id,
    task_type,
    COUNT(*) as task_count,
    AVG(pheromone_score) as avg_pheromone,
    AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate,
    SUM(tokens_total) as total_tokens,
    SUM(cost_usd) as total_cost,
    AVG(duration_ms) as avg_duration
FROM agent_performance
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at), agent_id, task_type;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_pheromone 
ON mv_daily_pheromone_trends(date, agent_id, task_type);

-- Refresh function for cron
CREATE OR REPLACE FUNCTION refresh_pheromone_trends()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_pheromone_trends;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- API Helper Functions
-- ============================================

-- Function: Get best agent for task (used by orchestrator)
CREATE OR REPLACE FUNCTION get_best_agent_for_task(
    p_task_type VARCHAR,
    p_complexity VARCHAR DEFAULT 'medium'
) RETURNS TABLE (
    agent_id VARCHAR,
    agent_focus VARCHAR,
    pheromone_score DECIMAL,
    success_rate DECIMAL,
    sample_size BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ap.agent_id,
        ap.agent_focus,
        AVG(ap.pheromone_score)::DECIMAL(6,3) as pheromone_score,
        AVG(CASE WHEN ap.success THEN 1 ELSE 0 END)::DECIMAL(5,2) as success_rate,
        COUNT(*)::BIGINT as sample_size
    FROM agent_performance ap
    WHERE ap.task_type = p_task_type
      AND (p_complexity IS NULL OR ap.task_complexity = p_complexity)
      AND ap.created_at >= NOW() - INTERVAL '14 days'
    GROUP BY ap.agent_id, ap.agent_focus
    HAVING COUNT(*) >= 2  -- Minimum confidence threshold
    ORDER BY pheromone_score DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function: Record skill invocation (simplified interface)
CREATE OR REPLACE FUNCTION log_agent_performance(
    p_agent_id VARCHAR,
    p_agent_focus VARCHAR,
    p_task_type VARCHAR,
    p_task_complexity VARCHAR,
    p_skill_used VARCHAR,
    p_success BOOLEAN,
    p_tokens_input INTEGER DEFAULT 0,
    p_tokens_output INTEGER DEFAULT 0,
    p_cost_usd DECIMAL DEFAULT 0.0,
    p_duration_ms INTEGER DEFAULT NULL,
    p_model_used VARCHAR DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
) RETURNS INTEGER AS $$
DECLARE
    v_id INTEGER;
BEGIN
    INSERT INTO agent_performance (
        agent_id,
        agent_focus,
        task_type,
        task_complexity,
        skill_used,
        success,
        tokens_input,
        tokens_output,
        cost_usd,
        duration_ms,
        model_used,
        metadata
    ) VALUES (
        p_agent_id,
        p_agent_focus,
        p_task_type,
        p_task_complexity,
        p_skill_used,
        p_success,
        p_tokens_input,
        p_tokens_output,
        p_cost_usd,
        p_duration_ms,
        p_model_used,
        p_metadata
    )
    RETURNING id INTO v_id;
    
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Sample Queries for Verification
-- ============================================

-- Check current pheromone rankings:
-- SELECT * FROM v_agent_pheromone_rankings WHERE task_type = 'security_scan';

-- Get best agent for a task:
-- SELECT * FROM get_best_agent_for_task('code_review', 'complex');

-- Agent health check:
-- SELECT * FROM v_agent_health_dashboard;

-- Recent performance trend:
-- SELECT * FROM mv_daily_pheromone_trends WHERE date >= CURRENT_DATE - 7;

COMMENT ON TABLE agent_performance IS 'Pheromone trail tracking for agent performance-based selection';
COMMENT ON COLUMN agent_performance.pheromone_score IS 'Composite score: success(40%) + efficiency(30%) + speed(20%) + quality(10%)';
