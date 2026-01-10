"""Console CLI for PAL MCP Server.

This module exists to keep lightweight subcommands (like `--version`) fast and
side-effect free for `uvx` usage.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from config import __version__


def main() -> None:
    """Entry point for the `pal-mcp-server` console script."""

    parser = argparse.ArgumentParser(prog="pal-mcp-server", add_help=True)
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print PAL MCP Server version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("start-mcp-server", help="Start the MCP server using stdio transport.")

    args, unknown = parser.parse_known_args(sys.argv[1:])
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    if args.version:
        print(__version__)
        return

    if args.command not in (None, "start-mcp-server"):
        parser.error(f"unknown command: {args.command}")

    # Import lazily so `--version` doesn't trigger server initialization.
    from server import main as server_main

    asyncio.run(server_main())


if __name__ == "__main__":  # pragma: no cover
    main()
