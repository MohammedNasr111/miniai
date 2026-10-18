"""Low-integrity Python runner with Job Object limits.

Never falls back to a normal (medium-integrity) launch.
"""

from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from tools.code.paths import (
    DEFAULT_TIMEOUT_S,
    FIREWALL_RULE_NAME,
    OUTPUT_CAP,
    PROCESS_MEMORY_LIMIT,
    ensure_runner_python,
    ensure_workspace,
    runner_python,
    runner_pythonhome,
    runner_venv_dir,
    workspace_dir,
)

# --- Win32 types / constants -------------------------------------------------

HANDLE = ctypes.c_void_p
DWORD = ctypes.c_ulong
BOOL = ctypes.c_int
LPWSTR = ctypes.c_wchar_p
ULONGLONG = ctypes.c_ulonglong
SIZE_T = ctypes.c_size_t

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100
SecurityImpersonation = 2
TokenPrimary = 1
TokenIntegrityLevel = 25
SE_GROUP_INTEGRITY = 0x20

CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_SUSPENDED = 0x00000004
NORMAL_PRIORITY_CLASS = 0x00000020
STARTF_USESTDHANDLES = 0x00000100
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0
HANDLE_FLAG_INHERIT = 0x00000001
WAIT_TIMEOUT = 0x00000102
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
INVALID_HANDLE_VALUE = HANDLE(-1)

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", LPWSTR),
        ("lpDesktop", LPWSTR),
        ("lpTitle", LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ULONGLONG),
        ("WriteOperationCount", ULONGLONG),
        ("OtherOperationCount", ULONGLONG),
        ("ReadTransferCount", ULONGLONG),
        ("WriteTransferCount", ULONGLONG),
        ("OtherTransferCount", ULONGLONG),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", SIZE_T),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]


def _bind() -> None:
    kernel32.GetCurrentProcess.restype = HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.CloseHandle.restype = BOOL
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(HANDLE),
        ctypes.POINTER(HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        DWORD,
    ]
    kernel32.CreatePipe.restype = BOOL
    kernel32.SetHandleInformation.argtypes = [HANDLE, DWORD, DWORD]
    kernel32.SetHandleInformation.restype = BOOL
    kernel32.ReadFile.argtypes = [
        HANDLE,
        ctypes.c_void_p,
        DWORD,
        ctypes.POINTER(DWORD),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = BOOL
    kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
    kernel32.WaitForSingleObject.restype = DWORD
    kernel32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    kernel32.GetExitCodeProcess.restype = BOOL
    kernel32.ResumeThread.argtypes = [HANDLE]
    kernel32.ResumeThread.restype = DWORD
    kernel32.TerminateProcess.argtypes = [HANDLE, DWORD]
    kernel32.TerminateProcess.restype = BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, LPWSTR]
    kernel32.CreateJobObjectW.restype = HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        DWORD,
    ]
    kernel32.SetInformationJobObject.restype = BOOL
    kernel32.AssignProcessToJobObject.argtypes = [HANDLE, HANDLE]
    kernel32.AssignProcessToJobObject.restype = BOOL
    kernel32.TerminateJobObject.argtypes = [HANDLE, DWORD]
    kernel32.TerminateJobObject.restype = BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    advapi32.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    advapi32.OpenProcessToken.restype = BOOL
    advapi32.DuplicateTokenEx.argtypes = [
        HANDLE,
        DWORD,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(HANDLE),
    ]
    advapi32.DuplicateTokenEx.restype = BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [LPWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = DWORD
    advapi32.SetTokenInformation.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD]
    advapi32.SetTokenInformation.restype = BOOL
    advapi32.CreateProcessAsUserW.argtypes = [
        HANDLE,
        LPWSTR,
        LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        BOOL,
        DWORD,
        ctypes.c_void_p,
        LPWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessAsUserW.restype = BOOL


_bind()


class LowIntegrityLaunchError(RuntimeError):
    """Raised when the process could not be started at low integrity."""


@dataclass
class RunResult:
    exit_code: Optional[int]
    wall_time_s: float
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    script_path: str
    pid: Optional[int] = None
    memory_limited: bool = False

    def as_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "wall_time_s": round(self.wall_time_s, 3),
            "timed_out": self.timed_out,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "script_path": self.script_path,
            "pid": self.pid,
            "memory_limited": self.memory_limited,
        }


def _last_error() -> int:
    return ctypes.get_last_error()


def _close(handle: Optional[HANDLE]) -> None:
    if handle:
        kernel32.CloseHandle(handle)


def _cap(text: str, limit: int = OUTPUT_CAP) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    note = f"\n[truncated: output exceeded {limit} characters]"
    keep = max(0, limit - len(note))
    return text[:keep] + note, True


def _system_root() -> str:
    root = ctypes.create_unicode_buffer(260)
    n = kernel32.GetEnvironmentVariableW("SYSTEMROOT", root, 260)
    if n == 0:
        return r"C:\Windows"
    return root.value


def _minimal_env_block(ws: Path, exe: Path) -> ctypes.Array:
    """Build a Unicode environment block from scratch (no secrets)."""
    systemroot = _system_root()
    tmp = str(ws / "tmp")
    venv = runner_venv_dir()
    scripts = str(venv / "Scripts")
    site = str(venv / "Lib" / "site-packages")
    # Copied python.exe needs PYTHONHOME for the stdlib (base install).
    pyhome = str(runner_pythonhome())
    pairs = [
        f"SYSTEMROOT={systemroot}",
        f"WINDIR={systemroot}",
        f"TEMP={tmp}",
        f"TMP={tmp}",
        f"PATH={scripts};{exe.parent};{pyhome}",
        f"VIRTUAL_ENV={venv}",
        f"PYTHONHOME={pyhome}",
        f"PYTHONPATH={site}",
        "PYTHONNOUSERSITE=1",
        "PYTHONIOENCODING=utf-8",
        "PYTHONUNBUFFERED=1",
    ]
    blob = "\0".join(pairs) + "\0\0"
    return ctypes.create_unicode_buffer(blob)


def firewall_rule_status() -> str:
    """Return INSTALLED or NOT INSTALLED (read-only; no admin required)."""
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-NetFirewallRule -DisplayName '{FIREWALL_RULE_NAME}' "
                "-ErrorAction SilentlyContinue | "
                "Select-Object -First 1 -ExpandProperty DisplayName",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return "NOT INSTALLED"
    name = (r.stdout or "").strip()
    if name == FIREWALL_RULE_NAME:
        return "INSTALLED"
    return "NOT INSTALLED"


def _duplicate_low_token() -> HANDLE:
    h_token = HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_DUPLICATE
        | TOKEN_QUERY
        | TOKEN_ASSIGN_PRIMARY
        | TOKEN_ADJUST_DEFAULT
        | TOKEN_ADJUST_SESSIONID,
        ctypes.byref(h_token),
    ):
        raise LowIntegrityLaunchError(f"OpenProcessToken failed ({_last_error()})")
    h_new = HANDLE()
    if not advapi32.DuplicateTokenEx(
        h_token, 0, None, SecurityImpersonation, TokenPrimary, ctypes.byref(h_new)
    ):
        err = _last_error()
        _close(h_token)
        raise LowIntegrityLaunchError(f"DuplicateTokenEx failed ({err})")
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid)):
        err = _last_error()
        _close(h_new)
        _close(h_token)
        raise LowIntegrityLaunchError(f"ConvertStringSidToSidW failed ({err})")
    tml = TOKEN_MANDATORY_LABEL()
    tml.Label.Attributes = SE_GROUP_INTEGRITY
    tml.Label.Sid = sid
    size = ctypes.sizeof(TOKEN_MANDATORY_LABEL) + advapi32.GetLengthSid(sid)
    if not advapi32.SetTokenInformation(
        h_new, TokenIntegrityLevel, ctypes.byref(tml), size
    ):
        err = _last_error()
        kernel32.LocalFree(sid)
        _close(h_new)
        _close(h_token)
        raise LowIntegrityLaunchError(f"SetTokenInformation failed ({err})")
    kernel32.LocalFree(sid)
    _close(h_token)
    return h_new


def _create_job() -> HANDLE:
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise LowIntegrityLaunchError(f"CreateJobObjectW failed ({_last_error()})")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    info.BasicLimitInformation.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = PROCESS_MEMORY_LIMIT
    if not kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        err = _last_error()
        _close(job)
        raise LowIntegrityLaunchError(f"SetInformationJobObject failed ({err})")
    return job


def _read_pipe(handle: HANDLE, sink: list[bytes], store_cap: int = OUTPUT_CAP * 2) -> None:
    """Blocking reader for a pipe; stores up to store_cap, then discards to EOF.

    Must keep draining after the store cap so a large print cannot fill the
    pipe buffer and deadlock the child against WaitForSingleObject.
    """
    buf = ctypes.create_string_buffer(8192)
    read = DWORD()
    stored = 0
    while True:
        ok = kernel32.ReadFile(handle, buf, 8192, ctypes.byref(read), None)
        if not ok or read.value == 0:
            break
        if stored < store_cap:
            chunk = buf.raw[: read.value]
            room = store_cap - stored
            sink.append(chunk[:room])
            stored += min(len(chunk), room)
        # else discard


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = DWORD()
    kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    _close(h)
    # STILL_ACTIVE = 259
    return code.value == 259


# OpenProcess binding
kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HANDLE
kernel32.GetEnvironmentVariableW.argtypes = [LPWSTR, LPWSTR, DWORD]
kernel32.GetEnvironmentVariableW.restype = DWORD


def launch_low_integrity(
    exe: Path,
    argv: list[str],
    cwd: Path,
    env_block: ctypes.Array,
    job: HANDLE,
) -> tuple[PROCESS_INFORMATION, HANDLE, HANDLE]:
    """CreateProcessAsUser at low IL, suspended, assigned to job, then resumed.

    Returns (pi, stdout_read, stderr_read). Raises LowIntegrityLaunchError;
    never falls back to a normal CreateProcess.
    """
    h_token = _duplicate_low_token()
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.bInheritHandle = True

    out_r, out_w = HANDLE(), HANDLE()
    err_r, err_w = HANDLE(), HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), ctypes.byref(sa), 0):
        _close(h_token)
        raise LowIntegrityLaunchError(f"CreatePipe stdout failed ({_last_error()})")
    if not kernel32.CreatePipe(ctypes.byref(err_r), ctypes.byref(err_w), ctypes.byref(sa), 0):
        _close(out_r)
        _close(out_w)
        _close(h_token)
        raise LowIntegrityLaunchError(f"CreatePipe stderr failed ({_last_error()})")
    # Parent ends must not be inherited.
    kernel32.SetHandleInformation(out_r, HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(err_r, HANDLE_FLAG_INHERIT, 0)

    # NUL stdin so the child has a valid handle under STARTF_USESTDHANDLES.
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    kernel32.CreateFileW.argtypes = [
        LPWSTR, DWORD, DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES), DWORD, DWORD, HANDLE
    ]
    kernel32.CreateFileW.restype = HANDLE
    nul_sa = SECURITY_ATTRIBUTES()
    nul_sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    nul_sa.bInheritHandle = True
    h_nul = kernel32.CreateFileW(
        "NUL", GENERIC_READ, FILE_SHARE_READ, ctypes.byref(nul_sa),
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )
    if not h_nul or h_nul == INVALID_HANDLE_VALUE:
        _close(out_r)
        _close(out_w)
        _close(err_r)
        _close(err_w)
        _close(h_token)
        raise LowIntegrityLaunchError(f"CreateFileW(NUL) failed ({_last_error()})")

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
    si.wShowWindow = SW_HIDE
    si.hStdInput = h_nul
    si.hStdOutput = out_w
    si.hStdError = err_w
    pi = PROCESS_INFORMATION()

    # Quote argv like CreateProcess expects a single command line.
    parts = [f'"{exe}"'] + [f'"{a}"' if " " in a else a for a in argv]
    cmdline = ctypes.create_unicode_buffer(" ".join(parts))

    ok = advapi32.CreateProcessAsUserW(
        h_token,
        str(exe),
        cmdline,
        None,
        None,
        True,  # inherit handles (pipes)
        CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED | NORMAL_PRIORITY_CLASS,
        ctypes.cast(env_block, ctypes.c_void_p),
        str(cwd),
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    # Close write ends / NUL in parent so ReadFile sees EOF when child exits.
    _close(out_w)
    _close(err_w)
    _close(h_nul)
    _close(h_token)
    if not ok:
        err = _last_error()
        _close(out_r)
        _close(err_r)
        raise LowIntegrityLaunchError(f"CreateProcessAsUserW failed ({err})")

    if not kernel32.AssignProcessToJobObject(job, pi.hProcess):
        err = _last_error()
        kernel32.TerminateProcess(pi.hProcess, 1)
        _close(pi.hThread)
        _close(pi.hProcess)
        _close(out_r)
        _close(err_r)
        raise LowIntegrityLaunchError(f"AssignProcessToJobObject failed ({err})")

    if kernel32.ResumeThread(pi.hThread) == 0xFFFFFFFF:
        err = _last_error()
        kernel32.TerminateJobObject(job, 1)
        _close(pi.hThread)
        _close(pi.hProcess)
        _close(out_r)
        _close(err_r)
        raise LowIntegrityLaunchError(f"ResumeThread failed ({err})")

    return pi, out_r, err_r


def run_python(code: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> RunResult:
    """Write code to the workspace and run it at low integrity under a job."""
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    ws = ensure_workspace()
    py = ensure_runner_python()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    script = ws / f"run_{stamp}.py"
    script.write_text(code, encoding="utf-8")

    env_block = _minimal_env_block(ws, py)
    job = _create_job()
    started = time.perf_counter()
    timed_out = False
    memory_limited = False
    exit_code: Optional[int] = None
    pid: Optional[int] = None
    stdout_s = ""
    stderr_s = ""

    try:
        pi, out_r, err_r = launch_low_integrity(
            py, ["-u", str(script)], ws, env_block, job
        )
        pid = int(pi.dwProcessId)
        # Drain pipes on background threads so a large print cannot fill the
        # pipe buffer and deadlock against WaitForSingleObject.
        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []
        t_out = threading.Thread(
            target=_read_pipe, args=(out_r, out_chunks), daemon=True
        )
        t_err = threading.Thread(
            target=_read_pipe, args=(err_r, err_chunks), daemon=True
        )
        t_out.start()
        t_err.start()

        timeout_ms = int(timeout_s * 1000)
        wait = kernel32.WaitForSingleObject(pi.hProcess, timeout_ms)
        if wait == WAIT_TIMEOUT:
            timed_out = True
            kernel32.TerminateJobObject(job, 1)
            kernel32.WaitForSingleObject(pi.hProcess, 5000)
        code_dw = DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code_dw))
        exit_code = int(code_dw.value)
        # STILL_ACTIVE after terminate is rare; normalize.
        if exit_code == 259:
            exit_code = 1

        # Closing our read handles unblocks the reader threads on EOF/error.
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        _close(out_r)
        _close(err_r)
        _close(pi.hThread)
        _close(pi.hProcess)

        stdout_s = b"".join(out_chunks).decode("utf-8", errors="replace")
        stderr_s = b"".join(err_chunks).decode("utf-8", errors="replace")
        combined_lower = (stdout_s + stderr_s).lower()
        if "memoryerror" in combined_lower:
            memory_limited = True
        # Job memory kill often yields STATUS_QUOTA_EXCEEDED-ish or abrupt death
        # with empty output while allocating; treat non-zero + OOM keywords.
        if exit_code not in (0, None) and not timed_out:
            if any(
                k in combined_lower
                for k in ("memoryerror", "out of memory", "quota", "paging file")
            ):
                memory_limited = True
    finally:
        _close(job)

    wall = time.perf_counter() - started
    stdout_s, out_trunc = _cap(stdout_s)
    stderr_s, err_trunc = _cap(stderr_s)

    # Confirm process is gone after timeout.
    if timed_out and pid is not None:
        # Brief retry for process exit.
        for _ in range(20):
            if not _process_alive(pid):
                break
            time.sleep(0.05)

    return RunResult(
        exit_code=exit_code,
        wall_time_s=wall,
        timed_out=timed_out,
        stdout=stdout_s,
        stderr=stderr_s,
        stdout_truncated=out_trunc,
        stderr_truncated=err_trunc,
        script_path=str(script),
        pid=pid,
        memory_limited=memory_limited,
    )


def format_run_result(result: RunResult) -> str:
    """Human/model-readable summary of a run."""
    lines = [
        f"exit_code: {result.exit_code}",
        f"wall_time_s: {result.wall_time_s:.3f}",
        f"timed_out: {result.timed_out}",
        f"script: {result.script_path}",
    ]
    if result.memory_limited:
        lines.append("memory_limited: true")
    if result.stdout_truncated:
        lines.append("stdout: [truncated]")
    lines.append("--- stdout ---")
    lines.append(result.stdout if result.stdout else "(empty)")
    lines.append("--- stderr ---")
    lines.append(result.stderr if result.stderr else "(empty)")
    return "\n".join(lines)
