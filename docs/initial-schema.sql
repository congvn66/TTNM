-- PostgreSQL 16+ baseline for design review and prototype.
-- Convert to versioned migrations before production use.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    normalized_email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (id, normalized_email)
);

CREATE TABLE projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (id, owner_id)
);

CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (id, owner_id)
);

CREATE TABLE project_documents (
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, document_id),
    FOREIGN KEY (project_id, owner_id) REFERENCES projects(id, owner_id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, owner_id) REFERENCES documents(id, owner_id) ON DELETE CASCADE
);

CREATE TABLE document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    version_no integer NOT NULL CHECK (version_no > 0),
    file_name text NOT NULL,
    storage_key text NOT NULL UNIQUE,
    file_hash text NOT NULL,
    content_type text NOT NULL DEFAULT 'application/pdf',
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    page_count integer CHECK (page_count > 0),
    status text NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'processing', 'ready', 'failed', 'deleted')),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no),
    UNIQUE (id, document_id),
    CHECK (status NOT IN ('ready', 'failed') OR page_count IS NOT NULL)
);

CREATE TABLE extraction_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    run_no integer NOT NULL CHECK (run_no > 0),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    extractor_name text NOT NULL,
    extractor_version text,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, run_no),
    UNIQUE (id, document_version_id),
    CHECK (
        (status IN ('completed', 'failed') AND completed_at IS NOT NULL)
        OR status IN ('queued', 'running')
    )
);

CREATE TABLE source_regions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id uuid NOT NULL REFERENCES extraction_runs(id) ON DELETE RESTRICT,
    region_key text,
    page_number integer NOT NULL CHECK (page_number > 0),
    bbox jsonb,
    region_type text NOT NULL CHECK (region_type IN ('paragraph', 'table', 'table_cell', 'chart', 'chart_element', 'image', 'other')),
    extracted_text text,
    meta jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, extraction_run_id),
    UNIQUE (extraction_run_id, region_key),
    CHECK (bbox IS NULL OR jsonb_typeof(bbox) = 'array')
);

CREATE TABLE extracted_evidences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id uuid NOT NULL,
    source_region_id uuid NOT NULL,
    value_kind text NOT NULL CHECK (value_kind IN ('number', 'text')),
    raw_value numeric,
    raw_text text,
    semantic jsonb NOT NULL,
    data_status text NOT NULL CHECK (data_status IN ('valid', 'missing', 'error')),
    extraction_method text NOT NULL CHECK (extraction_method IN ('direct_label', 'axis_estimation', 'text', 'table', 'ocr', 'none')),
    confidence numeric CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (extraction_run_id) REFERENCES extraction_runs(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_region_id, extraction_run_id)
        REFERENCES source_regions(id, extraction_run_id) ON DELETE RESTRICT,
    UNIQUE (id, extraction_run_id),
    CHECK (
        (data_status = 'valid' AND value_kind = 'number' AND raw_value IS NOT NULL AND raw_text IS NULL)
        OR (data_status = 'valid' AND value_kind = 'text' AND raw_text IS NOT NULL AND raw_value IS NULL)
        OR (data_status IN ('missing', 'error') AND raw_value IS NULL AND raw_text IS NULL)
    )
);

CREATE TABLE chats (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id uuid,
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    data_revision bigint NOT NULL DEFAULT 0 CHECK (data_revision >= 0),
    next_sequence_no bigint NOT NULL DEFAULT 1 CHECK (next_sequence_no > 0),
    archived_at timestamptz,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, owner_id),
    FOREIGN KEY (project_id, owner_id) REFERENCES projects(id, owner_id) ON DELETE RESTRICT
);

CREATE TABLE chat_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE RESTRICT,
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    extraction_run_id uuid NOT NULL,
    source_status text NOT NULL DEFAULT 'active' CHECK (source_status IN ('active', 'inactive')),
    added_at timestamptz NOT NULL DEFAULT now(),
    deactivated_at timestamptz,
    FOREIGN KEY (extraction_run_id, document_version_id)
        REFERENCES extraction_runs(id, document_version_id) ON DELETE RESTRICT,
    UNIQUE (id, chat_id),
    UNIQUE (chat_id, extraction_run_id),
    CHECK (
        (source_status = 'active' AND deactivated_at IS NULL)
        OR (source_status = 'inactive' AND deactivated_at IS NOT NULL)
    )
);

CREATE TABLE chat_evidences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id uuid NOT NULL,
    chat_source_id uuid NOT NULL,
    extracted_evidence_id uuid NOT NULL,
    extraction_run_id uuid NOT NULL,
    current_revision_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_source_id, chat_id) REFERENCES chat_sources(id, chat_id) ON DELETE RESTRICT,
    FOREIGN KEY (extracted_evidence_id, extraction_run_id)
        REFERENCES extracted_evidences(id, extraction_run_id) ON DELETE RESTRICT,
    UNIQUE (id, chat_id),
    UNIQUE (chat_id, chat_source_id, extracted_evidence_id)
);

CREATE TABLE evidence_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id uuid NOT NULL,
    chat_evidence_id uuid NOT NULL,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    value_kind text NOT NULL CHECK (value_kind IN ('number', 'text')),
    numeric_value numeric,
    text_value text,
    semantic jsonb NOT NULL,
    data_status text NOT NULL CHECK (data_status IN ('valid', 'missing', 'error')),
    verification_status text NOT NULL CHECK (verification_status IN ('unverified', 'verified', 'edited')),
    action text NOT NULL CHECK (action IN ('initialize', 'verify', 'edit', 'mark_error', 'restore')),
    reason text,
    created_by uuid REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_evidence_id, chat_id) REFERENCES chat_evidences(id, chat_id) ON DELETE RESTRICT,
    UNIQUE (chat_evidence_id, revision_no),
    UNIQUE (id, chat_id),
    CHECK (
        (data_status = 'valid' AND value_kind = 'number' AND numeric_value IS NOT NULL AND text_value IS NULL)
        OR (data_status = 'valid' AND value_kind = 'text' AND text_value IS NOT NULL AND numeric_value IS NULL)
        OR (data_status IN ('missing', 'error') AND numeric_value IS NULL AND text_value IS NULL)
    ),
    CHECK (action NOT IN ('edit', 'mark_error', 'restore') OR length(btrim(COALESCE(reason, ''))) > 0)
);

ALTER TABLE chat_evidences
    ADD CONSTRAINT chat_evidences_current_revision_fk
    FOREIGN KEY (current_revision_id, chat_id) REFERENCES evidence_revisions(id, chat_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE RESTRICT,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    reply_to_message_id uuid,
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    status text NOT NULL CHECK (status IN ('accepted', 'processing', 'completed', 'failed')),
    needs_update boolean NOT NULL DEFAULT false,
    current_answer_revision_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (chat_id, sequence_no),
    UNIQUE (id, chat_id),
    FOREIGN KEY (reply_to_message_id, chat_id) REFERENCES messages(id, chat_id) ON DELETE RESTRICT
);

CREATE TABLE answer_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id uuid NOT NULL,
    message_id uuid NOT NULL,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    answer_status text NOT NULL CHECK (answer_status IN ('answered', 'needs_clarification', 'insufficient_data', 'source_conflict', 'processing_error')),
    question_context jsonb NOT NULL,
    operation jsonb,
    result jsonb,
    answer_text text NOT NULL,
    assessment jsonb NOT NULL,
    input_data_revision bigint NOT NULL CHECK (input_data_revision >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (message_id, chat_id) REFERENCES messages(id, chat_id) ON DELETE RESTRICT,
    UNIQUE (message_id, revision_no),
    UNIQUE (id, chat_id)
);

ALTER TABLE messages
    ADD CONSTRAINT messages_current_answer_revision_fk
    FOREIGN KEY (current_answer_revision_id, chat_id) REFERENCES answer_revisions(id, chat_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE answer_inputs (
    answer_revision_id uuid NOT NULL,
    evidence_revision_id uuid NOT NULL,
    chat_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('operand', 'comparison_group', 'context_text')),
    param_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (answer_revision_id, evidence_revision_id, param_key),
    FOREIGN KEY (answer_revision_id, chat_id) REFERENCES answer_revisions(id, chat_id) ON DELETE RESTRICT,
    FOREIGN KEY (evidence_revision_id, chat_id) REFERENCES evidence_revisions(id, chat_id) ON DELETE RESTRICT
);

CREATE TABLE answer_scopes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    answer_revision_id uuid NOT NULL,
    chat_source_id uuid NOT NULL,
    chat_id uuid NOT NULL,
    filter jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (answer_revision_id, chat_id) REFERENCES answer_revisions(id, chat_id) ON DELETE RESTRICT,
    FOREIGN KEY (chat_source_id, chat_id) REFERENCES chat_sources(id, chat_id) ON DELETE RESTRICT,
    UNIQUE (answer_revision_id, chat_source_id, filter)
);

CREATE TABLE message_pins (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL,
    chat_id uuid NOT NULL,
    message_id uuid NOT NULL,
    answer_revision_id uuid,
    pinned_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id, owner_id) REFERENCES chats(id, owner_id) ON DELETE CASCADE,
    FOREIGN KEY (message_id, chat_id) REFERENCES messages(id, chat_id) ON DELETE CASCADE,
    FOREIGN KEY (answer_revision_id, chat_id) REFERENCES answer_revisions(id, chat_id) ON DELETE RESTRICT
);

CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    last_seen_at timestamptz,
    CHECK (expires_at > created_at)
);

CREATE TABLE account_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    purpose text NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CHECK (expires_at > created_at)
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    chat_id uuid REFERENCES chats(id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('extract_document', 'answer_question', 'recalculate_answer', 'purge_resource')),
    dedup_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'superseded')),
    input_data_revision bigint CHECK (input_data_revision IS NULL OR input_data_revision >= 0),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    error_code text,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_token uuid,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    FOREIGN KEY (chat_id, owner_id) REFERENCES chats(id, owner_id) ON DELETE RESTRICT,
    CHECK (
        (status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status <> 'running'
    ),
    CHECK (
        (status IN ('succeeded', 'failed', 'cancelled', 'superseded') AND finished_at IS NOT NULL)
        OR status IN ('queued', 'running')
    ),
    CHECK (chat_id IS NULL OR owner_id IS NOT NULL)
);

CREATE TABLE job_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_no bigint NOT NULL CHECK (event_no > 0),
    event_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, event_no)
);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id uuid,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE request_keys (
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    route text NOT NULL,
    key text NOT NULL,
    request_hash text NOT NULL,
    response_status integer,
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (owner_id, route, key),
    CHECK (expires_at > created_at)
);

CREATE INDEX chats_owner_updated_idx ON chats (owner_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX document_versions_document_idx ON document_versions (document_id, version_no DESC);
CREATE INDEX extraction_runs_version_idx ON extraction_runs (document_version_id, created_at DESC);
CREATE INDEX source_regions_run_page_idx ON source_regions (extraction_run_id, page_number);
CREATE INDEX extracted_evidences_run_idx ON extracted_evidences (extraction_run_id);
CREATE INDEX chat_sources_chat_status_idx ON chat_sources (chat_id, source_status);
CREATE INDEX messages_chat_sequence_idx ON messages (chat_id, sequence_no);
CREATE INDEX chat_evidences_source_idx ON chat_evidences (chat_source_id, extracted_evidence_id);
CREATE INDEX evidence_revisions_history_idx ON evidence_revisions (chat_evidence_id, revision_no DESC);
CREATE INDEX answer_revisions_history_idx ON answer_revisions (message_id, revision_no DESC);
CREATE INDEX answer_inputs_evidence_idx ON answer_inputs (evidence_revision_id);
CREATE INDEX answer_scopes_source_idx ON answer_scopes (chat_source_id);
CREATE INDEX jobs_claim_idx ON jobs (status, available_at, created_at)
    WHERE status IN ('queued', 'running');
CREATE INDEX job_events_stream_idx ON job_events (job_id, event_no);
CREATE INDEX audit_events_target_idx ON audit_events (target_type, target_id, created_at DESC);
CREATE UNIQUE INDEX message_pins_message_only_uk
    ON message_pins (owner_id, chat_id, message_id) WHERE answer_revision_id IS NULL;
CREATE UNIQUE INDEX message_pins_answer_uk
    ON message_pins (owner_id, chat_id, message_id, answer_revision_id) WHERE answer_revision_id IS NOT NULL;

CREATE OR REPLACE FUNCTION app_valid_bbox(value jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    x0 numeric;
    y0 numeric;
    x1 numeric;
    y1 numeric;
BEGIN
    IF value IS NULL THEN
        RETURN true;
    END IF;
    IF jsonb_typeof(value) <> 'array' OR jsonb_array_length(value) <> 4 THEN
        RETURN false;
    END IF;
    IF jsonb_typeof(value->0) <> 'number'
       OR jsonb_typeof(value->1) <> 'number'
       OR jsonb_typeof(value->2) <> 'number'
       OR jsonb_typeof(value->3) <> 'number' THEN
        RETURN false;
    END IF;
    x0 := (value->>0)::numeric;
    y0 := (value->>1)::numeric;
    x1 := (value->>2)::numeric;
    y1 := (value->>3)::numeric;
    RETURN x0 >= 0 AND y0 >= 0 AND x0 < x1 AND y0 < y1 AND x1 <= 1 AND y1 <= 1;
EXCEPTION WHEN OTHERS THEN
    RETURN false;
END;
$$;

ALTER TABLE source_regions
    ADD CONSTRAINT source_regions_bbox_shape_ck CHECK (app_valid_bbox(bbox));

CREATE OR REPLACE FUNCTION app_check_chat_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    run_status text;
    run_version uuid;
    chat_owner uuid;
    document_owner uuid;
BEGIN
    SELECT status, document_version_id
      INTO run_status, run_version
      FROM extraction_runs
     WHERE id = NEW.extraction_run_id;

    IF run_version IS DISTINCT FROM NEW.document_version_id THEN
        RAISE EXCEPTION 'chat_source_run_version_mismatch';
    END IF;
    IF NEW.source_status = 'active' AND run_status IS DISTINCT FROM 'completed' THEN
        RAISE EXCEPTION 'chat_source_run_not_completed';
    END IF;

    SELECT c.owner_id, d.owner_id
      INTO chat_owner, document_owner
      FROM chats c
      JOIN document_versions dv ON dv.id = NEW.document_version_id
      JOIN documents d ON d.id = dv.document_id
     WHERE c.id = NEW.chat_id;
    IF chat_owner IS NULL OR chat_owner IS DISTINCT FROM document_owner THEN
        RAISE EXCEPTION 'chat_source_cross_owner';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER chat_sources_integrity_trg
BEFORE INSERT OR UPDATE OF chat_id, document_version_id, extraction_run_id, source_status
ON chat_sources
FOR EACH ROW EXECUTE FUNCTION app_check_chat_source();

CREATE OR REPLACE FUNCTION app_check_chat_evidence_origin()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    source_run uuid;
    origin_run uuid;
BEGIN
    SELECT extraction_run_id INTO source_run
      FROM chat_sources
     WHERE id = NEW.chat_source_id AND chat_id = NEW.chat_id;
    SELECT extraction_run_id INTO origin_run
      FROM extracted_evidences
     WHERE id = NEW.extracted_evidence_id;
    IF source_run IS NULL OR origin_run IS NULL
       OR source_run IS DISTINCT FROM origin_run
       OR NEW.extraction_run_id IS DISTINCT FROM origin_run THEN
        RAISE EXCEPTION 'chat_evidence_origin_mismatch';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER chat_evidences_origin_trg
BEFORE INSERT OR UPDATE OF chat_id, chat_source_id, extracted_evidence_id, extraction_run_id
ON chat_evidences
FOR EACH ROW EXECUTE FUNCTION app_check_chat_evidence_origin();

CREATE OR REPLACE FUNCTION app_check_current_evidence_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.current_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM evidence_revisions er
         WHERE er.id = NEW.current_revision_id
           AND er.chat_evidence_id = NEW.id
           AND er.chat_id = NEW.chat_id
    ) THEN
        RAISE EXCEPTION 'current_evidence_revision_wrong_parent';
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER chat_evidences_current_revision_parent_trg
AFTER INSERT OR UPDATE
ON chat_evidences
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION app_check_current_evidence_revision();

CREATE OR REPLACE FUNCTION app_check_answer_revision_parent()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM messages m
         WHERE m.id = NEW.message_id
           AND m.chat_id = NEW.chat_id
           AND m.role = 'assistant'
    ) THEN
        RAISE EXCEPTION 'answer_revision_requires_assistant_message';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER answer_revisions_parent_trg
BEFORE INSERT OR UPDATE OF message_id, chat_id
ON answer_revisions
FOR EACH ROW EXECUTE FUNCTION app_check_answer_revision_parent();

CREATE OR REPLACE FUNCTION app_check_current_answer_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.current_answer_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM answer_revisions ar
         WHERE ar.id = NEW.current_answer_revision_id
           AND ar.message_id = NEW.id
           AND ar.chat_id = NEW.chat_id
    ) THEN
        RAISE EXCEPTION 'current_answer_revision_wrong_parent';
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER messages_current_answer_parent_trg
AFTER INSERT OR UPDATE
ON messages
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION app_check_current_answer_revision();

CREATE OR REPLACE FUNCTION app_guard_extraction_payload()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    run_id uuid;
    run_status text;
BEGIN
    run_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.extraction_run_id ELSE NEW.extraction_run_id END;
    SELECT status INTO run_status FROM extraction_runs WHERE id = run_id;
    IF run_status = 'completed' THEN
        RAISE EXCEPTION 'completed_extraction_is_immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER source_regions_immutable_after_complete_trg
BEFORE INSERT OR UPDATE OR DELETE ON source_regions
FOR EACH ROW EXECUTE FUNCTION app_guard_extraction_payload();

CREATE TRIGGER extracted_evidences_immutable_after_complete_trg
BEFORE INSERT OR UPDATE OR DELETE ON extracted_evidences
FOR EACH ROW EXECUTE FUNCTION app_guard_extraction_payload();

CREATE OR REPLACE FUNCTION app_deny_revision_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'revision_rows_are_immutable';
END;
$$;

CREATE TRIGGER evidence_revisions_immutable_trg
BEFORE UPDATE OR DELETE ON evidence_revisions
FOR EACH ROW EXECUTE FUNCTION app_deny_revision_mutation();

CREATE TRIGGER answer_revisions_immutable_trg
BEFORE UPDATE OR DELETE ON answer_revisions
FOR EACH ROW EXECUTE FUNCTION app_deny_revision_mutation();

CREATE TRIGGER answer_inputs_immutable_trg
BEFORE UPDATE OR DELETE ON answer_inputs
FOR EACH ROW EXECUTE FUNCTION app_deny_revision_mutation();

CREATE TRIGGER answer_scopes_immutable_trg
BEFORE UPDATE OR DELETE ON answer_scopes
FOR EACH ROW EXECUTE FUNCTION app_deny_revision_mutation();
