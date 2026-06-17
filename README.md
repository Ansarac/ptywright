# ptybridge

**Drive a persistent, native-Windows shell from a separate (even headless) process.**

A minimal [tmux](https://github.com/tmux/tmux)/[shpool](https://github.com/shell-pool/shpool)
for the *native* Windows console. A long-lived **server** owns a real pseudo console
([ConPTY](https://learn.microsoft.com/windows/console/pseudoconsoles)) running `pwsh`;
any number of **drivers** and **watchers** attach over a dead-simple file-spool
transport to inject keystrokes (including `Ctrl-C`) and read the full live output.

## Why this exists

Some Windows toolchains only work in a *real* interactive session — the one where your
`PATH`, certificates, Kerberos logon and hardware access are already set up. Run the same
build headless (CI sandbox, an automation agent, a remote helper) and it dies on missing
env, auth prompts, or interactive gates.

ptybridge bridges the gap: **a human starts the session once in the good terminal**, so the
shell inherits that real environment; **a separate process then drives it**. Unlike
`tmux`/`shpool` (Unix sockets, Linux-only) or tmux-under-MSYS2 (wraps an *MSYS* pty and the
*MSYS* environment, not native ConPTY), ptybridge hosts a native ConPTY with your native
PowerShell environment intact.

```
  ┌─ your good, authenticated terminal ─┐         ┌─ any other process ─┐
  │  ptybridge serve                    │  files  │  ptybridge send ... │  ← inject keys
  │   └─ pwsh inside a ConPTY ──────────┼────────►│  ptybridge watch    │  ← read output
  │      (inherits your real env)       │ session │  ptybridge read     │
  └─────────────────────────────────────┘   dir   └─────────────────────┘
```

## Requirements

- Windows 10 1809+ / Windows 11 (ConPTY).
- Python ≥ 3.13, [`uv`](https://docs.astral.sh/uv/).
- [`pywinpty`](https://pypi.org/project/pywinpty/) (installed automatically by uv; only the
  `serve` command needs it — `send`/`watch`/`status`/`read` are pure stdlib).

## Install

```powershell
git clone <this-repo> ; cd ptybridge
uv sync
```

## Quickstart

**1. In your good terminal**, start the session host (keep this window open; it mirrors the
live session so you can watch):

```powershell
uv run ptybridge serve
# session 'default' up - shell=pwsh.exe pid=12345
```

**2. From anywhere else** (another shell, a script, an automation agent), drive it:

```powershell
uv run ptybridge send --line "cd C:\Users\me\repo"
uv run ptybridge send --line ".\build.ps1 -Release"
uv run ptybridge send --key ctrl-c          # inject Ctrl-C (0x03) — see Limitations
uv run ptybridge send "y" --key enter       # answer a y/n prompt
```

**3. Read what happened** — either tail it live, or pull bytes from an offset:

```powershell
uv run ptybridge watch                       # like `tmux attach`, read-only, Ctrl-C to detach
uv run ptybridge read --offset 0             # print all output; prints next offset on stderr
```

## Commands

| command | what it does |
|---|---|
| `serve`  | Host `--shell` (default `pwsh.exe`) inside a ConPTY; mirror output to `out.log` and this console. Run in the authenticated terminal. |
| `send`   | Encode text + keys into one raw input chunk and spool it for injection. |
| `watch`  | Tail `out.log` live (read-only attach). |
| `read`   | Print output bytes from `--offset`; emits the new end offset on stderr (for scripted incremental reads). |
| `status` | Show whether the session is ready, its pid/meta, and exit status. |

Global: `-s/--session NAME` (default `default`) and `--root DIR` (default `~/.ptybridge`)
select the session, so you can run several at once.

### `send` cheatsheet

```powershell
ptybridge send --line "<command>"            # type + Enter (most common)
ptybridge send "<text>"                       # type, no Enter
ptybridge send --key ctrl-c                    # a control key alone
ptybridge send "<text>" --key enter            # text then a named key
ptybridge send -K esc "q" --key enter          # prefix key, text, suffix key
```

Named keys: `enter cr lf tab space esc backspace ctrl-c ctrl-d ctrl-z ctrl-l
up down left right home end`, or a raw `\xNN` byte.

## Session directory layout

`~/.ptybridge/<name>/`

| path | role |
|---|---|
| `in/` | spool of `*.bin` raw input chunks; the server injects then deletes each (tmp+rename, so no half-written reads). |
| `out.log` | append-only mirror of everything the PTY emitted (the readable stream). |
| `meta.json` | `{shell, pid, cols, rows, started}`. |
| `ready` | present while the server runs (holds the child pid). |
| `status` | final `exited code=N` line when the shell exits. |

The transport is **just files**, so any tool that can write a small file and read a growing
one can drive a session — no client library required.

## Security

- The session runs **as you**, in the environment of the terminal that launched `serve`.
  Anything that can write to `~/.ptybridge/<name>/in/` can run commands as you. Keep the
  session root on a profile-private path (the default is under your home dir).
- ptybridge does no auth itself; it relies on filesystem ACLs. Don't point `--root` at a
  world-writable location.

## Limitations / roadmap

- `out.log` is the raw VT byte stream (full scrollback) — ideal for line-oriented build
  output. It is **not** a rendered screen grid; a true `capture-pane` snapshot of a
  full-screen TUI would need a VT screen model (e.g. [`pyte`](https://github.com/selectel/pyte)).
  *(planned: optional `ptybridge snapshot`.)*
- One shell per session; the server exits when that shell exits (re-run `serve` to restart).
  *(planned: optional auto-respawn.)*
- `send --key ctrl-c` injects the `0x03` byte. That edits the current input line and feeds
  apps that read `0x03` as input, but under ConPTY it is **not** translated into a console
  `CTRL_C_EVENT`, so it does **not** reliably interrupt an already-running foreground command
  (true for `pwsh` and `cmd` alike). To stop a runaway command, send a targeted kill or close
  the session. Pressing `Ctrl-C` in the `serve` terminal stops the whole session cleanly.
- Windows-only by design (ConPTY). The transport layer is portable; a POSIX `serve` backend
  could be added, but on Unix you'd just use tmux.

## Development

```powershell
uv run pytest        # transport + encoding tests (no PTY needed)
uv run ruff check .
uv run ruff format .
```
