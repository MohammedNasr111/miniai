"""Duplicate-call guard checks. No LLM and no real filesystem writes.

Stubs replace read_file and write_file. check_permission is wrapped so
each test counts whether the gate was actually reached.
"""

import json
import sys

import security.gate as gate
from agent.executor.executor import execute_tool_calls
from agent.executor.guard import CallGuard
from security.gate import PermissionDenied, Tier
from tools.registry import TOOL_FUNCTIONS

FAILURES = 0
GATE_HITS = {"n": 0}
_REAL_GATE = gate.check_permission
_SAVED_TOOLS = {
    "read_file": TOOL_FUNCTIONS["read_file"],
    "write_file": TOOL_FUNCTIONS["write_file"],
}


def _counting_gate(action: str, tier: Tier, description: str) -> None:
    GATE_HITS["n"] += 1


def _install(deny_write: bool = False) -> None:
    GATE_HITS["n"] = 0
    gate.check_permission = _counting_gate

    def read_file(**kwargs):
        from security.gate import check_permission

        check_permission("read_file", Tier.AUTO_ALLOW, "stub read")
        return f"read {kwargs}"

    def write_file(**kwargs):
        from security.gate import check_permission

        check_permission("write_file", Tier.CONFIRM, "stub write")
        if deny_write:
            raise PermissionDenied("User denied: write_file")
        return f"wrote {kwargs}"

    TOOL_FUNCTIONS["read_file"] = read_file
    TOOL_FUNCTIONS["write_file"] = write_file


def _restore() -> None:
    TOOL_FUNCTIONS["read_file"] = _SAVED_TOOLS["read_file"]
    TOOL_FUNCTIONS["write_file"] = _SAVED_TOOLS["write_file"]
    gate.check_permission = _REAL_GATE
    GATE_HITS["n"] = 0


def _call(call_id: str, name: str, arguments) -> dict:
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    print(f"{status}: {name} - {detail}")


def _linked(calls: list[dict], messages) -> bool:
    if len(messages) != len(calls):
        return False
    return all(
        m.role == "tool" and m.tool_call_id == c["id"]
        for m, c in zip(messages, calls)
    )


def test_a() -> None:
    _install()
    try:
        guard = CallGuard()
        first = [_call("a1", "write_file", {"path": "x", "content": "y"})]
        second = [_call("a2", "write_file", {"path": "x", "content": "y"})]
        r1 = execute_tool_calls(first, guard)
        r2 = execute_tool_calls(second, guard)
        ok = (
            GATE_HITS["n"] == 1
            and "Blocked duplicate call" in r2[0].content
            and "Blocked duplicate call" not in r1[0].content
            and _linked(first, r1)
            and _linked(second, r2)
        )
        _check(
            "a",
            ok,
            f"gate={GATE_HITS['n']} (want 1); 2nd blocked={('Blocked duplicate call' in r2[0].content)}",
        )
    finally:
        _restore()


def test_b() -> None:
    _install(deny_write=True)
    try:
        guard = CallGuard()
        first = [_call("b1", "write_file", {"path": "x", "content": "y"})]
        second = [_call("b2", "write_file", {"path": "x", "content": "y"})]
        r1 = execute_tool_calls(first, guard)
        r2 = execute_tool_calls(second, guard)
        ok = (
            GATE_HITS["n"] == 1
            and r1[0].content.startswith("Denied by user:")
            and "Blocked duplicate call" in r2[0].content
            and _linked(first, r1)
            and _linked(second, r2)
        )
        _check(
            "b",
            ok,
            f"gate={GATE_HITS['n']} (want 1); denied then blocked",
        )
    finally:
        _restore()


def test_c() -> None:
    _install()
    try:
        guard = CallGuard()
        first = [_call("c1", "read_file", {"path": "X"})]
        second = [_call("c2", "read_file", {"path": "X"})]
        r1 = execute_tool_calls(first, guard)
        r2 = execute_tool_calls(second, guard)
        ok = (
            GATE_HITS["n"] == 1
            and "Blocked duplicate call" not in r1[0].content
            and "Blocked duplicate call" in r2[0].content
            and _linked(first, r1)
            and _linked(second, r2)
        )
        _check("c", ok, f"gate={GATE_HITS['n']} (want 1); 2nd read blocked")
    finally:
        _restore()


def test_d() -> None:
    _install()
    try:
        guard = CallGuard()
        read1 = [_call("d1", "read_file", {"path": "X"})]
        write = [_call("d2", "write_file", {"path": "Y", "content": "z"})]
        read2 = [_call("d3", "read_file", {"path": "X"})]
        r1 = execute_tool_calls(read1, guard)
        r2 = execute_tool_calls(write, guard)
        r3 = execute_tool_calls(read2, guard)
        ok = (
            GATE_HITS["n"] == 3
            and "Blocked duplicate call" not in r3[0].content
            and r3[0].content.startswith("read ")
            and _linked(read1, r1)
            and _linked(write, r2)
            and _linked(read2, r3)
        )
        _check("d", ok, f"gate={GATE_HITS['n']} (want 3); 3rd read allowed after write")
    finally:
        _restore()


def test_e() -> None:
    _install()
    try:
        guard = CallGuard()
        calls = [
            _call("e1", "read_file", {"path": "X"}),
            _call("e2", "read_file", {"path": "Z"}),
        ]
        # Separate rounds, same as the model retrying with different args.
        r1 = execute_tool_calls([calls[0]], guard)
        r2 = execute_tool_calls([calls[1]], guard)
        ok = (
            GATE_HITS["n"] == 2
            and "Blocked duplicate call" not in r1[0].content
            and "Blocked duplicate call" not in r2[0].content
            and _linked([calls[0]], r1)
            and _linked([calls[1]], r2)
        )
        _check("e", ok, f"gate={GATE_HITS['n']} (want 2); different args both allowed")
    finally:
        _restore()


def test_f() -> None:
    _install()
    try:
        guard = CallGuard()
        calls = [
            _call("f1", "write_file", {"path": "x", "content": "y"}),
            _call("f2", "write_file", {"path": "x", "content": "y"}),
        ]
        results = execute_tool_calls(calls, guard)
        ok = (
            GATE_HITS["n"] == 1
            and "Blocked duplicate call" not in results[0].content
            and "Blocked duplicate call" in results[1].content
            and _linked(calls, results)
        )
        _check("f", ok, f"gate={GATE_HITS['n']} (want 1); 2nd of the pair blocked")
    finally:
        _restore()


def test_h() -> None:
    _install()
    try:
        guard = CallGuard()
        calls = [
            _call("h1", "write_file", '{"a": 1, "b": 2}'),
            _call("h2", "write_file", '{"b": 2, "a": 1}'),
        ]
        results = execute_tool_calls(calls, guard)
        ok = (
            GATE_HITS["n"] == 1
            and "Blocked duplicate call" not in results[0].content
            and "Blocked duplicate call" in results[1].content
            and _linked(calls, results)
        )
        _check("h", ok, f"gate={GATE_HITS['n']} (want 1); key order is the same fingerprint")
    finally:
        _restore()


def test_i() -> None:
    _install()
    try:
        calls = [
            _call("i1", "write_file", {"path": "x", "content": "y"}),
            _call("i2", "write_file", {"path": "x", "content": "y"}),
        ]
        results = execute_tool_calls(calls, guard=None)
        ok = (
            GATE_HITS["n"] == 2
            and all("Blocked duplicate call" not in m.content for m in results)
            and all(m.content.startswith("wrote ") for m in results)
            and _linked(calls, results)
        )
        _check("i", ok, f"gate={GATE_HITS['n']} (want 2); guard=None does not block")
    finally:
        _restore()


def main() -> None:
    test_a()
    test_b()
    test_c()
    test_d()
    test_e()
    test_f()
    test_h()
    test_i()
    if FAILURES:
        print(f"\n{FAILURES} check(s) failed.")
        sys.exit(1)
    print("\nAll call-guard checks passed.")


if __name__ == "__main__":
    main()
