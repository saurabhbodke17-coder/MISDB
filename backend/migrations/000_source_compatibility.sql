-- Compatibility structures absent from the production backup. No rows are fabricated.
-- Must precede 001_mis.sql on a fresh database.

DO $$ BEGIN
CREATE TYPE public.support_report_category AS ENUM (
    'bug',
    'feedback',
    'other'
);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
CREATE TYPE public.support_report_status AS ENUM (
    'open',
    'acknowledged',
    'resolved'
);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS public.support_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    category public.support_report_category DEFAULT 'bug'::public.support_report_category NOT NULL,
    description text NOT NULL,
    screenshot_url text,
    screenshot_blank boolean DEFAULT false NOT NULL,
    route text,
    app_version text,
    build_number text,
    platform text,
    os_version text,
    device_model text,
    device_id text,
    posthog_distinct_id text,
    posthog_session_id text,
    status public.support_report_status DEFAULT 'open'::public.support_report_status NOT NULL,
    resolved_by uuid,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT support_reports_platform_check CHECK ((platform = ANY (ARRAY['ios'::text, 'android'::text])))
);

CREATE TABLE IF NOT EXISTS public.class_session_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    class_session_id uuid NOT NULL,
    batch_semester_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

COMMENT ON TABLE public.support_reports IS 'Application support register; production backup does not contain historical reports.';

COMMENT ON TABLE public.class_session_batches IS 'Optional secondary batch links; production backup contains only primary batch relationships.';
