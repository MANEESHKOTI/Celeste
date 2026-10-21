CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR(255) PRIMARY KEY,
    sandbox_name VARCHAR(255) NOT NULL,
    problem_id VARCHAR(255) NOT NULL,
    state VARCHAR(50) NOT NULL,
    execution_target VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
VALUES (
    'run-seeddemo1',
    'sbx-seeddemo1',
    'problem-seed-detonator',
    'deleted',
    'celesto_sandbox'
)
ON CONFLICT (run_id) DO UPDATE SET
    sandbox_name = EXCLUDED.sandbox_name,
    problem_id = EXCLUDED.problem_id,
    state = EXCLUDED.state,
    execution_target = EXCLUDED.execution_target;
