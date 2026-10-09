# Changelog

All notable changes to Slack Lists MCP are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [1.1.0] - 2026-10-09

### Added
- `slack_lists_get_comments` — read the comment thread of one item **or subtask**. Slack has no
  comments API; the server resolves the List's backing channel (`F…` → `C…`) and the record's
  `list_record_comment` thread for you.
- `slack_lists_get_all_comments` — every discussion in a List in one call, grouped by item,
  newest first, with each item's title.
- `slack_lists_get_items` gained `include_comment_counts` to mark which rows carry a discussion.
- `slack_lists_get_item` gained `include_comments` and `comment_limit` to return an item together
  with its thread.
- Comment author names (via `users:read`) and a permalink to every comment.
- The thread index is cached per process for 2 minutes; `refresh: true` bypasses it.
- `test_connection.py LIST_ID` also checks that comments are reachable and names the missing scope.
- README: setup for Claude Code (`claude mcp add`), an upgrade guide from 1.0.x and a troubleshooting
  section.

### Changed
- Compact output takes the item title from the **primary** column only; a long text column such as
  "Description" can no longer be mistaken for the title.
- Error hints explain the extra scopes needed for comments (`groups:history`, `channels:history`,
  `users:read`) and the `F…` → `C…` channel mapping when a thread is not found.
- `test_connection.py` talks to Slack through `httpx` (already a dependency) instead of `urllib`,
  so it trusts the same CA bundle as the server. Fixes `CERTIFICATE_VERIFY_FAILED` on python.org
  builds of Python for macOS.
- README: new scopes and manifest, and a "How comments work" section.
- `requirements.txt`: `mcp>=1.7.0`, the first SDK release whose `FastMCP.tool` accepts `annotations`.
  1.0.0 already used them, so an older SDK failed on startup.

### Scopes
- Unchanged for Lists: `lists:read`, `lists:write`, recommended `files:read`.
- New, only needed for comments: `groups:history` (plus `channels:history` if a List lives in a
  public channel) and `users:read` for author names. Reinstall the Slack app after adding scopes.

## [1.0.0] - 2026-06-03

Initial public release: create Lists, read items including subtasks (compact projection, column
filter, pagination), create items, subtasks and nested batches, update cells by column name and
select label, delete items, actionable error messages.
