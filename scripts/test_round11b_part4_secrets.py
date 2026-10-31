"""Round 11B Part 4 — eval sees real Groq DPAPI key under redirected LOCALAPPDATA."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> int:
    # Clear any test override so we exercise the real-path pointer.
    os.environ.pop("MINIAI_GROQ_SECRETS_DIR", None)

    from config.paths import real_local_appdata
    from security.groq_key import has_key, key_path, load_key, secrets_dir
    from tests.support import use_temp_data

    real_secrets = real_local_appdata() / "MiniAI" / "secrets"
    real_bin = real_secrets / "groq.bin"
    _check(
        "real_groq_bin_exists",
        real_bin.is_file() and real_bin.stat().st_size > 0,
        f"path_ok={real_bin.is_file()}",
    )

    temp_root = use_temp_data()
    redirected = Path(os.environ["LOCALAPPDATA"])
    _check(
        "localappdata_redirected",
        str(temp_root) in str(redirected) or redirected != real_local_appdata(),
        f"LOCALAPPDATA={redirected}",
    )
    # Must not point at the redirected temp tree.
    sd = secrets_dir()
    _check(
        "secrets_dir_is_real",
        sd.resolve() == real_secrets.resolve(),
        f"secrets_dir={sd}",
    )
    _check(
        "key_path_is_real",
        key_path().resolve() == real_bin.resolve(),
        f"key_path={key_path()}",
    )
    _check("has_key_True", has_key() is True, f"has_key={has_key()}")

    # Decrypt for Test only — never print/log the value.
    key = load_key()
    _check("load_key_nonempty", isinstance(key, str) and len(key) > 0, f"len={len(key) if key else 0}")
    if key:
        from llm.groq.provider import GroqProvider

        prov = GroqProvider(api_key=key)
        # Drop local reference immediately after construct.
        del key
        result = prov.test_key()
        status = str(result.get("status") or "")
        blob = repr(result)
        _check(
            "test_connected",
            result.get("ok") is True and "Test OK" in status,
            f"status={status!r} ok={result.get('ok')}",
        )
        _check(
            "no_key_in_test_result",
            "gsk_" not in blob,
            "result redacted",
        )
        print("connected", flush=True)

    print(f"FAILURES={len(FAILURES)}")
    for f in FAILURES:
        print(f"  - {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
