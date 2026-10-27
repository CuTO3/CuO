CREATE TABLE IF NOT EXISTS __SCHEMA__.log (
 task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), triggered_at TIMESTAMPTZ NOT NULL,
 business_date DATE NOT NULL, request_type TEXT NOT NULL DEFAULT 'message',
 user_id TEXT, message_id TEXT, original_text TEXT, params JSONB NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed','needs_review')),
 business_status TEXT NOT NULL DEFAULT 'pending' CHECK(business_status IN ('pending','running','completed','failed')),
 step TEXT NOT NULL DEFAULT 'queued', result JSONB NOT NULL DEFAULT '{}', error JSONB, completed_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS log_queue_idx ON __SCHEMA__.log(status,created_at);
CREATE INDEX IF NOT EXISTS log_day_idx ON __SCHEMA__.log(request_type,business_date);
CREATE TABLE IF NOT EXISTS __SCHEMA__.messages (
 id BIGSERIAL PRIMARY KEY, message_id TEXT NOT NULL UNIQUE,
 sent_at TIMESTAMPTZ NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(), business_date DATE NOT NULL,
 user_id TEXT NOT NULL, nickname TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
 segments JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(segments)='array'),
 generated_by TEXT, processing JSONB NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS messages_day_idx ON __SCHEMA__.messages(business_date,sent_at,id);
CREATE TABLE IF NOT EXISTS __SCHEMA__.members (
 user_id TEXT PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '', display_name TEXT,
 slots JSONB NOT NULL DEFAULT '[null,null,null,null,null,null]' CHECK(jsonb_typeof(slots)='array' AND jsonb_array_length(slots)=6),
 sheet_name TEXT UNIQUE, fortune BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS __SCHEMA__.summaries (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), task_id UUID NOT NULL UNIQUE REFERENCES __SCHEMA__.log(task_id),
 business_date DATE NOT NULL, start_at TIMESTAMPTZ NOT NULL, end_at TIMESTAMPTZ NOT NULL CHECK(end_at>start_at),
 content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS summaries_day_idx ON __SCHEMA__.summaries(business_date,end_at,created_at);
CREATE TABLE IF NOT EXISTS __SCHEMA__.divinations (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), task_id UUID NOT NULL UNIQUE REFERENCES __SCHEMA__.log(task_id),
 user_id TEXT NOT NULL REFERENCES __SCHEMA__.members(user_id), business_date DATE NOT NULL,
 status TEXT NOT NULL DEFAULT 'generating' CHECK(status IN ('generating','settled','failed')),
 zhou_yi JSONB, tarot JSONB, dictum JSONB, keyword TEXT, advice TEXT,
 luck_delta INTEGER CHECK(luck_delta BETWEEN -10 AND 10), fortune_before BIGINT, fortune_after BIGINT,
 content TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), settled_at TIMESTAMPTZ,
 UNIQUE(user_id,business_date),
 CHECK(status<>'settled' OR (fortune_before IS NOT NULL AND fortune_after IS NOT NULL AND luck_delta IS NOT NULL
 AND fortune_after=fortune_before+luck_delta AND content IS NOT NULL AND zhou_yi IS NOT NULL
 AND tarot IS NOT NULL AND dictum IS NOT NULL AND settled_at IS NOT NULL)));
