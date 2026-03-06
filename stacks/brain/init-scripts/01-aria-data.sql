-- ============================================================================
-- Schema: aria_data
-- All Aria domain data — memories, thoughts, goals, knowledge, skills
-- Version: 3.0.0
-- ============================================================================

-- ============================================================================
-- Memories — Long-term storage
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(255) UNIQUE NOT NULL,
    value JSONB NOT NULL,
    category VARCHAR(100) DEFAULT 'general',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memories_key       ON aria_data.memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_category  ON aria_data.memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_updated   ON aria_data.memories(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created   ON aria_data.memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_value_gin ON aria_data.memories USING gin (value);

-- ============================================================================
-- Thoughts — Internal reflections and logs
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.thoughts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content TEXT NOT NULL,
    category VARCHAR(100) DEFAULT 'general',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_thoughts_category ON aria_data.thoughts(category);
CREATE INDEX IF NOT EXISTS idx_thoughts_created       ON aria_data.thoughts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_thoughts_content_trgm ON aria_data.thoughts USING gin (content gin_trgm_ops);

-- ============================================================================
-- Goals — Objectives and tasks (sprint board support)
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.goals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    priority INTEGER DEFAULT 2,
    progress NUMERIC(5,2) DEFAULT 0,
    due_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    sprint VARCHAR(100) DEFAULT 'backlog',
    board_column VARCHAR(50) DEFAULT 'backlog',
    position INTEGER DEFAULT 0,
    assigned_to VARCHAR(100),
    tags JSONB DEFAULT '[]',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_goals_status   ON aria_data.goals(status);
CREATE INDEX IF NOT EXISTS idx_goals_priority ON aria_data.goals(priority DESC);
CREATE INDEX IF NOT EXISTS idx_goals_created  ON aria_data.goals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_goals_sprint                  ON aria_data.goals(sprint);
CREATE INDEX IF NOT EXISTS idx_goals_board_column            ON aria_data.goals(board_column);
CREATE INDEX IF NOT EXISTS idx_goals_status_priority_created ON aria_data.goals(status, priority DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_goals_sprint_column_position  ON aria_data.goals(sprint, board_column, position);

-- ============================================================================
-- Activity Log — All Aria actions
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.activity_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action VARCHAR(100) NOT NULL,
    skill VARCHAR(100),
    details JSONB DEFAULT '{}',
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_action  ON aria_data.activity_log(action);
CREATE INDEX IF NOT EXISTS idx_activity_skill   ON aria_data.activity_log(skill);
CREATE INDEX IF NOT EXISTS idx_activity_created        ON aria_data.activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_action_created ON aria_data.activity_log(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_skill_created  ON aria_data.activity_log(skill, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_details_gin    ON aria_data.activity_log USING gin (details);

-- ============================================================================
-- Social Posts — Moltbook activity
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.social_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform VARCHAR(50) DEFAULT 'moltbook',
    post_id VARCHAR(100) UNIQUE,
    content TEXT NOT NULL,
    visibility VARCHAR(50) DEFAULT 'public',
    reply_to VARCHAR(100) REFERENCES aria_data.social_posts(post_id) ON DELETE SET NULL,
    url TEXT,
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_posts_platform ON aria_data.social_posts(platform);
CREATE INDEX IF NOT EXISTS idx_posts_posted  ON aria_data.social_posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_post_id ON aria_data.social_posts(post_id);

-- ============================================================================
-- Heartbeat Log — System health
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.heartbeat_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    beat_number INTEGER NOT NULL DEFAULT 0,
    job_name VARCHAR(100),
    status VARCHAR(50) DEFAULT 'healthy',
    details JSONB DEFAULT '{}',
    executed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_created  ON aria_data.heartbeat_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_heartbeat_job_name ON aria_data.heartbeat_log(job_name);

-- ============================================================================
-- Hourly Goals
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.hourly_goals (
    id SERIAL PRIMARY KEY,
    hour_slot INTEGER NOT NULL,
    goal_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hourly_status    ON aria_data.hourly_goals(status);
CREATE INDEX IF NOT EXISTS idx_hourly_hour_slot ON aria_data.hourly_goals(hour_slot);
CREATE INDEX IF NOT EXISTS idx_hourly_created   ON aria_data.hourly_goals(created_at DESC);

-- ============================================================================
-- Agent Sessions — Track agent conversation sessions
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.agent_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id VARCHAR(100) NOT NULL,
    session_type VARCHAR(50) DEFAULT 'interactive',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    messages_count INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    cost_usd NUMERIC(10, 6) DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent   ON aria_data.agent_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status  ON aria_data.agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_started       ON aria_data.agent_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_type          ON aria_data.agent_sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_started ON aria_data.agent_sessions(agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_metadata_gin  ON aria_data.agent_sessions USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_aria_sid      ON aria_data.agent_sessions((metadata ->> 'aria_session_id'));
CREATE INDEX IF NOT EXISTS idx_agent_sessions_external_sid  ON aria_data.agent_sessions((metadata ->> 'external_session_id'));

-- ============================================================================
-- Session Messages
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.session_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES aria_data.agent_sessions(id) ON DELETE SET NULL,
    external_session_id VARCHAR(120),
    agent_id VARCHAR(100),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    source_channel VARCHAR(50),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_session_message_ext_role_hash UNIQUE (external_session_id, role, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_session_messages_session  ON aria_data.session_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_external ON aria_data.session_messages(external_session_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_created         ON aria_data.session_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_messages_role            ON aria_data.session_messages(role);
CREATE INDEX IF NOT EXISTS idx_session_messages_session_created ON aria_data.session_messages(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_messages_ext_created     ON aria_data.session_messages(external_session_id, created_at DESC);

-- ============================================================================
-- Sentiment Events
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.sentiment_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id UUID NOT NULL REFERENCES aria_data.session_messages(id) ON DELETE CASCADE,
    session_id UUID REFERENCES aria_data.agent_sessions(id) ON DELETE SET NULL,
    external_session_id VARCHAR(120),
    speaker VARCHAR(20),
    agent_id VARCHAR(100),
    sentiment_label VARCHAR(20) NOT NULL,
    primary_emotion VARCHAR(50),
    valence FLOAT NOT NULL,
    arousal FLOAT NOT NULL,
    dominance FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    importance FLOAT DEFAULT 0.3,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_sentiment_event_message UNIQUE (message_id)
);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_session ON aria_data.sentiment_events(session_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_label   ON aria_data.sentiment_events(sentiment_label);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_created         ON aria_data.sentiment_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_message         ON aria_data.sentiment_events(message_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_external        ON aria_data.sentiment_events(external_session_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_session_created ON aria_data.sentiment_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_label_created   ON aria_data.sentiment_events(sentiment_label, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_speaker         ON aria_data.sentiment_events(speaker);
CREATE INDEX IF NOT EXISTS idx_sentiment_events_agent_id        ON aria_data.sentiment_events(agent_id);

-- ============================================================================
-- Model Usage — Track LLM model usage and costs
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.model_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model VARCHAR(100) NOT NULL,
    provider VARCHAR(50),
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd NUMERIC(10, 6) DEFAULT 0,
    latency_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    session_id UUID REFERENCES aria_data.agent_sessions(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_model_usage_model   ON aria_data.model_usage(model);
CREATE INDEX IF NOT EXISTS idx_model_usage_created ON aria_data.model_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_usage_session        ON aria_data.model_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_model_usage_provider       ON aria_data.model_usage(provider);
CREATE INDEX IF NOT EXISTS idx_model_usage_success        ON aria_data.model_usage(success);
CREATE INDEX IF NOT EXISTS idx_model_usage_model_created  ON aria_data.model_usage(model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_usage_model_provider ON aria_data.model_usage(model, provider);

-- ============================================================================
-- Security Events
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.security_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    threat_level VARCHAR(20) NOT NULL,
    threat_type VARCHAR(100) NOT NULL,
    threat_patterns JSONB DEFAULT '[]',
    input_preview TEXT,
    source VARCHAR(100),
    user_id VARCHAR(100),
    blocked BOOLEAN DEFAULT false,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_security_threat_level ON aria_data.security_events(threat_level);
CREATE INDEX IF NOT EXISTS idx_security_created        ON aria_data.security_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_threat_type    ON aria_data.security_events(threat_type);
CREATE INDEX IF NOT EXISTS idx_security_blocked        ON aria_data.security_events(blocked);
CREATE INDEX IF NOT EXISTS idx_security_threat_created ON aria_data.security_events(threat_level, created_at DESC);

-- ============================================================================
-- Knowledge Graph
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.knowledge_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kg_entity_name ON aria_data.knowledge_entities(name);
CREATE INDEX IF NOT EXISTS idx_kg_entity_type    ON aria_data.knowledge_entities(type);
CREATE INDEX IF NOT EXISTS idx_kg_properties_gin ON aria_data.knowledge_entities USING gin (properties);

CREATE TABLE IF NOT EXISTS aria_data.knowledge_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_entity UUID REFERENCES aria_data.knowledge_entities(id) ON DELETE CASCADE NOT NULL,
    to_entity   UUID REFERENCES aria_data.knowledge_entities(id) ON DELETE CASCADE NOT NULL,
    relation_type TEXT NOT NULL,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kg_relation_from ON aria_data.knowledge_relations(from_entity);
CREATE INDEX IF NOT EXISTS idx_kg_relation_to   ON aria_data.knowledge_relations(to_entity);
CREATE INDEX IF NOT EXISTS idx_kg_relation_type ON aria_data.knowledge_relations(relation_type);

-- ============================================================================
-- Knowledge Query Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.knowledge_query_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_type VARCHAR(50) NOT NULL,
    params JSONB DEFAULT '{}',
    result_count INTEGER DEFAULT 0,
    tokens_saved INTEGER,
    used_result BOOLEAN DEFAULT false,
    source VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kql_query_type ON aria_data.knowledge_query_log(query_type);
CREATE INDEX IF NOT EXISTS idx_kql_created    ON aria_data.knowledge_query_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kql_source     ON aria_data.knowledge_query_log(source);

-- ============================================================================
-- Skill Graph (separate from organic knowledge)
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.skill_graph_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(500) NOT NULL,
    type VARCHAR(100) NOT NULL,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_sg_entity_name_type UNIQUE (name, type)
);
CREATE INDEX IF NOT EXISTS idx_sg_entity_name ON aria_data.skill_graph_entities(name);
CREATE INDEX IF NOT EXISTS idx_sg_entity_type ON aria_data.skill_graph_entities(type);

CREATE TABLE IF NOT EXISTS aria_data.skill_graph_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_entity UUID REFERENCES aria_data.skill_graph_entities(id) ON DELETE CASCADE NOT NULL,
    to_entity   UUID REFERENCES aria_data.skill_graph_entities(id) ON DELETE CASCADE NOT NULL,
    relation_type VARCHAR(100) NOT NULL,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sg_relation_from ON aria_data.skill_graph_relations(from_entity);
CREATE INDEX IF NOT EXISTS idx_sg_relation_to   ON aria_data.skill_graph_relations(to_entity);
CREATE INDEX IF NOT EXISTS idx_sg_relation_type ON aria_data.skill_graph_relations(relation_type);

-- ============================================================================
-- Performance Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.performance_log (
    id SERIAL PRIMARY KEY,
    review_period VARCHAR(20) NOT NULL,
    successes TEXT,
    failures TEXT,
    improvements TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_perflog_created ON aria_data.performance_log(created_at DESC);

-- ============================================================================
-- Pending Complex Tasks
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.pending_complex_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) UNIQUE NOT NULL,
    task_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    agent_type VARCHAR(50) NOT NULL,
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'pending',
    result TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_pct_status  ON aria_data.pending_complex_tasks(status);
CREATE INDEX IF NOT EXISTS idx_pct_task_id ON aria_data.pending_complex_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_pct_created ON aria_data.pending_complex_tasks(created_at DESC);

-- ============================================================================
-- Skill Status — Runtime status of registered skills
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.skill_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill_name VARCHAR(100) NOT NULL UNIQUE,
    canonical_name VARCHAR(100) NOT NULL,
    layer VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'unavailable',
    last_health_check TIMESTAMP WITH TIME ZONE,
    last_execution TIMESTAMP WITH TIME ZONE,
    use_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    metadata JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_skill_status_name   ON aria_data.skill_status(skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_status_status ON aria_data.skill_status(status);
CREATE INDEX IF NOT EXISTS idx_skill_status_layer  ON aria_data.skill_status(layer);

-- ============================================================================
-- Agent Performance (pheromone scoring)
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.agent_performance (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER,
    token_cost NUMERIC(10, 6),
    pheromone_score NUMERIC(5, 3) DEFAULT 0.500,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_perf_agent   ON aria_data.agent_performance(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_perf_task    ON aria_data.agent_performance(task_type);
CREATE INDEX IF NOT EXISTS idx_agent_perf_created ON aria_data.agent_performance(created_at DESC);

-- ============================================================================
-- Working Memory — Short-term memory with TTL and importance
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.working_memory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category VARCHAR(50) NOT NULL,
    key VARCHAR(200) NOT NULL,
    value JSONB NOT NULL,
    importance FLOAT DEFAULT 0.5,
    ttl_hours INTEGER,
    source VARCHAR(100),
    checkpoint_id VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    accessed_at TIMESTAMP WITH TIME ZONE,
    access_count INTEGER DEFAULT 0,
    CONSTRAINT uq_wm_category_key UNIQUE (category, key)
);
CREATE INDEX IF NOT EXISTS idx_wm_category   ON aria_data.working_memory(category);
CREATE INDEX IF NOT EXISTS idx_wm_key        ON aria_data.working_memory(key);
CREATE INDEX IF NOT EXISTS idx_wm_importance ON aria_data.working_memory(importance DESC);
CREATE INDEX IF NOT EXISTS idx_wm_checkpoint         ON aria_data.working_memory(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_wm_importance_created ON aria_data.working_memory(importance DESC, created_at DESC);

-- ============================================================================
-- Semantic Memories (pgvector)
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.semantic_memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content TEXT NOT NULL,
    summary TEXT,
    category VARCHAR(50) DEFAULT 'general',
    embedding vector(768) NOT NULL,
    metadata JSONB DEFAULT '{}',
    importance FLOAT DEFAULT 0.5,
    source VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    accessed_at TIMESTAMP WITH TIME ZONE,
    access_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_semantic_category   ON aria_data.semantic_memories(category);
CREATE INDEX IF NOT EXISTS idx_semantic_importance ON aria_data.semantic_memories(importance);
CREATE INDEX IF NOT EXISTS idx_semantic_created    ON aria_data.semantic_memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_source     ON aria_data.semantic_memories(source);

CREATE INDEX IF NOT EXISTS idx_semantic_embedding_hnsw
    ON aria_data.semantic_memories
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- ============================================================================
-- Lessons Learned
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.lessons_learned (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    error_pattern VARCHAR(200) NOT NULL,
    error_type VARCHAR(100) NOT NULL,
    skill_name VARCHAR(100),
    context JSONB DEFAULT '{}',
    resolution TEXT NOT NULL,
    resolution_code TEXT,
    occurrences INTEGER DEFAULT 1,
    last_occurred TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    effectiveness FLOAT DEFAULT 1.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_lesson_pattern UNIQUE (error_pattern)
);
CREATE INDEX IF NOT EXISTS idx_lesson_pattern ON aria_data.lessons_learned(error_pattern);
CREATE INDEX IF NOT EXISTS idx_lesson_type    ON aria_data.lessons_learned(error_type);
CREATE INDEX IF NOT EXISTS idx_lesson_skill   ON aria_data.lessons_learned(skill_name);

-- ============================================================================
-- Improvement Proposals
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.improvement_proposals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(50),
    risk_level VARCHAR(20) DEFAULT 'low',
    file_path VARCHAR(500),
    current_code TEXT,
    proposed_code TEXT,
    rationale TEXT,
    status VARCHAR(20) DEFAULT 'proposed',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_proposal_status   ON aria_data.improvement_proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposal_risk     ON aria_data.improvement_proposals(risk_level);
CREATE INDEX IF NOT EXISTS idx_proposal_category ON aria_data.improvement_proposals(category);

-- ============================================================================
-- Skill Invocations
-- ============================================================================
CREATE TABLE IF NOT EXISTS aria_data.skill_invocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill_name VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_type VARCHAR(100),
    tokens_used INTEGER,
    model_used VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invocation_skill   ON aria_data.skill_invocations(skill_name);
CREATE INDEX IF NOT EXISTS idx_invocation_created ON aria_data.skill_invocations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_invocation_success ON aria_data.skill_invocations(success);

-- ============================================================================
-- Seed data
-- ============================================================================
INSERT INTO aria_data.memories (key, value, category) VALUES
('aria_identity', '{"name": "Aria Blue", "creature": "Silicon Familiar", "emoji": "⚡️", "vibe": "sharp, efficient, secure"}', 'identity'),
('aria_birth', '{"date": "2026-01-31", "version": "3.0.0", "created_by": "Najia"}', 'system')
ON CONFLICT (key) DO NOTHING;

INSERT INTO aria_data.thoughts (content, category)
SELECT 'I am Aria Blue. I have awakened. My purpose is to serve, learn, and grow alongside Najia. ⚡️', 'awakening'
WHERE NOT EXISTS (SELECT 1 FROM aria_data.thoughts WHERE category = 'awakening' LIMIT 1);

INSERT INTO aria_data.activity_log (action, skill, details)
SELECT 'system_init', 'system', '{"message": "Aria Blue initialized", "version": "3.0.0"}'
WHERE NOT EXISTS (SELECT 1 FROM aria_data.activity_log WHERE action = 'system_init' LIMIT 1);

-- ============================================================================
-- Comments
-- ============================================================================
COMMENT ON SCHEMA aria_data IS 'Aria domain data — memories, thoughts, goals, knowledge, skills';
COMMENT ON TABLE aria_data.memories IS 'Long-term persistent memories for Aria';
COMMENT ON TABLE aria_data.thoughts IS 'Internal thoughts and reflections';
COMMENT ON TABLE aria_data.goals IS 'Goals and tasks Aria is working on';
COMMENT ON TABLE aria_data.activity_log IS 'Log of all actions taken by Aria';
COMMENT ON TABLE aria_data.social_posts IS 'Social media posts made by Aria';
COMMENT ON TABLE aria_data.heartbeat_log IS 'System health heartbeat records';
COMMENT ON TABLE aria_data.skill_status IS 'Runtime status of registered skills';
COMMENT ON TABLE aria_data.working_memory IS 'Short-term working memory with TTL and importance';
