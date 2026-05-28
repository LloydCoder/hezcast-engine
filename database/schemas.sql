-- ═══════════════════════════════════════════════════════
-- HezCast Engine — Database Schema v2.0
-- Tinlance Limited | Apache 2.0
-- PostgreSQL 16 + pgvector extension
-- ═══════════════════════════════════════════════════════

-- Enable pgvector for semantic clip embeddings
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ───────────────────────────────────────────
-- TENANTS (SaaS multi-tenant from Day 1)
-- ───────────────────────────────────────────
CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255) UNIQUE NOT NULL,
    api_key     VARCHAR(64) UNIQUE NOT NULL,
    plan        VARCHAR(20) DEFAULT 'free'
                CHECK (plan IN ('free', 'pro', 'agency')),
    credits     INTEGER DEFAULT 10 CHECK (credits >= 0),
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tenants_api_key ON tenants(api_key);
CREATE INDEX idx_tenants_email ON tenants(email);

-- ───────────────────────────────────────────
-- JOBS (core job tracking)
-- ───────────────────────────────────────────
CREATE TABLE jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID REFERENCES tenants(id) ON DELETE CASCADE,
    brand               VARCHAR(50) NOT NULL,
    topic               VARCHAR(1000) NOT NULL,
    tone                VARCHAR(50),
    status              VARCHAR(20) DEFAULT 'queued'
                        CHECK (status IN (
                            'queued', 'generating_hooks', 'awaiting_selection',
                            'processing', 'composing', 'qa_check',
                            'completed', 'failed', 'needs_review'
                        )),
    selected_hook_num   INTEGER,
    output_path         VARCHAR(1000),
    output_url          VARCHAR(1000),
    duration_sec        FLOAT,
    render_time_ms      INTEGER,
    qa_passed           BOOLEAN,
    qa_report           JSONB,
    llm_used            VARCHAR(20),
    error_message       TEXT,
    retry_count         INTEGER DEFAULT 0,
    celery_task_id      VARCHAR(255),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX idx_jobs_tenant_id ON jobs(tenant_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_brand ON jobs(brand);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);

-- ───────────────────────────────────────────
-- HOOK VARIANTS (A/B testing)
-- ───────────────────────────────────────────
CREATE TABLE hook_variants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID REFERENCES jobs(id) ON DELETE CASCADE,
    variant_num     INTEGER NOT NULL CHECK (variant_num >= 1),
    hook_text       TEXT NOT NULL,
    full_script     TEXT NOT NULL,
    selected        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(job_id, variant_num)
);

CREATE INDEX idx_hook_variants_job_id ON hook_variants(job_id);

-- ───────────────────────────────────────────
-- BRAND PERSONAS (runtime configurable)
-- ───────────────────────────────────────────
CREATE TABLE brand_personas (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand               VARCHAR(50) UNIQUE NOT NULL,
    persona_name        VARCHAR(100),
    persona_photo_path  VARCHAR(500),
    voice_model_path    VARCHAR(500),
    voice_speed         FLOAT DEFAULT 1.0,
    tone                VARCHAR(50),
    style               VARCHAR(50),
    audience            VARCHAR(100),
    subtitle_color      VARCHAR(7),
    subtitle_style      VARCHAR(50),
    hook_variants       INTEGER DEFAULT 3,
    video_duration_sec  INTEGER DEFAULT 25,
    cta_text            TEXT,
    brand_colors        JSONB,
    clip_emotion_tags   TEXT[],
    script_style_notes  TEXT,
    hook_patterns       TEXT[],
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ───────────────────────────────────────────
-- CLIP CACHE (Pexels + CLIP semantic index)
-- ───────────────────────────────────────────
CREATE TABLE clip_cache (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pexels_id           VARCHAR(50) UNIQUE,
    local_path          VARCHAR(1000),
    pexels_url          VARCHAR(1000),
    tags                TEXT[],
    emotion_tags        TEXT[],
    description         TEXT,
    duration_sec        FLOAT,
    width               INTEGER,
    height              INTEGER,
    -- CLIP embedding (512-dim for ViT-B/32)
    clip_embedding      VECTOR(512),
    brand_affinity      TEXT[],
    download_count      INTEGER DEFAULT 0,
    last_used_at        TIMESTAMPTZ,
    cached_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_clip_cache_pexels_id ON clip_cache(pexels_id);
CREATE INDEX idx_clip_cache_emotion_tags ON clip_cache USING GIN(emotion_tags);
-- Vector similarity index for semantic search
CREATE INDEX idx_clip_embedding ON clip_cache
    USING ivfflat (clip_embedding vector_cosine_ops)
    WITH (lists = 100);

-- ───────────────────────────────────────────
-- RENDER PIPELINE STAGES (observability)
-- ───────────────────────────────────────────
CREATE TABLE pipeline_stages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID REFERENCES jobs(id) ON DELETE CASCADE,
    stage_name      VARCHAR(50) NOT NULL,
    -- script_gen | hook_gen | voice | clip_select | avatar | compose | subtitle | qa
    status          VARCHAR(20) DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_ms     INTEGER,
    metadata        JSONB,
    error           TEXT
);

CREATE INDEX idx_pipeline_stages_job_id ON pipeline_stages(job_id);

-- ───────────────────────────────────────────
-- CREDIT TRANSACTIONS
-- ───────────────────────────────────────────
CREATE TABLE credit_transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    job_id          UUID REFERENCES jobs(id),
    amount          INTEGER NOT NULL,  -- negative = debit, positive = credit
    reason          VARCHAR(100),      -- 'video_render' | 'topup' | 'refund'
    balance_after   INTEGER NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_credit_transactions_tenant_id ON credit_transactions(tenant_id);

-- ───────────────────────────────────────────
-- QA REPORTS (structured)
-- ───────────────────────────────────────────
CREATE TABLE qa_reports (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                  UUID REFERENCES jobs(id) ON DELETE CASCADE UNIQUE,
    resolution_ok           BOOLEAN,
    duration_ok             BOOLEAN,
    audio_sync_ok           BOOLEAN,
    no_black_frames         BOOLEAN,
    subtitle_coverage       FLOAT,
    avatar_face_visible     BOOLEAN,
    file_size_ok            BOOLEAN,
    overall_pass            BOOLEAN,
    failure_reasons         TEXT[],
    actual_resolution       VARCHAR(20),
    actual_duration_sec     FLOAT,
    actual_file_size_bytes  BIGINT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ───────────────────────────────────────────
-- UPDATED_AT TRIGGERS
-- ───────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_brand_personas_updated_at
    BEFORE UPDATE ON brand_personas
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
