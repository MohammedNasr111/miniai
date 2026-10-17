"""Central configuration. Plain constants for now — no framework needed
at this stage.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

LEMONADE_BASE_URL = "http://localhost:13305/api/v1"
LEMONADE_MODEL = "Qwen3-14B-GGUF"
LEMONADE_TIMEOUT_SECONDS = 90  # generous: covers the ~20s cold-load seen
                               # in Stage 1 (idle-unload) plus generation
LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 450  # Measured up to 263 s for web_research synthesis (thinking on, ~4K
                                          # prompt tokens); Lemonade's own proxy limit is 600 s.
ENABLE_THINKING_DEFAULT = False  # per Stage 1 benchmarking decision
# on_after_tools: thinking off for first tool-selection call, on once any
# tool result is in history (current default). two_pass: every call starts
# with thinking off; if the response is a final answer (no tool calls),
# discard it and repeat with thinking on + synthesis timeout.
THINKING_POLICY = os.environ.get("MINIAI_THINKING_POLICY", "on_after_tools")
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
