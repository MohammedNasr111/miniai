"""Round 12 Part 5 — skip load probe when /health already shows model ready."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self) -> dict[str, Any]:
        return {}


class _FakeHealthResp:
    def __init__(self, payload: dict[str, Any]):
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


READY_HEALTH = {
    "all_models_loaded": [
        {
            "type": "llm",
            "model_name": "Qwen3-30B-A3B-GGUF",
            "backend_alive": True,
            "backend_health": "ready",
            "loaded": True,
        }
    ]
}


def test_skip_when_health_ready() -> None:
    from eval.run import wait_for_target_model

    posts: list[Any] = []

    def fake_post(url, json=None, timeout=180, **kwargs):
        posts.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResp(500, "should not be called")

    def fake_get(url, timeout=5, **kwargs):
        return _FakeHealthResp(READY_HEALTH)

    wait_for_target_model(
        "Qwen3-30B-A3B-GGUF",
        timeout_s=3.0,
        post_fn=fake_post,
        get_fn=fake_get,
        base_url="http://localhost:9/api/v1",
    )
    _check(
        "skip_when_health_ready",
        posts == [],
        f"posts={posts}",
    )


def test_http_timeout_is_180() -> None:
    from eval.run import wait_for_target_model

    timeouts: list[float] = []

    def fake_post(url, json=None, timeout=90, **kwargs):
        timeouts.append(timeout)
        return _FakeResp(500, "model_load_error")

    def fake_get(url, timeout=5, **kwargs):
        return _FakeHealthResp({"all_models_loaded": []})

    t = {"n": 0.0}

    def fake_time():
        t["n"] += 1.0
        return t["n"]

    with mock.patch("time.sleep", return_value=None), mock.patch(
        "time.time", side_effect=fake_time
    ):
        try:
            wait_for_target_model(
                "OnlyTarget",
                timeout_s=3.0,
                post_fn=fake_post,
                get_fn=fake_get,
                base_url="http://localhost:9/api/v1",
            )
            raised = False
            err = ""
        except RuntimeError as exc:
            raised = True
            err = str(exc)

    ok = (
        raised
        and "failed to load" in err
        and "free_ram_gb=" in err
        and timeouts
        and all(x == 180 for x in timeouts)
    )
    _check(
        "http_timeout_is_180",
        ok,
        f"raised={raised} timeouts={timeouts} err={err!r}",
    )


def test_ready_helper() -> None:
    from eval.run import _target_model_ready_in_health

    ok = _target_model_ready_in_health("Qwen3-30B-A3B-GGUF", READY_HEALTH)
    bad = _target_model_ready_in_health(
        "Qwen3-30B-A3B-GGUF",
        {
            "all_models_loaded": [
                {
                    "type": "llm",
                    "model_name": "Other-Model",
                    "backend_alive": True,
                    "backend_health": "ready",
                }
            ]
        },
    )
    _check("ready_helper", ok and not bad, f"ok={ok} bad={bad}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_ready_helper()
    test_skip_when_health_ready()
    test_http_timeout_is_180()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
