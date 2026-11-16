ALTER TABLE mis.work_items ADD COLUMN function_name text NOT NULL DEFAULT 'Unassigned';
ALTER TABLE mis.work_items ADD COLUMN category text NOT NULL DEFAULT 'Unclassified';
ALTER TABLE mis.work_items ADD COLUMN escalation_level integer NOT NULL DEFAULT 0 CHECK (escalation_level BETWEEN 0 AND 3);
ALTER TABLE mis.work_items ADD COLUMN completed_at timestamptz;
CREATE INDEX work_items_function_due_idx ON mis.work_items(kind,function_name,due_date);
