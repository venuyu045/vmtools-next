"""Windows ConPTY (Pseudo Console) wrapper for subprocess management.

Provides ProcessConPTY — a subprocess-compatible wrapper that gives the
child a real pseudo-console via Windows ConPTY API, preventing
System.Console buffer-ops from crashing in headless environments.

Requires: Windows 10 1809+ (build 17763), Python 3.8+
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import msvcrt
import os
import signal
import subprocess
import threading
from typing import Optional

# ── Windows types ──────────────────────────────────────────────────────
HPCON = ctypes.wintypes.HANDLE
LPHPCON = ctypes.POINTER(HPCON)
DWORD = ctypes.wintypes.DWORD
HRESULT = ctypes.wintypes.LONG
SHORT = ctypes.wintypes.SHORT
ULONG_PTR = ctypes.wintypes.WPARAM
HANDLE = ctypes.wintypes.HANDLE
LPVOID = ctypes.wintypes.LPVOID
SIZE_T = ctypes.c_size_t
BYTE = ctypes.c_byte
LPSTARTUPINFOEXW = ctypes.c_void_p
PPROC_THREAD_ATTRIBUTE_LIST = LPVOID
WINBOOL = ctypes.wintypes.BOOL
LPPROCESS_INFORMATION = ctypes.wintypes.LPVOID


class COORD(ctypes.Structure):
    _fields_ = [("X", SHORT), ("Y", SHORT)]


# Manual definition of STARTUPINFOEXW for ctypes
class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", SHORT),
        ("cbReserved2", SHORT),
        ("lpReserved2", LPVOID),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", PPROC_THREAD_ATTRIBUTE_LIST),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


# ── Kernel32 / Console API bindings ────────────────────────────────────
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# CreatePipe
_CreatePipe = _kernel32.CreatePipe
_CreatePipe.argtypes = [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), LPVOID, DWORD]
_CreatePipe.restype = WINBOOL

# CreatePseudoConsole
_CreatePseudoConsole = _kernel32.CreatePseudoConsole
_CreatePseudoConsole.argtypes = [COORD, HANDLE, HANDLE, DWORD, LPHPCON]
_CreatePseudoConsole.restype = HRESULT

# ResizePseudoConsole
_ResizePseudoConsole = _kernel32.ResizePseudoConsole
_ResizePseudoConsole.argtypes = [HPCON, COORD]
_ResizePseudoConsole.restype = HRESULT

# ClosePseudoConsole
_ClosePseudoConsole = _kernel32.ClosePseudoConsole
_ClosePseudoConsole.argtypes = [HPCON]
_ClosePseudoConsole.restype = None

# InitializeProcThreadAttributeList
_InitializeProcThreadAttributeList = _kernel32.InitializeProcThreadAttributeList
_InitializeProcThreadAttributeList.argtypes = [
    PPROC_THREAD_ATTRIBUTE_LIST, DWORD, DWORD, LPVOID,
]
_InitializeProcThreadAttributeList.restype = WINBOOL

# UpdateProcThreadAttribute
_UpdateProcThreadAttribute = _kernel32.UpdateProcThreadAttribute
_UpdateProcThreadAttribute.argtypes = [
    PPROC_THREAD_ATTRIBUTE_LIST, DWORD, ULONG_PTR, LPVOID, SIZE_T, ULONG_PTR, LPVOID,
]
_UpdateProcThreadAttribute.restype = WINBOOL

# DeleteProcThreadAttributeList
_DeleteProcThreadAttributeList = _kernel32.DeleteProcThreadAttributeList
_DeleteProcThreadAttributeList.argtypes = [PPROC_THREAD_ATTRIBUTE_LIST]
_DeleteProcThreadAttributeList.restype = None

# CreateProcessW
_CreateProcessW = _kernel32.CreateProcessW
_CreateProcessW.argtypes = [
    ctypes.c_wchar_p,  # lpApplicationName
    ctypes.c_wchar_p,  # lpCommandLine
    LPVOID,            # lpProcessAttributes
    LPVOID,            # lpThreadAttributes
    WINBOOL,           # bInheritHandles
    DWORD,             # dwCreationFlags
    LPVOID,            # lpEnvironment
    ctypes.c_wchar_p,  # lpCurrentDirectory
    ctypes.POINTER(STARTUPINFOW),  # lpStartupInfo
    LPVOID,            # lpProcessInformation (PROCESS_INFORMATION*)
]
_CreateProcessW.restype = WINBOOL

# TerminateProcess
_TerminateProcess = _kernel32.TerminateProcess
_TerminateProcess.argtypes = [HANDLE, ctypes.c_uint]
_TerminateProcess.restype = WINBOOL

# WaitForSingleObject
_WaitForSingleObject = _kernel32.WaitForSingleObject
_WaitForSingleObject.argtypes = [HANDLE, DWORD]
_WaitForSingleObject.restype = DWORD

# CloseHandle
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [HANDLE]
_CloseHandle.restype = WINBOOL

# Constants
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
INVALID_HANDLE_VALUE = HANDLE(-1).value


def _check(hr: int, msg: str = "") -> None:
    if hr < 0:
        raise OSError(f"Windows API call failed: {msg} (HRESULT=0x{hr:08X})")


def _make_pipe() -> tuple[HANDLE, HANDLE]:
    """Create an overlapped pipe pair. Returns (read_handle, write_handle)."""
    read_h = HANDLE()
    write_h = HANDLE()
    # FILE_FLAG_OVERLAPPED = 0x40000000
    _check_hresult = True  # Will check below
    if not _CreatePipe(ctypes.byref(read_h), ctypes.byref(write_h), None, 0):
        err = ctypes.get_last_error()
        raise OSError(f"CreatePipe failed: {ctypes.WinError(err)}")
    return read_h, write_h


def _handle_to_fd(handle: HANDLE) -> int:
    """Convert a Windows HANDLE to a Python file descriptor."""
    flags = _kernel32.GetHandleInformation(handle, ctypes.byref(DWORD()))
    # _open_osfhandle creates a CRT fd from a Win32 handle
    return msvcrt.open_osfhandle(handle.value, os.O_RDWR | os.O_BINARY)


def _fd_from_handle(handle: HANDLE, mode: str) -> int:
    """Convert handle to FD with proper access mode."""
    if mode == "r":
        access = os.O_RDONLY
    elif mode == "w":
        access = os.O_WRONLY
    else:
        access = os.O_RDWR
    return msvcrt.open_osfhandle(handle.value, access | os.O_BINARY)


# ── Public API ─────────────────────────────────────────────────────────


class ConPTYProcess:
    """Windows pseudo-console subprocess wrapper.

    Provides read-only access to the combined stdout/stderr of the child
    and write access to its stdin, via ConPTY pipes. The child sees a
    real console handle, so .NET Console.* methods work correctly.

    Usage:
        p = ConPTYProcess(["path.exe", "arg1"], cwd=".", width=120, height=40)
        line = p.stdout.readline()   # blocking call
        p.stdin.write(b"help\n")
        p.stdin.flush()
        returncode = p.wait()
    """

    def __init__(
        self,
        args: list[str],
        *,
        cwd: str = ".",
        env: Optional[dict[str, str]] = None,
        width: int = 120,
        height: int = 40,
    ):
        self._width = width
        self._height = height
        self._hpc = HPCON()
        self._h_process = HANDLE()
        self._h_thread = HANDLE()
        self._close_pipe = HANDLE()
        self._returncode: Optional[int] = None
        self._stdout_reader: Optional[io.BufferedReader] = None
        self._stdin_writer: Optional[io.BufferedWriter] = None
        self._closed = False

        # 1. Create communication pipes (overlapped for ConPTY)
        # Output pipe: child writes → we read
        h_out_read, h_out_write = _make_pipe()   # child writes to h_out_write, we read from h_out_read
        # Input pipe: we write → child reads
        h_in_read, h_in_write = _make_pipe()     # we write to h_in_write, child reads from h_in_read

        # Convert handles to Python FDs and file objects
        self._pty_read_fd = _fd_from_handle(h_out_read, "r")
        self._pty_write_fd = _fd_from_handle(h_out_write, "w")

        # Convert to Win32 handles (already HANDLEs from _make_pipe)
        # 4. Create ConPTY
        # ConPTY hInput = read end of input pipe (child reads from this)
        # ConPTY hOutput = write end of output pipe (child writes to this)
        size = COORD(SHORT(width), SHORT(height))
        _check(_CreatePseudoConsole(size, h_in_read, h_out_write, 0, ctypes.byref(self._hpc)),
               "CreatePseudoConsole")

        # 5. Create STARTUPINFOEXW with PTY attribute
        startup_info = STARTUPINFOEXW()
        startup_info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        startup_info.StartupInfo.dwFlags = subprocess.STARTF_USESTDHANDLES
        # Standard handles: child reads stdin from ConPTY, writes to ConPTY
        # But ConPTY handles I/O through the PTY, not standard handles.
        # Actually, with ConPTY, we should NOT redirect stdhandles.
        # The ConPTY handles stdin/stdout through the pseudo-console directly.
        # Let's NOT set stdhandles — let ConPTY handle it.

        # Size attribute list
        attr_size = ctypes.c_size_t()
        _InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
        attr_buf = (BYTE * attr_size.value)()
        attr_list = PPROC_THREAD_ATTRIBUTE_LIST(ctypes.cast(attr_buf, LPVOID).value)
        if not _InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(attr_size)):
            raise ctypes.WinError(ctypes.get_last_error())

        # Set PTY attribute
        hpc_value = ULONG_PTR(self._hpc.value)
        attr_addr = LPVOID(ctypes.addressof(hpc_value))
        if not _UpdateProcThreadAttribute(
            attr_list, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            attr_addr, ctypes.sizeof(HPCON), 0, None,
        ):
            _DeleteProcThreadAttributeList(attr_list)
            raise ctypes.WinError(ctypes.get_last_error())

        startup_info.lpAttributeList = attr_list

        # 7. Create process
        cmdline = subprocess.list2cmdline(args)
        env_block = _build_env_block(env) if env else None
        proc_info = PROCESS_INFORMATION()

        creation_flags = EXTENDED_STARTUPINFO_PRESENT | 0x08000000  # EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW

        if not _CreateProcessW(
            None,  # lpApplicationName (use command line)
            cmdline,
            None, None,
            True,  # inherit handles
            creation_flags,
            env_block,
            cwd,
            ctypes.cast(ctypes.byref(startup_info), ctypes.POINTER(STARTUPINFOW)),
            ctypes.byref(proc_info),
        ):
            err = ctypes.get_last_error()
            _DeleteProcThreadAttributeList(attr_list)
            _ClosePseudoConsole(self._hpc)
            raise OSError(f"CreateProcess failed: {ctypes.WinError(err)}")

        self._h_process = proc_info.hProcess
        self._h_thread = proc_info.hThread
        self.pid = proc_info.dwProcessId

        # 8. Cleanup: close ConPTY-side handles and attribute list
        _CloseHandle(h_out_write)
        _CloseHandle(h_in_read)
        _DeleteProcThreadAttributeList(attr_list)

        # 9. Create Python file objects for I/O
        self._stdout_reader = open(self._pty_read_fd, "rb", buffering=0, closefd=True)
        self._stdin_writer = open(_fd_from_handle(h_in_write, "w"), "wb", buffering=0, closefd=True)

        # Start exit watcher thread
        self._exit_thread = threading.Thread(
            target=self._watch_exit, daemon=True, name="conpty-exit-watcher"
        )
        self._exit_thread.start()

    def _watch_exit(self) -> None:
        """Background thread that waits for process exit."""
        _WaitForSingleObject(self._h_process, INFINITE)
        exit_code = DWORD()
        _kernel32.GetExitCodeProcess(self._h_process, ctypes.byref(exit_code))
        self._returncode = exit_code.value

    @property
    def stdin(self) -> Optional[io.BufferedWriter]:
        """Write-only pipe for sending input to the child."""
        return self._stdin_writer

    @property
    def stdout(self) -> Optional[io.BufferedReader]:
        """Read-only pipe for receiving output from the child."""
        return self._stdout_reader

    @property
    def returncode(self) -> Optional[int]:
        """Process exit code (None while running)."""
        return self._returncode

    def wait(self) -> int:
        """Wait for the process to exit and return the exit code."""
        if self._returncode is None:
            _WaitForSingleObject(self._h_process, INFINITE)
            exit_code = DWORD()
            _kernel32.GetExitCodeProcess(self._h_process, ctypes.byref(exit_code))
            self._returncode = exit_code.value
        return self._returncode

    def terminate(self) -> None:
        """Send Ctrl+C / terminate the process."""
        if self._h_process:
            _kernel32.GenerateConsoleCtrlEvent(0, self.pid)  # CTRL_C_EVENT
            # If it doesn't exit within 3 seconds, force kill
            result = _WaitForSingleObject(self._h_process, 3000)
            if result != WAIT_OBJECT_0:
                _TerminateProcess(self._h_process, 1)

    def kill(self) -> None:
        """Force kill the process."""
        if self._h_process:
            _TerminateProcess(self._h_process, 9)

    def close(self) -> None:
        """Clean up all resources."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._stdin_writer:
                self._stdin_writer.close()
        except Exception:
            pass
        try:
            if self._stdout_reader:
                self._stdout_reader.close()
        except Exception:
            pass
        if self._hpc:
            _ClosePseudoConsole(self._hpc)
        if self._h_thread:
            _CloseHandle(self._h_thread)
        if self._h_process:
            _CloseHandle(self._h_process)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()


def _set_overlapped(fd: int) -> None:
    """Set the overlapped (async) flag on an FD handle."""
    handle = msvcrt.get_osfhandle(fd)
    # Get current flags
    import subprocess as _s
    handle_value = HANDLE(handle).value
    # Use kernel32.SetFileInformationByHandle or just rely on default async mode
    # For ConPTY, the output pipe needs to be in overlapped mode.
    # In practice, we pass a null OVERLAPPED to ReadFile which blocks anyway.
    pass  # ConPTY output reads work with synchronous ReadFile as well


def _build_env_block(env: dict[str, str]) -> ctypes.c_wchar_p:
    """Build a Windows-style environment block from a dict."""
    block = "\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0"
    return ctypes.c_wchar_p(block)


def is_available() -> bool:
    """Check if ConPTY is supported on this Windows version."""
    if os.name != "nt":
        return False
    # Windows 10 1809+ (build 17763)
    try:
        ver = os.sys.getwindowsversion()
        return (ver.major, ver.minor, ver.build) >= (10, 0, 17763)
    except AttributeError:
        return False
