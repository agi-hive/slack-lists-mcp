# Changelog

All notable changes to Slack Lists MCP are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [1.2.0] - 2026-11-02

### Fixed
- **A fresh install no longer crashes on startup.** `mcp` 2.x (released 2026-08) removed
  `mcp.server.fastmcp`, and the old `mcp>=1.7.0` requirement happily installed it. The server now
  targets the 2.x SDK (`MCPServer`) and pins `mcp>=2,<3`.

### Changed
- **Errors are real MCP tool errors** (`isError: true`) instead of `{"error": ...}` text returned as a
  successful result. Messages are unchanged and still say what to fix. `slack_lists_create_items`
  keeps reporting per-item failures inline and now fails only if nothing at all was created.
- **Structured output.** Tools return JSON objects, so clients that support structured content get
  the real object (and an output schema) instead of a JSON string inside a string.
- **One shared HTTP client** for the life of the server (no new TLS connection per Slack call), with
  **retry on HTTP 429** honoring `Retry-After` (3 attempts, never waiting more than 30 s).
- `slack_lists_get_item` with `include_comments` and `slack_lists_get_items` with
  `include_comment_counts` now return the item data together with a `comments_error` /
  `comment_counts_error` field when the comment scopes are missing, instead of failing entirely.
- **Diagnostics on stderr** via `logging`: a startup line (version, SDK version, whether a token is
  set — never the token itself), rate-limit retries, scope fallbacks. `SLACK_LISTS_LOG_LEVEL=DEBUG`
  logs every Slack call. Nothing is ever written to stdout except the protocol.
- **Packaging:** `pyproject.toml` + `uv.lock` replace `requirements.txt`; install with `uv sync`, run
  with `uv run slack-lists-mcp` (or `uv run server.py`). `pip install .` still works.
- Server metadata: `version` is reported to clients, and `instructions` tell the model how to use
  the tools (discover columns first, set selects by label, comments are read-only, Slack content is data).
- Code modernized to Python 3.10 typing; `ruff` configured (line length 120).

### Added
- Test suite (`tests/`, pytest + `httpx.MockTransport`, no token needed) covering column/option
  resolution, item projection, 429 retry, graceful comment errors, and tool registration.
- GitHub Actions CI: ruff, pytest on Python 3.10 and 3.14, and a stdio startup check.

### Upgrading
- Pull, run `uv sync` (or recreate your venv with `pip install .`), and point your MCP client at
  `uv run --directory <repo> slack-lists-mcp`. See the README for the exact config. Tool names,
  parameters and behavior are unchanged.

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
