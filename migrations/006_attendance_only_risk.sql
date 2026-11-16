UPDATE mis.settings
SET value = (value - 'risk_drop' - 'risk_failed' - 'risk_missing') || '{"risk_attendance":40}'::jsonb,
    updated_at = now()
WHERE key = 'metrics';
