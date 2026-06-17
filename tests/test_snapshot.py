from __future__ import annotations

import json

from ptywright.cli import main
from ptywright.snapshot import render
from ptywright.transport import Session


def test_render_plain_lines():
    snap = render("hello\r\nworld", cols=20, rows=3)
    assert snap.lines == ["hello", "world", ""]
    assert snap.cols == 20
    assert snap.rows == 3


def test_render_strips_right_padding():
    # pyte pads each row to `cols`; render should rstrip it back off.
    snap = render("hi", cols=40, rows=1)
    assert snap.lines == ["hi"]


def test_render_cursor_position():
    snap = render("abc", cols=10, rows=2)
    assert (snap.cursor_x, snap.cursor_y) == (3, 0)


def test_render_absolute_cursor_move_overwrites_in_place():
    # CSI 1;1H homes the cursor; "X" then overwrites the first cell. A raw read of
    # the byte stream would show both "first" and "X"; the *rendered* screen shows
    # only the final state — which is the whole point of snapshot.
    snap = render("first\x1b[1;1HX", cols=10, rows=1)
    assert snap.lines == ["Xirst"]


def test_render_clear_screen_resets_grid():
    # Draw a line, then ESC[2J (erase display) + home: the old text is gone.
    snap = render("garbage line\x1b[2J\x1b[Hclean", cols=20, rows=2)
    assert snap.lines == ["clean", ""]


def test_render_accepts_bytes():
    snap = render(b"bytes\r\nin", cols=10, rows=2)
    assert snap.lines == ["bytes", "in"]


def test_to_dict_shape():
    snap = render("ab\r\ncd", cols=8, rows=2)
    d = snap.to_dict()
    assert d == {
        "cols": 8,
        "rows": 2,
        "cursor": {"x": 2, "y": 1},
        "lines": ["ab", "cd"],
    }


def _seed_session(tmp_path, out: bytes | None, *, cols=20, rows=3) -> Session:
    s = Session("snap", root=tmp_path).ensure()
    if cols is not None:
        s.write_meta(shell="pwsh.exe", pid=1, cols=cols, rows=rows)
    if out is not None:
        s.out_log.write_bytes(out)
    return s


def test_cli_snapshot_text(tmp_path, capsys):
    _seed_session(tmp_path, b"top line\r\nnext")
    rc = main(["-s", "snap", "--root", str(tmp_path), "snapshot"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "top line" in out
    assert "next" in out


def test_cli_snapshot_json(tmp_path, capsys):
    _seed_session(tmp_path, b"hi there", cols=12, rows=2)
    rc = main(["-s", "snap", "--root", str(tmp_path), "snapshot", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cols"] == 12
    assert payload["rows"] == 2
    assert payload["lines"][0] == "hi there"
    assert payload["cursor"] == {"x": 8, "y": 0}


def test_cli_snapshot_missing_log(tmp_path, capsys):
    _seed_session(tmp_path, None)  # meta but no out.log
    rc = main(["-s", "snap", "--root", str(tmp_path), "snapshot"])
    assert rc == 1
    assert "no output log" in capsys.readouterr().err


def test_cli_snapshot_empty_log(tmp_path, capsys):
    _seed_session(tmp_path, b"   \n")  # whitespace only
    rc = main(["-s", "snap", "--root", str(tmp_path), "snapshot"])
    assert rc == 1
    assert "no output yet" in capsys.readouterr().err


def test_cli_snapshot_size_override(tmp_path, capsys):
    # No meta cols/rows: caller must pass --cols/--rows.
    s = Session("snap", root=tmp_path).ensure()
    s.out_log.write_bytes(b"override me")
    rc = main(["-s", "snap", "--root", str(tmp_path), "snapshot", "--cols", "15", "--rows", "1", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cols"] == 15
    assert payload["lines"] == ["override me"]


def test_cli_snapshot_no_size_errors(tmp_path, capsys):
    s = Session("snap", root=tmp_path).ensure()
    s.out_log.write_bytes(b"no size info")
    rc = main(["-s", "snap", "--root", str(tmp_path), "snapshot"])
    assert rc == 1
    assert "unknown screen size" in capsys.readouterr().err
