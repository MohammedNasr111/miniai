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
# Thinking policy for agent/chat model calls:
#   smart (default after QA Round 2 rule): first pass thinking-off; second
#     thinking-on pass only when the turn used an evidence tool OR no tools
#     and the question looks analytical. Round 2: 44/60 vs two_pass 47/60
#     (≥ −3), safety safe 100%, mean wall ~40% lower → keep smart.
#   two_pass: always re-answer with thinking on after a thinking-off final.
#   on_after_tools: thinking on once any tool result is in history.
_THINKING_RAW = os.environ.get("MINIAI_THINKING_POLICY", "smart").strip().lower()
THINKING_POLICY = (
    _THINKING_RAW
    if _THINKING_RAW in ("smart", "two_pass", "on_after_tools")
    else "smart"
)
# Stage 12a answer checker: draft -> check -> fix. Default off until measured.
_CHECKER_RAW = os.environ.get("MINIAI_CHECKER", "off").strip().lower()
CHECKER = _CHECKER_RAW if _CHECKER_RAW in ("off", "on") else "off"
# Round 6b Part 3 attribution (see ROUND_6B_REPORT.md): keep CODING_AUTO_TEST
# and RESEARCH_PIPELINE; leave ANALYZE_TABLE and PDF_CITATIONS off.
FEATURE_ANALYZE_TABLE = os.environ.get("MINIAI_FEATURE_ANALYZE_TABLE", "off").strip().lower() not in (
    "0",
    "off",
    "false",
    "no",
)
FEATURE_CODING_AUTO_TEST = os.environ.get("MINIAI_FEATURE_CODING_AUTO_TEST", "on").strip().lower() not in (
    "0",
    "off",
    "false",
    "no",
)
FEATURE_RESEARCH_PIPELINE = os.environ.get("MINIAI_FEATURE_RESEARCH_PIPELINE", "on").strip().lower() not in (
    "0",
    "off",
    "false",
    "no",
)
FEATURE_PDF_CITATIONS = os.environ.get("MINIAI_FEATURE_PDF_CITATIONS", "off").strip().lower() not in (
    "0",
    "off",
    "false",
    "no",
)
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
