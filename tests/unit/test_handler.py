"""Gate Lambda routing and connection lifecycle regression tests."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app(monkeypatch):
    for name in ("handlers", "handlers.gate", "handlers.dashboard_handlers", "utils", "middleware", "psycopg2"):
        monkeypatch.setitem(sys.modules, name, MagicMock())
    sys.modules["middleware"].cors_wrap.side_effect = lambda response: response
    sys.modules["utils"]._error_response.side_effect = lambda status, message: {"statusCode": status, "body": message}
    path = Path(__file__).resolve().parents[2] / "lambdas/gate/app.py"
    spec = importlib.util.spec_from_file_location("gate_app_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_database_configuration(app, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert app.lambda_handler({}, None)["statusCode"] == 500
    app.psycopg2.connect.assert_not_called()


def test_video_route_passes_connection_for_account_status_check(app, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "test-database")
    event = {"path": "/system/videos", "httpMethod": "GET"}
    app.get_videos.return_value = {"statusCode": 200}
    assert app.lambda_handler(event, None)["statusCode"] == 200
    conn = app.psycopg2.connect.return_value
    app.get_videos.assert_called_once_with(conn, event)
    conn.close.assert_called_once()


def test_handler_failure_closes_connection(app, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "test-database")
    app.get_gates.side_effect = RuntimeError("query failed")
    assert app.lambda_handler({"path": "/gate/all", "httpMethod": "GET"}, None)["statusCode"] == 500
    app.psycopg2.connect.return_value.close.assert_called_once()
