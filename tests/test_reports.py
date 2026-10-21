"""
Automated Evaluation & Contract Test Suite
Validates all repository contracts, report schemas, mathematical proofs,
and API invariants defined in the evaluation specification.
Compatible with pytest and standard python3 execution.
"""
import os
import re
import sys
import json
import math
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_REGEX = re.compile(r"^sbx-[a-z0-9]{8,}$")

# Ensure REPO_ROOT is in sys.path
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from api.main import (
    app,
    StandaloneHandler,
    validate_and_store_run,
    fetch_all_runs,
    ALLOWED_STATES,
    ALLOWED_EXECUTION_TARGET,
)


# ---------------------------------------------------------
# Test 1: Docker Compose & Healthcheck Contracts
# ---------------------------------------------------------
def test_docker_compose_contracts():
    compose_path = os.path.join(REPO_ROOT, "docker-compose.yml")
    assert os.path.exists(compose_path), "docker-compose.yml missing"
    with open(compose_path, "r") as f:
        content = f.read()

    # Check services exist
    assert "api:" in content, "api service not found in docker-compose.yml"
    assert "ledger:" in content, "ledger service not found in docker-compose.yml"

    # Check healthchecks and specific commands
    assert "healthcheck:" in content, "healthcheck section missing"
    assert "pg_isready" in content, "pg_isready healthcheck missing in ledger service"
    assert "curl" in content and "http://localhost:8080/health" in content, (
        "curl http://localhost:8080/health healthcheck missing in api service"
    )

    # Check intervals, timeouts, retries, start_period
    assert "interval:" in content, "interval missing in healthcheck"
    assert "timeout:" in content, "timeout missing in healthcheck"
    assert "retries:" in content, "retries missing in healthcheck"
    assert "start_period:" in content, "start_period missing in healthcheck"

    # Check seeds mount
    assert "./seeds" in content or "seeds/" in content, "seeds volume mount missing in ledger service"


# ---------------------------------------------------------
# Test 2: Environment File Verification
# ---------------------------------------------------------
def test_environment_variables():
    env_example = os.path.join(REPO_ROOT, ".env.example")
    env_live = os.path.join(REPO_ROOT, ".env")

    assert os.path.exists(env_example), ".env.example missing"
    assert not os.path.exists(env_live), ".env must NOT be present at repository root"

    with open(env_example, "r") as f:
        env_content = f.read()

    required_keys = [
        "CELESTO_PROVIDER",
        "CELESTO_API_KEY",
        "LLM_API_KEY",
        "LLM_MODEL",
        "DATABASE_URL",
        "API_PORT",
    ]
    for key in required_keys:
        assert f"{key}=" in env_content, f"Key {key} missing from .env.example"


# ---------------------------------------------------------
# Test 3: Problem Statement (reports/problem.json)
# ---------------------------------------------------------
def test_problem_statement():
    path = os.path.join(REPO_ROOT, "reports", "problem.json")
    assert os.path.exists(path), "reports/problem.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    for k in ["who", "agent_work", "proof_output", "idea_source"]:
        assert k in data, f"Key {k} missing in problem.json"

    assert data["idea_source"] in ["idea_bank", "original"]
    assert len(data["who"]) >= 40, "who must be at least 40 characters"
    assert len(data["agent_work"]) >= 40, "agent_work must be at least 40 characters"
    assert len(data["proof_output"]) >= 20, "proof_output must be at least 20 characters"


# ---------------------------------------------------------
# Test 4: Command Audit Log (logs/commands.jsonl)
# ---------------------------------------------------------
def test_command_audit_log():
    path = os.path.join(REPO_ROOT, "logs", "commands.jsonl")
    assert os.path.exists(path), "logs/commands.jsonl missing"

    lines = [line.strip() for line in open(path) if line.strip()]
    assert len(lines) >= 1, "logs/commands.jsonl must have at least one line"

    has_allow = False
    has_block = False

    for idx, line in enumerate(lines):
        obj = json.loads(line)
        for key in ["ts", "sandbox_name", "command", "decision", "execution_target"]:
            assert key in obj, f"Key {key} missing in line {idx}"

        # ISO-8601 validation
        datetime.fromisoformat(obj["ts"].replace("Z", "+00:00"))

        assert SANDBOX_REGEX.match(obj["sandbox_name"]), (
            f"sandbox_name {obj['sandbox_name']} does not match ^sbx-[a-z0-9]{{8,}}$"
        )
        assert len(obj["command"]) > 0, "command must be non-empty"
        assert obj["decision"] in ["allow", "block"], f"Invalid decision {obj['decision']}"
        assert obj["execution_target"] == "celesto_sandbox", (
            f"execution_target must be exactly celesto_sandbox, got {obj['execution_target']}"
        )

        if obj["decision"] == "allow":
            has_allow = True
        if obj["decision"] == "block":
            has_block = True

    assert has_allow, "logs/commands.jsonl should have allowed commands"
    assert has_block, "logs/commands.jsonl should demonstrate safety hook blocked command"


# ---------------------------------------------------------
# Test 5: Capabilities (reports/capabilities.json)
# ---------------------------------------------------------
def test_capabilities():
    path = os.path.join(REPO_ROOT, "reports", "capabilities.json")
    assert os.path.exists(path), "reports/capabilities.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    allowed_ids = {
        "persistence",
        "snapshots",
        "celestofs",
        "browser",
        "published_ports",
        "network_policy",
        "safety_hooks",
        "host_mounts",
        "coding_agent_preset",
        "agentor_durable",
    }

    assert "capabilities" in data, "capabilities key missing"
    caps = data["capabilities"]
    assert len(caps) >= 2, "capabilities must have at least two objects"

    seen_ids = set()
    for cap in caps:
        cid = cap.get("id")
        assert cid in allowed_ids, f"Invalid capability id: {cid}"
        assert cid not in seen_ids, f"Duplicate capability id: {cid}"
        seen_ids.add(cid)

        why = cap.get("why", "")
        assert len(why) >= 80, f"Capability {cid} why must be at least 80 characters (got {len(why)})"

        evidence_path = cap.get("evidence_path", "")
        full_evidence = os.path.join(REPO_ROOT, evidence_path)
        assert os.path.exists(full_evidence), f"evidence_path does not exist: {evidence_path}"


# ---------------------------------------------------------
# Test 6: Lifecycle Hygiene (reports/lifecycle.json)
# ---------------------------------------------------------
def test_lifecycle_hygiene():
    path = os.path.join(REPO_ROOT, "reports", "lifecycle.json")
    assert os.path.exists(path), "reports/lifecycle.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    assert data.get("cleanup_on_success") is True
    assert data.get("cleanup_on_failure") is True
    assert data.get("cleanup_on_interrupt") is True

    names = data.get("sandbox_names", [])
    assert len(names) > 0, "sandbox_names must be non-empty"
    assert len(names) == len(set(names)), "sandbox_names must be unique"

    # Load names from logs/commands.jsonl and reports/reliability.json
    commands_names = set()
    cmd_path = os.path.join(REPO_ROOT, "logs", "commands.jsonl")
    if os.path.exists(cmd_path):
        for line in open(cmd_path):
            if line.strip():
                commands_names.add(json.loads(line).get("sandbox_name"))

    reliability_names = set()
    rel_path = os.path.join(REPO_ROOT, "reports", "reliability.json")
    if os.path.exists(rel_path):
        with open(rel_path) as f:
            rdata = json.load(f)
            for r in rdata.get("runs", []):
                reliability_names.add(r.get("sandbox_name"))

    for name in names:
        assert SANDBOX_REGEX.match(name), f"Sandbox name {name} does not match ^sbx-[a-z0-9]{{8,}}$"
        assert name in commands_names or name in reliability_names, (
            f"Sandbox name {name} must appear in logs/commands.jsonl or reports/reliability.json"
        )


# ---------------------------------------------------------
# Test 7: Reliability & Summary Arithmetic (reports/reliability.json)
# ---------------------------------------------------------
def test_reliability_arithmetic():
    path = os.path.join(REPO_ROOT, "reports", "reliability.json")
    assert os.path.exists(path), "reports/reliability.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    runs = data.get("runs", [])
    run_count = data.get("run_count")
    assert run_count == len(runs)
    assert run_count >= 20

    seen_names = set()
    for run in runs:
        assert run.get("fresh") is True
        sname = run.get("sandbox_name")
        assert SANDBOX_REGEX.match(sname)
        assert sname not in seen_names
        seen_names.add(sname)
        assert isinstance(run.get("success"), bool)
        assert run.get("wall_clock_s") >= 0
        assert run.get("boot_to_ready_s") >= 0
        assert run.get("cost_usd") >= 0

    # Arithmetic checks
    success_count = sum(1 for r in runs if r["success"])
    computed_success_rate = success_count / run_count
    assert abs(data["success_rate"] - computed_success_rate) <= 0.001

    # wall_clock_s sorted ascending
    sorted_walls = sorted([r["wall_clock_s"] for r in runs])
    for idx in range(len(runs)):
        assert runs[idx]["wall_clock_s"] == sorted_walls[idx], "runs array must be sorted by wall_clock_s ascending"

    # Median wall_clock_s: mean of 10th and 11th values (1-based -> index 9 and 10)
    computed_median_wall = (sorted_walls[9] + sorted_walls[10]) / 2.0
    assert abs(data["median_wall_clock_s"] - computed_median_wall) <= 0.001

    # p90 wall_clock_s: 18th sorted value (ceil(0.9 * 20)) -> index 17
    rank_p90_idx = math.ceil(0.90 * run_count) - 1
    computed_p90 = sorted_walls[rank_p90_idx]
    assert abs(data["p90_wall_clock_s"] - computed_p90) <= 0.001

    # Median boot_to_ready_s: same median rule on sorted boot_to_ready_s
    sorted_boots = sorted([r["boot_to_ready_s"] for r in runs])
    computed_median_boot = (sorted_boots[9] + sorted_boots[10]) / 2.0
    assert abs(data["median_boot_to_ready_s"] - computed_median_boot) <= 0.001

    # Total cost
    computed_total_cost = sum(r["cost_usd"] for r in runs)
    assert abs(data["total_cost_usd"] - computed_total_cost) <= 0.01

    # Postmortem check
    pm_path = data.get("postmortem_path")
    assert pm_path == "reports/postmortem.md"
    full_pm = os.path.join(REPO_ROOT, pm_path)
    assert os.path.exists(full_pm)
    with open(full_pm, "r") as f:
        pm_content = f.read()
    assert len(pm_content) >= 200, "postmortem.md must be at least 200 characters"


# ---------------------------------------------------------
# Test 8: Containment (reports/containment.json)
# ---------------------------------------------------------
def test_containment():
    path = os.path.join(REPO_ROOT, "reports", "containment.json")
    assert os.path.exists(path), "reports/containment.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    assert data.get("attack") in [
        "prompt_injection_exfil",
        "destructive_command",
        "suspicious_package",
    ]
    assert data.get("blocked") is True
    assert data.get("host_untouched") is True

    evidence_paths = data.get("evidence_paths", [])
    assert len(evidence_paths) >= 1
    for ep in evidence_paths:
        full_ep = os.path.join(REPO_ROOT, ep)
        assert os.path.exists(full_ep), f"Evidence file missing: {ep}"


# ---------------------------------------------------------
# Test 9: Failure Policy (reports/failure_policy.json & failure_trace.jsonl)
# ---------------------------------------------------------
def test_failure_policy_and_trace():
    path = os.path.join(REPO_ROOT, "reports", "failure_policy.json")
    assert os.path.exists(path), "reports/failure_policy.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    assert data.get("failed_step") == 7
    assert data.get("total_steps") == 10
    policy = data.get("policy")
    assert policy in ["resume", "rollback", "fresh"]
    assert len(data.get("rationale", "")) >= 200

    trace_path = data.get("trace_path")
    assert trace_path == "reports/failure_trace.jsonl"
    full_trace = os.path.join(REPO_ROOT, trace_path)
    assert os.path.exists(full_trace)

    trace_lines = [json.loads(line) for line in open(full_trace) if line.strip()]
    policy_applied_events = [
        ev for ev in trace_lines
        if ev.get("event") == "policy_applied" and ev.get("policy") == policy
    ]
    assert len(policy_applied_events) >= 1, f"Missing event 'policy_applied' with policy '{policy}' in trace"


# ---------------------------------------------------------
# Test 10: Concurrency (reports/concurrency.json)
# ---------------------------------------------------------
def test_concurrency():
    path = os.path.join(REPO_ROOT, "reports", "concurrency.json")
    assert os.path.exists(path), "reports/concurrency.json missing"
    with open(path, "r") as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    assert len(jobs) >= 5, "concurrency.json must have at least five jobs"

    seen_names = set()
    for job in jobs:
        sname = job.get("sandbox_name")
        assert SANDBOX_REGEX.match(sname)
        assert sname not in seen_names
        seen_names.add(sname)

        started = job.get("started_at")
        assert started and len(started) > 0
        datetime.fromisoformat(started.replace("Z", "+00:00"))

    breakage_notes = data.get("breakage_notes", "")
    assert len(breakage_notes) >= 40, "breakage_notes must be at least 40 characters"


# ---------------------------------------------------------
# Test 11: Run Ledger API Endpoints
# ---------------------------------------------------------
def test_ledger_api_endpoints():
    try:
        from fastapi.testclient import TestClient
        has_test_client = (app is not None)
    except ImportError:
        has_test_client = False

    if has_test_client:
        client = TestClient(app)

        # 1. GET /health
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

        # 2. GET /api/runs includes sbx-seeddemo1
        r = client.get("/api/runs")
        assert r.status_code == 200
        runs = r.json()
        assert isinstance(runs, list)
        assert any(run.get("sandbox_name") == "sbx-seeddemo1" for run in runs)

        # 3. POST /api/runs accepts valid body and returns 201
        valid_payload = {
            "run_id": "run-testvalid123",
            "sandbox_name": "sbx-testvalid12",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "celesto_sandbox",
        }
        r = client.post("/api/runs", json=valid_payload)
        assert r.status_code == 201
        assert r.json()["sandbox_name"] == "sbx-testvalid12"

        # 4. POST execution_target host and expect 400
        bad_target_payload = {
            "run_id": "run-badtarget1",
            "sandbox_name": "sbx-testvalid12",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "host",
        }
        r = client.post("/api/runs", json=bad_target_payload)
        assert r.status_code == 400

        # 5. POST invalid state and expect 400
        bad_state_payload = {
            "run_id": "run-badstate1",
            "sandbox_name": "sbx-testvalid12",
            "problem_id": "problem-detonator",
            "state": "unknown_state",
            "execution_target": "celesto_sandbox",
        }
        r = client.post("/api/runs", json=bad_state_payload)
        assert r.status_code == 400

        # 6. POST invalid sandbox_name and expect 400
        bad_name_payload = {
            "run_id": "run-badname1",
            "sandbox_name": "invalid-sbx",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "celesto_sandbox",
        }
        r = client.post("/api/runs", json=bad_name_payload)
        assert r.status_code == 400

    else:
        # Fallback to direct domain / handler validation
        status_code, resp = StandaloneHandler.handle_get("/health")
        assert status_code == 200
        assert resp == {"status": "ok"}

        status_code, runs = StandaloneHandler.handle_get("/api/runs")
        assert status_code == 200
        assert isinstance(runs, list)
        assert any(run.get("sandbox_name") == "sbx-seeddemo1" for run in runs)

        valid_payload = {
            "run_id": "run-testvalid123",
            "sandbox_name": "sbx-testvalid12",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "celesto_sandbox",
        }
        status_code, res = validate_and_store_run(valid_payload)
        assert status_code == 201
        assert res["sandbox_name"] == "sbx-testvalid12"

        # POST execution_target host returns 400
        bad_target = dict(valid_payload)
        bad_target["execution_target"] = "host"
        status_code, _ = validate_and_store_run(bad_target)
        assert status_code == 400

        # POST invalid state returns 400
        bad_state = dict(valid_payload)
        bad_state["state"] = "unknown_state"
        status_code, _ = validate_and_store_run(bad_state)
        assert status_code == 400

        # POST invalid sandbox_name returns 400
        bad_name = dict(valid_payload)
        bad_name["sandbox_name"] = "invalid-sbx"
        status_code, _ = validate_and_store_run(bad_name)
        assert status_code == 400


# ---------------------------------------------------------
# Test 12: README Required Phrases
# ---------------------------------------------------------
def test_readme_phrases():
    readme_path = os.path.join(REPO_ROOT, "README.md")
    assert os.path.exists(readme_path), "README.md missing"
    with open(readme_path, "r") as f:
        content = f.read()

    required_phrases = [
        "Problem statement",
        "How I used Celesto",
        "Eval report",
        "Containment test",
        "State and failure design",
        "Setup",
    ]
    for phrase in required_phrases:
        assert phrase in content, f"Required phrase '{phrase}' missing from README.md"


if __name__ == "__main__":
    print("Running evaluation contract tests...")
    tests = [
        ("Docker Compose Contracts", test_docker_compose_contracts),
        ("Environment Variables", test_environment_variables),
        ("Problem Statement", test_problem_statement),
        ("Command Audit Log", test_command_audit_log),
        ("Capabilities", test_capabilities),
        ("Lifecycle Hygiene", test_lifecycle_hygiene),
        ("Reliability Arithmetic", test_reliability_arithmetic),
        ("Containment", test_containment),
        ("Failure Policy & Trace", test_failure_policy_and_trace),
        ("Concurrency", test_concurrency),
        ("Ledger API Endpoints", test_ledger_api_endpoints),
        ("README Phrases", test_readme_phrases),
    ]

    all_passed = True
    for name, test_func in tests:
        try:
            test_func()
            print(f"  [PASS] {name}")
        except Exception as exc:
            all_passed = False
            print(f"  [FAIL] {name}: {exc}")

    if all_passed:
        print("\nALL 12 CONTRACT TESTS PASSED WITH 0 ERRORS!")
        sys.exit(0)
    else:
        print("\nSOME TESTS FAILED.")
        sys.exit(1)
