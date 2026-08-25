"""
CognifyAI - cross-platform installer / first-time setup.

Works on macOS, Linux, and Windows. Run once after cloning:

    python install.py                # install everything (skips work that's
                                     # already done)
    python install.py --force        # force a clean reinstall
    python install.py --auto-tools   # also try to install missing system
                                     # tools via brew / winget / apt
    python install.py --clean        # remove venv, node_modules, and cache

It will:
  1. Check that Python, Node, npm, ffmpeg, and tesseract are installed.
  2. Create backend/.venv if it does not already exist.
  3. Install Python dependencies into that venv (skipped if requirements
     have not changed since the last successful run).
  4. Install Node dependencies in frontend/ (skipped if package-lock.json
     has not changed since the last successful run).
  5. Copy backend/.env.example -> backend/.env if it doesn't exist and
     prompt for the GEMINI_API_KEY.

After this finishes, run:

    python start.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, "backend")
FRONTEND_DIR = os.path.join(ROOT, "frontend")
VENV_DIR = os.path.join(BACKEND_DIR, ".venv")
CACHE_FILE = os.path.join(ROOT, ".install-cache.json")

REQUIREMENTS_FILE = os.path.join(BACKEND_DIR, "requirements.txt")
PACKAGE_LOCK = os.path.join(FRONTEND_DIR, "package-lock.json")
PACKAGE_JSON = os.path.join(FRONTEND_DIR, "package.json")
ENV_EXAMPLE = os.path.join(BACKEND_DIR, ".env.example")
ENV_FILE = os.path.join(BACKEND_DIR, ".env")

TOTAL_STEPS = 5


# ----------------------------------------------------------------------
# UI helpers
# ----------------------------------------------------------------------

def _supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    if IS_WINDOWS:
        # Enable ANSI on Windows 10+ terminals.
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


def banner(text: str) -> None:
    bar = "=" * max(60, len(text) + 4)
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")


def step(num: int, total: int, msg: str) -> None:
    print(f"\n{CYAN}[{num}/{total}]{RESET} {BOLD}{msg}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}    {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


# ----------------------------------------------------------------------
# Hashing / cache
# ----------------------------------------------------------------------

def _file_hash(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_cache() -> dict:
    if not os.path.isfile(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass


# ----------------------------------------------------------------------
# Tool detection
# ----------------------------------------------------------------------

def which(name: str) -> str | None:
    """Find a CLI on PATH, accounting for Windows extensions."""
    found = shutil.which(name)
    if found:
        return found
    if IS_WINDOWS:
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
    return None


def have(name: str) -> bool:
    if name == "python":
        return which("python") is not None or which("python3") is not None
    return which(name) is not None


def install_hint(tool: str) -> str:
    if IS_MAC:
        mapping = {
            "python": "brew install python",
            "node": "brew install node",
            "npm": "brew install node",
            "ffmpeg": "brew install ffmpeg",
            "tesseract": "brew install tesseract",
            "git": "brew install git",
        }
    elif IS_WINDOWS:
        mapping = {
            "python": "winget install -e --id Python.Python.3.12",
            "node": "winget install -e --id OpenJS.NodeJS.LTS",
            "npm": "winget install -e --id OpenJS.NodeJS.LTS",
            "ffmpeg": "winget install -e --id Gyan.FFmpeg",
            "tesseract": "winget install -e --id UB-Mannheim.TesseractOCR",
            "git": "winget install -e --id Git.Git",
        }
    else:
        mapping = {
            "python": "sudo apt install -y python3 python3-venv python3-pip",
            "node": "sudo apt install -y nodejs npm",
            "npm": "sudo apt install -y nodejs npm",
            "ffmpeg": "sudo apt install -y ffmpeg",
            "tesseract": "sudo apt install -y tesseract-ocr",
            "git": "sudo apt install -y git",
        }
    return mapping.get(tool, f"install {tool}")


def _try_auto_install(tool: str) -> bool:
    """Attempt to install a missing system tool via the OS package manager."""
    cmd = install_hint(tool)
    info(f"running: {cmd}")
    try:
        if IS_MAC:
            if not which("brew"):
                fail("Homebrew not found. Install from https://brew.sh and re-run.")
                return False
        elif IS_WINDOWS:
            if not which("winget"):
                fail("winget not found. Install from the Microsoft Store ('App Installer').")
                return False
        else:
            if not which("apt") and not which("apt-get"):
                fail("apt not found. Use your distro's package manager to install.")
                return False
        subprocess.check_call(cmd, shell=True)
        return True
    except subprocess.CalledProcessError as exc:
        fail(f"auto-install of {tool} failed: {exc}")
        return False


# ----------------------------------------------------------------------
# Steps
# ----------------------------------------------------------------------

def step_check_prereqs(auto_tools: bool) -> bool:
    step(1, TOTAL_STEPS, "Checking prerequisites")
    required = ["python", "node", "npm"]
    optional = ["ffmpeg", "tesseract"]

    missing_required: list[str] = []
    for tool in required:
        if have(tool):
            ok(f"{tool} found")
        else:
            fail(f"{tool} not found")
            missing_required.append(tool)

    missing_optional: list[str] = []
    for tool in optional:
        if have(tool):
            ok(f"{tool} found")
        else:
            warn(f"{tool} not found (optional, recommended for video / OCR)")
            missing_optional.append(tool)

    targets = missing_required + (missing_optional if auto_tools else [])
    if auto_tools and targets:
        print(f"\n{CYAN}[*]{RESET} {BOLD}Auto-installing missing tools{RESET}")
        for tool in list(targets):
            if _try_auto_install(tool) and have(tool):
                ok(f"{tool} installed")
                if tool in missing_required:
                    missing_required.remove(tool)

    if missing_required:
        print()
        fail("Required tools are missing:")
        for tool in missing_required:
            info(f"- {tool}: {install_hint(tool)}")
        print()
        info("Install them and re-run, or pass --auto-tools to attempt it for you.")
        return False

    if missing_optional and not auto_tools:
        info("(pass --auto-tools to install optional tools too)")
    return True


def _venv_python() -> str:
    if IS_WINDOWS:
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def step_create_venv() -> None:
    step(2, TOTAL_STEPS, "Setting up Python virtual environment")
    if os.path.isdir(VENV_DIR) and os.path.isfile(_venv_python()):
        ok(f"venv already exists at backend/.venv")
        return
    info("creating backend/.venv ...")
    venv.EnvBuilder(with_pip=True, clear=False, symlinks=not IS_WINDOWS).create(VENV_DIR)
    ok("venv created")


def step_install_python_deps(force: bool, cache: dict) -> None:
    step(3, TOTAL_STEPS, "Installing Python dependencies")
    current = _file_hash(REQUIREMENTS_FILE)
    cached = cache.get("requirements_sha256")
    if not force and current and current == cached and os.path.isdir(VENV_DIR):
        ok("requirements.txt unchanged - skipping pip install")
        return

    py = _venv_python()
    info("upgrading pip ...")
    subprocess.check_call(
        [py, "-m", "pip", "install", "--upgrade", "--quiet", "pip"]
    )
    info(f"installing from backend/requirements.txt ...")
    subprocess.check_call(
        [py, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS_FILE]
    )
    cache["requirements_sha256"] = current
    ok("python dependencies installed")


def step_install_node_deps(force: bool, cache: dict) -> None:
    step(4, TOTAL_STEPS, "Installing Node dependencies")
    npm = which("npm")
    if not npm:
        raise RuntimeError("npm not found on PATH - install Node.js first.")

    lock_hash = _file_hash(PACKAGE_LOCK)
    pkg_hash = _file_hash(PACKAGE_JSON)
    cached_lock = cache.get("package_lock_sha256")
    cached_pkg = cache.get("package_json_sha256")

    node_modules = os.path.join(FRONTEND_DIR, "node_modules")
    fingerprint_unchanged = (
        lock_hash and lock_hash == cached_lock
        and pkg_hash and pkg_hash == cached_pkg
    )

    if not force and fingerprint_unchanged and os.path.isdir(node_modules):
        ok("package-lock.json unchanged - skipping npm install")
        return

    if os.path.isfile(PACKAGE_LOCK):
        info("running: npm ci")
        try:
            subprocess.check_call([npm, "ci"], cwd=FRONTEND_DIR)
        except subprocess.CalledProcessError:
            warn("npm ci failed - falling back to npm install")
            subprocess.check_call([npm, "install"], cwd=FRONTEND_DIR)
    else:
        info("running: npm install")
        subprocess.check_call([npm, "install"], cwd=FRONTEND_DIR)

    cache["package_lock_sha256"] = _file_hash(PACKAGE_LOCK)
    cache["package_json_sha256"] = _file_hash(PACKAGE_JSON)
    ok("node dependencies installed")


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


def _write_env_value(path: str, key: str, value: str) -> None:
    lines: list[str] = []
    replaced = False
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    if k.strip() == key:
                        lines.append(f"{key}={value}\n")
                        replaced = True
                        continue
                lines.append(line)
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        lines.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    v = value.strip().lower()
    if not v:
        return True
    return v in {
        "your_gemini_api_key",
        "your-gemini-api-key",
        "changeme",
        "todo",
    }


def step_setup_env(prompt_for_key: bool) -> None:
    step(5, TOTAL_STEPS, "Configuring backend/.env")
    if not os.path.isfile(ENV_FILE):
        if os.path.isfile(ENV_EXAMPLE):
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
            ok("created backend/.env from .env.example")
        else:
            warn("backend/.env.example not found - you'll need to create backend/.env manually")
            return
    else:
        ok("backend/.env already exists")

    key = _read_env_value(ENV_FILE, "GEMINI_API_KEY")
    if not _is_placeholder(key):
        ok("GEMINI_API_KEY is set")
        return

    if not prompt_for_key:
        warn("GEMINI_API_KEY is not set in backend/.env")
        info("Get a free key from https://aistudio.google.com/app/apikey,")
        info("then paste it into backend/.env and re-run.")
        return

    print()
    info("Get a free Gemini API key: https://aistudio.google.com/app/apikey")
    info("Paste it below (or press Enter to skip and edit backend/.env later).")
    try:
        entered = input("  GEMINI_API_KEY> ").strip()
    except (EOFError, KeyboardInterrupt):
        entered = ""
    if entered and not _is_placeholder(entered):
        _write_env_value(ENV_FILE, "GEMINI_API_KEY", entered)
        ok("GEMINI_API_KEY saved to backend/.env")
    else:
        warn("Skipped - remember to add GEMINI_API_KEY to backend/.env before running.")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def do_clean() -> int:
    """Remove venv, node_modules, and the install cache."""
    banner("CognifyAI clean")
    targets = [
        VENV_DIR,
        os.path.join(BACKEND_DIR, "venv"),
        os.path.join(FRONTEND_DIR, "node_modules"),
        os.path.join(FRONTEND_DIR, ".next"),
        CACHE_FILE,
    ]
    removed_any = False
    for path in targets:
        if not os.path.exists(path):
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            ok(f"removed {os.path.relpath(path, ROOT)}")
            removed_any = True
        except OSError as exc:
            fail(f"could not remove {path}: {exc}")
            return 1
    if not removed_any:
        info("nothing to clean - already pristine.")
    else:
        print()
        if IS_WINDOWS:
            print(f"  Re-run: {CYAN}install.bat{RESET}")
        else:
            print(f"  Re-run: {CYAN}./install.sh{RESET}")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CognifyAI installer (cross-platform).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force pip / npm install even if nothing has changed.",
    )
    parser.add_argument(
        "--auto-tools", action="store_true",
        help="Try to install missing system tools (brew / winget / apt).",
    )
    parser.add_argument(
        "--no-prompt", action="store_true",
        help="Don't interactively ask for GEMINI_API_KEY.",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove backend/.venv, frontend/node_modules, and install cache.",
    )
    args = parser.parse_args()

    if args.clean:
        return do_clean()

    banner("CognifyAI installer")

    if not step_check_prereqs(auto_tools=args.auto_tools):
        return 1

    cache = _load_cache()

    try:
        step_create_venv()
        step_install_python_deps(force=args.force, cache=cache)
        step_install_node_deps(force=args.force, cache=cache)
    except subprocess.CalledProcessError as exc:
        fail(f"install failed: {exc}")
        _save_cache(cache)
        return exc.returncode or 1
    except Exception as exc:
        fail(f"install failed: {exc}")
        _save_cache(cache)
        return 1

    _save_cache(cache)

    step_setup_env(prompt_for_key=not args.no_prompt)

    print()
    banner("All set!")
    print(f"\n{BOLD}Next steps:{RESET}")
    print(f"  1. Make sure {CYAN}backend/.env{RESET} has your GEMINI_API_KEY.")
    if IS_WINDOWS:
        print(f"  2. Run: {CYAN}python start.py{RESET}   (or double-click start.bat)")
    else:
        print(f"  2. Run: {CYAN}python3 start.py{RESET}   (or {CYAN}./start.sh{RESET})")
    print(f"\n  Then open {CYAN}http://localhost:3000{RESET}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
