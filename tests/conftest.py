"""Shared fixtures: every test runs on asyncio, with a fresh token, empty caches and no sleeping."""

import httpx
import pytest

import server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("SLACK_LISTS_TOKEN", "xoxp-test-token")
    server._reset_caches()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(server, "_sleep", no_sleep)
    yield
    server._http = None


@pytest.fixture
def slack(monkeypatch):
    """A fake Slack API.

    `slack.on(method, response)` registers a JSON body (or a list of bodies, served in order) for a Web API
    method; `slack.calls` records every request as (method, params/json).
    """

    class FakeSlack:
        def __init__(self) -> None:
            self.responses: dict[str, list] = {}
            self.calls: list[tuple[str, dict]] = []

        def on(self, method: str, *responses) -> None:
            self.responses[method] = list(responses)

        def handler(self, request: httpx.Request) -> httpx.Response:
            method = request.url.path.rsplit("/", 1)[-1]
            if request.method == "POST":
                body = httpx.Response(200, content=request.content).json() if request.content else {}
            else:
                body = dict(request.url.params)
            self.calls.append((method, body))
            queue = self.responses.get(method)
            if not queue:
                return httpx.Response(200, json={"ok": False, "error": f"unmocked_method:{method}"})
            resp = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(resp, httpx.Response):
                return resp
            return httpx.Response(200, json=resp)

    fake = FakeSlack()
    server._http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return fake
