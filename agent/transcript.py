"""JSON Lines log of one agent run.

One object per line, flushed after every write, so a crash mid-run
still leaves a usable log. Never records settings, environment
variables, or HTTP headers.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]


class Transcript:
    """Opened once per agent run at logs/agent_<YYYYMMDD-HHMMSS>.log."""

    def __init__(self) -> None:
        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = log_dir / f"agent_{stamp}.log"
        self._file = self.path.open("w", encoding="utf-8")
        self.rounds = 0
        self.round_cap_hit = False

    def write(self, event_type: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "type": event_type,
        }
        record.update(fields)
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def run_start(self, user_prompt: str, model: str, system_prompt: str) -> None:
        self.write(
            "run_start",
            user_prompt=user_prompt,
            model=model,
            system_prompt=system_prompt,
        )

    def llm_call(
        self,
        enable_thinking: bool,
        timeout: int,
        wall_clock_seconds: float,
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        finish_reason: Optional[str],
        content: Optional[str],
        tool_calls: Optional[list[dict[str, Any]]],
    ) -> None:
        self.write(
            "llm_call",
            enable_thinking=enable_thinking,
            timeout=timeout,
            wall_clock_seconds=wall_clock_seconds,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
            finish_reason=finish_reason,
            content=content,
            tool_calls=tool_calls,
        )

    def tool_call(
        self,
        name: str,
        args: Any,
        result: str,
        outcome: str,
        wall_clock_seconds: float,
    ) -> None:
        self.write(
            "tool_call",
            name=name,
            args=args,
            result=result,
            outcome=outcome,
            wall_clock_seconds=wall_clock_seconds,
        )

    def final(self, raw: str, shown: str) -> None:
        self.write("final", raw=raw, shown=shown)

    def run_end(
        self, wall_clock_seconds: float, rounds: int, round_cap_hit: bool
    ) -> None:
        self.write(
            "run_end",
            wall_clock_seconds=wall_clock_seconds,
            rounds=rounds,
            round_cap_hit=round_cap_hit,
        )

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
