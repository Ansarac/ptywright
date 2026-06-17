"""Render the live screen from a session's raw VT stream.

`out.log` is the *scrollback* — every byte the PTY ever emitted, including the
cursor moves and erases a full-screen TUI uses to repaint in place. Reading it
raw tells you what was *transmitted*, not what is currently *on screen*. To see
the screen a human would see, you have to replay that byte stream through a VT
terminal emulator and read off the resulting character grid.

`render` does exactly that with [`pyte`](https://github.com/selectel/pyte): feed
the whole stream into a `pyte.Screen` sized to the ConPTY and snapshot the grid.
It takes plain bytes/str, so it is testable without a real PTY.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Snapshot:
    """A rendered screen grid: the current display, not the scrollback."""

    cols: int
    rows: int
    cursor_x: int
    cursor_y: int
    lines: list[str]  # one string per row, right padding stripped

    def to_text(self) -> str:
        return "\n".join(self.lines)

    def to_dict(self) -> dict:
        return {
            "cols": self.cols,
            "rows": self.rows,
            "cursor": {"x": self.cursor_x, "y": self.cursor_y},
            "lines": self.lines,
        }


def render(data: bytes | str, cols: int, rows: int) -> Snapshot:
    """Replay a raw VT stream through a `cols` x `rows` screen and snapshot it.

    `data` is the full `out.log` (bytes or already-decoded text). The pyte import
    is local so the stdlib-only commands (`send`/`watch`/`read`) keep working when
    pyte isn't installed.
    """
    try:
        import pyte
    except ImportError as e:  # pragma: no cover - import guard
        raise SystemExit("pyte is required for `snapshot`: pip install pyte") from e

    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode("utf-8", "replace")

    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    stream.feed(data)

    lines = [row.rstrip() for row in screen.display]
    return Snapshot(cols, rows, screen.cursor.x, screen.cursor.y, lines)
