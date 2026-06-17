"""Session layout + input encoding for the file-spool transport.

A ptywright *session* is a directory shared between the server (which owns the
ConPTY) and any number of drivers / watchers:

    <session>/
        in/         spool of *.bin input chunks; the server injects + deletes them
        out.log     append-only mirror of everything the PTY emitted
        meta.json   server metadata (shell, pid, size, start time)
        ready       present while the server is running (holds the child pid)
        status      final line written when the shell exits

Input chunks are *raw bytes* so control keys (Ctrl-C, Esc, arrows, ...) travel
verbatim into the pseudo console. Each chunk is written tmp-then-rename so the
server never reads a half-written file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".ptywright"

# Named keys -> the bytes a real terminal would send for them.
KEYS: dict[str, bytes] = {
    "enter": b"\r",
    "cr": b"\r",
    "lf": b"\n",
    "tab": b"\t",
    "space": b" ",
    "esc": b"\x1b",
    "backspace": b"\x7f",
    "ctrl-c": b"\x03",
    "ctrl-d": b"\x04",
    "ctrl-z": b"\x1a",
    "ctrl-l": b"\x0c",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
}


class Session:
    """Paths + helpers for one named session directory."""

    def __init__(self, name: str = "default", root: str | os.PathLike[str] | None = None) -> None:
        self.name = name
        self.root = Path(root) if root else DEFAULT_ROOT
        self.dir = self.root / name

    @property
    def in_dir(self) -> Path:
        return self.dir / "in"

    @property
    def out_log(self) -> Path:
        return self.dir / "out.log"

    @property
    def meta_file(self) -> Path:
        return self.dir / "meta.json"

    @property
    def ready_file(self) -> Path:
        return self.dir / "ready"

    @property
    def status_file(self) -> Path:
        return self.dir / "status"

    def ensure(self) -> Session:
        self.in_dir.mkdir(parents=True, exist_ok=True)
        return self

    def is_ready(self) -> bool:
        return self.ready_file.exists()

    def write_meta(self, **kw: object) -> None:
        self.meta_file.write_text(json.dumps(kw, indent=2), encoding="utf-8")

    def read_meta(self) -> dict:
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def clear_spool(self) -> int:
        """Delete any leftover input chunks (and stray tmps) from the spool.

        Called on `serve` startup so keystrokes queued against a *previous*
        (possibly crashed) session can't replay into the freshly spawned shell.
        Returns the number of files removed.
        """
        if not self.in_dir.exists():
            return 0
        removed = 0
        for f in [*self.in_dir.glob("*.bin"), *self.in_dir.glob("*.tmp")]:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def spool(self, data: bytes) -> Path:
        """Atomically drop one raw input chunk into the spool (tmp + rename)."""
        self.in_dir.mkdir(parents=True, exist_ok=True)
        # Fixed-width ns timestamp keeps lexical sort == chronological order.
        stem = f"{time.time_ns():020d}-{os.getpid():06d}"
        tmp = self.in_dir / (stem + ".tmp")
        dst = self.in_dir / (stem + ".bin")
        tmp.write_bytes(data)
        tmp.replace(dst)  # atomic on the same volume
        return dst


def key_bytes(name: str) -> bytes:
    r"""Resolve a named key (or a ``\xNN`` hex escape) to raw bytes."""
    key = name.strip().lower()
    if key in KEYS:
        return KEYS[key]
    if key.startswith("\\x") and len(key) == 4:
        return bytes([int(key[2:], 16)])  # noqa: FURB166 — explicit base on a stripped prefix is clearer
    raise ValueError(f"unknown key: {name!r} (known: {', '.join(sorted(KEYS))} or \\xNN)")


def encode_keys(
    text: str = "",
    *,
    enter: bool = False,
    keys: list[str] | None = None,
    prefix_keys: list[str] | None = None,
) -> bytes:
    """Build one input chunk: [prefix keys] + utf8(text) + [keys] + [CR if enter]."""
    out = bytearray()
    for k in prefix_keys or []:
        out += key_bytes(k)
    if text:
        out += text.encode("utf-8")
    for k in keys or []:
        out += key_bytes(k)
    if enter:
        out += b"\r"
    return bytes(out)
