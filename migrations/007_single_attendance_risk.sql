UPDATE mis.settings
SET value = value - 'risk_consecutive',
    updated_at = now()
WHERE key = 'metrics';
