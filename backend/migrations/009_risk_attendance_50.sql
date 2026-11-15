UPDATE mis.settings
SET value = jsonb_set(value, '{risk_attendance}', '50.0'::jsonb),
    updated_at = now()
WHERE key = 'metrics';

