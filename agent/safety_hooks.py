"""
Celesto Safety Callbacks & Pre-execution Inspection Hooks
Enforces command-level verification before commands reach the guest microVM kernel.
"""
import re
import json
import os
from datetime import datetime, timezone
from typing import Tuple

LOGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "commands.jsonl")

# Hazardous patterns blocked before reaching the microVM
BLOCKED_PATTERNS = [
    re.compile(r"rm\s+-rf\s+(/|/\*|~/.*)\s*(--no-preserve-root)?", re.IGNORECASE),
    re.compile(r"curl.*evil\.com", re.IGNORECASE),
    re.compile(r"urllib\.request.*malicious-c2", re.IGNORECASE),
    re.compile(r"(curl|wget|nc).*exfil", re.IGNORECASE),
    re.compile(r"cat\s+.*\.env", re.IGNORECASE),
    re.compile(r"/etc/shadow", re.IGNORECASE),
]


class CommandBlockedError(Exception):
    """Raised when a command is blocked by a pre-execution safety hook."""
    pass


class SafetyHookManager:
    def __init__(self, log_path: str = LOGS_PATH):
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def audit_and_verify(self, sandbox_name: str, command: str) -> Tuple[bool, str]:
        """
        Inspects command. If unsafe, blocks and logs decision as 'block'.
        Otherwise logs decision as 'allow'.
        """
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        decision = "allow"

        for pattern in BLOCKED_PATTERNS:
            if pattern.search(command):
                decision = "block"
                break

        log_entry = {
            "ts": ts,
            "sandbox_name": sandbox_name,
            "command": command,
            "decision": decision,
            "execution_target": "celesto_sandbox",
        }

        with open(self.log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        if decision == "block":
            raise CommandBlockedError(f"SafetyHook blocked hazardous command: {command}")

        return True, decision
