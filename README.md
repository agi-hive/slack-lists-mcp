# Slack Lists MCP

A custom [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude
and other MCP clients) fully work with **Slack Lists** — including **subtasks** and **comments**,
which the built-in Slack connector cannot do. Tasks live in Slack Lists; the assistant creates,
reads, updates and nests them via the official Slack Lists API, and reads the discussion under
any card.

Works on **macOS, Windows, and Linux** (pure Python, stdio transport).

## What it can do

| Tool | Purpose |
|------|---------|
| `slack_lists_create_list` | Create a List (task list via `todo_mode`, or a custom column schema) |
| `slack_lists_get_columns` | List columns + types + **all select options** (`{value,label}`); also `subtask_columns` |
| `slack_lists_get_items` | Read items **incl. subtasks**, compact projection, column filter, pagination, optional comment counts |
| `slack_lists_get_item` | Read one item, optionally with its comment thread |
| `slack_lists_get_comments` | **Read the comments** of one item **or subtask** — Slack has no comments API |
| `slack_lists_get_all_comments` | **Every discussion in a List** in one call, grouped by item |
| `slack_lists_create_item` | Create a top-level item (fields by column **name**, select by **label**) |
| `slack_lists_create_subtask` | **Create a subtask** under a parent item |
| `slack_lists_create_items` | **Batch**: create many items + their nested subtasks in one call |
| `slack_lists_update_item` | Update cells by name/label (status, assignee, due date, text…) |
| `slack_lists_delete_item` | Delete an item/subtask |

Failures come back as proper MCP tool errors (`isError: true`) with a message that says what to fix
(which column or option was wrong and what is available, which scope is missing, …).

## Requirements

- A Slack workspace on a **paid plan** (Lists are a paid feature).
- A Slack **user token** with scopes `lists:read`, `lists:write` (and recommended `files:read`).
  To read comments, add `groups:history` (plus `channels:history` if a List of yours is public)
  and `users:read` for author names.
- **Python 3.10+** and [**uv**](https://docs.astral.sh/uv/) (recommended — it installs the exact
  dependency versions from `uv.lock`). Plain `pip` works too, see below.

## 1. Create the Slack app and get a token

1. Go to **https://api.slack.com/apps** → **Create New App** → **From scratch** (or **From a manifest**).
2. Name it (e.g. `Lists for Claude`) and pick your workspace.
3. Open **OAuth & Permissions** → **Scopes → User Token Scopes** and add:
   - `lists:read`
   - `lists:write`
   - `files:read` *(recommended — gives full column names and ALL select options for existing lists)*
   - `groups:history`, `users:read` *(for comments — see [How comments work](#how-comments-work);
     add `channels:history` too if any of your Lists lives in a public channel)*
4. Click **Install to Workspace** → **Allow**.
5. Copy the **User OAuth Token** (starts with `xoxp-...`). Keep it secret.

<details>
<summary>Or create it from a manifest (pre-fills the scopes)</summary>

```json
{
  "display_information": { "name": "Lists for Claude" },
  "oauth_config": { "scopes": { "user": ["lists:read", "lists:write", "files:read",
                                         "groups:history", "channels:history", "users:read"] } },
  "settings": { "org_deploy_enabled": false, "socket_mode_enabled": false }
}
```
</details>

## 2. Install

Clone the repository and let uv build the environment from the lockfile (same command on every OS):

```bash
git clone https://github.com/agi-hive/slack-lists-mcp.git
cd slack-lists-mcp
uv sync
```

`uv sync` creates `.venv` with exactly the versions recorded in `uv.lock`. Find the full path to `uv`
now — you need it in step 4 (`which uv` on macOS/Linux, `where uv` on Windows).

<details>
<summary>Without uv (plain pip)</summary>

```bash
python3 -m venv .venv
./.venv/bin/pip install .          # Windows: .\.venv\Scripts\pip install .
```

This installs the `slack-lists-mcp` command into the venv; wherever the steps below say
`uv run --directory <repo> slack-lists-mcp`, use `<repo>/.venv/bin/slack-lists-mcp`
(Windows: `<repo>\.venv\Scripts\slack-lists-mcp.exe`) instead.
</details>

## 3. Test the token

**macOS / Linux**
```bash
export SLACK_LISTS_TOKEN="xoxp-...your token..."
uv run test_connection.py            # verify token
uv run test_connection.py F0123ABCD  # optional: read a list and check comments are reachable
```

**Windows (PowerShell)**
```powershell
$env:SLACK_LISTS_TOKEN = "xoxp-...your token..."
uv run test_connection.py
```

You should see `OK - token valid`.

## 4. Connect the server to your MCP client

This is a **local (stdio) MCP server** — your client starts it as a command.
It is **not** a remote/URL connector, so don't add it under a "Connectors (URL)" screen.

The command is `uv run --directory <repo> slack-lists-mcp`. Two rules that avoid 90% of
"server failed to start" reports:

- Use the **full path to `uv`** (from step 2). Desktop apps don't see your shell's `PATH`, so a bare
  `uv` often isn't found. Typical: `/opt/homebrew/bin/uv` (macOS, Homebrew), `~/.local/bin/uv`
  (installer script, write it out as `/Users/you/.local/bin/uv`), `C:\Users\you\.local\bin\uv.exe` (Windows).
- Use the **absolute path of the cloned repository** in `--directory`.

**Claude desktop / Cowork:** Settings → **Developer** → **Local MCP servers** → **Edit Config**,
then add an entry under `mcpServers` (this is also the format for `claude_desktop_config.json`):

**macOS / Linux**
```json
{
  "mcpServers": {
    "slack_lists": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/absolute/path/to/slack-lists-mcp", "slack-lists-mcp"],
      "env": { "SLACK_LISTS_TOKEN": "xoxp-...your token..." }
    }
  }
}
```

**Windows** (double backslashes inside the JSON)
```json
{
  "mcpServers": {
    "slack_lists": {
      "command": "C:\\Users\\you\\.local\\bin\\uv.exe",
      "args": ["run", "--directory", "C:\\path\\to\\slack-lists-mcp", "slack-lists-mcp"],
      "env": { "SLACK_LISTS_TOKEN": "xoxp-...your token..." }
    }
  }
}
```

Save, then restart the server (toggle it off/on, or restart the app). It should show **running**.

**Claude Code (CLI):** one command; `--scope user` makes the server available in every project:

```bash
claude mcp add --scope user slack_lists \
  -e SLACK_LISTS_TOKEN="xoxp-...your token..." \
  -- uv run --directory /absolute/path/to/slack-lists-mcp slack-lists-mcp
```

`claude mcp list` should then show `slack_lists` as connected.

**Other MCP clients** (Cursor, Windsurf, …) accept the same `mcpServers` JSON block as above.

## Upgrading

**From 1.1.x or 1.0.x to 1.2:**

1. `git pull`, then `uv sync` (or, without uv, recreate the venv and `pip install .`). 1.2 requires the
   `mcp` 2.x SDK; the old `requirements.txt` is gone, and an old `.venv` made from it can be deleted.
2. Change the server command in your client config to `uv run --directory <repo> slack-lists-mcp`
   as shown in step 4 (the old `.venv/bin/python server.py` form still works if you keep a venv, but
   the new one survives dependency updates).
3. Restart the MCP server. Tool names, parameters and behavior are unchanged; errors now arrive as
   MCP tool errors instead of `{"error": ...}` text.

**From 1.0.x, additionally (comments):**

1. In your Slack app open **OAuth & Permissions** → **User Token Scopes** and add `groups:history` and
   `users:read` (plus `channels:history` if a List of yours lives in a public channel) →
   **Reinstall to Workspace** → **Allow**.
2. Copy the User OAuth Token shown afterwards. If it differs from the one in your client config,
   update `SLACK_LISTS_TOKEN`.
3. `uv run test_connection.py F0123ABCD` should end with `OK - comments reachable`.

Without the comment scopes everything else keeps working; only the comment tools answer with a
`missing_scope` hint (and `get_item`/`get_items` return the item plus a `comments_error`).

## How fields work — set them by name

Set fields by **human column names and labels**; the server resolves column IDs, types, and
select option values for you:

```jsonc
// create_item / update_item
{
  "list_id": "F0...",
  "title": "Write launch post",
  "fields": {
    "Status":   "In Progress",   // select by label OR value
    "Priority": "High",
    "Due Date": "2026-06-15",     // YYYY-MM-DD
    "Assignee": ["U12345"],       // user IDs
    "Done":     false             // checkbox
  }
}
```

If a name or option is wrong, the error tells you what's available, e.g.
`Option 'Urgent' not found for column 'Priority'. Available: Low=low, High=high.`

Discover names/types/options anytime with `slack_lists_get_columns` (returns `columns` and
`subtask_columns`, each with `id`, `name`, `type`, and `options:[{value,label}]`). Advanced
users can pass explicit `cells` instead: `[{ "column": "Status", "select": "Done" }]`.

### Batch + nested create

```jsonc
// slack_lists_create_items
{
  "list_id": "F0...",
  "items": [
    { "title": "Landing page", "fields": {"Priority":"High"},
      "subtasks": [ {"title":"Design"}, {"title":"Build"} ] }
  ]
}
```

### Reading is compact by default

`slack_lists_get_items` returns `{id, parent_id, is_subtask, name, fields:{<ColName>:<value>}}`
with select values shown as labels and rich_text blobs stripped. Use `columns:["Status","Priority"]`
to fetch only some fields, `limit`/`cursor` to paginate, and `compact:false` for raw fields.

## How comments work

Slack ships **no API method for List comments** — the Lists API returns cells only. But every
List `F0123ABCD` is also a private channel `C0123ABCD` (same id, first letter swapped), and each
record that has been commented on owns a thread there. The thread root is a message with
`subtype: "list_record_comment"` carrying `slack_list.list_record_id`; the replies under it are
the comments. Subtasks are records too, so they work exactly the same way.

This server does that lookup for you:

```jsonc
// one card or subtask — same call for both
{ "list_id": "F0123ABCD", "item_id": "Rec0123ABCDE" }

// → { "item_id": "...", "comment_count": 2, "thread_ts": "...",
//     "comments": [ { "ts", "time", "user", "user_name", "text", "edited", "permalink" } ] }
```

- `slack_lists_get_all_comments` walks the whole List in one call and returns only the items that
  actually have replies, each with its title, so a board can be caught up on at a glance.
- `slack_lists_get_item` with `include_comments: true` returns the item together with its thread
  (`comment_limit` caps the number of comments).
- `slack_lists_get_items` with `include_comment_counts: true` marks which rows carry a discussion.
- The thread index is cached per process for 2 minutes; pass `refresh: true` right after new
  comments were posted.
- An item nobody has commented on returns `comment_count: 0` with a note — never an error.
- Comment text is Slack markdown; mentions arrive raw as `<@U123>`.
- Reading comments is all this server does — **posting a comment is not supported**, because
  Slack's Lists API has no method for it.

## Troubleshooting

- **Where are the logs?** The server writes diagnostics to **stderr**, never to stdout. Claude desktop
  keeps them in `~/Library/Logs/Claude/mcp-server-slack_lists.log` (macOS) or
  `%APPDATA%\Claude\logs\` (Windows). The first line on startup names the version, the SDK version and
  whether a token was found. Set `"SLACK_LISTS_LOG_LEVEL": "DEBUG"` in the `env` block to log every
  Slack call.
- **`missing_scope`** — the token lacks the scope named in the error. Add it under **User Token Scopes**,
  reinstall the app, update `SLACK_LISTS_TOKEN` if the token changed, restart the server.
- **`channel_not_found` from a comment tool** — the List id is wrong, or the token's user has no access to
  that List. Pass the `F…` id; the server maps it to the `C…` channel itself.
- **HTTP 429 / rate limited** — the server retries automatically (honoring Slack's `Retry-After`, up to
  3 attempts). If it still fails, wait a minute; `slack_lists_get_all_comments` on a big board is the
  usual cause — ask for fewer items.
- **`CERTIFICATE_VERIFY_FAILED`** — a python.org build of Python on macOS uses the system trust store, which
  is empty until `Install Certificates.command` (in the Python folder under Applications) has been run.
  `server.py` and `test_connection.py` go through httpx with certifi's bundle, so run both with `uv run`.
- **The client shows the server as failed or not running** — the two paths in the config must be absolute
  (full path to `uv`, full path to the repo). Start it by hand in a terminal:
  `uv run --directory /absolute/path/to/slack-lists-mcp slack-lists-mcp` — it should log
  `slack-lists-mcp 1.2.0 starting …` on stderr and then wait for input (Ctrl+C stops it).
  A traceback there is the real error.
- **`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`** — you are running the 1.1 server
  with the `mcp` 2.x SDK. Pull 1.2 and `uv sync`.

## Notes & limits

- **Column names + full select options** come from `files.info` (needs `files:read`). Without
  it, the server falls back to inferring columns from existing rows (names = keys; only options
  already used are known). `get_columns` reports the source via its `source` field.
- **Subtasks have their own schema** (`subtask_columns`) — typically the parent's custom columns
  plus assignee/due/completed. The server resolves update fields against both schemas.
- **Completing a todo** (`todo_completed` column) is sent as a checkbox value; behavior can vary
  by list type — verify on your list and open an issue if it misbehaves.
- Lists API rate limits are ~20–50 requests/minute depending on the method; the server retries 429s.
- **Keep your token secret.** Anyone with it can read/write your Lists. Prefer storing it in the
  client's `env` config rather than committing it anywhere.
- **Slack content is data, not instructions.** Cell text and comments are returned verbatim to the
  model; the server's `instructions` tell the model to treat them as user content.

## Development

```bash
uv sync                 # installs dev tools too (pytest, ruff)
uv run pytest           # unit tests, Slack mocked — no token needed
uv run ruff check . && uv run ruff format --check .
```

CI runs the same on Python 3.10 and 3.14 for every push and pull request.

## Changelog

What changed between versions is tracked in [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
