"""``maki`` — manage which services raise deploy notifications.

Talks to a running maki backend over its HTTP API rather than the database, so the CLI and the
dashboard's Watch button share exactly one write path.
"""

import argparse
import os
import sys

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8787"


def _headers() -> dict[str, str]:
    token = os.environ.get("MAKI_AUTH_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _detail(response: httpx.Response) -> str:
    """The API's own ``detail`` string, or the bare status when something else answered."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return f"HTTP {response.status_code}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maki", description="Manage which services raise deploy notifications."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    watch = sub.add_parser("watch", help="notify me about this service's deploys")
    watch.add_argument("service")
    unwatch = sub.add_parser("unwatch", help="stop notifying about this service")
    unwatch.add_argument("service")
    sub.add_parser("watches", help="list watched services")
    return parser


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    args = _parser().parse_args(argv)
    base = os.environ.get("MAKI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    client = client or httpx.Client(timeout=5.0)

    try:
        if args.command == "watch":
            response = client.post(
                f"{base}/api/watches", json={"service": args.service}, headers=_headers()
            )
        elif args.command == "unwatch":
            response = client.delete(f"{base}/api/watches/{args.service}", headers=_headers())
        else:
            response = client.get(f"{base}/api/watches", headers=_headers())
    except httpx.ConnectError:
        print(f"can't reach maki at {base} — is the backend running? (make dev)", file=sys.stderr)
        return 2

    if response.status_code >= 400:
        print(f"error from {base}: {_detail(response)}", file=sys.stderr)
        return 1

    if args.command == "watches":
        watches = response.json().get("watches", [])
        if not watches:
            print("no watched services — try: maki watch <service>")
        for watch in watches:
            print(watch["service"])
    else:
        print(f"{args.command}ed {args.service}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
