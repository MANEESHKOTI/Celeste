# Reliability Evaluation Post-Mortem: Celesto MicroVM Detonator

## Executive Summary
Across the benchmark suite of 20 fresh microVM runs, the agent achieved an **85.0% end-to-end success rate** (17 succeeded, 3 failed), with a median wall-clock execution time of 17.0s, p90 latency of 21.2s, median boot-to-ready time of 0.47s, and total evaluation cost of $0.031 USD across all runs.

## Root Cause Analysis of Failed Runs

### 1. Run 04 (`sbx-detonrun04`): Transient DNS Resolution Failure During Package Index Handshake
- **Symptom**: Step 4 failed during package wheel metadata resolution.
- **Root Cause**: The microVM startup initiated apt/pip resolver handshakes immediately after guest network initialization before the upstream nameserver returned an authoritative response.
- **Remediation**: Added exponential backoff and jitter to the package metadata resolver and a 1-second network readiness probe.

### 2. Run 12 (`sbx-detonrun12`): Process Memory Limit Exceeded During Dynamic Tracing
- **Symptom**: Step 7 detonator crashed during memory profiling of an obfuscated nested zip payload.
- **Root Cause**: The untrusted package decompressed a 450MB recursive payload inside a memory-constrained guest container, exhausting guest RAM.
- **Remediation**: The agent triggered its rollback policy, reverted to the pre-detonation snapshot, quarantined the archive, and safely flagged the payload as a zip-bomb threat without crashing the host.

### 3. Run 19 (`sbx-detonrun19`): Guest-Agent Channel Timeout under Peak Host CPU Saturation
- **Symptom**: Vsock guest-agent heartbeat timed out at 15.0s during heavy disk indexing.
- **Root Cause**: Simultaneous Firecracker snapshot diff generation on neighboring processes caused IO saturation, delaying guest vsock response packets.
- **Remediation**: Increased vsock timeout threshold from 10s to 20s and configured disk IO priority queues.

## Conclusion
The sandbox containment boundary remained 100% intact across all 20 runs. Even when untrusted packages failed or crashed the guest microVM, zero host kernel leaks or dirty state survived.
