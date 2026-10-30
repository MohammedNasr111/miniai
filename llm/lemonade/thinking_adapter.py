"""Per-model thinking / sampling adapters for Lemonade chat completions.

Round 10 Part 1: Qwen3.6 uses chat_template_kwargs.enable_thinking;
Nemotron 3.5 Lightning uses the same kwargs (template default enable_thinking=True).
Sampling values follow each model's published recommendations.
"""

from __future__ import annotations

from typing import Any


def _model_family(model: str) -> str:
    name = (model or "").lower()
    if "nemotron" in name and "lightning" in name:
        return "nemotron_lightning"
    if "qwen3.6" in name or "qwen3-6" in name:
        return "qwen36"
    if "qwen3" in name:
        return "qwen3"
    return "default"


def thinking_template_kwargs(model: str, enable_thinking: bool) -> dict[str, Any]:
    """chat_template_kwargs for this model. All current candidates use enable_thinking."""
    family = _model_family(model)
    kwargs: dict[str, Any] = {"enable_thinking": bool(enable_thinking)}
    if family == "nemotron_lightning":
        # Truncate prior-turn thinking unless we opt into preserve later.
        kwargs.setdefault("truncate_history_thinking", True)
    return kwargs


def sampling_for_model(model: str, *, enable_thinking: bool) -> dict[str, Any]:
    """Recommended sampling params for the model family and thinking mode.

    Only keys Lemonade / llama-server commonly accept on chat/completions.
    Callers merge these under the payload; explicit kwargs from the caller win.
    """
    family = _model_family(model)
    if family == "qwen36":
        if enable_thinking:
            # Qwen3.6-35B-A3B thinking (general tasks).
            return {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 20,
                "presence_penalty": 1.5,
                "repetition_penalty": 1.0,
            }
        # Instruct / non-thinking (general).
        return {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "presence_penalty": 1.5,
            "repetition_penalty": 1.0,
        }
    if family == "nemotron_lightning":
        # generation_config.json: temperature 1.0, top_p 0.95, do_sample true.
        return {
            "temperature": 1.0,
            "top_p": 0.95,
        }
    # Control Qwen3-30B and others: leave server/model defaults (no override).
    return {}


def apply_model_adapter(
    payload: dict[str, Any],
    *,
    model: str,
    enable_thinking: bool,
) -> dict[str, Any]:
    """Mutate payload with template kwargs + sampling; caller kwargs already merged win."""
    tmpl = thinking_template_kwargs(model, enable_thinking)
    existing = payload.get("chat_template_kwargs")
    if isinstance(existing, dict):
        merged = dict(tmpl)
        merged.update(existing)
        payload["chat_template_kwargs"] = merged
    else:
        payload["chat_template_kwargs"] = tmpl
    for key, value in sampling_for_model(model, enable_thinking=enable_thinking).items():
        payload.setdefault(key, value)
    return payload
