import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

spec = importlib.util.spec_from_file_location(
    'template_deploy', Path(__file__).resolve().parents[2] / 'scripts/template_deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


@pytest.fixture
def template(tmp_path):
    path = tmp_path / 'template.yaml'
    path.write_text('''Parameters:
  DatabaseUrl:
    Default: "mysql://test:password@localhost/db"
  JwtSecret:
    Default: 'signing-test'
  FeedbackSecret:
    Default: 'feedback-test'
Globals:
  Function:
    Environment:
      Variables:
        DATABASE_URL: !Ref DatabaseUrl
''')
    return path


@pytest.mark.parametrize('mode,script', [
    ('--check-only', 'scripts/check_database.py'),
    ('--deploy-only', 'scripts/deploy.py'),
])
def test_template_supplies_credentials_without_build_variables(template, monkeypatch, mode, script, capsys):
    monkeypatch.setattr(deploy, 'ROOT', template.parent)
    for key in deploy.PARAMETERS.values():
        monkeypatch.delenv(key, raising=False)
    run = MagicMock(return_value=MagicMock(returncode=7))
    monkeypatch.setattr(deploy.subprocess, 'run', run)
    assert deploy.main([mode]) == 7
    args, kwargs = run.call_args
    assert args[0][-1] == script
    assert kwargs['env']['JWT_SECRET'] == 'signing-test'
    assert kwargs['env']['FIHANKRA_FEEDBACK_SECRET'] == 'feedback-test'
    assert 'password' not in str(args)
    assert 'password' not in str(capsys.readouterr())


def test_template_is_authoritative_and_preserves_other_environment(template):
    result = deploy.load_environment(template, {'JWT_SECRET': 'stale', 'AWS_REGION': 'eu-west-1'})
    assert result['JWT_SECRET'] == 'signing-test'
    assert result['AWS_REGION'] == 'eu-west-1'


def test_malformed_template_error_does_not_expose_values(template):
    template.write_text('Parameters: [private-secret:')
    with pytest.raises(ValueError) as exc:
        deploy.load_environment(template, {})
    assert 'private-secret' not in str(exc.value)


def test_blank_database_default_uses_environment(template):
    template.write_text(template.read_text().replace('mysql://test:password@localhost/db', ''))
    result = deploy.load_environment(template, {'DATABASE_URL': 'mysql://test:password@localhost/new_db'})
    assert result['DATABASE_URL'].endswith('/new_db')
    with pytest.raises(ValueError):
        deploy.load_environment(template, {})


def test_postgres_environment_url_is_rejected(template):
    with pytest.raises(ValueError):
        deploy.load_environment(template, {'DATABASE_URL': 'postgresql://test:password@localhost/db'})


def test_required_database_parameter_without_default(template):
    template.write_text(template.read_text().replace('    Default: "mysql://test:password@localhost/db"\n', '    Type: String\n    MinLength: 1\n'))
    result = deploy.load_environment(template, {'DATABASE_URL': 'mysql://test:password@localhost/db'})
    assert result['DATABASE_URL'] == 'mysql://test:password@localhost/db'
    with pytest.raises(ValueError):
        deploy.load_environment(template, {})
