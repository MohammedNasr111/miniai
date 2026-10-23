"""Subprocess helpers for the MiniAI app process."""

from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden_subprocess_kwargs(**extra: Any) -> dict[str, Any]:
    """Kwargs so child processes do not flash a console under pythonw.

    On Windows: CREATE_NO_WINDOW plus a STARTUPINFO with STARTF_USESHOWWINDOW /
    SW_HIDE. Any caller ``creationflags`` are bitwise-ORed in (never replaced).
    On other platforms: returns ``extra`` unchanged (or ``{}`` if none).
    """
    if sys.platform != "win32":
        return dict(extra)

    flags = int(subprocess.CREATE_NO_WINDOW)
    caller_flags = extra.pop("creationflags", 0) or 0
    flags |= int(caller_flags)

    si = extra.pop("startupinfo", None)
    if si is None:
        si = subprocess.STARTUPINFO()
    # STARTF_USESHOWWINDOW / SW_HIDE are on the subprocess module on Windows.
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE

    out: dict[str, Any] = {"creationflags": flags, "startupinfo": si}
    out.update(extra)
    return out
