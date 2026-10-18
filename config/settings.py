"""Central configuration. Plain constants for now — no framework needed
at this stage.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

LEMONADE_BASE_URL = "http://localhost:13305/api/v1"
# Default: Qwen3-30B-A3B-GGUF. Override with MINIAI_MODEL (e.g. Qwen3-14B-GGUF).
LEMONADE_MODEL = os.environ.get("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
# Approximate RAM the loaded default model needs (for the low-memory warning).
MODEL_NEEDED_RAM_GB = 18
LEMONADE_TIMEOUT_SECONDS = 90  # generous: covers the ~20s cold-load seen
                               # in Stage 1 (idle-unload) plus generation
LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 450  # Measured up to 263 s for web_research synthesis (thinking on, ~4K
                                          # prompt tokens); Lemonade's own proxy limit is 600 s.
ENABLE_THINKING_DEFAULT = False  # per Stage 1 benchmarking decision
# two_pass (default): every call starts with thinking off; if the response
# is a final answer (no tool calls), discard it and repeat with thinking on
# + synthesis timeout. on_after_tools: thinking off until a tool result is
# in history, then on (previous default; still available via env).
THINKING_POLICY = os.environ.get("MINIAI_THINKING_POLICY", "two_pass")
EMBEDDING_MODEL = "nomic-embed-text-v1-GGUF"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")  # may be None; never print or log this

# Store paths: overridable for tests via MINIAI_MEMORY_DB / MINIAI_VECTOR_DB.
# Defaults are the production locations under the project tree.
MEMORY_DB_PATH = Path(
    os.environ.get(
        "MINIAI_MEMORY_DB",
        str(_PROJECT_ROOT / "memory" / "database" / "miniai_memory.db"),
    )
)
VECTOR_DB_PATH = Path(
    os.environ.get(
        "MINIAI_VECTOR_DB",
        str(_PROJECT_ROOT / "memory" / "vector" / "lancedb"),
    )
)
