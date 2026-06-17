"""The ConPTY session host.

Run this from a fully-initialized terminal (one where your build/auth
environment is already loaded). The spawned shell inherits *that* environment,
so anything you drive through it sees your real PATH, certificates and desktop
logon — which is the whole point: it sidesteps the broken headless environment.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time

from .transport import Session

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11


def _enable_vt_console() -> None:
    """Turn on ANSI/VT rendering for our own console so the mirror looks right."""
    if sys.platform != "win32":
        return
    try:
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(_STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


def _append(path, text: str) -> None:
    with open(path, "a", encoding="utf-8", errors="replace", newline="") as f:
        f.write(text)
        f.flush()


def serve(
    session: Session,
    shell: str = "pwsh.exe",
    cols: int = 120,
    rows: int = 50,
    *,
    quiet: bool = False,
) -> int:
    """Host `shell` inside a ConPTY and bridge it to the session directory."""
    try:
        from winpty import PtyProcess
    except ImportError as e:  # pragma: no cover - import guard
        raise SystemExit("pywinpty is required for `serve`: pip install pywinpty") from e

    _enable_vt_console()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    session.ensure()
    session.out_log.write_text("", encoding="utf-8")  # truncate previous run
    if session.status_file.exists():
        session.status_file.unlink()

    proc = PtyProcess.spawn(shell, dimensions=(rows, cols))
    session.write_meta(shell=shell, pid=proc.pid, cols=cols, rows=rows, started=time.time())
    session.ready_file.write_text(str(proc.pid), encoding="utf-8")

    banner = f"[ptybridge] session '{session.name}' up - shell={shell} pid={proc.pid}\r\n"
    _append(session.out_log, banner)
    if not quiet:
        sys.stdout.write(banner)
        sys.stdout.flush()

    stop = threading.Event()

    def reader() -> None:
        # One persistent append handle; the only writer to out.log while running.
        with open(session.out_log, "a", encoding="utf-8", errors="replace", newline="") as f:
            while not stop.is_set():
                try:
                    data = proc.read(4096)
                except EOFError:
                    break
                except Exception:
                    break
                if not data:
                    continue
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "replace")
                f.write(data)
                f.flush()
                if not quiet:
                    try:
                        sys.stdout.write(data)
                        sys.stdout.flush()
                    except Exception:
                        pass
        stop.set()

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()

    try:
        while not stop.is_set() and proc.isalive():
            for chunk in sorted(session.in_dir.glob("*.bin")):
                try:
                    proc.write(chunk.read_bytes().decode("utf-8", "replace"))
                finally:
                    try:
                        chunk.unlink()
                    except OSError:
                        pass
            time.sleep(0.04)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        rt.join(timeout=3)
        code = getattr(proc, "exitstatus", None)
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
        msg = f"\r\n[ptybridge] shell exited (code={code}); session stopped\r\n"
        _append(session.out_log, msg)
        session.status_file.write_text(f"exited code={code}\n", encoding="utf-8")
        try:
            session.ready_file.unlink()
        except OSError:
            pass
        if not quiet:
            sys.stdout.write(msg)
            sys.stdout.flush()
    return 0
