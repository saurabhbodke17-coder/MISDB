UPDATE mis.settings SET value=value || '{"sla_target":90,"task_target":90}'::jsonb WHERE key='metrics';
