"""
Concurrent launcher for the Intelligent Educational Assessment System.

Starts both the FastAPI backend (uvicorn) and the React frontend (vite dev)
in parallel. Use --backend-only or --frontend-only to run one at a time.

Usage:
    python run.py                  # Start both servers
    python run.py --backend-only   # Start only the API server
    python run.py --frontend-only  # Start only the frontend dev server
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def _run_backend() -> subprocess.Popen:
    """Launch the FastAPI server with uvicorn."""
    print("[Backend]  Starting FastAPI on http://localhost:8000 ...")
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def _run_frontend() -> subprocess.Popen:
    """Launch the Vite dev server for the React frontend."""
    print("[Frontend] Starting Vite on http://localhost:3000 ...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=str(FRONTEND_DIR),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch the Assessment System (backend + frontend)."
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Start only the FastAPI backend server.",
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="Start only the Vite frontend dev server.",
    )
    args = parser.parse_args()

    if args.backend_only and args.frontend_only:
        print("Error: --backend-only and --frontend-only are mutually exclusive.")
        sys.exit(1)

    processes: list[subprocess.Popen] = []

    def _shutdown(signum: int | None = None, frame=None) -> None:
        print("\n[Launcher] Shutting down ...")
        for proc in processes:
            try:
                proc.terminate()
            except OSError:
                pass
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        if not args.frontend_only:
            processes.append(_run_backend())

        if not args.backend_only:
            if not FRONTEND_DIR.is_dir():
                print(
                    f"[Frontend] Directory not found: {FRONTEND_DIR}\n"
                    "           Run 'cd frontend && npm install' first."
                )
                sys.exit(1)
            processes.append(_run_frontend())

        print(f"\n[Launcher] {len(processes)} server(s) running. Press Ctrl+C to stop.\n")

        # Wait for any process to exit
        while True:
            for proc in processes:
                retcode = proc.poll()
                if retcode is not None:
                    name = "Backend" if "uvicorn" in " ".join(proc.args) else "Frontend"
                    print(f"\n[Launcher] {name} exited with code {retcode}.")
                    _shutdown()
            import time
            time.sleep(1)

    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
