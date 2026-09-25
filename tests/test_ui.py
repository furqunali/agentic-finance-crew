"""Tests for the web console being served and the root redirect."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_root_redirects_to_ui():
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/ui/"


def test_ui_index_is_served():
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Agentic Finance Crew" in body
    assert 'id="login"' in body          # the console shell is present
    assert "/auth/login" in body          # it wires to the auth API


def test_ui_is_public_no_auth_needed():
    # The static console loads without a token; the API calls it makes are gated.
    assert client.get("/ui/", headers={}).status_code == 200
