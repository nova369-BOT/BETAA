"""Shared fixtures.

`client` lived in test_api.py until a second module needed the same engine
fixture. It is defined once here instead: two copies of "point the config at
a sandbox, build the app" drift apart silently, and a test that hits the
developer's real config is a test that deletes the developer's real work.
"""

import pytest
from fastapi.testclient import TestClient

from lse_terminal.engine.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point config at a sandbox and hide any real key so `lse` shows
    # unconfigured; tests must never touch the developer's real config.
    monkeypatch.setenv("LSE_TERMINAL_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    return TestClient(create_app(), base_url="http://127.0.0.1")
