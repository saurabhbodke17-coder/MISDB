CREATE SCHEMA IF NOT EXISTS mis;
CREATE TABLE mis.accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('admin','operator','viewer')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE mis.sessions (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES mis.accounts(id),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);
CREATE INDEX ON mis.sessions(account_id);
CREATE TABLE mis.login_attempts (
    username text NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now(),
    success boolean NOT NULL
);
CREATE INDEX ON mis.login_attempts(username, attempted_at DESC);
CREATE TABLE mis.work_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind IN ('action','task','compliance','project','incident','intervention','correction')),
    title text NOT NULL CHECK (length(title) BETWEEN 3 AND 250),
    description text NOT NULL DEFAULT '',
    owner_id uuid NOT NULL REFERENCES mis.accounts(id),
    batch_id uuid REFERENCES public.batches(id),
    due_date date NOT NULL,
    severity text NOT NULL CHECK (severity IN ('Low','Medium','High','Critical')),
    status text NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','In progress','Blocked','Done – awaiting verification','Verified & closed','Reopened')),
    root_cause text NOT NULL DEFAULT '',
    evidence text NOT NULL DEFAULT '',
    source_module text NOT NULL DEFAULT 'actions',
    source_id text,
    version integer NOT NULL DEFAULT 1,
    created_by uuid NOT NULL REFERENCES mis.accounts(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz
);
CREATE INDEX ON mis.work_items(kind, due_date);
CREATE INDEX ON mis.work_items(owner_id, status);
CREATE INDEX ON mis.work_items(batch_id);
CREATE TABLE mis.audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES mis.accounts(id),
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    event text NOT NULL,
    before_data jsonb,
    after_data jsonb,
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON mis.audit_events(entity_type, entity_id, created_at);
CREATE TABLE mis.settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_by uuid REFERENCES mis.accounts(id),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO mis.settings(key,value) VALUES ('metrics', '{"attendance_target":85,"delivery_target":95,"completion_target":92,"late_tolerance":5,"risk_attendance":75,"pass_mark":40,"late_counts_present":true}');
CREATE TABLE mis.support_metadata (
    report_id uuid PRIMARY KEY REFERENCES public.support_reports(id),
    owner_id uuid REFERENCES mis.accounts(id),
    severity text NOT NULL DEFAULT 'Medium' CHECK (severity IN ('Low','Medium','High','Critical')),
    sla_due timestamptz,
    version integer NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now()
);
