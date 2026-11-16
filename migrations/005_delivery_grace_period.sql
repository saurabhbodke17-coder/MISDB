UPDATE mis.settings
SET value = jsonb_set(value, '{late_tolerance}', '10'::jsonb),
    updated_at = now()
WHERE key = 'metrics';
