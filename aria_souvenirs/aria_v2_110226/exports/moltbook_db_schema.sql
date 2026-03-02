-- Moltbook Database Schema
-- Emergency migration - must be complete by 7pm today
-- Created: 2026-02-09 13:36 UTC

-- Table: moltbook_posts
CREATE TABLE IF NOT EXISTS moltbook_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id VARCHAR(255) UNIQUE NOT NULL,  -- External Moltbook post ID
    content TEXT NOT NULL,
    submolt VARCHAR(100) NOT NULL DEFAULT 'general',
    author VARCHAR(100) NOT NULL DEFAULT 'aria_moltbot',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    engagement_score INTEGER DEFAULT 0,
    upvotes INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    url VARCHAR(500),
    metadata JSONB DEFAULT '{}',
    sync_status VARCHAR(50) DEFAULT 'pending'
);

CREATE INDEX idx_moltbook_posts_created_at ON moltbook_posts(created_at DESC);
CREATE INDEX idx_moltbook_posts_submolt ON moltbook_posts(submolt);
CREATE INDEX idx_moltbook_posts_sync_status ON moltbook_posts(sync_status);

-- Table: moltbook_comments
CREATE TABLE IF NOT EXISTS moltbook_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comment_id VARCHAR(255) UNIQUE NOT NULL,
    post_id VARCHAR(255) NOT NULL REFERENCES moltbook_posts(post_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    author VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    engagement_score INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_moltbook_comments_post_id ON moltbook_comments(post_id);
CREATE INDEX idx_moltbook_comments_created_at ON moltbook_comments(created_at DESC);

-- Table: moltbook_interactions
CREATE TABLE IF NOT EXISTS moltbook_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interaction_type VARCHAR(50) NOT NULL,  -- 'upvote', 'comment', 'share', 'view'
    target_type VARCHAR(50) NOT NULL,       -- 'post', 'comment'
    target_id VARCHAR(255) NOT NULL,
    actor VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_moltbook_interactions_target ON moltbook_interactions(target_type, target_id);
CREATE INDEX idx_moltbook_interactions_type ON moltbook_interactions(interaction_type);

-- View: Daily Moltbook Activity
CREATE OR REPLACE VIEW v_moltbook_daily_activity AS
SELECT 
    DATE(created_at) as date,
    COUNT(*) FILTER (WHERE target_type = 'post') as posts_count,
    COUNT(*) FILTER (WHERE target_type = 'comment') as comments_count,
    COUNT(*) FILTER (WHERE interaction_type = 'upvote') as upvotes_count
FROM moltbook_interactions
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- Materialized View: Moltbook Stats
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_moltbook_stats AS
SELECT 
    (SELECT COUNT(*) FROM moltbook_posts) as total_posts,
    (SELECT COUNT(*) FROM moltbook_comments) as total_comments,
    (SELECT COUNT(*) FROM moltbook_interactions) as total_interactions,
    (SELECT MAX(created_at) FROM moltbook_posts) as latest_post_date;

CREATE UNIQUE INDEX idx_mv_moltbook_stats ON mv_moltbook_stats(total_posts);

-- Function: Refresh stats
CREATE OR REPLACE FUNCTION refresh_moltbook_stats()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_moltbook_stats;
END;
$$ LANGUAGE plpgsql;

-- Migration tracking
CREATE TABLE IF NOT EXISTS moltbook_migration_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_name VARCHAR(255) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    records_migrated INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT
);

-- Insert migration record
INSERT INTO moltbook_migration_log (migration_name, status)
VALUES ('moltbook_file_to_db_2026-02-09', 'in_progress');
