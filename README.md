# Slack Lists MCP

A custom [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude
and other MCP clients) fully work with **Slack Lists** — including **subtasks**, which the
built-in Slack connector cannot do. Tasks live in Slack Lists; the assistant creates, reads,
updates, and nests them via the official Slack Lists API.

Works on **macOS, Windows, and Linux** (pure Python, stdio transport).

## What it can do

| Tool | Purpose |
|------|---------|
| `slack_lists_create_list` | Create a List (task list via `todo_mode`, or a custom column schema) |
| `slack_lists_get_columns` | List columns + types + **all select options** (`{value,label}`); also `subtask_columns` |
| `slack_lists_get_items` | Read items **incl. subtasks**, compact projection, column filter, pagination |
| `slack_lists_get_item` | Read one item |
| `slack_lists_create_item` | Create a top-level item (fields by column **name**, select by **label**) |
| `slack_lists_create_subtask` | **Create a subtask** under a parent item |
| `slack_lists_create_items` | **Batch**: create many items + their nested subtasks in one call |
| `slack_lists_update_item` | Update cells by name/label (status, assignee, due date, text…) |
| `slack_lists_delete_item` | Delete an item/subtask |

## Requirements

- A Slack workspace on a **paid plan** (Lists are a paid feature).
- A Slack **user token** with scopes `lists:read`, `lists:write` (and recommended `files:read`).
- **Python 3.10+**.

## 1. Create the Slack app and get a token

1. Go to **https://api.slack.com/apps** → **Create New App** → **From scratch** (or **From a manifest**).
2. Name it (e.g. `Lists for Claude`) and pick your workspace.
3. Open **OAuth & Permissions** → **Scopes → User Token Scopes** and add:
   - `lists:read`
   - `lists:write`
   - `files:read` *(recommended — gives full column names and ALL select options for existing lists)*
4. Click **Install to Workspace** → **Allow**.
5. Copy the **User OAuth Token** (starts with `xoxp-...`). Keep it secret.

<details>
<summary>Or create it from a manifest (pre-fills the scopes)</summary>

```json
{
  "display_information": { "name": "Lists for Claude" },
  "oauth_config": { "scopes": { "user": ["lists:read", "lists:write", "files:read"] } },
  "settings": { "org_deploy_enabled": false, "socket_mode_enabled": false }
}
```
</details>

## 2. Install dependencies (virtual environment)

**macOS / Linux**
```bash
cd slack-lists-mcp
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
cd slack-lists-mcp
py -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 3. Test the token

**macOS / Linux**
```bash
export SLACK_LISTS_TOKEN="xoxp-...your token..."
./.venv/bin/python test_connection.py            # verify token
./.venv/bin/python test_connection.py F0123ABCD  # optional: read a list
```

**Windows (PowerShell)**
```powershell
$env:SLACK_LISTS_TOKEN = "xoxp-...your token..."
.\.venv\Scripts\python test_connection.py
```

You should see `OK - token valid`.

## 4. Connect the server to your MCP client

This is a **local (stdio) MCP server** — you point your client at the `server.py` command.
It is **not** a remote/URL connector, so don't add it under a "Connectors (URL)" screen.

Use the **full absolute path** to the venv Python and to `server.py`.

**Claude desktop / Cowork:** Settings → **Developer** → **Local MCP servers** → **Edit Config**,
then add an entry under `mcpServers` (this is also the format for `claude_desktop_config.json`):

**macOS / Linux**
```json
{
  "mcpServers": {
    "slack_lists": {
      "command": "/absolute/path/to/slack-lists-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/slack-lists-mcp/server.py"],
      "env": { "SLACK_LISTS_TOKEN": "xoxp-...your token..." }
    }
  }
}
```

**Windows** (note the `Scripts\python.exe` path and double backslashes)
```json
{
  "mcpServers": {
    "slack_lists": {
      "command": "C:\\path\\to\\slack-lists-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\slack-lists-mcp\\server.py"],
      "env": { "SLACK_LISTS_TOKEN": "xoxp-...your token..." }
    }
  }
}
```

Save, then restart the server (toggle it off/on, or restart the app). It should show **running**.

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

## Notes & limits

- **Column names + full select options** come from `files.info` (needs `files:read`). Without
  it, the server falls back to inferring columns from existing rows (names = keys; only options
  already used are known). `get_columns` reports the source via its `source` field.
- **Subtasks have their own schema** (`subtask_columns`) — typically the parent's custom columns
  plus assignee/due/completed. The server resolves update fields against both schemas.
- **Completing a todo** (`todo_completed` column) is sent as a checkbox value; behavior can vary
  by list type — verify on your list and open an issue if it misbehaves.
- Lists API rate limits are ~20–50 requests/minute depending on the method.
- **Keep your token secret.** Anyone with it can read/write your Lists. Prefer storing it in the
  client's `env` config rather than committing it anywhere.

## License

MIT — see [LICENSE](LICENSE).
