"""Deprecated data-carrying URL tests — superseded by test_url_provenance.

Kept as a thin redirect so older docs still run a check.
"""

from __future__ import annotations

import runpy
import sys


def main() -> None:
    sys.argv = ["scripts.test_url_provenance"]
    runpy.run_module("scripts.test_url_provenance", run_name="__main__")


if __name__ == "__main__":
    main()
