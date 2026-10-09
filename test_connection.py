#!/usr/bin/env python3
"""
Quick connectivity test for the Slack Lists MCP token.

Usage (run it with the project venv so httpx is available):
    export SLACK_LISTS_TOKEN="xoxp-..."   # token with lists:read + lists:write
    ./.venv/bin/python test_connection.py [LIST_ID]

- With no LIST_ID: verifies the token via auth.test.
- With a LIST_ID:  also reads the first few items of that list (incl. subtasks),
                   and checks that comments are reachable (needs groups:history).

The test talks to Slack through httpx, exactly like server.py does, so it trusts
the same CA bundle (certifi). The standard library's urllib uses the OS trust
store instead, which python.org builds of Python for macOS leave empty until
"Install Certificates.command" is run — that showed up as CERTIFICATE_VERIFY_FAILED.
"""
import os
import sys

try:
    import httpx
except ImportError:  # pragma: no cover - only hit outside the venv
    sys.exit("ERROR: httpx is not installed. Run this with the project venv: "
             "./.venv/bin/python test_connection.py  (pip install -r requirements.txt first)")

SLACK_API = "https://slack.com/api"
TIMEOUT = 30.0


def _token() -> str:
    token = (
        os.environ.get("SLACK_LISTS_TOKEN")
        or os.environ.get("SLACK_USER_TOKEN")
        or os.environ.get("SLACK_TOKEN")
    )
    if not token:
        sys.exit("ERROR: set SLACK_LISTS_TOKEN to a token with lists:read + lists:write.")
    return token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def slack_post(method: str, payload: dict) -> dict:
    r = httpx.post(f"{SLACK_API}/{method}", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def slack_get(method: str, params: dict) -> dict:
    r = httpx.get(f"{SLACK_API}/{method}", params=params, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def main() -> None:
    auth = slack_post("auth.test", {})
    if not auth.get("ok"):
        sys.exit(f"Auth failed: {auth.get('error')}")
    print("OK - token valid")
    print(f"  team: {auth.get('team')}  user: {auth.get('user')}  url: {auth.get('url')}")

    if len(sys.argv) > 1:
        list_id = sys.argv[1]
        res = slack_post("slackLists.items.list", {"list_id": list_id, "limit": 5})
        if not res.get("ok"):
            sys.exit(f"Could not read list {list_id}: {res.get('error')}")
        items = res.get("items", []) or []
        print(f"OK - read {len(items)} item(s) from list {list_id}")
        for it in items:
            sub = " [subtask]" if it.get("parent_record_id") else ""
            title = ""
            for f in it.get("fields", []) or []:
                if f.get("text"):
                    title = f["text"]
                    break
            print(f"  - {it.get('id')}{sub}: {title}")

        # Comments live in the channel that backs the List: same id, 'F' -> 'C'.
        channel = "C" + list_id[1:]
        history = slack_get("conversations.history", {"channel": channel, "limit": 200})
        if not history.get("ok"):
            err = history.get("error")
            hint = " (add groups:history to the token and reinstall the app)" if err == "missing_scope" else ""
            print(f"WARN - comments unreachable for {list_id}: {err}{hint}")
            return
        threads = [m for m in history.get("messages", []) or []
                   if m.get("subtype") == "list_record_comment"]
        discussed = [m for m in threads if (m.get("reply_count") or 0) > 0]
        print(f"OK - comments reachable: {len(threads)} thread(s) on this page, "
              f"{len(discussed)} with comments")


if __name__ == "__main__":
    main()
