# ptywright

**A scriptable driver for interactive terminal programs on native Windows.**

`ptywright` runs a real shell or TUI inside a Windows pseudo console
([ConPTY](https://learn.microsoft.com/windows/console/pseudoconsoles)) and lets a separate
process — a script, a CI step, or a headless AI coding agent — **inject keystrokes and read
back the live output** over a dead-simple file transport. Think of it as a remote control for
a terminal program: something else holds the keyboard and watches the screen.

## Why this exists

A headless process can run `program --flag` and read its stdout, but it is blind and mute the
moment a program is *interactive*: a TUI (an installer wizard, `fzf`, a pager, a build with a
live progress UI), a prompt that waits for `y/n`, or a toolchain that only works inside a
*real* session — the one where your `PATH`, certificates, Kerberos logon and hardware access
are already set up. Run those headless and they hang, die on missing environment, or have no
way to be answered.

`ptywright` gives that headless process **hands and eyes on a real terminal**:

- **Drive & debug TUIs.** Send arrow keys, `Enter`, `Esc`, `Ctrl-*`; read what the program
  drew. An automation agent can finally operate full-screen terminal apps.
- **Do the headless-hostile work.** Answer interactive prompts, and run commands that need the
  authenticated, environment-rich session a human already has open.

A human starts the host once in a good terminal, so the shell inherits that real environment;
a separate process then drives it. The transport is **just files**, so anything that can write
a small file and read a growing one can be the driver — no client library required.

```
  ┌─ a real, authenticated terminal ────┐         ┌─ any other process ─┐
  │  ptywright serve                    │  files  │  ptywright send ... │  ← inject keys
  │   └─ pwsh / a TUI in a ConPTY ──────┼────────►│  ptywright watch    │  ← read output
  │      (inherits your real env)       │ session │  ptywright read     │
  └─────────────────────────────────────┘   dir   └─────────────────────┘
```

> It can double as a lightweight, tmux-style session host — but its reason for being is
> *programmatic* control of a terminal program, not multiplexing panes for a human.

## Requirements

- Windows 10 1809+ / Windows 11 (ConPTY).
- Python ≥ 3.13, [`uv`](https://docs.astral.sh/uv/).
- [`pywinpty`](https://pypi.org/project/pywinpty/) (installed automatically by uv; only the
  `serve` command needs it — `send`/`watch`/`status`/`read` are pure stdlib).
- [`pyte`](https://pypi.org/project/pyte/) (installed automatically by uv; only `snapshot`
  needs it, to render the screen grid).

## Install

```powershell
git clone https://github.com/Ansarac/ptywright ; cd ptywright
uv sync
# or install the command onto your PATH:
uv tool install .          # then just run `ptywright ...` (no `uv run`)
```

## Quickstart

**1. In a real terminal**, start the host (it sizes the ConPTY to this window and mirrors the
live session, so you can watch what the driver is doing):

```powershell
uv run ptywright serve
```

**2. From anywhere else** (another shell, a script, an automation agent), drive it:

```powershell
uv run ptywright send --line "cd C:\Users\me\repo"
uv run ptywright send --line ".\build.ps1 -Release"
uv run ptywright send --key down --key down --key enter   # navigate a menu / TUI
uv run ptywright send "y" --key enter                     # answer a y/n prompt
```

**3. Read what happened** — tail it live, or pull bytes from an offset for scripted reads:

```powershell
uv run ptywright watch                       # read-only attach, Ctrl-C to detach
uv run ptywright read --offset 0             # print output; prints next offset on stderr
```

`watch`/`read` give you the raw scrollback. To see what a *full-screen* TUI is currently
drawing — the rendered screen, not the byte stream that drew it — use `snapshot`:

```powershell
uv run ptywright snapshot                    # print the current screen grid as text
uv run ptywright snapshot --json             # {cols, rows, cursor:{x,y}, lines:[...]}
```

## Commands

| command | what it does |
|---|---|
| `serve`  | Host `--shell` (default `pwsh.exe`) inside a ConPTY sized to your terminal; mirror output to `out.log` and this console. Run it in the authenticated terminal. `Ctrl-C` here stops the session cleanly. |
| `send`   | Encode text + named keys into one raw input chunk and spool it for injection. |
| `watch`  | Tail `out.log` live (read-only attach). |
| `read`   | Print output bytes from `--offset`; emits the new end offset on stderr (for scripted incremental reads). |
| `snapshot` | Replay `out.log` through a VT screen model ([`pyte`](https://github.com/selectel/pyte)) sized from `meta.json` and print the **rendered** screen grid — what a full-screen TUI currently shows, not its scrollback. `--json` for `{cols, rows, cursor, lines}`; `--cols`/`--rows` override the size. |
| `status` | Show whether the session is ready, its pid/meta, and exit status. |

Global: `-s/--session NAME` (default `default`) and `--root DIR` (default `~/.ptywright`)
select the session, so you can run several at once.

### `send` cheatsheet

```powershell
ptywright send --line "<command>"            # type + Enter (most common)
ptywright send "<text>"                       # type, no Enter
ptywright send --key ctrl-c                    # a control key alone (see Limitations)
ptywright send "<text>" --key enter            # text then a named key
ptywright send -K esc "q" --key enter          # prefix key, text, suffix key
```

Named keys: `enter cr lf tab space esc backspace ctrl-c ctrl-d ctrl-z ctrl-l
up down left right home end`, or a raw `\xNN` byte.

## Session directory layout

`~/.ptywright/<name>/`

| path | role |
|---|---|
| `in/` | spool of `*.bin` raw input chunks; the server injects then deletes each (tmp+rename, so no half-written reads). Cleared on `serve` startup so a crashed run can't replay stale keystrokes. |
| `out.log` | append-only mirror of everything the PTY emitted (the readable stream). |
| `meta.json` | `{shell, pid, cols, rows, started}`. |
| `ready` | present while the server runs (holds the child pid). |
| `status` | final line when the session ends (`exited code=N` or `interrupted`). |

The transport is **just files**, so any tool that can write a small file and read a growing
one can drive a session — no client library required.

## Security

- The session runs **as you**, in the environment of the terminal that launched `serve`.
  Anything that can write to `~/.ptywright/<name>/in/` can run commands as you. Keep the
  session root on a profile-private path (the default is under your home dir).
- ptywright does no auth itself; it relies on filesystem ACLs. Don't point `--root` at a
  world-writable location.

## Limitations / roadmap

- `out.log` is the raw VT byte stream (full scrollback) — ideal for line-oriented build
  output. It is **not** a rendered screen grid, so to snapshot a full-screen TUI's current
  display use `ptywright snapshot`, which replays the stream through a
  [`pyte`](https://github.com/selectel/pyte) screen sized from `meta.json` and prints the
  rendered grid (text, or `--json` with cursor position). Note it renders the *whole* log from
  the start of the session, so an `out.log` with megabytes of scrollback is replayed each call.
- `send --key ctrl-c` injects the `0x03` byte. That edits the current input line and feeds
  apps that read `0x03` as input, but under ConPTY it is **not** translated into a console
  `CTRL_C_EVENT`, so it does **not** reliably interrupt an already-running foreground command
  (true for `pwsh` and `cmd` alike). Pressing `Ctrl-C` in the `serve` terminal stops the whole
  session cleanly.
- The ConPTY is sized to the terminal at startup; resizing that terminal mid-session is not
  yet propagated to the child.
- One shell per session; the server exits when that shell exits (re-run `serve` to restart).
- Windows-only by design (ConPTY). The transport layer is portable; a POSIX `serve` backend
  could be added, but on Unix you'd reach for `tmux`/`expect`.

## Development

```powershell
uv run pytest        # transport + encoding tests (no PTY needed)
uv run ruff check .
uv run ruff format .
```
