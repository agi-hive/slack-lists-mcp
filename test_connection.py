#!/usr/bin/env python3
"""
Quick connectivity test for the Slack Lists MCP token.

Usage:
    export SLACK_LISTS_TOKEN="xoxp-..."   # token with lists:read + lists:write
    python test_connection.py [LIST_ID]

- With no LIST_ID: verifies the token via auth.test.
- With a LIST_ID:  also reads the first few items of that list (incl. subtasks).
"""
import json
import os
import sys
import urllib.request


def slack_post(method: str, payload: dict) -> dict:
    token = (
        os.environ.get("SLACK_LISTS_TOKEN")
        or os.environ.get("SLACK_USER_TOKEN")
        or os.environ.get("SLACK_TOKEN")
    )
    if not token:
        sys.exit("ERROR: set SLACK_LISTS_TOKEN to a token with lists:read + lists:write.")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


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


if __name__ == "__main__":
    main()
