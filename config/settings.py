"""Central configuration. Plain constants for now — no framework needed
at this stage.
"""

LEMONADE_BASE_URL = "http://localhost:13305/api/v1"
LEMONADE_MODEL = "Qwen3-14B-GGUF"
LEMONADE_TIMEOUT_SECONDS = 90  # generous: covers the ~20s cold-load seen
                               # in Stage 1 (idle-unload) plus generation
LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 300  # thinking-on synthesis calls measured
                                          # 98s warm at ~4 tok/s; 90s is not
                                          # enough once reasoning is enabled
ENABLE_THINKING_DEFAULT = False  # per Stage 1 benchmarking decision
EMBEDDING_MODEL = "nomic-embed-text-v1-GGUF"
