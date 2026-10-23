"""Offline tests for the safe calculator tool."""

from __future__ import annotations

from tests.support import use_temp_data

use_temp_data()

from tools.calculate import CalcError, calculate, safe_calculate

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _rejects(name: str, expr: str) -> None:
    try:
        safe_calculate(expr)
        _check(name, False, "did not raise")
    except CalcError as exc:
        _check(name, True, str(exc)[:120])


def main() -> None:
    pct = safe_calculate("17% of 2350")
    _check("pct_of", abs(float(pct) - 399.5) < 1e-9, str(pct))
    _check("basic", safe_calculate("(3+4)*2") == 14, "")
    _check("floor", safe_calculate("7//2") == 3, "")
    _check("pow_ok", safe_calculate("2**10") == 1024, "")
    _check("round", safe_calculate("round(3.14159, 2)") == 3.14, "")
    _check("abs_min_max", safe_calculate("max(1, abs(-9), min(3, 8))") == 9, "")
    _check("tool_str", calculate("1+2") == "3", calculate("1+2"))

    _rejects("import", "__import__('os')")
    _rejects("attr", "(1).bit_length()")
    _rejects("name", "os.system('x')")
    _rejects("huge_pow", "9**9**9")
    _rejects("long", "1+" * 120 + "1")
    _rejects("lambda", "(lambda x: x)(1)")
    _rejects("string", "'hi'+'there'")

    # Tool wrapper returns Error: for CalcError
    out = calculate("__import__('os')")
    _check("tool_error", out.startswith("Error:"), out)

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
