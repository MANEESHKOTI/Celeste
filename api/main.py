"""
Run Ledger API Control Plane
Provides health checks, run tracking, and Celesto sandbox verification endpoints.
Designed to run seamlessly in modern FastAPI / Uvicorn environments (Docker),
with a standard library fallback for zero-dependency execution.
"""
import os
import re
import json
import logging
from typing import List, Optional, Dict, Any, Tuple

logger = logging.getLogger("ledger_api")
logging.basicConfig(level=logging.INFO)

# Environment configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ledger:ledger@ledger:5432/ledger")
API_PORT = int(os.getenv("API_PORT", "8080"))
CELESTO_PROVIDER = os.getenv("CELESTO_PROVIDER", "cloud")
CELESTO_API_KEY = os.getenv("CELESTO_API_KEY", "replace-me")
CELESTO_BACKEND = os.getenv("CELESTO_BACKEND", "firecracker")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://example-llm-host/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "replace-me")
LLM_MODEL = os.getenv("LLM_MODEL", "replace-with-a-model-name")

# Allowed values and regex according to spec
ALLOWED_STATES = {"created", "ready", "running", "succeeded", "failed", "deleted"}
ALLOWED_EXECUTION_TARGET = "celesto_sandbox"
SANDBOX_NAME_REGEX = re.compile(r"^sbx-[a-z0-9]{8,}$")

# In-memory store (used as cache or fallback)
seed_row = {
    "run_id": "run-seeddemo1",
    "sandbox_name": "sbx-seeddemo1",
    "problem_id": "problem-seed-detonator",
    "state": "deleted",
    "execution_target": "celesto_sandbox",
}
in_memory_runs: Dict[str, Dict[str, Any]] = {
    "run-seeddemo1": dict(seed_row)
}


def get_db_connection():
    try:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    except Exception as exc:
        logger.debug(f"Postgres connection unavailable ({exc}); using fallback store")
        return None


def init_db():
    conn = get_db_connection()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id VARCHAR(255) PRIMARY KEY,
                    sandbox_name VARCHAR(255) NOT NULL,
                    problem_id VARCHAR(255) NOT NULL,
                    state VARCHAR(50) NOT NULL,
                    execution_target VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
                VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'problem-seed-detonator', 'deleted', 'celesto_sandbox')
                ON CONFLICT (run_id) DO NOTHING;
                """
            )
            conn.commit()
            logger.info("Database schema initialized and seed verified.")
    except Exception as exc:
        logger.error(f"Error initializing DB schema: {exc}")
    finally:
        conn.close()


def validate_and_store_run(payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Core domain validation and persistence logic."""
    sandbox_name = payload.get("sandbox_name", "")
    state = payload.get("state", "")
    execution_target = payload.get("execution_target", "")
    run_id = payload.get("run_id", "")
    problem_id = payload.get("problem_id", "")

    # Validation Rule 1: sandbox_name regex
    if not sandbox_name or not SANDBOX_NAME_REGEX.match(sandbox_name):
        return 400, {"detail": "Invalid sandbox_name. Must match ^sbx-[a-z0-9]{8,}$"}

    # Validation Rule 2: state enum
    if state not in ALLOWED_STATES:
        return 400, {"detail": f"Invalid state '{state}'. Must be one of {sorted(list(ALLOWED_STATES))}"}

    # Validation Rule 3: execution_target exact match
    if execution_target != ALLOWED_EXECUTION_TARGET:
        return 400, {"detail": f"Invalid execution_target '{execution_target}'. Must be '{ALLOWED_EXECUTION_TARGET}'"}

    # Validation Rule 4: non-empty IDs
    if not run_id or not str(run_id).strip():
        return 400, {"detail": "run_id must be a non-empty string"}
    if not problem_id or not str(problem_id).strip():
        return 400, {"detail": "problem_id must be a non-empty string"}

    run_data = {
        "run_id": run_id,
        "sandbox_name": sandbox_name,
        "problem_id": problem_id,
        "state": state,
        "execution_target": execution_target,
    }

    in_memory_runs[run_id] = run_data

    conn = get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        sandbox_name = EXCLUDED.sandbox_name,
                        problem_id = EXCLUDED.problem_id,
                        state = EXCLUDED.state,
                        execution_target = EXCLUDED.execution_target;
                    """,
                    (run_id, sandbox_name, problem_id, state, execution_target),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"Failed to persist to database: {exc}")
        finally:
            conn.close()

    return 201, run_data


def fetch_all_runs() -> List[Dict[str, Any]]:
    """Retrieves all recorded runs, ensuring seeded row presence."""
    conn = get_db_connection()
    if conn is not None:
        try:
            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT run_id, sandbox_name, problem_id, state, execution_target FROM runs ORDER BY created_at ASC"
                )
                rows = cur.fetchall()
                if not any(r.get("sandbox_name") == "sbx-seeddemo1" for r in rows):
                    cur.execute(
                        """
                        INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
                        VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'problem-seed-detonator', 'deleted', 'celesto_sandbox')
                        ON CONFLICT (run_id) DO NOTHING;
                        """
                    )
                    conn.commit()
                    cur.execute(
                        "SELECT run_id, sandbox_name, problem_id, state, execution_target FROM runs ORDER BY created_at ASC"
                    )
                    rows = cur.fetchall()
                return list(rows)
        except Exception as exc:
            logger.error(f"Failed to query database: {exc}")
        finally:
            conn.close()

    return list(in_memory_runs.values())


# =========================================================
# FastAPI Application (Standard Production Mode)
# =========================================================
try:
    from fastapi import FastAPI, HTTPException, status
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        yield

    app = FastAPI(
        title="Celesto Run Ledger API",
        description="Trusted control plane recording agent sandbox runs and enforcing microVM boundaries",
        version="1.0.0",
        lifespan=lifespan,
    )

    reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    if os.path.exists(reports_dir):
        app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")

    class RunPayload(BaseModel):
        run_id: str
        sandbox_name: str
        problem_id: str
        state: str
        execution_target: str

    @app.get("/health")
    def health_endpoint():
        return {"status": "ok"}

    @app.get("/api/runs")
    def get_runs_endpoint():
        return fetch_all_runs()

    @app.post("/api/runs", status_code=status.HTTP_201_CREATED)
    def create_run_endpoint(payload: RunPayload):
        status_code, data = validate_and_store_run(payload.model_dump())
        if status_code != 201:
            raise HTTPException(status_code=status_code, detail=data.get("detail", "Error"))
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=data)

except ImportError:
    app = None  # Standard library fallback will be used when run directly


# =========================================================
# Standard Library HTTP Server (Zero-Dependency Fallback)
# =========================================================
class StandaloneHandler:
    @staticmethod
    def handle_get(path: str) -> Tuple[int, Dict[str, Any]]:
        if path == "/health":
            return 200, {"status": "ok"}
        elif path == "/api/runs":
            return 200, fetch_all_runs()
        return 404, {"detail": "Not found"}

    @staticmethod
    def handle_post(path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if path == "/api/runs":
            return validate_and_store_run(body)
        return 404, {"detail": "Not found"}


def run_stdlib_server(port: int = API_PORT):
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            status_code, resp = StandaloneHandler.handle_get(self.path)
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_len)
            try:
                payload = json.loads(body_raw.decode("utf-8"))
            except Exception:
                payload = {}
            status_code, resp = StandaloneHandler.handle_post(self.path, payload)
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

    server = HTTPServer(("0.0.0.0", port), RequestHandler)
    logger.info(f"Running zero-dependency ledger API on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    init_db()
    if app is not None:
        import uvicorn
        uvicorn.run("api.main:app", host="0.0.0.0", port=API_PORT, reload=False)
    else:
        run_stdlib_server(API_PORT)
