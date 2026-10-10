from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="storm-vps-dashboard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="Inicia o servidor MCP storm-vps (stdio)")

    args = parser.parse_args()
    if args.cmd == "serve":
        from .mcp_server import run
        run()


if __name__ == "__main__":
    main()
