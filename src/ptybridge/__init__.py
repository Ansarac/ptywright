"""ptybridge — drive a persistent native-Windows shell inside a ConPTY.

A minimal tmux/shpool for native Windows: a long-lived server owns a pseudo
console (ConPTY) running pwsh; external drivers inject keystrokes and read the
full output stream over a simple file-spool transport. See README.md.
"""

__version__ = "0.1.0"
