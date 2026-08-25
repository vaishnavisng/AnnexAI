import os


def _env_search_paths() -> tuple[str, ...]:
    config_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(config_dir)
    project_root = os.path.dirname(app_dir)
    return (
        os.path.join(project_root, ".env"),
        os.path.join(config_dir, ".env"),
    )


def _load_dotenv_if_exists() -> None:
    """
    Load key=value pairs from a local .env file into os.environ if present.
    Existing environment variables are not overwritten.
    """
    for env_path in _env_search_paths():
        if not os.path.exists(env_path):
            continue

        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key:
                        os.environ.setdefault(key, value)
            return
        except Exception:
            return


_load_dotenv_if_exists()

# Base folders
# Assuming settings.py is in app/config/
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(CONFIG_DIR)
PROJECT_ROOT = os.path.dirname(APP_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
TRANSCRIPT_DIR = os.path.join(DATA_DIR, "transcripts")
INDEX_DIR = os.path.join(DATA_DIR, "indexes")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
SUMMARY_DIR = os.path.join(DATA_DIR, "summaries")
QUIZ_DIR = os.path.join(DATA_DIR, "quizzes")
LECTURE_META_DIR = os.path.join(DATA_DIR, "lectures")
FRAME_DIR = os.path.join(DATA_DIR, "frames")
FLASHCARD_DIR = os.path.join(DATA_DIR, "flashcards")
REVIEW_DIR = os.path.join(DATA_DIR, "reviews")
QUIZ_ATTEMPT_DIR = os.path.join(DATA_DIR, "quiz_attempts")
COACHING_DIR = os.path.join(DATA_DIR, "coaching")

for d in (
    DATA_DIR,
    TRANSCRIPT_DIR,
    INDEX_DIR,
    UPLOAD_DIR,
    AUDIO_DIR,
    PDF_DIR,
    SUMMARY_DIR,
    QUIZ_DIR,
    LECTURE_META_DIR,
    FRAME_DIR,
    FLASHCARD_DIR,
    REVIEW_DIR,
    QUIZ_ATTEMPT_DIR,
    COACHING_DIR,
):
    os.makedirs(d, exist_ok=True)

# Embedding model for semantic search
# (Good quality + reasonably fast on CPU)
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# You could also try "BAAI/bge-small-en-v1.5" if you want better retrieval
# and are okay with a larger download.

# Gemini model configuration
# Supported models the user can switch between at runtime from the UI.
GEMINI_MODEL_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "description": "Balanced speed and reasoning quality.",
    },
    {
        "id": "gemini-2.5-flash-lite",
        "label": "Gemini 2.5 Flash Lite",
        "description": "Faster and lighter — best for quick, cheap tasks.",
    },
)
GEMINI_ALLOWED_MODELS: frozenset[str] = frozenset(
    option["id"] for option in GEMINI_MODEL_OPTIONS
)
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", GEMINI_DEFAULT_MODEL)
if GEMINI_MODEL_NAME not in GEMINI_ALLOWED_MODELS:
    GEMINI_MODEL_NAME = GEMINI_DEFAULT_MODEL
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Comma-separated browser origins allowed to call the API.
_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
CORS_ORIGINS = tuple(origin.strip() for origin in _cors_origins.split(",") if origin.strip())

# Approx words per merged caption chunk
MAX_CHUNK_WORDS = 120

# Hybrid retrieval: weight between semantic (cosine) and lexical (BM25)
# 1.0 = only embeddings, 0.0 = only BM25
HYBRID_ALPHA = 0.65

# Retrieval hyperparameters
RETRIEVAL_CANDIDATES = 40   # initial pool size from hybrid ranking
RETRIEVAL_TOPK = 5          # number of chunks we pass to the LLM
NEIGHBOR_WINDOW = 1         # neighbor chunks around each chosen one

# Upload settings
MAX_UPLOAD_MB = 500
MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {"mp4", "mkv", "avi", "mov"}

# OCR / frame analysis settings
OCR_FRAME_SAMPLE_SECONDS = 30
OCR_MAX_FRAMES = 30
OCR_MIN_TEXT_CHARS = 24
OCR_MAX_WORDS_PER_FRAME = 80
OCR_MIN_CONFIDENCE = 45.0
OCR_WORKERS = 4

# Speechmatics settings
SPEECHMATICS_API_KEY = os.getenv("SPEECHMATICS_API_KEY", "")
SPEECHMATICS_API_URL = os.getenv("SPEECHMATICS_API_URL", "https://asr.api.speechmatics.com/v2")

# Speechmatics Text-to-Speech (preview) settings
SPEECHMATICS_TTS_API_KEY = os.getenv(
    "SPEECHMATICS_TTS_API_KEY", os.getenv("SPEECHMATICS_API_KEY", "")
)
SPEECHMATICS_TTS_URL = os.getenv(
    "SPEECHMATICS_TTS_URL", "https://preview.tts.speechmatics.com/generate"
)
SPEECHMATICS_TTS_DEFAULT_VOICE = os.getenv("SPEECHMATICS_TTS_DEFAULT_VOICE", "jack")
SPEECHMATICS_TTS_ALLOWED_VOICES = frozenset({"sarah", "theo", "megan", "jack"})
SPEECHMATICS_TTS_MAX_CHARS = 4000

# Learning assets defaults
SUMMARY_MAX_WORDS = 800
QUIZ_NUM_QUESTIONS = 10
FLASHCARD_NUM_CARDS = 12
SUMMARY_CHUNK_BATCH_SIZE = 45
LLM_MAX_PARALLEL_REQUESTS = 1
LLM_RETRY_ATTEMPTS = 5
LLM_RETRY_BASE_DELAY = 2.0
LLM_MIN_REQUEST_INTERVAL = 1.5
LLM_POST_PARTIALS_DELAY = 1.0

# Automatic model fallback: when the active Gemini model fails with a
# rate-limit / quota / transient error after all retries, try the next model
# in the fallback chain (see GEMINI_MODEL_OPTIONS ordering).
LLM_ENABLE_FALLBACK = True
