"""The ConPTY session host.

Run this from a fully-initialized terminal (one where your build/auth
environment is already loaded). The spawned shell inherits *that* environment,
so anything you drive through it sees your real PATH, certificates and desktop
logon — which is the whole point: it sidesteps the broken headless environment.
"""

from __future__ import annotations

import ctypes
import shutil
import sys
import threading
import time

from .transport import Session

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11
_STD_INPUT_HANDLE = -10


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


def _flush_console_input() -> None:
    """Discard pending console input on teardown.

    While serving, we mirror the child's raw VT output to this real console.
    That output can include terminal *queries* (Primary Device Attributes
    ``ESC[c``, cursor reports, ...); conhost answers them by queuing the reply
    in *our* console input buffer. Once serve exits, the outer shell reads those
    replies as if typed — a line of garbage (``[?61;...c``) at its prompt.
    Flushing the input buffer on the way out drops those stray replies.
    """
    if sys.platform != "win32":
        return
    try:
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(_STD_INPUT_HANDLE)
        k.FlushConsoleInputBuffer(h)
    except Exception:
        pass


def _append(path, text: str) -> None:
    with open(path, "a", encoding="utf-8", errors="replace", newline="") as f:
        f.write(text)
        f.flush()


def serve(
    session: Session,
    shell: str = "pwsh.exe",
    cols: int | None = None,
    rows: int | None = None,
    *,
    quiet: bool = False,
) -> int:
    """Host `shell` inside a ConPTY and bridge it to the session directory.

    `cols`/`rows` default to the *real* terminal's size. That match matters:
    the shell's line editor (PSReadLine) redraws input with absolute cursor
    moves (``CSI row;col H``) computed against the pseudo-console's screen. If
    that screen is a different size than the terminal we mirror into, the
    redraws land on the wrong rows and scramble earlier output.
    """
    try:
        from winpty import PtyProcess
    except ImportError as e:  # pragma: no cover - import guard
        raise SystemExit("pywinpty is required for `serve`: pip install pywinpty") from e

    if cols is None or rows is None:
        size = shutil.get_terminal_size(fallback=(120, 50))
        cols = cols or size.columns
        rows = rows or size.lines

    _enable_vt_console()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not quiet:
        # Start the mirror from a clean, homed screen so its coordinates line up
        # with the fresh pseudo-console (otherwise absolute cursor moves from the
        # shell overwrite whatever was already on this terminal).
        try:
            sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
            sys.stdout.flush()
        except Exception:
            pass

    session.ensure()
    session.clear_spool()  # drop any keystrokes queued against a previous (crashed) session
    session.out_log.write_text("", encoding="utf-8")  # truncate previous run
    if session.status_file.exists():
        session.status_file.unlink()

    proc = PtyProcess.spawn(shell, dimensions=(rows, cols))
    session.write_meta(shell=shell, pid=proc.pid, cols=cols, rows=rows, started=time.time())
    session.ready_file.write_text(str(proc.pid), encoding="utf-8")

    banner = f"[ptywright] session '{session.name}' up - shell={shell} pid={proc.pid}\r\n"
    _append(session.out_log, banner)
    # Note: the banner is logged but intentionally NOT mirrored to stdout — an extra
    # line here would push the shell's screen down one row relative to the pseudo-console
    # and re-introduce the absolute-cursor misalignment we just cleared the screen to avoid.

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

    interrupted = False
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
        interrupted = True  # Ctrl-C in the serve terminal => stop the session cleanly
    finally:
        stop.set()
        rt.join(timeout=3)
        code = getattr(proc, "exitstatus", None)
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
        why = "interrupted (Ctrl-C); session stopped" if interrupted else f"shell exited (code={code}); session stopped"
        msg = f"\r\n[ptywright] {why}\r\n"
        _append(session.out_log, msg)
        session.status_file.write_text(
            ("interrupted\n" if interrupted else f"exited code={code}\n"), encoding="utf-8"
        )
        try:
            session.ready_file.unlink()
        except OSError:
            pass
        if not quiet:
            sys.stdout.write(msg)
            sys.stdout.flush()
        _flush_console_input()  # drop terminal query replies so they don't litter the outer prompt
    return 0
