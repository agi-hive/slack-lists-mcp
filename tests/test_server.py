"""Unit tests for the pure helpers and the tool layer (Slack is mocked via httpx.MockTransport)."""

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from server import SlackListError

# --------------------------------------------------------------------------- #
# Fixtures data
# --------------------------------------------------------------------------- #

COLUMNS = [
    {"id": "Col1", "key": "name", "name": "Task", "type": "text", "is_primary": True, "options": []},
    {
        "id": "Col2",
        "key": "status",
        "name": "Status",
        "type": "select",
        "is_primary": False,
        "options": [
            {"value": "opt_todo", "label": "To Do", "color": None},
            {"value": "opt_done", "label": "Done", "color": None},
        ],
    },
    {"id": "Col3", "key": "notes", "name": "Description", "type": "rich_text", "is_primary": False, "options": []},
    {"id": "Col4", "key": "due", "name": "Due Date", "type": "date", "is_primary": False, "options": []},
    {"id": "Col5", "key": "done", "name": "Completed", "type": "checkbox", "is_primary": False, "options": []},
]

FILES_INFO = {
    "ok": True,
    "file": {
        "permalink": "https://acme.slack.com/lists/T123/F0123ABCD",
        "list_metadata": {
            "schema": [
                {"id": "Col1", "key": "name", "name": "Task", "type": "text", "is_primary_column": True},
                {
                    "id": "Col2",
                    "key": "status",
                    "name": "Status",
                    "type": "select",
                    "options": {
                        "choices": [{"value": "opt_todo", "label": "To Do"}, {"value": "opt_done", "label": "Done"}]
                    },
                },
                {"id": "Col3", "key": "notes", "name": "Description", "type": "rich_text"},
            ],
            "subtask_schema": [
                {"id": "Col1", "key": "name", "name": "Task", "type": "text", "is_primary_column": True}
            ],
        },
    },
}

ITEM = {
    "id": "Rec1",
    "list_id": "F0123ABCD",
    "fields": [
        {"column_id": "Col3", "key": "notes", "text": "A very long description that must not become the title"},
        {"column_id": "Col1", "key": "name", "text": "Write launch post"},
        {"column_id": "Col2", "key": "status", "value": "opt_done"},
    ],
}
SUBTASK = {
    "id": "Rec2",
    "list_id": "F0123ABCD",
    "parent_record_id": "Rec1",
    "fields": [{"column_id": "Col1", "text": "Design"}],
}

# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_list_channel_id_maps_f_to_c():
    assert server._list_channel_id("F0123ABCD") == "C0123ABCD"
    assert server._list_channel_id(" C0123ABCD ") == "C0123ABCD"


@pytest.mark.parametrize("bad", ["", "X123", "F", None])
def test_list_channel_id_rejects_non_list_ids(bad):
    with pytest.raises(SlackListError, match="not a List id"):
        server._list_channel_id(bad)


def test_resolve_column_by_id_name_and_key():
    assert server._resolve_column(COLUMNS, "Col2")["name"] == "Status"
    assert server._resolve_column(COLUMNS, "status")["id"] == "Col2"
    assert server._resolve_column(COLUMNS, "  DUE DATE ")["id"] == "Col4"


def test_resolve_column_error_lists_available_columns():
    with pytest.raises(SlackListError) as exc:
        server._resolve_column(COLUMNS, "Priority")
    assert "Column 'Priority' not found" in str(exc.value)
    assert "Status(Col2)" in str(exc.value)


def test_resolve_option_by_label_or_value_and_error():
    status = COLUMNS[1]
    assert server._resolve_option(status, "done") == "opt_done"
    assert server._resolve_option(status, "opt_todo") == "opt_todo"
    with pytest.raises(SlackListError, match="Available: To Do=opt_todo, Done=opt_done"):
        server._resolve_option(status, "Urgent")


def test_resolve_option_passes_through_when_schema_has_no_options():
    derived = {"id": "ColX", "name": "Status", "type": "select", "options": []}
    assert server._resolve_option(derived, "whatever") == "whatever"


def test_cell_for_builds_payload_by_column_type():
    assert server._cell_for(COLUMNS[0], "Hello")["rich_text"][0]["elements"][0]["elements"][0]["text"] == "Hello"
    assert server._cell_for(COLUMNS[1], "Done") == {"column_id": "Col2", "select": ["opt_done"]}
    assert server._cell_for(COLUMNS[3], "2026-06-15") == {"column_id": "Col4", "date": ["2026-06-15"]}
    assert server._cell_for(COLUMNS[4], 1) == {"column_id": "Col5", "checkbox": True}


def test_project_item_prefers_primary_column_for_title_and_maps_select_labels():
    idx = server._col_lookup(COLUMNS)
    out = server._project_item(ITEM, idx, None)
    assert out["name"] == "Write launch post"
    assert out["fields"]["Status"] == "Done"
    assert out["is_subtask"] is False
    sub = server._project_item(SUBTASK, idx, None)
    assert sub == {
        "id": "Rec2",
        "parent_id": "Rec1",
        "is_subtask": True,
        "name": "Design",
        "fields": {"Task": "Design"},
    }


def test_project_item_column_filter():
    idx = server._col_lookup(COLUMNS)
    out = server._project_item(ITEM, idx, {"Status"})
    assert list(out["fields"]) == ["Status"]
    assert out["name"] == "Write launch post"  # the title is still found even when its column is filtered out


def test_iso_and_permalink():
    assert server._iso("1700000000.123456") == "2023-11-14T22:13:20Z"
    assert server._iso("not-a-ts") is None
    link = server._comment_permalink("https://acme.slack.com", "C01", "1700000000.123456", "1699999999.000100")
    assert link == "https://acme.slack.com/archives/C01/p1700000000123456?thread_ts=1699999999.000100&cid=C01"
    assert server._comment_permalink(None, "C01", "1", "1") is None


# --------------------------------------------------------------------------- #
# Server registration
# --------------------------------------------------------------------------- #

EXPECTED_TOOLS = {
    "slack_lists_create_list",
    "slack_lists_get_columns",
    "slack_lists_get_items",
    "slack_lists_get_item",
    "slack_lists_get_comments",
    "slack_lists_get_all_comments",
    "slack_lists_create_item",
    "slack_lists_create_subtask",
    "slack_lists_create_items",
    "slack_lists_update_item",
    "slack_lists_delete_item",
}


@pytest.mark.anyio
async def test_all_tools_registered_with_annotations_and_output_schema():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    for name, tool in tools.items():
        assert tool.annotations is not None, name
        assert tool.output_schema and tool.output_schema["type"] == "object", name
        assert tool.annotations.read_only_hint is name.startswith("slack_lists_get_"), name
        assert tool.annotations.destructive_hint is (name == "slack_lists_delete_item"), name


@pytest.mark.anyio
async def test_missing_token_is_a_tool_error(monkeypatch):
    for var in server.TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ToolError, match="SLACK_LISTS_TOKEN"):
        await server.mcp.call_tool("slack_lists_get_columns", {"list_id": "F0123ABCD"})


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_slack_error_becomes_actionable_tool_error(slack):
    slack.on("files.info", {"ok": False, "error": "missing_scope", "needed": "files:read"})
    slack.on("slackLists.items.list", {"ok": False, "error": "invalid_auth"})
    with pytest.raises(SlackListError, match=r"invalid_auth.*reinstall the Slack app"):
        await server.slack_lists_get_columns("F0123ABCD")


@pytest.mark.anyio
async def test_429_is_retried_with_retry_after(slack, caplog):
    slack.on(
        "files.info",
        httpx.Response(429, headers={"Retry-After": "2"}, json={"ok": False, "error": "ratelimited"}),
        FILES_INFO,
    )
    with caplog.at_level("WARNING", logger="slack_lists_mcp"):
        out = await server.slack_lists_get_columns("F0123ABCD")
    assert out["source"] == "files.info"
    assert [m for m, _ in slack.calls] == ["files.info", "files.info"]
    assert "rate limited; retrying in 2.0s" in caplog.text


@pytest.mark.anyio
async def test_429_gives_up_after_max_attempts(slack):
    limited = httpx.Response(429, headers={"Retry-After": "1"}, json={"ok": False, "error": "ratelimited"})
    slack.on("files.info", limited, limited, limited)
    slack.on("slackLists.items.list", limited, limited, limited)
    with pytest.raises(SlackListError, match="rate limited"):
        await server.slack_lists_get_columns("F0123ABCD")
    assert len([m for m, _ in slack.calls if m == "files.info"]) == server.MAX_ATTEMPTS


@pytest.mark.anyio
async def test_shared_client_is_reused(slack):
    slack.on("files.info", FILES_INFO)
    first = server._client()
    await server.slack_lists_get_columns("F0123ABCD")
    await server.slack_lists_get_columns("F0123ABCD", refresh=True)
    assert server._client() is first


# --------------------------------------------------------------------------- #
# Tools against a fake Slack
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_get_items_compact_projection(slack):
    slack.on("files.info", FILES_INFO)
    slack.on(
        "slackLists.items.list", {"ok": True, "items": [ITEM, SUBTASK], "response_metadata": {"next_cursor": "abc"}}
    )
    out = await server.slack_lists_get_items("F0123ABCD", limit=10)
    assert out["count"] == 2 and out["next_cursor"] == "abc"
    assert out["items"][0]["name"] == "Write launch post"
    assert out["items"][0]["fields"]["Status"] == "Done"
    assert out["items"][1]["is_subtask"] is True
    method, body = slack.calls[0]
    assert method == "slackLists.items.list" and body == {"list_id": "F0123ABCD", "limit": 10}


@pytest.mark.anyio
async def test_schema_falls_back_to_rows_without_files_read(slack):
    slack.on("files.info", {"ok": False, "error": "missing_scope", "needed": "files:read"})
    slack.on("slackLists.items.list", {"ok": True, "items": [ITEM]})
    out = await server.slack_lists_get_columns("F0123ABCD")
    assert out["source"] == "derived"
    assert {c["id"] for c in out["columns"]} == {"Col1", "Col2", "Col3"}


@pytest.mark.anyio
async def test_create_item_resolves_names_and_labels(slack):
    slack.on("files.info", FILES_INFO)
    slack.on("slackLists.items.create", {"ok": True, "item": {"id": "RecNew", "list_id": "F0123ABCD", "fields": []}})
    out = await server.slack_lists_create_item("F0123ABCD", title="New task", fields={"Status": "done"})
    assert out == {
        "created": True,
        "item_id": "RecNew",
        "item": server._simplify_full({"id": "RecNew", "list_id": "F0123ABCD", "fields": []}),
    }
    _, body = next(c for c in slack.calls if c[0] == "slackLists.items.create")
    assert body["initial_fields"] == [
        {"column_id": "Col1", "rich_text": [server._rich_text("New task")]},
        {"column_id": "Col2", "select": ["opt_done"]},
    ]


@pytest.mark.anyio
async def test_update_item_requires_fields_or_cells():
    with pytest.raises(SlackListError, match="Provide `fields`"):
        await server.slack_lists_update_item("F0123ABCD", "Rec1")


@pytest.mark.anyio
async def test_update_item_sets_row_id_on_every_cell(slack):
    slack.on("files.info", FILES_INFO)
    slack.on("slackLists.items.update", {"ok": True})
    out = await server.slack_lists_update_item("F0123ABCD", "Rec1", fields={"Status": "To Do", "Task": "Renamed"})
    assert out == {"updated": True, "item_id": "Rec1", "cells_updated": 2}
    _, body = next(c for c in slack.calls if c[0] == "slackLists.items.update")
    assert all(cell["row_id"] == "Rec1" for cell in body["cells"])


@pytest.mark.anyio
async def test_create_items_reports_partial_failures_inline(slack):
    slack.on("files.info", FILES_INFO)
    slack.on(
        "slackLists.items.create",
        {"ok": True, "item": {"id": "RecA", "fields": []}},
        {"ok": False, "error": "internal_error"},
        {"ok": True, "item": {"id": "RecB", "fields": []}},
    )
    out = await server.slack_lists_create_items(
        "F0123ABCD", items=[{"title": "A", "subtasks": [{"title": "A.1"}]}, {"title": "B"}]
    )
    assert out["errors"] == 1
    assert out["created"][0]["item_id"] == "RecA"
    assert "error" in out["created"][0]["subtasks"][0]
    assert out["created"][1]["item_id"] == "RecB"


@pytest.mark.anyio
async def test_create_items_fails_when_nothing_was_created(slack):
    slack.on("files.info", FILES_INFO)
    slack.on("slackLists.items.create", {"ok": False, "error": "internal_error"})
    with pytest.raises(SlackListError, match="No item could be created"):
        await server.slack_lists_create_items("F0123ABCD", items=[{"title": "A"}])


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #

HISTORY = {
    "ok": True,
    "has_more": False,
    "messages": [
        {
            "ts": "1700000000.000100",
            "subtype": "list_record_comment",
            "slack_list": {"list_record_id": "Rec1"},
            "reply_count": 2,
            "latest_reply": "1700000200.000100",
        },
        {
            "ts": "1700000001.000100",
            "subtype": "list_record_comment",
            "slack_list": {"list_record_id": "Rec9"},
            "reply_count": 0,
        },
        {"ts": "1700000002.000100", "text": "a normal channel message"},
    ],
}
REPLIES = {
    "ok": True,
    "has_more": False,
    "messages": [
        {"ts": "1700000000.000100", "subtype": "list_record_comment", "text": "A comment was added"},
        {"ts": "1700000100.000100", "user": "U1", "text": "Looks good"},
        {"ts": "1700000200.000100", "user": "U2", "text": "Shipping Friday", "edited": {"ts": "1"}},
    ],
}


@pytest.mark.anyio
async def test_get_comments_reads_thread_and_resolves_names(slack):
    slack.on("files.info", FILES_INFO)
    slack.on("conversations.history", HISTORY)
    slack.on("conversations.replies", REPLIES)
    slack.on("users.info", {"ok": True, "user": {"profile": {"display_name": "Nino"}}})
    out = await server.slack_lists_get_comments("F0123ABCD", "Rec1")
    assert out["comment_count"] == 2
    assert out["comments"][0]["user_name"] == "Nino"
    assert out["comments"][1]["edited"] is True
    assert out["comments"][1]["permalink"].startswith("https://acme.slack.com/archives/C0123ABCD/p1700000200000100")
    _, params = next(c for c in slack.calls if c[0] == "conversations.history")
    assert params["channel"] == "C0123ABCD"


@pytest.mark.anyio
async def test_get_comments_on_uncommented_item_is_not_an_error(slack):
    slack.on("conversations.history", HISTORY)
    out = await server.slack_lists_get_comments("F0123ABCD", "RecNobody")
    assert out["comment_count"] == 0 and "note" in out


@pytest.mark.anyio
async def test_comment_index_is_cached_until_refresh(slack):
    slack.on("conversations.history", HISTORY)
    await server.slack_lists_get_comments("F0123ABCD", "RecNobody")
    await server.slack_lists_get_comments("F0123ABCD", "RecNobody")
    assert len([m for m, _ in slack.calls if m == "conversations.history"]) == 1
    await server.slack_lists_get_comments("F0123ABCD", "RecNobody", refresh=True)
    assert len([m for m, _ in slack.calls if m == "conversations.history"]) == 2


@pytest.mark.anyio
async def test_get_item_degrades_gracefully_when_comment_scope_is_missing(slack):
    slack.on("files.info", FILES_INFO)
    slack.on("slackLists.items.info", {"ok": True, "item": ITEM})
    slack.on("conversations.history", {"ok": False, "error": "missing_scope", "needed": "groups:history"})
    out = await server.slack_lists_get_item("F0123ABCD", "Rec1", include_comments=True)
    assert out["name"] == "Write launch post"
    assert "groups:history" in out["comments_error"]
    assert "comments" not in out


@pytest.mark.anyio
async def test_get_all_comments_groups_by_discussed_item(slack):
    slack.on("files.info", FILES_INFO)
    slack.on("conversations.history", HISTORY)
    slack.on("conversations.replies", REPLIES)
    slack.on("slackLists.items.list", {"ok": True, "items": [ITEM, SUBTASK], "response_metadata": {"next_cursor": ""}})
    out = await server.slack_lists_get_all_comments("F0123ABCD", with_names=False)
    assert out["threads_total"] == 2 and out["items_with_comments"] == 1 and out["comments_total"] == 2
    assert out["items"][0]["item_id"] == "Rec1" and out["items"][0]["name"] == "Write launch post"
    assert all(c["user_name"] is None for c in out["items"][0]["comments"])
    assert not any(m == "users.info" for m, _ in slack.calls)
