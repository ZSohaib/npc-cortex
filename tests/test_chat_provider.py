"""ChatCompletionsProvider speaks OpenAI-style chat endpoints (real HTTP)."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from npc_cortex.providers import ChatCompletionsProvider


class _Stub:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {
            "choices": [{"message": {"content": "Evening, and welcome!"}}]}
        self.seen = {}

    def handler(self):
        stub = self

        class _H(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                stub.seen = {"path": self.path,
                             "auth": self.headers.get("Authorization"),
                             "body": json.loads(self.rfile.read(length) or b"{}")}
                payload = json.dumps(stub.body).encode()
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return _H


@pytest.fixture()
def stub(monkeypatch):
    monkeypatch.setenv("NPC_CORTEX_API_KEY", "test-key")
    monkeypatch.delenv("NPC_CORTEX_FAKE_LLM", raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    holder = _Stub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), holder.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield holder, "http://127.0.0.1:%d/v1/chat/completions" % server.server_port
    server.shutdown()
    server.server_close()


def test_posts_openai_shape_and_returns_content(stub):
    holder, url = stub
    out = ChatCompletionsProvider(url, "muse-wonder-1.0",
                                  timeout=5.0).complete("Say hi.")
    assert out == "Evening, and welcome!"
    assert holder.seen["path"] == "/v1/chat/completions"
    assert holder.seen["auth"] == "Bearer test-key"
    assert holder.seen["body"]["model"] == "muse-wonder-1.0"
    assert holder.seen["body"]["messages"] == [
        {"role": "user", "content": "Say hi."}]
    assert holder.seen["body"]["reasoning_effort"] == "low"
    assert holder.seen["body"]["max_tokens"] == 800


def test_http_error_raises(stub, monkeypatch):
    holder, url = stub
    holder.status = 500
    with pytest.raises(RuntimeError, match="HTTP 500"):
        ChatCompletionsProvider(url, "m", timeout=5.0).complete("hi")


def test_unexpected_body_raises(stub):
    holder, url = stub
    holder.body = {"oops": True}
    with pytest.raises(RuntimeError, match="unexpected body"):
        ChatCompletionsProvider(url, "m", timeout=5.0).complete("hi")


def test_env_key_fallback(monkeypatch):
    monkeypatch.delenv("NPC_CORTEX_API_KEY", raising=False)
    monkeypatch.setenv("NPC_LLM_API_KEY", "legacy-key")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    holder = _Stub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), holder.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_port
        ChatCompletionsProvider(url, "m", timeout=5.0).complete("hi")
        assert holder.seen["auth"] == "Bearer legacy-key"
    finally:
        server.shutdown()
        server.server_close()
