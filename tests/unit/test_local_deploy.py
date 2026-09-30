import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def deploy():
    path = Path(__file__).resolve().parents[2] / "scripts/local_deploy.py"
    spec = importlib.util.spec_from_file_location("local_deploy_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "DATABASE_URL": "mysql://test:password@localhost/db?ssl_disabled=true",
        "JWT_SECRET": "private-test-key",
        "FIHANKRA_FEEDBACK_SECRET": "private-feedback-key",
        "GATE_STACK_NAME": "existing-api-stack",
        "AWS_REGION": "eu-west-1",
    }))
    return path


@pytest.mark.parametrize("field,value", [
    ("GATE_STACK_NAME", ""),
    ("JWT_SECRET", None),
    ("DATABASE_URL", "mysql://user:YOUR_URL_ENCODED_PASSWORD@localhost/db"),
    ("DATABASE_URL", "postgresql://user:password@localhost/db"),
])
def test_invalid_config_stops_before_running_commands(deploy, config, monkeypatch, field, value):
    data = json.loads(config.read_text())
    data[field] = value
    config.write_text(json.dumps(data))
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected command"))
    assert deploy.main(["--config", str(config)]) == 1


@pytest.mark.parametrize("check_only,failed_check,expected_count", [
    (True, False, 1), (False, True, 1), (False, False, 3),
])
def test_local_flow_uses_private_environment_and_stops_on_failure(
        deploy, config, monkeypatch, capsys, check_only, failed_check, expected_count):
    calls = []

    def run(command, **kwargs):
        assert "private-test-key" not in str(command)
        assert kwargs["env"]["JWT_SECRET"] == "private-test-key"
        assert kwargs["env"]["GATE_STACK_NAME"] == "existing-api-stack"
        assert kwargs["env"]["AWS_DEFAULT_REGION"] == "eu-west-1"
        calls.append(command)
        return SimpleNamespace(returncode=1 if failed_check else 0)

    monkeypatch.setattr(deploy.subprocess, "run", run)
    args = ["--config", str(config)] + (["--check-only"] if check_only else [])
    assert deploy.main(args) == (1 if failed_check else 0)
    assert len(calls) == expected_count
    assert calls[0][-1] == "scripts/check_database.py"
    if expected_count == 3:
        assert calls[1] == ["sam", "build"]
        assert calls[2][-1] == "scripts/deploy.py"
    output = capsys.readouterr()
    assert "private-test-key" not in output.out + output.err
