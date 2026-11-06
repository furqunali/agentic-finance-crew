"""Model Context Protocol (MCP) server — the approval workflow as AI-assistant tools.

Lets an MCP client (Claude Desktop, an IDE agent, any MCP-capable assistant)
submit expense requests to the crew, look up decisions, read the review queue
and inspect the spend policy — over the standard **JSON-RPC 2.0 on stdio**
transport (one JSON message per line; stdout carries protocol traffic only,
logs go to stderr).

Deliberately dependency-free: the protocol surface an MCP *tool server* needs
(``initialize``, ``tools/list``, ``tools/call``, ``ping`` + standard JSON-RPC
error codes) is small, so it is implemented here on the stdlib rather than
pulling a new SDK into the base install.

Design guarantees carried over from the rest of the system:

* **The model advises; policy decides.** ``submit_expense_request`` runs the
  same orchestrator + ``decide()`` guardrail and persists the same audit trail
  as ``POST /approve``. An assistant can *submit* and *read*, but there is
  deliberately **no tool to approve or reject** a review item — that stays a
  human action behind RBAC in the API/UI.
* Runs fully offline with the deterministic local engine (no API key).

Run it::

    python -m finance_crew.mcp_server        # or the `afc-mcp` console script
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import asdict
from typing import IO, Any

from . import __version__, repository
from .config import Settings
from .db import init_db, session_scope
from .errors import ConfigurationError, FinanceCrewError, ValidationError
from .records import DecisionRecord

logger = logging.getLogger("finance_crew.mcp")

SERVER_NAME = "agentic-finance-crew"
# Newest first. We answer with the client's requested version when we support
# it (per the MCP lifecycle spec), otherwise with our latest.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

# Standard JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_LIST_LIMIT = 100


class ToolError(Exception):
    """A tool ran but could not complete — reported to the client as a tool
    result with ``isError: true`` (so the model can see and react to it),
    not as a protocol-level error."""


class InvalidParams(Exception):
    """Arguments that don't match the tool's input schema (JSON-RPC -32602)."""


# --- Tool definitions (name, description, JSON Schema) -----------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "submit_expense_request",
        "title": "Submit expense request",
        "description": (
            "Submit one expense/reimbursement request to the finance crew. Runs the "
            "Intake -> Policy Analyst -> Approver workflow behind the deterministic "
            "policy guardrail, persists the decision with its audit trail, and returns "
            "the decision (auto_approved / needs_human_review / rejected), risk score "
            "and the reasons (rules fired). Items needing review wait for a human; "
            "this tool can never approve them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "minLength": 1, "description": "Business request id, e.g. EXP-1001"},
                "employee": {"type": "string", "minLength": 1, "description": "Employee name"},
                "category": {
                    "type": "string",
                    "description": "travel | meals | software | equipment | other (aliases like 'hotel' are normalized)",
                },
                "amount": {"type": "number", "description": "Amount in the request currency"},
                "description": {"type": "string", "description": "Free-text description"},
                "currency": {"type": "string", "description": "ISO currency code (default USD)"},
                "has_receipt": {"type": "boolean", "description": "Whether a receipt is attached"},
                "date": {"type": "string", "description": "Expense date (YYYY-MM-DD)"},
            },
            "required": ["id", "employee", "category", "amount"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_decision",
        "title": "Get decision",
        "description": (
            "Look up the most recent persisted decision for a business request id, "
            "including its status (pending_review / auto_approved / human_approved ...), "
            "rules fired, risk score, rationale and who resolved it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Business request id, e.g. EXP-1001",
                },
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_pending_approvals",
        "title": "List pending approvals",
        "description": "List decisions awaiting a human sign-off (the review queue), oldest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIST_LIMIT,
                    "description": f"Max items to return (1-{MAX_LIST_LIMIT}, default 20)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_policy",
        "title": "Get spend policy",
        "description": (
            "Return the active spend policy: auto-approve limit, human-review limit, "
            "receipt threshold and per-category limits."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}

_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    # bool is a subclass of int in Python; JSON Schema keeps them distinct.
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
}


def validate_arguments(schema: dict[str, Any], args: Any) -> dict[str, Any]:
    """Check tool arguments against the (flat) input schema we publish.

    Covers exactly the keywords our schemas use — type, required,
    additionalProperties, minLength, minimum, maximum — so bad input is
    rejected with a precise message before any work runs.
    """
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise InvalidParams("arguments must be an object")
    props: dict[str, Any] = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise InvalidParams(f"missing required argument(s): {', '.join(missing)}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(args) - set(props))
        if unknown:
            raise InvalidParams(f"unknown argument(s): {', '.join(unknown)}")
    for key, value in args.items():
        spec = props.get(key, {})
        expected = spec.get("type")
        if expected and not _JSON_TYPES[expected](value):
            raise InvalidParams(f"argument '{key}' must be of type {expected}")
        if "minLength" in spec and len(value.strip()) < spec["minLength"]:
            raise InvalidParams(f"argument '{key}' must not be empty")
        if "minimum" in spec and value < spec["minimum"]:
            raise InvalidParams(f"argument '{key}' must be >= {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise InvalidParams(f"argument '{key}' must be <= {spec['maximum']}")
    return args


# --- Tool implementations ----------------------------------------------------
def _record_summary(record: DecisionRecord) -> dict[str, Any]:
    """The client-facing view of a stored decision."""
    data = record.to_dict()
    data["record_id"] = record.id
    return data


def _tool_submit_expense_request(args: dict[str, Any], actor: str) -> dict[str, Any]:
    from .service import decide_and_store

    try:
        with session_scope() as session:
            result, record_id = decide_and_store(session, dict(args), requested_by=actor)
            record = repository.get_decision(session, record_id)
            assert record is not None  # just written in this transaction
            payload = _record_summary(record)
    except (ValidationError, ConfigurationError) as exc:
        raise ToolError(str(exc)) from exc
    payload["reasons"] = list(result.analysis.violations) or [result.rationale]
    payload["intake_issues"] = list(result.intake.issues)
    return payload


def _tool_get_decision(args: dict[str, Any], _actor: str) -> dict[str, Any]:
    request_id = args["request_id"].strip()
    with session_scope() as session:
        record = repository.get_by_request_id(session, request_id)
        if record is None:
            raise ToolError(f"no decision found for request id '{request_id}'")
        return _record_summary(record)


def _tool_list_pending_approvals(args: dict[str, Any], _actor: str) -> dict[str, Any]:
    limit = int(args.get("limit", 20))
    with session_scope() as session:
        rows = repository.list_review_queue(session, limit=limit)
        items = [_record_summary(r) for r in rows]
    return {"count": len(items), "items": items}


def _tool_get_policy(_args: dict[str, Any], _actor: str) -> dict[str, Any]:
    settings = Settings.from_env()
    return {"policy": asdict(settings.policy), "engine": settings.active_engine}


_HANDLERS: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "submit_expense_request": _tool_submit_expense_request,
    "get_decision": _tool_get_decision,
    "list_pending_approvals": _tool_list_pending_approvals,
    "get_policy": _tool_get_policy,
}


# --- JSON-RPC / MCP protocol -------------------------------------------------
def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _tool_result(data: dict[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    """Wrap a tool outcome in the MCP CallToolResult shape (text + structured)."""
    if error is not None:
        return {"content": [{"type": "text", "text": error}], "isError": True}
    assert data is not None
    return {
        "content": [{"type": "text", "text": json.dumps(data, default=str)}],
        "structuredContent": data,
        "isError": False,
    }


class MCPServer:
    """A minimal, spec-conformant MCP tool server over JSON-RPC 2.0.

    ``handle()`` is pure message-in / message-out (``None`` for notifications),
    which keeps the protocol fully unit-testable without spawning a process.
    """

    def __init__(self, actor: str | None = None) -> None:
        # Recorded as `requested_by` in the audit trail for submissions.
        self.actor = actor or os.getenv("MCP_ACTOR", "mcp-client")
        self.initialized = False

    # -- dispatch ------------------------------------------------------------
    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "invalid request: expected a JSON-RPC object")
        msg_id = message.get("id")
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(msg_id, INVALID_REQUEST, "invalid request: jsonrpc must be '2.0' with a method")
        if "id" in message and (not isinstance(msg_id, (str, int)) or isinstance(msg_id, bool)):
            return _error(None, INVALID_REQUEST, "invalid request: id must be a string or integer")

        method: str = message["method"]
        params = message.get("params") or {}
        is_notification = "id" not in message

        if is_notification:
            # Notifications never get a response (initialized, cancelled, ...).
            if method == "notifications/initialized":
                self.initialized = True
            return None
        if not isinstance(params, dict):
            return _error(msg_id, INVALID_PARAMS, "params must be an object")

        handler = {
            "initialize": self._initialize,
            "ping": lambda _p: {},
            "tools/list": self._tools_list,
            "tools/call": self._tools_call,
        }.get(method)
        if handler is None:
            return _error(msg_id, METHOD_NOT_FOUND, f"method not found: {method}")
        try:
            return _result(msg_id, handler(params))
        except InvalidParams as exc:
            return _error(msg_id, INVALID_PARAMS, str(exc))
        except Exception:  # pragma: no cover - last-resort safety net
            logger.exception("internal error handling %s", method)
            return _error(msg_id, INTERNAL_ERROR, "internal error")

    def handle_line(self, line: str) -> str | None:
        """Parse one stdio line, dispatch it, and serialize the response."""
        line = line.strip()
        if not line:
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return json.dumps(_error(None, PARSE_ERROR, "parse error: invalid JSON"))
        response = self.handle(message)
        return None if response is None else json.dumps(response, default=str)

    # -- methods ---------------------------------------------------------------
    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "Agentic Finance Crew", "version": __version__},
            "instructions": (
                "Expense-approval tools. Decisions come from a deterministic policy "
                "guardrail; anything risky is routed to a human review queue. "
                "There is no tool to approve review items — humans do that."
            ),
        }

    def _tools_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": TOOLS}

    def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise InvalidParams("tools/call requires a tool 'name'")
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            raise InvalidParams(f"unknown tool: {name}")
        args = validate_arguments(tool["inputSchema"], params.get("arguments"))
        try:
            data = _HANDLERS[name](args, self.actor)
        except ToolError as exc:
            return _tool_result(None, error=str(exc))
        except FinanceCrewError as exc:
            return _tool_result(None, error=str(exc))
        return _tool_result(data)

    # -- transport -------------------------------------------------------------
    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        """Read newline-delimited JSON-RPC from ``stdin`` until EOF."""
        for line in stdin:
            reply = self.handle_line(line)
            if reply is not None:
                stdout.write(reply + "\n")
                stdout.flush()


def main() -> int:
    """Entry point for ``python -m finance_crew.mcp_server`` / ``afc-mcp``."""
    # stdout is reserved for protocol messages — logs must go to stderr.
    logging.basicConfig(
        stream=sys.stderr,
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    init_db()
    logger.info("MCP server %s %s ready on stdio", SERVER_NAME, __version__)
    try:
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):  # pragma: no cover - non-reconfigurable stream
        logger.debug("stdio streams could not be reconfigured to UTF-8")
    MCPServer().serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
