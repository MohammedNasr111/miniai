"""Offline tests for code-path remember-intent and recall re-run gating."""

from __future__ import annotations

from agent.action_claim_check import (
    needs_action_claim_fix,
    note_pre_succeeded_tool,
    recall_intent_unsatisfied,
    reset_action_claim_state,
    set_auto_recall_hits,
)
from memory.intent_save import extract_remember_fact, guess_memory_category


def test_extract_remember_fact():
    assert (
        extract_remember_fact("Remember my favourite colour is teal.")
        == "my favourite colour is teal."
    )
    assert (
        extract_remember_fact("don't forget that the wifi is hunter2")
        == "the wifi is hunter2"
    )
    assert extract_remember_fact("What's my favourite colour?") is None


def test_guess_category():
    assert guess_memory_category("my favourite colour is teal") == "preference"
    assert guess_memory_category("the meeting is at 3pm") == "fact"


def test_code_save_before_answer(monkeypatch):
    calls = []

    def fake_save(content, category):
        calls.append((content, category))
        return "Saved memory #1 in category 'preference'."

    monkeypatch.setattr("tools.memory.memory_tools.save_memory", fake_save)

    from memory.intent_save import code_save_remember_intent

    out = code_save_remember_intent("Remember my favourite colour is teal.")
    assert out and out["ok"]
    assert calls == [("my favourite colour is teal.", "preference")]

    # Pre-success marks save so no re-run on happy path
    reset_action_claim_state()
    note_pre_succeeded_tool("save_memory")
    reset_action_claim_state()  # applies pre-success into succeeded
    needs, _, gap = needs_action_claim_fix(
        "Got it.",
        "Remember my favourite colour is teal.",
    )
    assert not needs and not gap


def test_recall_happy_path_no_rerun_when_injected():
    reset_action_claim_state()
    set_auto_recall_hits(2)
    assert not recall_intent_unsatisfied("What's my favourite colour?", set())
    needs, _, gap = needs_action_claim_fix(
        "Your favourite colour is teal.",
        "What's my favourite colour?",
    )
    assert not needs and not gap


def test_recall_with_no_injection_still_requires_search():
    reset_action_claim_state()
    set_auto_recall_hits(0)
    assert recall_intent_unsatisfied("What's my favourite colour?", set())
    needs, _, gap = needs_action_claim_fix(
        "I don't know.",
        "What's my favourite colour?",
        set(),
    )
    assert needs and gap
