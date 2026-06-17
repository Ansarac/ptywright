"""Command-line entry point: serve / send / watch / status / read."""

from __future__ import annotations

import sys
import time

from . import __version__
from .transport import Session, encode_keys


def build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="ptybridge",
        description="Drive a persistent native-Windows shell hosted inside a ConPTY.",
    )
    p.add_argument("--version", action="version", version=f"ptybridge {__version__}")
    p.add_argument("-s", "--session", default="default", help="session name (default: 'default')")
    p.add_argument("--root", default=None, help="sessions root dir (default: ~/.ptybridge)")
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


if __name__ == "__main__":
    raise SystemExit(main())
