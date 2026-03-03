-- ============================================================================
-- Schema: aria_engine
-- Engine infrastructure — sessions, agents, scheduling, models
-- ============================================================================

-- ============================================================================
-- Chat Sessions
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.chat_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id VARCHAR(100) NOT NULL DEFAULT 'aria',
    session_type VARCHAR(50) NOT NULL DEFAULT 'interactive',
    title VARCHAR(500),
    system_prompt TEXT,
    model VARCHAR(200),
    temperature FLOAT DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 4096,
    context_window INTEGER DEFAULT 50,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    total_cost NUMERIC(10,6) DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_ae_cs_agent   ON aria_engine.chat_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_ae_cs_status  ON aria_engine.chat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_ae_cs_created ON aria_engine.chat_sessions(created_at);

-- ============================================================================
-- Chat Messages
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES aria_engine.chat_sessions(id) ON DELETE CASCADE,
    agent_id VARCHAR(100),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    thinking TEXT,
    tool_calls JSONB,
    tool_results JSONB,
    model VARCHAR(200),
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost NUMERIC(10,6),
    latency_ms INTEGER,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_cm_session ON aria_engine.chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_ae_cm_agent   ON aria_engine.chat_messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_ae_cm_role    ON aria_engine.chat_messages(role);
CREATE INDEX IF NOT EXISTS idx_ae_cm_created ON aria_engine.chat_messages(created_at);

-- ============================================================================
-- Cron Jobs
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.cron_jobs (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    schedule VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) DEFAULT 'aria',
    model VARCHAR(200) DEFAULT NULL,
    enabled BOOLEAN DEFAULT true,
    payload_type VARCHAR(50) DEFAULT 'prompt',
    payload TEXT NOT NULL,
    session_mode VARCHAR(50) DEFAULT 'isolated',
    max_duration_seconds INTEGER DEFAULT 300,
    retry_count INTEGER DEFAULT 0,
    last_run_at TIMESTAMP WITH TIME ZONE,
    last_status VARCHAR(20),
    last_duration_ms INTEGER,
    last_error TEXT,
    next_run_at TIMESTAMP WITH TIME ZONE,
    run_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_cj_enabled  ON aria_engine.cron_jobs(enabled);
CREATE INDEX IF NOT EXISTS idx_ae_cj_next_run ON aria_engine.cron_jobs(next_run_at);

-- ============================================================================
-- Agent State
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.agent_state (
    agent_id VARCHAR(100) PRIMARY KEY,
    display_name VARCHAR(200),
    agent_type VARCHAR(30) DEFAULT 'agent',
    parent_agent_id VARCHAR(100),
    model VARCHAR(200) NOT NULL,
    fallback_model VARCHAR(200),
    temperature FLOAT DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 4096,
    system_prompt TEXT,
    focus_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'idle',
    enabled BOOLEAN DEFAULT true,
    skills JSONB DEFAULT '[]',
    capabilities JSONB DEFAULT '[]',
    current_session_id UUID,
    current_task TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    pheromone_score NUMERIC(5,3) DEFAULT 0.500,
    timeout_seconds INTEGER DEFAULT 600,
    rate_limit JSONB DEFAULT '{}',
    last_active_at TIMESTAMP WITH TIME ZONE,
    app_managed BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Config (key-value store)
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.config (
    key VARCHAR(200) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_by VARCHAR(100) DEFAULT 'system'
);

-- ============================================================================
-- Agent Tools
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.agent_tools (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id VARCHAR(100) NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    function_name VARCHAR(100) NOT NULL,
    description TEXT,
    parameters JSONB DEFAULT '{}',
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_at_agent ON aria_engine.agent_tools(agent_id);

-- ============================================================================
-- Rate Limits
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.rate_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill VARCHAR(100) NOT NULL UNIQUE,
    last_action TIMESTAMP WITH TIME ZONE,
    action_count INTEGER DEFAULT 0,
    window_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_post TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_rl_skill ON aria_engine.rate_limits(skill);

-- ============================================================================
-- API Key Rotations
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.api_key_rotations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service VARCHAR(100) NOT NULL,
    rotated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reason TEXT,
    rotated_by VARCHAR(100) DEFAULT 'system',
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ae_akr_service ON aria_engine.api_key_rotations(service);

-- ============================================================================
-- Schedule Tick (singleton)
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.schedule_tick (
    id INTEGER PRIMARY KEY,
    last_tick TIMESTAMP WITH TIME ZONE,
    tick_count INTEGER DEFAULT 0,
    heartbeat_interval INTEGER DEFAULT 3600,
    enabled BOOLEAN DEFAULT true,
    jobs_total INTEGER DEFAULT 0,
    jobs_successful INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    last_job_name VARCHAR(255),
    last_job_status VARCHAR(50),
    next_job_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Scheduled Jobs
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.scheduled_jobs (
    id VARCHAR(50) PRIMARY KEY,
    agent_id VARCHAR(50) DEFAULT 'aria',
    name VARCHAR(100) NOT NULL,
    enabled BOOLEAN DEFAULT true,
    schedule_kind VARCHAR(20) DEFAULT 'cron',
    schedule_expr VARCHAR(50) NOT NULL,
    session_target VARCHAR(50),
    wake_mode VARCHAR(50),
    payload_kind VARCHAR(50),
    payload_text TEXT,
    next_run_at TIMESTAMP WITH TIME ZONE,
    last_run_at TIMESTAMP WITH TIME ZONE,
    last_status VARCHAR(20),
    last_duration_ms INTEGER,
    run_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    created_at_ms INTEGER,
    updated_at_ms INTEGER,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_sj_name    ON aria_engine.scheduled_jobs(name);
CREATE INDEX IF NOT EXISTS idx_ae_sj_enabled ON aria_engine.scheduled_jobs(enabled);
CREATE INDEX IF NOT EXISTS idx_ae_sj_next    ON aria_engine.scheduled_jobs(next_run_at);

-- ============================================================================
-- LLM Model Catalog
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.llm_models (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(300) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'litellm',
    tier VARCHAR(30) NOT NULL DEFAULT 'free',
    reasoning BOOLEAN DEFAULT false,
    vision BOOLEAN DEFAULT false,
    tool_calling BOOLEAN DEFAULT false,
    input_types JSONB DEFAULT '["text"]',
    context_window INTEGER DEFAULT 8192,
    max_tokens INTEGER DEFAULT 4096,
    cost_input NUMERIC(12, 6) DEFAULT 0,
    cost_output NUMERIC(12, 6) DEFAULT 0,
    cost_cache_read NUMERIC(12, 6) DEFAULT 0,
    litellm_model VARCHAR(300),
    litellm_api_key VARCHAR(500),
    litellm_api_base VARCHAR(500),
    route_skill VARCHAR(100),
    aliases JSONB DEFAULT '[]',
    enabled BOOLEAN DEFAULT true,
    sort_order INTEGER DEFAULT 100,
    app_managed BOOLEAN DEFAULT false,
    extra JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_lm_provider ON aria_engine.llm_models(provider);
CREATE INDEX IF NOT EXISTS idx_ae_lm_tier     ON aria_engine.llm_models(tier);
CREATE INDEX IF NOT EXISTS idx_ae_lm_enabled  ON aria_engine.llm_models(enabled);

-- ============================================================================
-- Focus Profiles — personality layers for agents
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.focus_profiles (
    focus_id VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    emoji VARCHAR(10) NOT NULL DEFAULT '🎯',
    description TEXT,
    tone VARCHAR(30) NOT NULL DEFAULT 'neutral',
    style VARCHAR(30) NOT NULL DEFAULT 'directive',
    delegation_level INTEGER NOT NULL DEFAULT 2,
    token_budget_hint INTEGER NOT NULL DEFAULT 2000,
    temperature_delta DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    expertise_keywords JSONB NOT NULL DEFAULT '[]',
    system_prompt_addon TEXT,
    model_override VARCHAR(200),
    auto_skills JSONB NOT NULL DEFAULT '[]',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_fp_enabled ON aria_engine.focus_profiles(enabled);

-- ============================================================================
-- Chat Sessions Archive — archived engine chat sessions
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.chat_sessions_archive (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    session_type VARCHAR(50) NOT NULL,
    title VARCHAR(500),
    system_prompt TEXT,
    model VARCHAR(200),
    temperature DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 4096,
    context_window INTEGER NOT NULL DEFAULT 50,
    status VARCHAR(20) NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost NUMERIC(10,6) NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    archived_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_csa_archived      ON aria_engine.chat_sessions_archive(archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_ae_csa_session_type  ON aria_engine.chat_sessions_archive(session_type);
CREATE INDEX IF NOT EXISTS idx_ae_csa_status        ON aria_engine.chat_sessions_archive(status);
CREATE INDEX IF NOT EXISTS idx_ae_csa_updated       ON aria_engine.chat_sessions_archive(updated_at DESC);

-- ============================================================================
-- Chat Messages Archive — archived engine chat messages
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_engine.chat_messages_archive (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES aria_engine.chat_sessions_archive(id) ON DELETE CASCADE,
    agent_id VARCHAR(100),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    thinking TEXT,
    tool_calls JSONB,
    tool_results JSONB,
    model VARCHAR(200),
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost NUMERIC(10,6),
    latency_ms INTEGER,
    embedding vector(1536),
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    archived_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ae_cma_session ON aria_engine.chat_messages_archive(session_id);
CREATE INDEX IF NOT EXISTS idx_ae_cma_role    ON aria_engine.chat_messages_archive(role);
CREATE INDEX IF NOT EXISTS idx_ae_cma_created ON aria_engine.chat_messages_archive(created_at);
CREATE INDEX IF NOT EXISTS idx_ae_cma_archived ON aria_engine.chat_messages_archive(archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_ae_cma_session_created ON aria_engine.chat_messages_archive(session_id, created_at);

-- ============================================================================
-- Seed default agent
-- ============================================================================
INSERT INTO aria_engine.agent_state (agent_id, display_name, model, system_prompt, status)
VALUES ('aria', 'Aria (Orchestrator)', 'kimi', 'You are Aria, an autonomous AI agent.', 'idle')
ON CONFLICT (agent_id) DO NOTHING;
