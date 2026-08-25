"""
CognifyAI - single-command launcher for backend + frontend.

Cross-platform: works on macOS, Linux, and Windows.

Usage:
    python start.py                   # starts both servers + opens browser
    python start.py --backend-only
    python start.py --frontend-only
    python start.py --no-browser      # don't open the browser automatically
    python start.py --no-install      # don't auto-run install on first run

Environment:
    BACKEND_PORT   override the FastAPI port (default 8000)
    FRONTEND_PORT  override the Next.js port (default 3000)
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

IS_WINDOWS = os.name == "nt"

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, "backend")
FRONTEND_DIR = os.path.join(ROOT, "frontend")
ENV_FILE = os.path.join(BACKEND_DIR, ".env")
INSTALL_SCRIPT = os.path.join(ROOT, "install.py")


# ----------------------------------------------------------------------
# UI helpers
# ----------------------------------------------------------------------

def _supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    if IS_WINDOWS:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True


_COLOR = _supports_color()
GREEN = "\033[32m" if _COLOR else ""
RED = "\033[31m" if _COLOR else ""
YELLOW = "\033[33m" if _COLOR else ""
CYAN = "\033[36m" if _COLOR else ""
DIM = "\033[2m" if _COLOR else ""
BOLD = "\033[1m" if _COLOR else ""
RESET = "\033[0m" if _COLOR else ""


def _log(tag: str, color: str, msg: str) -> None:
    print(f"{color}[{tag:<7}]{RESET} {msg}")


def info(msg: str) -> None:
    _log("info", DIM, msg)


def setup(msg: str) -> None:
    _log("setup", CYAN, msg)


def start(msg: str) -> None:
    _log("start", GREEN, msg)


def warn(msg: str) -> None:
    _log("warn", YELLOW, msg)


def err(msg: str) -> None:
    _log("error", RED, msg)


def ready(msg: str) -> None:
    _log("ready", GREEN, msg)


# ----------------------------------------------------------------------
# Tool resolution
# ----------------------------------------------------------------------

def _venv_python() -> str:
    """Return the venv python path, or fall back to the current interpreter."""
    candidates = [
        os.path.join(BACKEND_DIR, ".venv"),
        os.path.join(BACKEND_DIR, "venv"),
        os.path.join(ROOT, ".venv"),
        os.path.join(ROOT, "venv"),
    ]
    for vdir in candidates:
        if IS_WINDOWS:
            cand = os.path.join(vdir, "Scripts", "python.exe")
        else:
            cand = os.path.join(vdir, "bin", "python")
            if not os.path.isfile(cand):
                cand = os.path.join(vdir, "bin", "python3")
        if os.path.isfile(cand):
            return cand
    return sys.executable


def _resolve(name: str) -> str:
    """Locate a CLI tool, accounting for Windows extensions."""
    found = shutil.which(name)
    if found:
        return found
    if IS_WINDOWS:
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
    raise RuntimeError(
        f"`{name}` not found on PATH. Install it and try again "
        f"(or run: python install.py)."
    )


# ----------------------------------------------------------------------
# Auto-bootstrap on first run
# ----------------------------------------------------------------------

def _needs_install() -> bool:
    venv_dir_a = os.path.join(BACKEND_DIR, ".venv")
    venv_dir_b = os.path.join(BACKEND_DIR, "venv")
    has_venv = os.path.isdir(venv_dir_a) or os.path.isdir(venv_dir_b)
    has_node_modules = os.path.isdir(os.path.join(FRONTEND_DIR, "node_modules"))
    return not (has_venv and has_node_modules)


def _maybe_bootstrap(no_install: bool) -> None:
    if not _needs_install():
        return
    if no_install:
        warn("first-time setup not done; pass without --no-install or run: python install.py")
        return
    setup("first-time setup detected, running installer ...")
    rc = subprocess.call([sys.executable, INSTALL_SCRIPT, "--no-prompt"])
    if rc != 0:
        err(f"installer exited with code {rc}. Run `python install.py` manually.")
        sys.exit(rc)


# ----------------------------------------------------------------------
# Env validation
# ----------------------------------------------------------------------

def _read_env_value(path: str, key: str) -> str | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _validate_env() -> None:
    if not os.path.isfile(ENV_FILE):
        warn("backend/.env not found. AI features will not work until it's created.")
        return
    key = _read_env_value(ENV_FILE, "GEMINI_API_KEY")
    placeholder_values = {"", "your_gemini_api_key", "your-gemini-api-key", "changeme"}
    if not key or key.strip().lower() in placeholder_values:
        warn("GEMINI_API_KEY is not set in backend/.env. AI features will fail.")
        info("get one free: https://aistudio.google.com/app/apikey")


# ----------------------------------------------------------------------
# Port handling
# ----------------------------------------------------------------------

def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _find_free_port(preferred: int, label: str) -> int:
    if not _port_in_use(preferred):
        return preferred
    warn(f"{label} port {preferred} is busy - searching for a free one ...")
    for offset in range(1, 50):
        cand = preferred + offset
        if not _port_in_use(cand):
            info(f"{label} will use port {cand}")
            return cand
    raise RuntimeError(f"no free port near {preferred} for {label}")


# ----------------------------------------------------------------------
# Process management
# ----------------------------------------------------------------------

def _popen_kwargs() -> dict:
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {}


def start_backend(port: int) -> subprocess.Popen:
    py = _venv_python()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(
        [
            py, "-m", "uvicorn", "run:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--reload",
        ],
        cwd=BACKEND_DIR,
        env=env,
        **_popen_kwargs(),
    )


def start_frontend(frontend_port: int, backend_port: int) -> subprocess.Popen:
    npm = _resolve("npm")
    env = {
        **os.environ,
        "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{backend_port}/api",
    }
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--port", str(frontend_port)],
        cwd=FRONTEND_DIR,
        env=env,
        **_popen_kwargs(),
    )


def terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    except (OSError, ValueError):
        pass


# ----------------------------------------------------------------------
# Readiness probing
# ----------------------------------------------------------------------

def _probe_url(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


def _wait_then_open_browser(frontend_port: int, backend_port: int, max_wait: float = 90.0) -> None:
    """Poll the frontend until it responds, then open the browser."""
    frontend_url = f"http://localhost:{frontend_port}"
    backend_url = f"http://127.0.0.1:{backend_port}/api/lectures"

    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _probe_url(frontend_url):
            ready(f"frontend ready  {frontend_url}")
            try:
                webbrowser.open(frontend_url)
            except Exception:
                pass
            return
        time.sleep(0.75)
    warn(f"frontend didn't respond within {int(max_wait)}s - open {frontend_url} manually")
    _ = backend_url  # reserved for future health checks


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Start CognifyAI servers")
    parser.add_argument("--backend-only", action="store_true", help="Start only the FastAPI backend")
    parser.add_argument("--frontend-only", action="store_true", help="Start only the Next.js frontend")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    parser.add_argument("--no-install", action="store_true", help="Skip auto-bootstrap on first run")
    args = parser.parse_args()

    run_backend = not args.frontend_only
    run_frontend = not args.backend_only

    _maybe_bootstrap(no_install=args.no_install)
    _validate_env()

    backend_port = int(os.environ.get("BACKEND_PORT", 8000))
    frontend_port = int(os.environ.get("FRONTEND_PORT", 3000))
    if run_backend:
        backend_port = _find_free_port(backend_port, "backend")
    if run_frontend:
        frontend_port = _find_free_port(frontend_port, "frontend")

    procs: list[subprocess.Popen] = []

    def shutdown(signum=None, frame=None):
        print()
        info("shutting down ...")
        for p in procs:
            terminate(p)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, shutdown)
        except (ValueError, OSError):
            pass

    if run_backend:
        start(f"backend  -> http://127.0.0.1:{backend_port}")
        procs.append(start_backend(backend_port))

    if run_frontend:
        time.sleep(0.5)
        start(f"frontend -> http://localhost:{frontend_port}")
        procs.append(start_frontend(frontend_port, backend_port))

    if run_frontend and not args.no_browser:
        threading.Thread(
            target=_wait_then_open_browser,
            args=(frontend_port, backend_port),
            daemon=True,
        ).start()

    print()
    info("press Ctrl+C to stop.")
    print()

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
