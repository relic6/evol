"""``evol`` command-line interface.

This package wires Click subcommands. Run ``evol --help`` after installing
the package to see all commands.
"""

from evol.cli.main import main

__all__ = ["main"]
