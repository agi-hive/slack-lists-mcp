#!/usr/bin/env python3
"""
Slack Lists MCP Server (slack_lists_mcp) — v2

Full Slack Lists access for an LLM, including subtasks, with ergonomics:
  - explicit per-tool parameter schemas (named params, types, descriptions)
  - real column metadata: names + types + select options (id/label) via files.info
  - set fields by human names/labels (e.g. {"Status": "Done"}) — auto label->value
  - compact get_items output (no rich_text blobs), column filtering, pagination
  - batch + nested create (item with its subtasks in one call)
  - actionable errors (which column/option was wrong + what's available)

Auth: env SLACK_LISTS_TOKEN = Slack user token with scopes:
  required: lists:read, lists:write
  recommended: files:read   (enables full column names + ALL select options)

Requires a paid Slack plan (Lists feature).
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, Dict, List, Optional, Union

import httpx
from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("slack_lists_mcp")

SLACK_API_BASE = "https://slack.com/api"
TOKEN_ENV_VARS = ("SLACK_LISTS_TOKEN", "SLACK_USER_TOKEN", "SLACK_TOKEN")
HTTP_TIMEOUT = 30.0
DEFAULT_ITEM_LIMIT = 50

# Per-process cache of normalized list schemas: list_id -> {"schema":[...], "subtask_schema":[...], "source":str}
_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}

# Column types that accept plain text (rich_text payload)
_TEXT_TYPES = {"text", "rich_text"}
_SELECT_TYPES = {"select", "multi_select"}
_USER_TYPES = {"user", "assignee", "todo_assignee"}
_DATE_TYPES = {"date", "due_date", "todo_due_date"}
_BOOL_TYPES = {"checkbox", "completed", "todo_completed"}


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class SlackListError(Exception):
    """Actionable error surfaced to the agent."""


def _get_token() -> str:
    for var in TOKEN_ENV_VARS:
        val = os.environ.get(var)
        if val:
            return val.strip()
    raise SlackListError(
        "No Slack token. Set SLACK_LISTS_TOKEN to a user token with scopes "
        "lists:read, lists:write (and ideally files:read)."
    )


def _err_hint(method: str, err: str, needed: Optional[str]) -> str:
    if err == "missing_scope":
        extra = f" needed: {needed}." if needed else ""
        if method == "files.info":
            extra += " files:read enables full column names/options; without it the server falls back to deriving columns from existing rows."
        return f"Token missing a scope.{extra}"
    if err in ("not_authed", "invalid_auth", "token_expired", "token_revoked"):
        return "Token is invalid/expired — reinstall the Slack app and update SLACK_LISTS_TOKEN."
    if err in ("feature_not_enabled", "paid_only"):
        return "Lists require a paid Slack plan."
    if err == "invalid_input_type":
        return ("A cell value type didn't match the column type. Use slack_lists_get_columns "
                "to see each column's type; for select columns pass an option label or value.")
    if err in ("invalid_option_id", "invalid_option"):
        return "A select option was not recognized. Use slack_lists_get_columns to list valid options."
    return ""


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

async def _slack_post(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{SLACK_API_BASE}/{method}", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok", False):
        err = data.get("error", "unknown_error")
        raise SlackListError(f"Slack {method} failed: {err}. {_err_hint(method, err, data.get('needed'))}".strip())
    return data


async def _slack_get(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(f"{SLACK_API_BASE}/{method}", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok", False):
        err = data.get("error", "unknown_error")
        raise SlackListError(f"Slack {method} failed: {err}. {_err_hint(method, err, data.get('needed'))}".strip())
    return data


# --------------------------------------------------------------------------- #
# Rich text helpers
# --------------------------------------------------------------------------- #

def _rich_text(text: str) -> Dict[str, Any]:
    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_section", "elements": [{"type": "text", "text": text}]}],
    }


# --------------------------------------------------------------------------- #
# Schema layer
# --------------------------------------------------------------------------- #

def _normalize_schema(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cols = []
    for c in raw or []:
        opts = []
        for ch in ((c.get("options") or {}).get("choices") or []):
            opts.append({"value": ch.get("value"), "label": ch.get("label"), "color": ch.get("color")})
        cols.append({
            "id": c.get("id") or c.get("column_id") or c.get("key"),
            "key": c.get("key"),
            "name": c.get("name") or c.get("key"),
            "type": c.get("type"),
            "is_primary": bool(c.get("is_primary_column")),
            "options": opts,
        })
    return cols


def cache_schema_from_create(list_id: str, list_metadata: Dict[str, Any]) -> None:
    _SCHEMA_CACHE[list_id] = {
        "schema": _normalize_schema(list_metadata.get("schema", [])),
        "subtask_schema": _normalize_schema(list_metadata.get("subtask_schema", [])),
        "source": "create",
    }


async def _derive_schema_from_items(list_id: str) -> Dict[str, Any]:
    """Fallback: infer columns from one existing row (no files:read). Names = keys; options = those in use."""
    data = await _slack_post("slackLists.items.list", {"list_id": list_id, "limit": 5})
    items = data.get("items", []) or []
    by_id: Dict[str, Dict[str, Any]] = {}
    for it in items:
        for f in it.get("fields", []) or []:
            cid = f.get("column_id") or f.get("key")
            if not cid:
                continue
            col = by_id.setdefault(cid, {"id": cid, "key": f.get("key"), "name": f.get("key"),
                                          "type": None, "is_primary": False, "options": []})
            # collect used select option (value+label) when both present and differ
            val, txt = f.get("value"), f.get("text")
            if isinstance(val, str) and txt and val != txt and not any(o["value"] == val for o in col["options"]):
                col["options"].append({"value": val, "label": txt, "color": None})
    cols = list(by_id.values())
    return {"schema": cols, "subtask_schema": cols, "source": "derived"}


async def _get_schema(list_id: str, refresh: bool = False) -> Dict[str, Any]:
    if not refresh and list_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[list_id]
    # Preferred: files.info -> file.list_metadata (full names + all options)
    try:
        data = await _slack_get("files.info", {"file": list_id})
        meta = (data.get("file") or {}).get("list_metadata") or {}
        if meta.get("schema"):
            _SCHEMA_CACHE[list_id] = {
                "schema": _normalize_schema(meta.get("schema", [])),
                "subtask_schema": _normalize_schema(meta.get("subtask_schema", [])),
                "source": "files.info",
            }
            return _SCHEMA_CACHE[list_id]
    except SlackListError:
        pass  # likely missing files:read — fall back
    derived = await _derive_schema_from_items(list_id)
    _SCHEMA_CACHE[list_id] = derived
    return derived


def _columns(schema: Dict[str, Any], for_subtasks: bool) -> List[Dict[str, Any]]:
    return schema["subtask_schema"] if for_subtasks else schema["schema"]


def _resolve_column(cols: List[Dict[str, Any]], ref: str) -> Dict[str, Any]:
    if ref is None:
        raise SlackListError("Missing column reference.")
    for c in cols:  # exact id
        if c["id"] == ref:
            return c
    low = str(ref).strip().lower()
    for c in cols:  # name (ci)
        if (c.get("name") or "").lower() == low:
            return c
    for c in cols:  # key (ci)
        if (c.get("key") or "").lower() == low:
            return c
    avail = ", ".join(f"{c.get('name')}({c['id']})" for c in cols) or "none"
    raise SlackListError(f"Column '{ref}' not found. Available: {avail}.")


def _resolve_option(col: Dict[str, Any], val: Any) -> str:
    opts = col.get("options") or []
    sval = str(val)
    for o in opts:  # exact value
        if str(o.get("value")) == sval:
            return o["value"]
    low = sval.lower()
    for o in opts:  # label (ci)
        if (o.get("label") or "").lower() == low:
            return o["value"]
    if not opts:
        # schema derived without files:read may not know options; pass through as raw value
        return sval
    avail = ", ".join(f"{o.get('label')}={o.get('value')}" for o in opts)
    raise SlackListError(f"Option '{val}' not found for column '{col.get('name')}'. Available: {avail}.")


def _primary_column(cols: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for c in cols:
        if c.get("is_primary"):
            return c
    for c in cols:  # fallback: first text-type column
        if c.get("type") in _TEXT_TYPES:
            return c
    return cols[0] if cols else None


def _cell_for(col: Dict[str, Any], value: Any) -> Dict[str, Any]:
    """Build a Slack cell payload from a column + a friendly value, inferring by column type."""
    ctype = (col.get("type") or "").lower()
    cell: Dict[str, Any] = {"column_id": col["id"]}
    if ctype in _TEXT_TYPES or (ctype == "" and isinstance(value, str)):
        cell["rich_text"] = [_rich_text(str(value))]
    elif ctype in _SELECT_TYPES:
        vals = value if isinstance(value, list) else [value]
        cell["select"] = [_resolve_option(col, v) for v in vals]
    elif ctype in _USER_TYPES:
        cell["user"] = value if isinstance(value, list) else [value]
    elif ctype in _DATE_TYPES:
        cell["date"] = value if isinstance(value, list) else [value]
    elif ctype == "number":
        cell["number"] = value
    elif ctype in _BOOL_TYPES:
        cell["checkbox"] = bool(value)
    elif ctype == "email":
        cell["email"] = value
    elif ctype == "phone":
        cell["phone"] = value
    else:
        # Unknown type: best effort string -> rich_text
        cell["rich_text"] = [_rich_text(str(value))]
    return cell


def _cell_from_explicit(cols: List[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Explicit cell: {column|column_id|column_name, + one of text/select/user/date/number/checkbox/email/phone/rich_text}."""
    ref = spec.get("column") or spec.get("column_id") or spec.get("column_name")
    col = _resolve_column(cols, ref)
    if "rich_text" in spec:
        rt = spec["rich_text"]
        return {"column_id": col["id"], "rich_text": rt if isinstance(rt, list) else [rt]}
    for key in ("text", "select", "user", "date", "number", "checkbox", "email", "phone"):
        if key in spec:
            if key == "select":
                vals = spec[key] if isinstance(spec[key], list) else [spec[key]]
                return {"column_id": col["id"], "select": [_resolve_option(col, v) for v in vals]}
            if key == "text":
                return {"column_id": col["id"], "rich_text": [_rich_text(str(spec[key]))]}
            v = spec[key]
            if key in ("user", "date") and not isinstance(v, list):
                v = [v]
            if key == "checkbox":
                v = bool(v)
            return {"column_id": col["id"], key: v}
    # No explicit value key -> infer from column type
    if "value" in spec:
        return _cell_for(col, spec["value"])
    raise SlackListError(f"Cell for column '{ref}' has no value.")


async def _build_cells(
    list_id: str,
    for_subtasks: bool,
    title: Optional[str],
    fields: Optional[Dict[str, Any]],
    cells: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    schema = await _get_schema(list_id)
    cols = _columns(schema, for_subtasks)
    out: List[Dict[str, Any]] = []
    if title is not None:
        pc = _primary_column(cols)
        if not pc:
            raise SlackListError("No primary text column found for `title`; pass fields/cells with an explicit column.")
        out.append({"column_id": pc["id"], "rich_text": [_rich_text(title)]})
    if fields:
        for ref, value in fields.items():
            col = _resolve_column(cols, ref)
            out.append(_cell_for(col, value))
    if cells:
        for spec in cells:
            out.append(_cell_from_explicit(cols, spec))
    return out


# --------------------------------------------------------------------------- #
# Item projection
# --------------------------------------------------------------------------- #

def _col_lookup(cols: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx = {}
    for c in cols:
        idx[c["id"]] = c
        if c.get("key"):
            idx[c["key"]] = c
    return idx


def _project_item(item: Dict[str, Any], cols_idx: Dict[str, Dict[str, Any]],
                  wanted: Optional[set]) -> Dict[str, Any]:
    name = None
    fields_out: Dict[str, Any] = {}
    for f in item.get("fields", []) or []:
        cid = f.get("column_id") or f.get("key")
        col = cols_idx.get(cid) or {}
        cname = col.get("name") or f.get("key") or cid
        ctype = (col.get("type") or "").lower()
        # human value
        if f.get("text") not in (None, ""):
            hv: Any = f.get("text")
        else:
            hv = f.get("value")
        # map select value -> label
        if ctype in _SELECT_TYPES and isinstance(f.get("value"), str):
            for o in col.get("options", []):
                if str(o.get("value")) == str(f.get("value")):
                    hv = o.get("label")
                    break
        if col.get("is_primary") or ctype in _TEXT_TYPES:
            if name is None and isinstance(hv, str):
                name = hv
        if wanted is not None and cname not in wanted and cid not in wanted:
            continue
        fields_out[cname] = hv
    return {
        "id": item.get("id"),
        "parent_id": item.get("parent_record_id"),
        "is_subtask": bool(item.get("parent_record_id")),
        "name": name,
        "fields": fields_out,
    }


def _simplify_full(item: Dict[str, Any]) -> Dict[str, Any]:
    fields = [{"column_id": f.get("column_id") or f.get("key"), "key": f.get("key"),
               "text": f.get("text"), "value": f.get("value")} for f in item.get("fields", []) or []]
    return {
        "id": item.get("id"), "list_id": item.get("list_id"),
        "is_subtask": bool(item.get("parent_record_id")),
        "parent_record_id": item.get("parent_record_id"),
        "date_created": item.get("date_created"), "fields": fields,
    }


def _ok(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fail(e: Exception) -> str:
    if isinstance(e, SlackListError):
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    if isinstance(e, httpx.HTTPStatusError):
        return json.dumps({"error": f"HTTP {e.response.status_code} from Slack."}, ensure_ascii=False)
    if isinstance(e, httpx.TimeoutException):
        return json.dumps({"error": "Slack request timed out."}, ensure_ascii=False)
    return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

@mcp.tool(
    name="slack_lists_create_list",
    annotations={"title": "Create a Slack List", "readOnlyHint": False, "destructiveHint": False,
                 "idempotentHint": False, "openWorldHint": True},
)
async def slack_lists_create_list(
    name: Annotated[str, Field(description="Name of the new List")],
    todo_mode: Annotated[bool, Field(description="Create with task columns (Completed/Assignee/Due Date). Recommended for task lists.")] = True,
    description: Annotated[Optional[str], Field(description="Optional plain-text description")] = None,
    columns: Annotated[Optional[List[Dict[str, Any]]], Field(description='Optional custom schema array: [{"key","name","type","is_primary_column"?,"options"?}]. One text column must be primary.')] = None,
) -> str:
    """Create a new Slack List. Returns {list_id, schema, subtask_schema} with each column's id/key/name/type/options.
    The schema is cached so later create/update calls can resolve column names and select labels automatically."""
    try:
        payload: Dict[str, Any] = {"name": name}
        if todo_mode:
            payload["todo_mode"] = True
        if description:
            payload["description_blocks"] = [_rich_text(description)]
        if columns:
            payload["schema"] = columns
        data = await _slack_post("slackLists.create", payload)
        meta = data.get("list_metadata", {}) or {}
        list_id = data.get("list_id")
        if list_id:
            cache_schema_from_create(list_id, meta)
        return _ok({"list_id": list_id,
                    "schema": _normalize_schema(meta.get("schema", [])),
                    "subtask_schema": _normalize_schema(meta.get("subtask_schema", []))})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_get_columns",
    annotations={"title": "Get Slack List columns (names, types, options)", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def slack_lists_get_columns(
    list_id: Annotated[str, Field(description="The List ID, e.g. 'F0123ABCD'")],
    refresh: Annotated[bool, Field(description="Bypass cache and re-fetch the schema")] = False,
) -> str:
    """Return the List's columns with id, key, display name, type, and full select options [{value,label}].
    Also returns subtask_columns (subtasks have their own schema). `source` tells you where the schema came
    from: 'files.info'/'create' = full names+options; 'derived' = inferred from rows (names=keys, only used options,
    grant files:read for complete data)."""
    try:
        schema = await _get_schema(list_id, refresh=refresh)
        return _ok({"source": schema["source"], "columns": schema["schema"], "subtask_columns": schema["subtask_schema"]})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_get_items",
    annotations={"title": "List Slack List items (compact, incl. subtasks)", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def slack_lists_get_items(
    list_id: Annotated[str, Field(description="The List ID")],
    limit: Annotated[int, Field(description="Max items to return", ge=1, le=1000)] = DEFAULT_ITEM_LIMIT,
    cursor: Annotated[Optional[str], Field(description="Pagination cursor from a previous call's next_cursor")] = None,
    columns: Annotated[Optional[List[str]], Field(description="Only include these columns (by name or id). Omit for all.")] = None,
    compact: Annotated[bool, Field(description="Compact projection (no rich_text blobs). Set false for raw fields.")] = True,
    archived: Annotated[bool, Field(description="Return archived items instead of active")] = False,
) -> str:
    """Read items incl. subtasks. Compact mode returns {id, parent_id, is_subtask, name, fields:{<ColName>:<value>}}
    with select values shown as labels and rich_text blobs stripped — much smaller. Subtasks have is_subtask=true and
    parent_id set. Use `columns` to fetch only the fields you need, and cursor/limit for pagination."""
    try:
        payload: Dict[str, Any] = {"list_id": list_id, "limit": limit}
        if cursor:
            payload["cursor"] = cursor
        if archived:
            payload["archived"] = True
        data = await _slack_post("slackLists.items.list", payload)
        raw_items = data.get("items", []) or []
        next_cursor = (data.get("response_metadata", {}) or {}).get("next_cursor") or None
        if compact:
            schema = await _get_schema(list_id)
            idx = _col_lookup(schema["schema"] + schema["subtask_schema"])
            wanted = set(columns) if columns else None
            items = [_project_item(it, idx, wanted) for it in raw_items]
        else:
            items = [_simplify_full(it) for it in raw_items]
        return _ok({"count": len(items), "items": items, "next_cursor": next_cursor})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_get_item",
    annotations={"title": "Get one Slack List item", "readOnlyHint": True, "destructiveHint": False,
                 "idempotentHint": True, "openWorldHint": True},
)
async def slack_lists_get_item(
    list_id: Annotated[str, Field(description="The List ID")],
    item_id: Annotated[str, Field(description="The item/record ID, e.g. 'Rec0123...'")],
) -> str:
    """Get a single item/record (compact projection with named fields)."""
    try:
        data = await _slack_post("slackLists.items.info", {"list_id": list_id, "id": item_id})
        item = data.get("item") or data.get("record") or data
        schema = await _get_schema(list_id)
        idx = _col_lookup(schema["schema"] + schema["subtask_schema"])
        return _ok(_project_item(item, idx, None))
    except Exception as e:  # noqa: BLE001
        return _fail(e)


async def _create_one(list_id: str, parent_item_id: Optional[str], title: Optional[str],
                      fields: Optional[Dict[str, Any]], cells: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    initial = await _build_cells(list_id, parent_item_id is not None, title, fields, cells)
    payload: Dict[str, Any] = {"list_id": list_id}
    if parent_item_id:
        payload["parent_item_id"] = parent_item_id
    if initial:
        payload["initial_fields"] = initial
    data = await _slack_post("slackLists.items.create", payload)
    return data.get("item") or data


@mcp.tool(
    name="slack_lists_create_item",
    annotations={"title": "Create a Slack List item", "readOnlyHint": False, "destructiveHint": False,
                 "idempotentHint": False, "openWorldHint": True},
)
async def slack_lists_create_item(
    list_id: Annotated[str, Field(description="The List ID to add the item to")],
    title: Annotated[Optional[str], Field(description="Text for the primary column (resolved automatically from the list schema)")] = None,
    fields: Annotated[Optional[Dict[str, Any]], Field(description='Fields by column NAME or id, e.g. {"Status":"Done","Priority":"High","Due Date":"2026-06-15","Assignee":["U123"]}. Select values may be labels OR option values.')] = None,
    cells: Annotated[Optional[List[Dict[str, Any]]], Field(description='Advanced: explicit cells [{"column":"Status","select":"Done"}]. Use instead of/alongside fields.')] = None,
) -> str:
    """Create a top-level item. Set the title and any fields by human-friendly column names; the server resolves
    column ids, types, and select labels for you. Returns {created, item_id, item}. Use item_id as parent for subtasks."""
    try:
        item = await _create_one(list_id, None, title, fields, cells)
        return _ok({"created": True, "item_id": item.get("id"), "item": _simplify_full(item)})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_create_subtask",
    annotations={"title": "Create a Slack List subtask", "readOnlyHint": False, "destructiveHint": False,
                 "idempotentHint": False, "openWorldHint": True},
)
async def slack_lists_create_subtask(
    list_id: Annotated[str, Field(description="The List ID")],
    parent_item_id: Annotated[str, Field(description="ID of the parent item this subtask belongs to")],
    title: Annotated[Optional[str], Field(description="Text for the subtask's primary column")] = None,
    fields: Annotated[Optional[Dict[str, Any]], Field(description="Fields by column name/id (subtasks use the subtask schema, which usually shares the parent's custom columns plus assignee/due/completed)")] = None,
    cells: Annotated[Optional[List[Dict[str, Any]]], Field(description="Advanced explicit cells")] = None,
) -> str:
    """Create a SUBTASK under a parent item (the capability the stock connector lacks). Fields are resolved against
    the list's subtask schema. Returns {created, item_id, item} with parent_record_id set."""
    try:
        item = await _create_one(list_id, parent_item_id, title, fields, cells)
        return _ok({"created": True, "item_id": item.get("id"), "item": _simplify_full(item)})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_create_items",
    annotations={"title": "Batch-create items + subtasks", "readOnlyHint": False, "destructiveHint": False,
                 "idempotentHint": False, "openWorldHint": True},
)
async def slack_lists_create_items(
    list_id: Annotated[str, Field(description="The List ID")],
    items: Annotated[List[Dict[str, Any]], Field(description='Items to create, each: {"title"?, "fields"?, "cells"?, "subtasks"?:[{"title"?,"fields"?,"cells"?}]}. Subtasks are created under their parent automatically.')],
) -> str:
    """Create many items (and their nested subtasks) in ONE call. Each item may include a `subtasks` array.
    Returns a tree of created ids: [{item_id, name, subtasks:[{item_id,name}]}]. Continues past per-item errors,
    reporting them inline so a partial batch still tells you what succeeded."""
    try:
        results = []
        for spec in items:
            entry: Dict[str, Any] = {}
            try:
                parent = await _create_one(list_id, None, spec.get("title"), spec.get("fields"), spec.get("cells"))
                pid = parent.get("id")
                entry["item_id"] = pid
                entry["name"] = spec.get("title")
                subs = []
                for sub in spec.get("subtasks", []) or []:
                    try:
                        s = await _create_one(list_id, pid, sub.get("title"), sub.get("fields"), sub.get("cells"))
                        subs.append({"item_id": s.get("id"), "name": sub.get("title")})
                    except Exception as se:  # noqa: BLE001
                        subs.append({"error": str(se) if isinstance(se, SlackListError) else f"{type(se).__name__}: {se}",
                                     "name": sub.get("title")})
                if subs:
                    entry["subtasks"] = subs
            except Exception as ie:  # noqa: BLE001
                entry["error"] = str(ie) if isinstance(ie, SlackListError) else f"{type(ie).__name__}: {ie}"
                entry["name"] = spec.get("title")
            results.append(entry)
        return _ok({"created": results})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_update_item",
    annotations={"title": "Update a Slack List item", "readOnlyHint": False, "destructiveHint": False,
                 "idempotentHint": True, "openWorldHint": True},
)
async def slack_lists_update_item(
    list_id: Annotated[str, Field(description="The List ID")],
    item_id: Annotated[str, Field(description="The item/record ID to update (parent or subtask)")],
    fields: Annotated[Optional[Dict[str, Any]], Field(description='Fields to set by column NAME or id, e.g. {"Status":"Done","Priority":"Low"}. Select by label or value; date "YYYY-MM-DD"; users as list of IDs; completed as true/false.')] = None,
    cells: Annotated[Optional[List[Dict[str, Any]]], Field(description="Advanced explicit cells (same shape as create)")] = None,
) -> str:
    """Update one or more cells by human-friendly column names/labels. Pass `fields` like {"Status":"Done"} and the
    server resolves the column id + option value. Returns {updated, item_id}."""
    try:
        if not fields and not cells:
            raise SlackListError("Provide `fields` (e.g. {\"Status\":\"Done\"}) or `cells`.")
        is_sub = False  # cells must reference valid columns; try parent schema first, subtask cols are a superset in cache
        built = await _build_cells(list_id, is_sub, None, fields, cells)
        for c in built:
            c["row_id"] = item_id
        await _slack_post("slackLists.items.update", {"list_id": list_id, "cells": built})
        return _ok({"updated": True, "item_id": item_id})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool(
    name="slack_lists_delete_item",
    annotations={"title": "Delete a Slack List item", "readOnlyHint": False, "destructiveHint": True,
                 "idempotentHint": True, "openWorldHint": True},
)
async def slack_lists_delete_item(
    list_id: Annotated[str, Field(description="The List ID")],
    item_id: Annotated[str, Field(description="The item/record ID to delete (parent or subtask)")],
) -> str:
    """Delete an item/record (or subtask). Destructive. Returns {deleted, item_id}."""
    try:
        await _slack_post("slackLists.items.delete", {"list_id": list_id, "id": item_id})
        return _ok({"deleted": True, "item_id": item_id})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


if __name__ == "__main__":
    mcp.run()
