"""MCP server tests: JSON-RPC 2.0 handshake, tool schemas, every tool, bad
input, unknown tools/methods, and a real stdio round-trip in a subprocess.

All key-free — submissions run through the deterministic local engine and the
in-memory test database configured in conftest.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from finance_crew.mcp_server import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    TOOLS,
    MCPServer,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def server() -> MCPServer:
    return MCPServer(actor="mcp-test")


def _call(server: MCPServer, method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    resp = server.handle(msg)
    assert resp is not None
    assert resp["jsonrpc"] == "2.0" and resp["id"] == msg_id
    return resp


def _tool(server: MCPServer, name: str, arguments: dict | None = None) -> dict:
    params: dict = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return _call(server, "tools/call", params)["result"]


# --- Protocol handshake ------------------------------------------------------
def test_initialize_handshake(server):
    resp = _call(
        server,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    )
    result = resp["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "agentic-finance-crew"
    # the initialized notification produces no response
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.initialized


def test_initialize_negotiates_older_and_unknown_versions(server):
    old = _call(server, "initialize", {"protocolVersion": "2024-11-05"})["result"]
    assert old["protocolVersion"] == "2024-11-05"
    unknown = _call(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert unknown["protocolVersion"] == LATEST_PROTOCOL_VERSION


def test_ping(server):
    assert _call(server, "ping")["result"] == {}


# --- tools/list --------------------------------------------------------------
def test_tools_list_schema(server):
    tools = _call(server, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"submit_expense_request", "get_decision", "list_pending_approvals", "get_policy"}
    for tool in tools:
        assert tool["description"]
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert set(schema.get("required", [])) <= set(schema["properties"])
    submit = next(t for t in tools if t["name"] == "submit_expense_request")
    assert submit["inputSchema"]["required"] == ["id", "employee", "category", "amount"]


def test_no_tool_can_approve_or_reject():
    # Human sign-off must stay a human action behind RBAC — never an AI tool.
    for tool in TOOLS:
        assert "approve" not in tool["name"].replace("approvals", "")
        assert "reject" not in tool["name"]


# --- tools/call: each tool ---------------------------------------------------
def test_submit_auto_approved(server):
    result = _tool(
        server,
        "submit_expense_request",
        {
            "id": "MCP-1",
            "employee": "Mcp Mia",
            "category": "software",
            "amount": 149,
            "has_receipt": True,
        },
    )
    assert result["isError"] is False
    data = result["structuredContent"]
    assert data["decision"] == "auto_approved"
    assert data["requested_by"] == "mcp-test"
    assert data["record_id"] > 0
    assert data["reasons"]  # always explains itself
    # text content mirrors the structured payload
    assert json.loads(result["content"][0]["text"])["request_id"] == "MCP-1"


def test_submit_needs_review_returns_reasons(server):
    data = _tool(
        server,
        "submit_expense_request",
        {
            "id": "MCP-2",
            "employee": "Mcp Max",
            "category": "meals",
            "amount": 180,
        },
    )["structuredContent"]
    assert data["decision"] == "needs_human_review"
    assert data["status"] == "pending_review"
    assert any("receipt required" in r for r in data["reasons"])


def test_submit_invalid_amount_is_rejected_not_error(server):
    data = _tool(
        server,
        "submit_expense_request",
        {
            "id": "MCP-3",
            "employee": "Mcp Moe",
            "category": "software",
            "amount": -5,
        },
    )["structuredContent"]
    assert data["decision"] == "rejected"
    assert "amount must be positive" in data["intake_issues"]


def test_get_decision_found_and_missing(server):
    _tool(
        server,
        "submit_expense_request",
        {
            "id": "MCP-GET",
            "employee": "Mcp Gus",
            "category": "software",
            "amount": 99,
            "has_receipt": True,
        },
    )
    found = _tool(server, "get_decision", {"request_id": "MCP-GET"})
    assert found["isError"] is False
    assert found["structuredContent"]["request_id"] == "MCP-GET"

    missing = _tool(server, "get_decision", {"request_id": "NOPE-404"})
    assert missing["isError"] is True
    assert "no decision found" in missing["content"][0]["text"]


def test_list_pending_approvals(server):
    _tool(
        server,
        "submit_expense_request",
        {
            "id": "MCP-Q",
            "employee": "Mcp Queue",
            "category": "software",
            "amount": 1450,
            "has_receipt": True,
        },
    )
    data = _tool(server, "list_pending_approvals", {"limit": 100})["structuredContent"]
    assert data["count"] == len(data["items"]) >= 1
    assert all(item["status"] == "pending_review" for item in data["items"])
    assert any(item["request_id"] == "MCP-Q" for item in data["items"])
    # default limit (no arguments at all) also works
    assert _tool(server, "list_pending_approvals")["isError"] is False


def test_get_policy(server):
    data = _tool(server, "get_policy", {})["structuredContent"]
    policy = data["policy"]
    assert policy["auto_approve_limit"] == 200.0
    assert policy["category_limits"]["meals"] == 100.0
    assert data["engine"] == "local"


# --- Bad input ---------------------------------------------------------------
@pytest.mark.parametrize(
    "arguments, fragment",
    [
        ({"id": "X", "employee": "E", "category": "software"}, "missing required"),
        ({"id": "X", "employee": "E", "category": "software", "amount": "lots"}, "type number"),
        ({"id": "X", "employee": "E", "category": "software", "amount": True}, "type number"),
        ({"id": "", "employee": "E", "category": "software", "amount": 5}, "must not be empty"),
        ({"id": "X", "employee": "E", "category": "software", "amount": 5, "evil": 1}, "unknown argument"),
    ],
)
def test_submit_bad_arguments_are_invalid_params(server, arguments, fragment):
    resp = _call(server, "tools/call", {"name": "submit_expense_request", "arguments": arguments})
    assert resp["error"]["code"] == INVALID_PARAMS
    assert fragment in resp["error"]["message"]


def test_list_limit_out_of_range(server):
    resp = _call(server, "tools/call", {"name": "list_pending_approvals", "arguments": {"limit": 0}})
    assert resp["error"]["code"] == INVALID_PARAMS
    resp = _call(server, "tools/call", {"name": "list_pending_approvals", "arguments": {"limit": 1000}})
    assert resp["error"]["code"] == INVALID_PARAMS


def test_arguments_must_be_object(server):
    resp = _call(server, "tools/call", {"name": "get_policy", "arguments": ["x"]})
    assert resp["error"]["code"] == INVALID_PARAMS


def test_unknown_tool(server):
    resp = _call(server, "tools/call", {"name": "approve_everything", "arguments": {}})
    assert resp["error"]["code"] == INVALID_PARAMS
    assert "unknown tool" in resp["error"]["message"]


def test_missing_tool_name(server):
    resp = _call(server, "tools/call", {"arguments": {}})
    assert resp["error"]["code"] == INVALID_PARAMS


def test_unknown_method(server):
    resp = _call(server, "resources/list")
    assert resp["error"]["code"] == METHOD_NOT_FOUND


@pytest.mark.parametrize(
    "message",
    [
        ["not", "an", "object"],
        {"id": 1, "method": "ping"},  # missing jsonrpc
        {"jsonrpc": "1.0", "id": 1, "method": "ping"},  # wrong version
        {"jsonrpc": "2.0", "id": 1},  # missing method
        {"jsonrpc": "2.0", "id": True, "method": "ping"},  # bool id
        {"jsonrpc": "2.0", "id": None, "method": "ping"},  # null id
    ],
)
def test_invalid_requests(server, message):
    resp = server.handle(message)
    assert resp["error"]["code"] == INVALID_REQUEST


def test_params_must_be_object(server):
    resp = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": [1]})
    assert resp["error"]["code"] == INVALID_PARAMS


def test_parse_error_and_blank_lines(server):
    reply = json.loads(server.handle_line("{not json"))
    assert reply["error"]["code"] == PARSE_ERROR
    assert reply["id"] is None
    assert server.handle_line("   ") is None


def test_unknown_notification_is_ignored(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled"}) is None


# --- Transport ---------------------------------------------------------------
def test_serve_over_in_memory_streams(server):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n")
    stdout = io.StringIO()
    server.serve(stdin, stdout)
    replies = [json.loads(x) for x in stdout.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2]  # notification got no reply
    assert len(replies[1]["result"]["tools"]) == 4


def test_stdio_subprocess_end_to_end(tmp_path):
    """Spawn the real CLI entry point and talk MCP to it over pipes."""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'mcp.db').as_posix()}"}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")])
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "submit_expense_request",
                "arguments": {
                    "id": "SUB-1",
                    "employee": "Proc Pam",
                    "category": "software",
                    "amount": 149,
                    "has_receipt": True,
                },
            },
        },
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "finance_crew.mcp_server"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    replies = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
    assert [r["id"] for r in replies] == [1, 2]  # stdout carries protocol only
    assert replies[1]["result"]["structuredContent"]["decision"] == "auto_approved"
