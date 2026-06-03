# Slack Lists MCP

A custom MCP server that lets Claude fully work with **Slack Lists** — including
**subtasks**, which the built-in Slack connector cannot do. Tasks live in Slack
Lists; Claude creates, reads, updates, and nests them via the Slack Lists API.

## What it can do

| Tool | Purpose |
|------|---------|
| `slack_lists_create_list` | Create a List (task list via `todo_mode`, or custom columns) |
| `slack_lists_get_items` | Read items **including subtasks** (paginated) |
| `slack_lists_get_item` | Read one item |
| `slack_lists_get_columns` | Discover a List's column IDs |
| `slack_lists_create_item` | Create a top-level item |
| `slack_lists_create_subtask` | **Create a subtask** under a parent item |
| `slack_lists_update_item` | Update cells (status, assignee, due date, text…) |
| `slack_lists_delete_item` | Delete an item/subtask |

## Requirements

- A Slack workspace on a **paid plan** (Lists are a paid feature — you already have them).
- A Slack token with the `lists:read` and `lists:write` scopes.
- Python 3.10+.

## 1. Create the Slack app and get a token

1. Go to **https://api.slack.com/apps** → **Create New App** → **From scratch**.
2. Name it (e.g. `Lists for Claude`) and pick your **AGI-HIVE** workspace.
3. In the left menu open **OAuth & Permissions**.
4. Scroll to **Scopes → User Token Scopes** and add:
   - `lists:read`
   - `lists:write`
   - `files:read`  *(recommended — gives full column names and ALL select options for existing lists)*
   (Use *User* token scopes so Lists are created under your own account.)
5. Scroll up and click **Install to Workspace** → **Allow**.
6. Copy the **User OAuth Token** (starts with `xoxp-...`). Keep it secret.

## 2. Install dependencies

```bash
cd "slack-lists-mcp"
pip install -r requirements.txt
```

## 3. Test the token

```bash
export SLACK_LISTS_TOKEN="xoxp-...your token..."
python test_connection.py
# Optional: also read an existing list
python test_connection.py F0123ABCD
```

You should see `OK - token valid`.

## 4. Run / connect the server

The server speaks MCP over stdio. To connect it to Claude (desktop / Cowork), add
it as a local MCP server. Example config entry:

```json
{
  "mcpServers": {
    "slack_lists": {
      "command": "python",
      "args": ["/Users/guram/Documents/oClaude/PDLC/slack-lists-mcp/server.py"],
      "env": { "SLACK_LISTS_TOKEN": "xoxp-...your token..." }
    }
  }
}
```

> Tip: Claude can wire this up for you — just ask, and have the token ready.

## How fields work (v2 — by name)

You normally set fields by **human column names and labels** — the server resolves
column IDs, types, and select option values for you:

```jsonc
// create_item / update_item
{
  "list_id": "F0...",
  "title": "Write launch post",
  "fields": {
    "Status":   "In Progress",      // select by label OR value
    "Priority": "High",
    "Due Date": "2026-06-15",
    "Assignee": ["U12345"],
    "Done":     false
  }
}
```

If a name or option is wrong, the error tells you what's available, e.g.
`Option 'Urgent' not found for column 'Priority'. Available: Low=low, High=high.`

Discover names/types/options anytime with `slack_lists_get_columns` (returns
`columns` and `subtask_columns`, each with `id`, `name`, `type`, and `options:[{value,label}]`).

Advanced: pass explicit `cells` instead of/with `fields`:
`[{ "column": "Status", "select": "Done" }]`.

### Batch + nested create

Create many items and their subtasks in one call with `slack_lists_create_items`:

```jsonc
{
  "list_id": "F0...",
  "items": [
    { "title": "Landing page", "fields": {"Priority":"High"},
      "subtasks": [ {"title":"Design"}, {"title":"Build"} ] }
  ]
}
```

### get_items is compact by default

`slack_lists_get_items` returns `{id, parent_id, is_subtask, name, fields:{<ColName>:<value>}}`
with select values shown as labels and rich_text blobs stripped. Use `columns:["Status","Priority"]`
to fetch only some fields, `limit`/`cursor` to paginate, and `compact:false` for raw fields.

## Subtasks

```text
1. create_item        -> returns the parent item id (Rec...)
2. create_subtask     -> pass parent_item_id = that Rec..., plus title/fields
3. get_items          -> subtasks come back with "is_subtask": true
```

Subtasks use the list's separate `subtask_schema` columns (also returned by
`slack_lists_create_list`).

## Notes & limits

- Column names + full select options come from `files.info` (needs `files:read`). Without
  that scope the server falls back to inferring columns from existing rows: column names
  appear as keys and only options already used in the list are known. `get_columns` reports
  which source was used via the `source` field.
- Subtasks have their **own** schema (`subtask_columns`) — usually the parent's custom
  columns plus assignee/due/completed. Set subtask fields against those.
- Lists API rate limits are ~20–50 requests/minute depending on the method.
- Keep your token secret; anyone with it can read/write your Lists.
