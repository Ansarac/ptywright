from __future__ import annotations

from pathlib import Path

from ptywright.cli import _skill_text, main


def test_skill_text_loads_from_source():
    text = _skill_text()
    assert text.startswith("---")
    assert "name: ptywright" in text


def test_install_skill_writes_file(tmp_path, capsys):
    rc = main(["install-skill", "--dest", str(tmp_path)])
    assert rc == 0
    target = tmp_path / "ptywright" / "SKILL.md"
    assert target.is_file()
    assert "name: ptywright" in target.read_text(encoding="utf-8")
    assert str(target) in capsys.readouterr().out


def test_install_skill_refuses_overwrite(tmp_path, capsys):
    target = tmp_path / "ptywright" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("OLD", encoding="utf-8")
    rc = main(["install-skill", "--dest", str(tmp_path)])
    assert rc == 1
    assert target.read_text(encoding="utf-8") == "OLD"  # untouched
    assert "already exists" in capsys.readouterr().err


def test_install_skill_force_overwrites(tmp_path):
    target = tmp_path / "ptywright" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("OLD", encoding="utf-8")
    rc = main(["install-skill", "--dest", str(tmp_path), "--force"])
    assert rc == 0
    assert "name: ptywright" in target.read_text(encoding="utf-8")


def test_install_skill_print_only(tmp_path, capsys):
    rc = main(["install-skill", "--dest", str(tmp_path), "--print"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name: ptywright" in out
    assert not (tmp_path / "ptywright").exists()  # nothing written


def test_bundled_skill_matches_repo_copy():
    repo = Path(__file__).resolve().parents[1] / "skills" / "ptywright" / "SKILL.md"
    assert _skill_text() == repo.read_text(encoding="utf-8")
