from __future__ import annotations

import pytest

from ptywright.transport import KEYS, Session, encode_keys, key_bytes


def test_plain_text():
    assert encode_keys("dir") == b"dir"


def test_text_enter():
    assert encode_keys("dir", enter=True) == b"dir\r"


def test_line_is_text_plus_cr():
    assert encode_keys("cd C:\\repo", enter=True) == b"cd C:\\repo\r"


def test_ctrl_c_only():
    assert encode_keys("", keys=["ctrl-c"]) == b"\x03"


def test_prefix_and_suffix_keys():
    # answer a prompt: Esc, then "y", then Enter
    assert encode_keys("y", prefix_keys=["esc"], keys=["enter"]) == b"\x1by\r"


def test_arrow_key():
    assert encode_keys("", keys=["up"]) == b"\x1b[A"


def test_hex_escape_key():
    assert encode_keys("", keys=["\\x03"]) == b"\x03"


def test_unicode_text_is_utf8():
    assert encode_keys("café") == "café".encode()


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown key"):
        key_bytes("ctrl-q-nope")


def test_every_named_key_is_bytes():
    assert all(isinstance(v, bytes) and v for v in KEYS.values())


def test_spool_roundtrip(tmp_path):
    s = Session("t", root=tmp_path).ensure()
    p = s.spool(b"hello\r")
    assert p.suffix == ".bin"
    assert p.read_bytes() == b"hello\r"
    assert list(s.in_dir.glob("*.tmp")) == []  # nothing left half-written


def test_spool_orders_chronologically(tmp_path):
    s = Session("t", root=tmp_path).ensure()
    first = s.spool(b"1")
    second = s.spool(b"2")
    names = sorted(p.name for p in s.in_dir.glob("*.bin"))
    assert names == [first.name, second.name]


def test_session_paths(tmp_path):
    s = Session("foo", root=tmp_path)
    assert s.dir == tmp_path / "foo"
    assert s.in_dir == tmp_path / "foo" / "in"
    assert not s.is_ready()


def test_meta_roundtrip(tmp_path):
    s = Session("m", root=tmp_path).ensure()
    s.write_meta(shell="pwsh.exe", pid=1234)
    assert s.read_meta()["pid"] == 1234


def test_clear_spool_removes_stale_chunks(tmp_path):
    s = Session("c", root=tmp_path).ensure()
    s.spool(b"echo stale\r")
    (s.in_dir / "leftover.tmp").write_bytes(b"half")
    assert s.clear_spool() == 2
    assert list(s.in_dir.glob("*")) == []


def test_clear_spool_on_missing_dir_is_noop(tmp_path):
    s = Session("none", root=tmp_path)  # never ensure()'d
    assert s.clear_spool() == 0
