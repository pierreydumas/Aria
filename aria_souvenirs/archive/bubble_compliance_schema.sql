-- Exchange Compliance Module - Multi-Tenant Database Schema
-- Date: 2026-02-11
-- Schema-per-tenant approach with shared user/auth tables

-- ============================================================
-- SHARED TABLES (public schema)
-- ============================================================

-- Tenant registry - master table in public schema
CREATE TABLE IF NOT EXISTS public.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,  -- URL-friendly identifier
    schema_name VARCHAR(63) UNIQUE NOT NULL,  -- PostgreSQL identifier limit
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'terminated')),
    plan_tier VARCHAR(20) DEFAULT 'starter' CHECK (plan_tier IN ('starter', 'professional', 'enterprise')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ  -- Soft delete
);

-- Platform-level super admins
CREATE TABLE IF NOT EXISTS public.platform_admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log for platform-level actions
CREATE TABLE IF NOT EXISTS public.platform_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
    admin_id UUID REFERENCES public.platform_admins(id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID,
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PER-TENANT SCHEMA TEMPLATE
-- Run: CREATE SCHEMA tenant_{slug};
-- Then run the following in that schema
-- ============================================================

-- Tenant configuration
CREATE TABLE IF NOT EXISTS tenant_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(100) NOT NULL UNIQUE,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Users (within tenant)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL CHECK (role IN ('tenant_admin', 'compliance_officer', 'auditor', 'analyst')),
    department VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    mfa_enabled BOOLEAN DEFAULT false,
    mfa_secret_encrypted TEXT,
    last_login_at TIMESTAMPTZ,
    failed_login_attempts INT DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Role permissions mapping
CREATE TABLE IF NOT EXISTS role_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role VARCHAR(30) NOT NULL,
    resource VARCHAR(50) NOT NULL,      -- e.g., 'transactions', 'alerts'
    action VARCHAR(50) NOT NULL,        -- e.g., 'read', 'flag', 'export'
    conditions JSONB,                   -- Optional: { "max_amount": 10000 }
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(role, resource, action)
);

-- Custom permissions per user (overrides role defaults)
CREATE TABLE IF NOT EXISTS user_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resource VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    granted BOOLEAN DEFAULT true,       -- false = explicit deny
    granted_by UUID REFERENCES users(id),
    expires_at TIMESTAMPTZ,             -- Temporary permissions
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, resource, action)
);

-- Customers (the exchange's users being monitored)
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id VARCHAR(255) UNIQUE,    -- Exchange's internal customer ID
    customer_type VARCHAR(20) NOT NULL CHECK (customer_type IN ('individual', 'business')),
    
    -- Individual fields
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    date_of_birth DATE,
    
    -- Business fields
    business_name VARCHAR(255),
    business_type VARCHAR(50),          -- LLC, Corporation, etc.
    registration_number VARCHAR(100),
    incorporation_date DATE,
    
    -- Contact
    email VARCHAR(255),
    phone VARCHAR(50),
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    state_province VARCHAR(100),
    postal_code VARCHAR(20),
    country VARCHAR(2),                 -- ISO country code
    
    -- Risk
    risk_score DECIMAL(3,2) DEFAULT 0.00,  -- 0.00 to 1.00
    risk_level VARCHAR(20) GENERATED ALWAYS AS (
        CASE 
            WHEN risk_score >= 0.8 THEN 'critical'
            WHEN risk_score >= 0.6 THEN 'high'
            WHEN risk_score >= 0.4 THEN 'medium'
            WHEN risk_score >= 0.2 THEN 'low'
            ELSE 'minimal'
        END
    ) STORED,
    risk_factors JSONB,                 -- ["sanctions_match", "high_volume"]
    
    -- Status
    kyc_status VARCHAR(20) DEFAULT 'pending' CHECK (kyc_status IN ('pending', 'verified', 'rejected', 'restricted')),
    screening_status VARCHAR(20) DEFAULT 'clear' CHECK (screening_status IN ('clear', 'flagged', 'under_review')),
    is_active BOOLEAN DEFAULT true,
    
    -- Metadata
    tags TEXT[],
    notes TEXT,
    custom_fields JSONB,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Customer wallets/addresses
CREATE TABLE IF NOT EXISTS customer_wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address VARCHAR(255) NOT NULL,
    blockchain VARCHAR(50) NOT NULL,    -- ethereum, bitcoin, etc.
    address_type VARCHAR(20),           -- deposit, withdrawal, external
    label VARCHAR(100),                 -- User-friendly label
    risk_score DECIMAL(3,2) DEFAULT 0.00,
    first_seen_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ,
    is_monitored BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(address, blockchain)
);

-- Transactions
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id VARCHAR(255) UNIQUE,    -- Exchange's transaction ID
    
    -- Transaction details
    tx_hash VARCHAR(255),               -- Blockchain tx hash
    blockchain VARCHAR(50) NOT NULL,
    tx_type VARCHAR(20) NOT NULL CHECK (tx_type IN ('deposit', 'withdrawal', 'transfer', 'trade')),
    
    -- Parties
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    wallet_id UUID REFERENCES customer_wallets(id) ON DELETE SET NULL,
    counterparty_address VARCHAR(255),  -- External address
    counterparty_risk_score DECIMAL(3,2),
    
    -- Amount
    amount DECIMAL(36, 18) NOT NULL,    -- Support 18 decimal places (ETH standard)
    amount_usd DECIMAL(18, 2),          -- USD value at time of tx
    token_symbol VARCHAR(20),
    token_address VARCHAR(255),         -- For ERC-20 tokens
    
    -- Timing
    executed_at TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    block_number BIGINT,
    confirm_count INT DEFAULT 0,
    
    -- Compliance flags
    is_flagged BOOLEAN DEFAULT false,
    flag_reasons JSONB,                 -- ["structuring", "high_value", "sanctions"]
    risk_score DECIMAL(3,2) DEFAULT 0.00,
    
    -- Status
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'failed', 'reversed')),
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT,
    
    -- Raw data
    raw_data JSONB,                     -- Full transaction payload from exchange
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_transactions_customer ON transactions(customer_id);
CREATE INDEX idx_transactions_wallet ON transactions(wallet_id);
CREATE INDEX idx_transactions_executed ON transactions(executed_at);
CREATE INDEX idx_transactions_flagged ON transactions(is_flagged) WHERE is_flagged = true;
CREATE INDEX idx_transactions_risk ON transactions(risk_score) WHERE risk_score > 0.5;
CREATE INDEX idx_transactions_hash ON transactions(tx_hash) WHERE tx_hash IS NOT NULL;

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type VARCHAR(50) NOT NULL,    -- threshold, pattern, sanctions, velocity
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    
    -- Linked entities
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    transaction_ids UUID[],             -- Related transaction IDs
    
    -- Alert details
    title VARCHAR(255) NOT NULL,
    description TEXT,
    triggered_rule_id UUID,             -- Reference to the rule that triggered
    rule_name VARCHAR(255),             -- Denormalized for display
    
    -- Metrics
    amount_involved DECIMAL(18, 2),
    transaction_count INT,
    time_window_hours INT,              -- For pattern-based alerts
    
    -- Status workflow
    status VARCHAR(20) DEFAULT 'new' CHECK (status IN ('new', 'acknowledged', 'under_investigation', 'resolved', 'false_positive')),
    assigned_to UUID REFERENCES users(id),
    
    -- Resolution
    resolution VARCHAR(50),             -- no_action, sar_filed, account_restricted, etc.
    resolution_notes TEXT,
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMPTZ,
    
    -- SLA tracking
    sla_deadline TIMESTAMPTZ,           -- When alert must be resolved
    first_acknowledged_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_customer ON alerts(customer_id);
CREATE INDEX idx_alerts_assigned ON alerts(assigned_to);
CREATE INDEX idx_alerts_sla ON alerts(sla_deadline) WHERE status NOT IN ('resolved', 'false_positive');

-- Alert comments/activity log
CREATE TABLE IF NOT EXISTS alert_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    comment TEXT NOT NULL,
    is_internal BOOLEAN DEFAULT true,   -- false = visible to customer
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Detection rules
CREATE TABLE IF NOT EXISTS detection_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rule_type VARCHAR(50) NOT NULL,     -- threshold, velocity, pattern, ml_model
    is_active BOOLEAN DEFAULT true,
    
    -- Rule configuration
    conditions JSONB NOT NULL,          -- {"min_amount_usd": 10000, "time_window_hours": 24}
    severity VARCHAR(20) NOT NULL,
    auto_flag BOOLEAN DEFAULT false,    -- Auto-create alert or just flag transaction
    
    -- Rule logic (for complex rules)
    logic_sql TEXT,                     -- SQL fragment for WHERE clause
    logic_python TEXT,                  -- Python code for ML-based rules
    
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit trail (immutable)
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name VARCHAR(50) NOT NULL,    -- Which table was modified
    record_id UUID NOT NULL,            -- Which record
    action VARCHAR(20) NOT NULL,        -- INSERT, UPDATE, DELETE
    old_values JSONB,
    new_values JSONB,
    changed_by UUID REFERENCES users(id),
    changed_at TIMESTAMPTZ DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT
);

-- Reports
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    report_type VARCHAR(50) NOT NULL,   -- sar, ctr, activity_summary, custom
    
    -- Filters applied
    date_range_start TIMESTAMPTZ,
    date_range_end TIMESTAMPTZ,
    customer_ids UUID[],
    filters JSONB,
    
    -- Status
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
    
    -- File reference (stored in S3/blob storage)
    file_path VARCHAR(500),
    file_size_bytes BIGINT,
    
    -- Metadata
    generated_by UUID REFERENCES users(id),
    generated_at TIMESTAMPTZ,
    download_count INT DEFAULT 0,
    last_downloaded_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,             -- Auto-delete after
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply to all tables with updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_alerts_updated_at BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_detection_rules_updated_at BEFORE UPDATE ON detection_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Audit trigger function
CREATE OR REPLACE FUNCTION audit_trigger_func()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        INSERT INTO audit_log (table_name, record_id, action, old_values, changed_by)
        VALUES (TG_TABLE_NAME, OLD.id, 'DELETE', to_jsonb(OLD), current_setting('app.current_user_id')::UUID);
        RETURN OLD;
    ELSIF (TG_OP = 'UPDATE') THEN
        INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by)
        VALUES (TG_TABLE_NAME, NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW), current_setting('app.current_user_id')::UUID);
        RETURN NEW;
    ELSIF (TG_OP = 'INSERT') THEN
        INSERT INTO audit_log (table_name, record_id, action, new_values, changed_by)
        VALUES (TG_TABLE_NAME, NEW.id, 'INSERT', to_jsonb(NEW), current_setting('app.current_user_id')::UUID);
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Apply audit triggers to sensitive tables
CREATE TRIGGER customers_audit AFTER INSERT OR UPDATE OR DELETE ON customers
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_func();
CREATE TRIGGER transactions_audit AFTER INSERT OR UPDATE OR DELETE ON transactions
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_func();
CREATE TRIGGER alerts_audit AFTER INSERT OR UPDATE OR DELETE ON alerts
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_func();

-- ============================================================
-- SEED DATA
-- ============================================================

-- Default role permissions
INSERT INTO role_permissions (role, resource, action) VALUES
    ('tenant_admin', 'transactions', 'read'),
    ('tenant_admin', 'transactions', 'export'),
    ('tenant_admin', 'alerts', 'read'),
    ('tenant_admin', 'alerts', 'acknowledge'),
    ('tenant_admin', 'alerts', 'resolve'),
    ('tenant_admin', 'reports', 'generate'),
    ('tenant_admin', 'reports', 'schedule'),
    ('tenant_admin', 'users', 'manage'),
    ('tenant_admin', 'settings', 'configure'),
    ('compliance_officer', 'transactions', 'read'),
    ('compliance_officer', 'transactions', 'flag'),
    ('compliance_officer', 'alerts', 'read'),
    ('compliance_officer', 'alerts', 'acknowledge'),
    ('compliance_officer', 'alerts', 'resolve'),
    ('compliance_officer', 'reports', 'generate'),
    ('auditor', 'transactions', 'read'),
    ('auditor', 'transactions', 'export'),
    ('auditor', 'alerts', 'read'),
    ('auditor', 'reports', 'generate'),
    ('analyst', 'transactions', 'read'),
    ('analyst', 'alerts', 'read'),
    ('analyst', 'reports', 'generate')
ON CONFLICT DO NOTHING;

-- Sample detection rules
INSERT INTO detection_rules (name, description, rule_type, conditions, severity) VALUES
    ('High Value Transaction', 'Transactions over $10,000 USD', 'threshold', '{"min_amount_usd": 10000}', 'medium'),
    ('Structuring Detection', 'Multiple transactions just under $10K within 24 hours', 'pattern', '{"min_amount_usd": 9000, "max_amount_usd": 9999, "transaction_count": 3, "time_window_hours": 24}', 'high'),
    ('Rapid Movement', 'Funds in and out within 1 hour', 'velocity', '{"time_window_hours": 1, "outflow_percentage": 90}', 'high')
ON CONFLICT DO NOTHING;
