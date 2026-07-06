import os


def pid_alive(pid):
    """True if a process with this pid is currently running.

    The workers use this to ask "is the previous player/downloader still
    going?". On POSIX that's os.kill(pid, 0). On Windows os.kill(pid, 0) is
    NOT a probe — signal 0 is CTRL_C_EVENT, so it *sends* a console interrupt
    and usually reports success for any pid, which made the workers think a
    long-dead process was still running (queued downloads never started).
    OpenProcess + a zero-timeout wait is the real Windows liveness check.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x100000
        WAIT_TIMEOUT = 0x102          # still running when asked to wait 0ms
        handle = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        # Includes EPERM: the old bare-except probes also treated any error
        # as "not running", so keep that behavior identical on Linux.
        return False
    return True
