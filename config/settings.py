"""Central configuration. Plain constants for now — no framework needed
at this stage.
"""

LEMONADE_BASE_URL = "http://localhost:13305/api/v1"
LEMONADE_MODEL = "Qwen3-14B-GGUF"
LEMONADE_TIMEOUT_SECONDS = 90  # generous: covers the ~20s cold-load seen
                               # in Stage 1 (idle-unload) plus generation
ENABLE_THINKING_DEFAULT = False  # per Stage 1 benchmarking decision
