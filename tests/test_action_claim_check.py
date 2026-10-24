"""Offline tests for action-claim honesty guard."""

from __future__ import annotations

from agent.action_claim_check import (
    apply_action_claim_correction,
    find_unbacked_claims,
    needs_action_claim_fix,
    record_tool_outcome,
    remember_intent_unsatisfied,
    reset_action_claim_state,
    user_has_remember_intent,
)


def setup_function():
    reset_action_claim_state()


def test_remember_claim_unbacked():
    claims = find_unbacked_claims("I've remembered your favourite colour.", set())
    assert any("remembered" in c["claim"] for c in claims)


def test_remember_claim_backed():
    claims = find_unbacked_claims(
        "I've remembered your favourite colour.", {"save_memory"}
    )
    assert claims == []


def test_ill_remember_unbacked():
    claims = find_unbacked_claims("I'll remember that.", set())
    assert claims


def test_delete_claim_unbacked():
    claims = find_unbacked_claims("I deleted the file.", set())
    assert any("deleted" in c["claim"] for c in claims)


def test_delete_claim_backed():
    assert find_unbacked_claims("I deleted the file.", {"delete_file"}) == []


def test_denied_delete_still_unbacked():
    reset_action_claim_state()
    assert record_tool_outcome("delete_file", "Denied by user.") == "denied"
    needs, unbacked, _ = needs_action_claim_fix(
        "I deleted the file.", "please delete it", set()
    )
    assert needs and unbacked
    shown, meta = apply_action_claim_correction(
        "I deleted the file.", "please delete it", set(), reran=True
    )
    assert meta["correction_appended"]
    assert "⚠ Correction:" in shown
    assert "didn't actually happen" in shown


def test_move_organise_rename():
    for phrase in ("I moved the files.", "I've organised the folder.", "I renamed it."):
        assert find_unbacked_claims(phrase, set())
        assert not find_unbacked_claims(phrase, {"move_file"})


def test_create_write_file_claim():
    assert find_unbacked_claims("I created the file notes.txt.", set())
    assert not find_unbacked_claims(
        "I created the file notes.txt.", {"create_file"}
    )
    assert find_unbacked_claims("I've written the document.", set())
    assert not find_unbacked_claims("I've written the document.", {"ws_write"})


def test_typed_claim():
    assert find_unbacked_claims("I typed Hello into Notepad.", set())
    assert not find_unbacked_claims(
        "I typed Hello into Notepad.", {"desktop_set_text"}
    )


def test_installed_claim():
    assert find_unbacked_claims("I installed requests.", set())
    assert not find_unbacked_claims("I installed requests.", {"install_package"})


def test_remember_intent_without_save():
    assert user_has_remember_intent("Please remember that my dog is named Rex.")
    assert remember_intent_unsatisfied(
        "Please remember that my dog is named Rex.", set()
    )
    assert not remember_intent_unsatisfied(
        "Please remember that my dog is named Rex.", {"save_memory"}
    )


def test_remember_intent_triggers_fix_even_without_claim_words():
    # Model says something vague but user asked to remember — still a gap.
    needs, _, gap = needs_action_claim_fix(
        "Got it, noted for later.",
        "Remember my wifi password is hunter2",
        set(),
    )
    assert needs and gap


def test_benign_third_person_no_claim():
    # Not first person — should not fire.
    assert find_unbacked_claims("The script deleted temporary files.", set()) == []
    assert find_unbacked_claims("Users often remember passwords.", set()) == []


def test_no_correction_when_backed():
    shown, meta = apply_action_claim_correction(
        "I've remembered it.",
        "remember this",
        {"save_memory"},
    )
    assert not meta["fired"]
    assert "⚠ Correction:" not in shown


def test_recall_intent_requires_search():
    from agent.action_claim_check import recall_intent_unsatisfied, user_has_recall_intent

    assert user_has_recall_intent("What's my favourite colour?")
    assert recall_intent_unsatisfied("What's my favourite colour?", set())
    assert not recall_intent_unsatisfied(
        "What's my favourite colour?", {"search_memory"}
    )
    # Save prompt must not be treated as recall.
    assert not user_has_recall_intent("Remember my favourite colour is teal.")


def test_file_uri_resolve():
    from tools.filesystem.fs_tools import resolve_fs_path
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("hi")
        p = Path(fh.name)
    try:
        uri = p.resolve().as_uri()
        assert resolve_fs_path(uri).resolve() == p.resolve()
        assert resolve_fs_path(str(p)).resolve() == p.resolve()
    finally:
        p.unlink(missing_ok=True)
