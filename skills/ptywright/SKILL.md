---
name: ptywright
description: >-
  Drive an interactive terminal program you cannot run headless — a full-screen TUI, a y/n
  prompt, or a command that only works inside a real authenticated session (PATH, certs,
  Kerberos). A human hosts a real shell with `ptywright serve` in a good terminal; you inject
  keystrokes and read/snapshot the screen over a plain-file transport. Use this when a command
  hangs waiting for input, dies on missing environment, or paints a full-screen UI you need to
  see and navigate.
---

# Driving a terminal program with ptywright

`ptywright` lets you (a headless agent) operate a *live, interactive* terminal that a human
started for you. The human runs the host; you hold the keyboard and watch the screen — entirely
over files under `~/.ptywright/<session>/`, so every step is an ordinary CLI call.

## Before you start: the host must be running

You **cannot** start the host yourself in a useful way — `serve` needs a real console and the
human's authenticated environment. Confirm it is up:

```
ptywright status
```

Look for `ready : True`. If it is not ready, ask the human to run `ptywright serve` (optionally
`--shell cmd.exe`) in a real terminal and leave it open. Everything below is run from your own
shell; add `-s <name>` to target a non-default session.

**`ready : True` can lie.** The `ready` file is removed only on a *clean* exit; if the host was
force-killed (not `Ctrl-C`), it lingers and `status` still reports the dead pid as ready. Before
trusting a session, confirm the `pid` from `status` is actually alive, or send a sentinel and
check it lands:

```
ptywright send --line "echo __ALIVE__$(Get-Random)"   # then snapshot/read for the echo
```

If nothing echoes back, the host is dead — ask the human to re-`serve`.

## The core loop

1. **Send** input (text and/or named keys).
2. **Wait** briefly — the program needs time to react and repaint (start with ~0.3–1s; a build
   or network step needs longer).
3. **Look** at the result, then decide the next input:
   - `ptywright snapshot` — the **rendered screen** (what a full-screen TUI currently shows).
     Use this for menus, wizards, pagers, `fzf`, anything that repaints in place.
   - `ptywright read --offset N` — the **raw scrollback** from byte offset `N`; prints the new
     end offset on stderr so you can resume from there. Use this for line-oriented output (a
     build log, command results) where you want only what is new.

```
ptywright send --line "cd C:\path\to\repo"      # type a command + Enter
ptywright send --line ".\build.ps1 -Release"
ptywright snapshot                               # see the screen
ptywright read --offset 0                        # or pull the scrollback; note the new offset
```

## Sending keystrokes

```
ptywright send --line "<command>"     # type text then Enter (the common case)
ptywright send "<text>"               # type text, no Enter
ptywright send --key down --key down --key enter   # navigate a menu / TUI
ptywright send "y" --key enter        # answer a y/n prompt
ptywright send -K esc "q" --key enter # a prefix key, then text, then a suffix key
```

Named keys: `enter cr lf tab space esc backspace ctrl-c ctrl-d ctrl-z ctrl-l up down left right
home end`, or a raw `\xNN` byte. `--key`/`-k` goes *after* the text; `--prefix-key`/`-K` goes
*before* it; both are repeatable and applied in order.

## snapshot vs read — pick the right eyes

- **`snapshot`** replays the whole VT stream through a screen model and prints the current grid
  (`--json` gives `{cols, rows, cursor:{x,y}, lines:[...]}`). This is the only honest view of a
  full-screen TUI: cursor moves and in-place repaints have already been applied, so you see the
  final frame, not the keystrokes that drew it.
- **`read`** gives the literal bytes, including every intermediate repaint. Great for a scrolling
  log; misleading for a TUI (you'll see overlapping frames).

When in doubt for an interactive UI, use `snapshot`. For "what did that command print," use
`read --offset <last>`.

## Gotchas

- **Drive with the `ptywright` on your PATH, not `uv run` inside the repo.** The host holds the
  project's `.venv\Scripts\ptywright.exe` open, so a bare `uv run ptywright ...` in the repo tries
  to re-sync that venv and fails with *Access is denied (os error 5)* — and a failed `read` can
  come back silently empty. Install once with `ptywright install-skill`'s companion
  `uv tool install .` (or `uv run --no-sync ptywright` if you must run from the repo).
- **Let the screen settle.** If a `snapshot` looks mid-redraw or a `read` is empty, wait longer
  and look again. There is no "command done" signal — you infer it from the screen (a prompt
  returned, a marker line appeared).
- **`send --key ctrl-c` does not reliably interrupt a running command.** Under ConPTY the `0x03`
  byte edits the input line and feeds apps that read it as input, but it is **not** turned into a
  console `CTRL_C_EVENT`, so it won't stop an already-running foreground command. To truly stop
  the session, the human presses `Ctrl-C` in the `serve` terminal.
- **One shell per session.** If the shell exits, the session ends; ask the human to re-`serve`.
- **Encoding.** `snapshot` and `watch` emit UTF-8, so Nerd Font / box-drawing glyphs from a TUI
  survive even on a CP936/GBK (e.g. Chinese) Windows console. If your *own* terminal still mangles
  them, prefix the command with `PYTHONUTF8=1`, or use `snapshot --json` and read the `lines`.
- **Use a marker when you need certainty.** To know a command finished, have it echo a sentinel
  (`... ; echo __DONE__`) and poll `read`/`snapshot` until the sentinel shows up.

## Quick reference

| step | command |
|---|---|
| is the host up? | `ptywright status` |
| type a command | `ptywright send --line "<cmd>"` |
| press keys | `ptywright send --key <name> [...]` |
| see the screen (TUI) | `ptywright snapshot` (`--json` for structured) |
| read new output (logs) | `ptywright read --offset <N>` |
| live tail (rarely needed) | `ptywright watch` |

Target a named session with `-s <name>` on any command; `--root <dir>` if the host used a custom
sessions root.
