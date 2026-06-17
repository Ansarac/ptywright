"""Command-line entry point: serve / send / watch / status / read."""

from __future__ import annotations

import sys
import time

from . import __version__
from .transport import Session, encode_keys


def build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="ptywright",
        description="Drive a persistent native-Windows shell hosted inside a ConPTY.",
    )
    p.add_argument("--version", action="version", version=f"ptywright {__version__}")
    p.add_argument("-s", "--session", default="default", help="session name (default: 'default')")
    p.add_argument("--root", default=None, help="sessions root dir (default: ~/.ptywright)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="host a shell inside a ConPTY (run in your good terminal)")
    sp.add_argument("--shell", default="pwsh.exe", help="shell to spawn (default: pwsh.exe)")
    sp.add_argument("--cols", type=int, default=None, help="ConPTY width (default: this terminal's width)")
    sp.add_argument("--rows", type=int, default=None, help="ConPTY height (default: this terminal's height)")
    sp.add_argument("--quiet", action="store_true", help="don't mirror the session to this console")

    se = sub.add_parser("send", help="inject input into the session")
    se.add_argument("text", nargs="*", help="text to type")
    se.add_argument("--enter", dest="enter", action="store_true", default=None, help="append Enter (CR)")
    se.add_argument("--no-enter", dest="enter", action="store_false")
    se.add_argument("--line", action="store_true", help="shorthand for: type text + Enter")
    se.add_argument(
        "-k",
        "--key",
        action="append",
        default=[],
        metavar="KEY",
        help="named key AFTER text (ctrl-c, esc, up, ...) or \\xNN; repeatable",
    )
    se.add_argument(
        "-K", "--prefix-key", action="append", default=[], metavar="KEY", help="named key BEFORE text; repeatable"
    )

    sub.add_parser("status", help="show session state")

    w = sub.add_parser("watch", help="tail the session output (read-only attach)")
    w.add_argument("--tail", type=int, default=40, help="lines of backlog to print first")

    r = sub.add_parser("read", help="print output bytes from an offset (for scripted drivers)")
    r.add_argument("--offset", type=int, default=0)

    sn = sub.add_parser("snapshot", help="render the current screen grid from out.log (for TUIs)")
    sn.add_argument("--json", action="store_true", help="emit {cols, rows, cursor, lines} as JSON")
    sn.add_argument("--cols", type=int, default=None, help="override screen width (default: meta.json cols)")
    sn.add_argument("--rows", type=int, default=None, help="override screen height (default: meta.json rows)")

    ik = sub.add_parser("install-skill", help="install the Claude Code skill into ~/.claude/skills")
    ik.add_argument("--dest", default=None, help="skills dir (default: ~/.claude/skills)")
    ik.add_argument("--force", action="store_true", help="overwrite an existing SKILL.md")
    ik.add_argument("--print", dest="print_only", action="store_true", help="print the skill to stdout, don't install")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sess = Session(args.session, root=args.root)

    if args.cmd == "serve":
        from . import server

        return server.serve(sess, shell=args.shell, cols=args.cols, rows=args.rows, quiet=args.quiet)

    if args.cmd == "send":
        if not sess.is_ready():
            print(f"warning: session '{sess.name}' is not marked ready ({sess.dir})", file=sys.stderr)
        enter = True if args.line else args.enter
        data = encode_keys(" ".join(args.text), enter=bool(enter), keys=args.key, prefix_keys=args.prefix_key)
        if not data:
            print("nothing to send", file=sys.stderr)
            return 2
        path = sess.spool(data)
        print(f"sent {len(data)} byte(s) -> {path.name}")
        return 0

    if args.cmd == "status":
        print(f"session : {sess.name}")
        print(f"dir     : {sess.dir}")
        print(f"ready   : {sess.is_ready()}")
        meta = sess.read_meta()
        if meta:
            print(f"meta    : {meta}")
        if sess.status_file.exists():
            print(f"status  : {sess.status_file.read_text(encoding='utf-8').strip()}")
        return 0

    if args.cmd == "watch":
        return _watch(sess, args.tail)

    if args.cmd == "read":
        return _read(sess, args.offset)

    if args.cmd == "snapshot":
        return _snapshot(sess, json_out=args.json, cols=args.cols, rows=args.rows)

    if args.cmd == "install-skill":
        return _install_skill(dest=args.dest, force=args.force, print_only=args.print_only)

    return 1


def _watch(sess: Session, tail: int) -> int:
    path = sess.out_log
    while not path.exists():
        time.sleep(0.2)
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f.readlines()[-tail:]:
            sys.stdout.write(line)
        sys.stdout.flush()
        try:
            while True:
                where = f.tell()
                line = f.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.2)
                    f.seek(where)
        except KeyboardInterrupt:
            return 0


def _read(sess: Session, offset: int) -> int:
    path = sess.out_log
    if not path.exists():
        sys.stderr.write("[offset 0]\n")
        return 0
    with open(path, "rb") as f:
        size = f.seek(0, 2)  # end; byte length of the log
        # An offset past EOF means the log was truncated by a newer serve run; realign to 0.
        f.seek(offset if 0 <= offset <= size else 0)
        out = sys.stdout.buffer
        while True:  # stream in chunks so a huge tail never lands in memory at once
            chunk = f.read(65536)
            if not chunk:
                break
            out.write(chunk)
        sys.stdout.flush()
        end = f.tell()
    sys.stderr.write(f"\n[offset {end}]\n")  # next --offset to resume from
    return 0


def _snapshot(sess: Session, *, json_out: bool, cols: int | None, rows: int | None) -> int:
    from .snapshot import render

    path = sess.out_log
    if not path.exists():
        sys.stderr.write(f"no output log for session '{sess.name}' ({path}); is it serving?\n")
        return 1

    data = path.read_bytes()
    if not data.strip():
        sys.stderr.write(f"session '{sess.name}' has produced no output yet\n")
        return 1

    meta = sess.read_meta()
    cols = cols or meta.get("cols")
    rows = rows or meta.get("rows")
    if not cols or not rows:
        sys.stderr.write("unknown screen size: no meta.json cols/rows; pass --cols and --rows\n")
        return 1

    snap = render(data, cols, rows)
    if json_out:
        import json

        print(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(snap.to_text())
    return 0


def _skill_text() -> str:
    """Load the bundled SKILL.md — from the wheel's package data, or the source tree."""
    from importlib.resources import files
    from pathlib import Path

    try:  # installed wheel: force-included at ptywright/_skill/SKILL.md
        res = files("ptywright").joinpath("_skill/SKILL.md")
        if res.is_file():
            return res.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    # source checkout / editable install: repo-root skills/ptywright/SKILL.md
    src = Path(__file__).resolve().parents[2] / "skills" / "ptywright" / "SKILL.md"
    if src.is_file():
        return src.read_text(encoding="utf-8")
    raise SystemExit("could not locate the bundled SKILL.md")


def _install_skill(*, dest: str | None, force: bool, print_only: bool) -> int:
    from pathlib import Path

    text = _skill_text()
    if print_only:
        sys.stdout.write(text)
        return 0

    base = Path(dest) if dest else Path.home() / ".claude" / "skills"
    target = base / "ptywright" / "SKILL.md"
    if target.exists() and not force:
        sys.stderr.write(f"{target} already exists; pass --force to overwrite\n")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"installed ptywright skill -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
