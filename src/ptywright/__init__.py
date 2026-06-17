"""ptywright — a scriptable driver for interactive terminal programs on Windows.

A long-lived server owns a real pseudo console (ConPTY) running a shell or TUI;
external drivers inject keystrokes and read back the live output over a simple
file-spool transport — so a script or a headless agent can operate a terminal
program it otherwise couldn't. See README.md.
"""

__version__ = "0.1.0"
