UPDATE mis.settings SET value=value || '{"risk_consecutive":3,"risk_drop":15,"risk_failed":4,"risk_missing":3}'::jsonb WHERE key='metrics';
