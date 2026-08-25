# AnnexAI

AI-powered lecture study platform with RAG-based Q&A, quiz generation, flashcards, and spaced repetition.

Runs on **macOS, Linux, and Windows**. One command to install, one command to run.

## Features

- **Lecture Processing** — YouTube URL or local video upload with transcript extraction + OCR
- **RAG Q&A** — Hybrid semantic + lexical retrieval with streaming Gemini responses
- **Smart Summary** — Multi-pass academic summaries with PDF export
- **Detailed Notes** — Structured lecture notes with table of contents
- **Exam Quiz** — Auto-generated MCQ, multi-select, true/false, and short-answer questions
- **Flashcards** — Spaced repetition with Again/Hard/Good/Easy ratings
- **Coaching** — Weakness-aware study recommendations based on quiz performance
- **Library Dashboard** — Centralized view of all lectures with due card tracking

## Quick start

You'll need a free Gemini API key: https://aistudio.google.com/app/apikey

### macOS / Linux

```bash
git clone https://github.com/<your-username>/AnnexAI.git
cd AnnexAI
./install.sh        # one-time setup; prompts for GEMINI_API_KEY
./start.sh          # boots backend + frontend, opens http://localhost:3000
```

Press `Ctrl+C` to stop. Re-running `./start.sh` later is instant — nothing is reinstalled unless dependencies actually changed.

> **Missing system tools?** If `./install.sh` reports them, install with one of:
> - **macOS:** `brew install python node ffmpeg tesseract git`
> - **Linux:** `sudo apt install -y python3 python3-venv python3-pip nodejs npm ffmpeg tesseract-ocr git`
> - Or run `./install.sh --auto-tools` to attempt it for you.

### Windows

In PowerShell or Command Prompt (or just **double-click** `install.bat` in Explorer):

```powershell
git clone https://github.com/<your-username>/AnnexAI.git
cd AnnexAI
.\install.bat        # one-time setup; prompts for GEMINI_API_KEY
.\start.bat          # boots backend + frontend, opens http://localhost:3000
```

Press `Ctrl+C` to stop.

> **Missing system tools?** Use `winget`:
> ```powershell
> winget install -e --id Python.Python.3.12
> winget install -e --id OpenJS.NodeJS.LTS
> winget install -e --id Gyan.FFmpeg
> winget install -e --id UB-Mannheim.TesseractOCR
> winget install -e --id Git.Git
> ```
> Or run `.\install.bat --auto-tools` to attempt it for you. Close and reopen the terminal after installing system tools.

### What you get

- Backend (FastAPI + Uvicorn) on http://127.0.0.1:8000
- Frontend (Next.js dev server) on http://localhost:3000 (auto-opens in your browser)
- If those ports are busy, the launcher picks the next free ones and prints them.

### Useful flags

The `start` and `install` commands forward flags to the underlying Python scripts.

**Launching:**

| Flag | What it does |
|---|---|
| `--backend-only` | Only the FastAPI server |
| `--frontend-only` | Only the Next.js dev server |
| `--no-browser` | Don't auto-open the browser |
| `--no-install` | Skip the auto-bootstrap on first run |

**Installing:**

| Flag | What it does |
|---|---|
| `--force` | Reinstall everything (ignores the cache) |
| `--auto-tools` | Auto-install missing system tools via `brew` / `winget` / `apt` |
| `--clean` | Remove `backend/.venv`, `frontend/node_modules`, `frontend/.next`, and the install cache |
| `--no-prompt` | Don't interactively ask for `GEMINI_API_KEY` |

Examples:

```bash
./start.sh --backend-only          # macOS / Linux
.\start.bat --no-browser           # Windows
./install.sh --clean && ./install.sh   # nuke and rebuild everything
```

> If the wrapper scripts don't work for some reason, the underlying Python entry points still do:
> `python3 install.py` and `python3 start.py` (use `python` instead of `python3` on Windows).

## Architecture

```
AnnexAI/
├── backend/                 # Python FastAPI — AI/core processing service
│   ├── app/
│   │   ├── api/             # REST API routes
│   │   ├── core/            # AI engines (QA, quiz, summary, flashcards, coaching)
│   │   ├── services/        # LLM client, transcription, OCR, TTS
│   │   ├── utils/           # Storage, media, PDF generation
│   │   └── config/          # Settings and environment
│   ├── run.py               # Uvicorn entry point
│   ├── requirements.txt
│   └── .env.example         # Copied to backend/.env by the installer
├── frontend/                # Next.js + TypeScript — UI
│   ├── app/                 # App Router pages (qa, quiz, flashcards, ...)
│   ├── components/          # Shared React components
│   ├── lib/                 # API client, utilities
│   └── public/              # Static assets (videos, scripts)
├── install.py               # Cross-platform installer (all logic)
├── start.py                 # Cross-platform launcher (all logic)
├── install.sh / install.bat # Thin one-command install wrappers per OS
├── start.sh   / start.bat   # Thin one-command launch wrappers per OS
├── LICENSE
└── README.md
```

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/lectures/process` | Process a YouTube URL or uploaded video |
| GET | `/api/lectures` | Library dashboard data |
| DELETE | `/api/lectures/{id}` | Delete a lecture |
| GET | `/api/qa` | QA page info |
| POST | `/api/qa` | Ask a question (non-streaming) |
| POST | `/api/qa/stream` | Ask a question (SSE streaming) |
| GET | `/api/summary` | Generate/get summary |
| GET | `/api/notes` | Generate/get notes |
| GET | `/api/download/{type}` | Download PDF |
| GET | `/api/quiz` | Get quiz questions |
| POST | `/api/quiz/submit` | Submit quiz answers |
| POST | `/api/quiz/regenerate` | Regenerate quiz |
| GET | `/api/flashcards` | Get flashcard data |
| POST | `/api/flashcards/review` | Review a flashcard |
| POST | `/api/flashcards/regenerate` | Regenerate flashcard deck |

## Environment variables

All env vars live in `backend/.env`. Only `GEMINI_API_KEY` is required — the installer prompts for it on first run.

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key (required) |
| `GEMINI_MODEL_NAME` | Gemini model — `gemini-2.5-flash` (default) or `gemini-2.5-flash-lite` |
| `SPEECHMATICS_API_KEY` | Speechmatics API key (audio transcription fallback) |
| `SPEECHMATICS_TTS_API_KEY` | Speechmatics TTS key (falls back to `SPEECHMATICS_API_KEY`) |
| `NEXT_PUBLIC_API_URL` | Backend API URL (default: `http://127.0.0.1:8000/api`) |
| `BACKEND_PORT` / `FRONTEND_PORT` | Override default ports (`8000` / `3000`) |

## Tech stack

- **Backend** — FastAPI, Uvicorn, Google Gemini, Sentence-Transformers, hybrid retrieval (BM25 + cosine), ReportLab (PDF), Tesseract (OCR), Speechmatics (ASR + TTS)
- **Frontend** — Next.js 16 (App Router), React 19, TypeScript

## Troubleshooting

- **Wrapper says Python is missing** — install Python 3.10+ from your package manager (see [Quick start](#quick-start)) or https://www.python.org/downloads, then reopen your terminal.
- **Port 3000 or 8000 already in use** — the launcher picks the next free port automatically and prints it. To force specific ports, set `BACKEND_PORT` / `FRONTEND_PORT` before running `start`.
- **`GEMINI_API_KEY` warning at startup** — open `backend/.env`, paste your key from https://aistudio.google.com/app/apikey, and restart.
- **First install is slow** — that's mostly `torch` and `sentence-transformers` (~700 MB). Subsequent installs are skipped via SHA-256 caching of `requirements.txt` / `package-lock.json`.
- **Need a clean slate** — `./install.sh --clean` on macOS/Linux or `.\install.bat --clean` on Windows, then re-run the installer.

## License

MIT — see [`LICENSE`](LICENSE).
