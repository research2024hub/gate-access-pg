"""Regression coverage without contacting AWS, PostgreSQL, or notification services."""
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-signing-secret")
    for name in ("requests", "firebase_admin", "firebase_admin.credentials",
                 "firebase_admin.messaging", "boto3", "jwt", "google",
                 "google.oauth2", "google.auth", "google.auth.transport"):
        monkeypatch.setitem(sys.modules, name, MagicMock())
    jwt = sys.modules["jwt"]
    jwt.ExpiredSignatureError = type("ExpiredSignatureError", (Exception,), {})
    jwt.InvalidTokenError = type("InvalidTokenError", (Exception,), {})
    utils = load_module("test_utils", "shared/python/utils.py")
    monkeypatch.setitem(sys.modules, "utils", utils)
    middleware = load_module("test_middleware", "shared/python/middleware.py")
    monkeypatch.setitem(sys.modules, "middleware", middleware)
    return utils, middleware, jwt


@pytest.mark.parametrize("database_error", [False, True])
def test_auth_rejects_deleted_user_or_database_failure(modules, database_error):
    _, middleware, jwt = modules
    jwt.decode.return_value = {"user_id": 1}
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None
    if database_error:
        cur.execute.side_effect = RuntimeError("database unavailable")
    payload, response = middleware.verify_token(
        {"headers": {"Authorization": "Bearer token"}}, conn)
    assert payload is None
    assert response["statusCode"] == (503 if database_error else 401)
    if database_error:
        conn.rollback.assert_called_once()


def test_auth_active_user_and_controller(modules):
    _, middleware, jwt = modules
    conn = MagicMock()
    for payload in ({"user_id": 1}, {"gate_id": 2, "type": "GATE"}):
        jwt.decode.return_value = payload
        result, error = middleware.verify_token(
            {"headers": {"authorization": "Bearer token"}}, conn)
        assert result == payload and error is None
    assert middleware.verify_token({"headers": None}, conn)[1]["statusCode"] == 401


@pytest.mark.parametrize("start,end,expected", [
    ("2026-01-01T11:00:00", "2026-01-01T13:00:00", 200),
    ("2026-01-01T11:00:00Z", "2026-01-01T13:00:00Z", 200),
    ("2026-01-01T13:00:00+02:00", "2026-01-01T15:00:00+02:00", 200),
    ("2026-01-01T08:00:00+02:00", "2026-01-01T09:00:00+02:00", 400),
])
def test_guest_otp_entry_windows(modules, monkeypatch, start, end, expected):
    guest = load_module("test_guest", "lambdas/guest/handlers/guest.py")
    monkeypatch.setattr(guest, "verify_token", lambda *a: ({"gate_id": 1, "type": "TABLET"}, None))
    monkeypatch.setattr(guest, "utc_now", lambda: datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(guest, "log", MagicMock())
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        {"id": 1, "name": "Guest", "inviter_user_id": 1,
         "other_info": {"otp": "123456", "entry_window": {"start": start, "end": end}}},
        {"id": 1},
    ]
    response = guest.verify_guest_otp(conn, {"otp": "123456"}, {})
    assert response["statusCode"] == expected
    assert conn.commit.called == (expected == 200)


class SQLiteCursor:
    def __init__(self, db):
        self.cursor = db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, params=()):
        self.cursor.execute(sql.replace("%s", "?").replace("FOR UPDATE", ""), params)

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None


@pytest.mark.parametrize("removed,disabled,user_removed,user_disabled", [
    (False, False, False, False),
    (True, False, False, False),
    (False, True, False, False),
    (False, False, True, False),
    (False, False, False, True),
])
def test_controller_vehicle_list_excludes_inactive_owners(
        modules, monkeypatch, removed, disabled, user_removed, user_disabled):
    gate = load_module("test_gate", "lambdas/gate/handlers/gate.py")
    monkeypatch.setattr(gate, "verify_token", lambda *a: ({"gate_id": 1, "type": "GATE"}, None))
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE users (id INTEGER, deleted_at TEXT, is_active BOOLEAN);
        CREATE TABLE account_holders (id INTEGER, personal_info_id INTEGER,
                                     user_id INTEGER, deleted_at TEXT, is_active BOOLEAN);
        CREATE TABLE personal_info (id INTEGER, access_group_id INTEGER);
        CREATE TABLE vehicles (id INTEGER, personal_info_id INTEGER);
        CREATE TABLE guests (personal_info_id INTEGER, creator_id INTEGER);
        CREATE TABLE gate_access_group_links (gate_id INTEGER, access_group_id INTEGER);
        INSERT INTO personal_info VALUES (1, 1), (2, 1), (3, 1);
        INSERT INTO vehicles VALUES (1, 1), (2, 2), (3, 3);
        INSERT INTO guests VALUES (2, 1);
        INSERT INTO gate_access_group_links VALUES (1, 1);
    ''')
    db.execute("INSERT INTO users VALUES (1, ?, ?)", ("deleted" if user_removed else None, not user_disabled))
    db.execute("INSERT INTO account_holders VALUES (1, 1, 1, ?, ?)",
               ("deleted" if removed else None, not disabled))
    conn = MagicMock()
    conn.cursor.side_effect = lambda **kwargs: SQLiteCursor(db)
    try:
        response = gate.get_vehicles_by_gate_no_time_check_by_gate_controller(conn, {})
        ids = [v["id"] for v in json.loads(response["body"])["vehicles"]]
        assert ids == ([] if any((removed, disabled, user_removed, user_disabled)) else [1, 2])
    finally:
        db.close()


@pytest.mark.parametrize("revision,valid", [
    ("2047cc35125e", True), ("80651478bdd9", True), ("9a900bb97a92", False),
    ("unreviewed-future-revision", False),
])
def test_deployment_blocks_incompatible_database(modules, revision, valid):
    check = load_module("test_db_check", "scripts/check_database.py")
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [(revision,)]
    if valid:
        check.check_database(conn)
    else:
        with pytest.raises(ValueError):
            check.check_database(conn)
    conn.set_session.assert_called_once_with(readonly=True)


def test_deployment_rejects_stamped_database_with_missing_columns(modules):
    check = load_module("test_missing_schema", "scripts/check_database.py")
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [("80651478bdd9",)]
    cur.execute.side_effect = [None, None, None, RuntimeError("missing log column")]
    with pytest.raises(RuntimeError, match="missing log column"):
        check.check_database(conn)


def test_deployment_requires_environment_configuration(modules, monkeypatch, capsys):
    check = load_module("test_missing_secret", "scripts/check_database.py")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert check.main() == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_deployment_config_uses_environment_credentials():
    deploy = load_module("test_deploy_config", "scripts/deploy.py")
    env = {"DATABASE_URL": "postgresql://test:p%40ss@localhost/db?sslmode=require",
           "JWT_SECRET": 'test with "quotes"', "FIHANKRA_FEEDBACK_SECRET": "feedback-test"}
    config = deploy.deployment_config(env)
    params = config["default"]["deploy"]["parameters"]
    assert 'DatabaseUrl="postgresql://test:p%40ss@localhost/db?sslmode=require"' in params["parameter_overrides"]
    assert 'JwtSecret="test with \\"quotes\\""' in params["parameter_overrides"]
    assert params["stack_name"] == "gate-access-pg-stack"
    with pytest.raises(ValueError, match="JWT_SECRET"):
        deploy.deployment_config({"DATABASE_URL": "test"})


def test_deploy_keeps_credentials_out_of_arguments_and_output(monkeypatch, tmp_path, capsys):
    deploy = load_module("test_deploy_wrapper", "scripts/deploy.py")
    root = tmp_path / "project"
    template = root / ".aws-sam/build/template.yaml"
    template.parent.mkdir(parents=True)
    template.write_text("test template")
    monkeypatch.setattr(deploy, "__file__", str(root / "scripts/deploy.py"))
    for key in deploy.PARAMETERS.values():
        monkeypatch.setenv(key, "sensitive-test-value")
    seen = []

    def run(args, **kwargs):
        assert "sensitive-test-value" not in str(args)
        path = (template.parent / args[args.index("--config-file") + 1]).resolve()
        assert "sensitive-test-value" in path.read_text()
        assert path.stat().st_mode & 0o777 == 0o600
        assert kwargs["stdout"] == deploy.subprocess.DEVNULL
        assert kwargs["stderr"] == deploy.subprocess.DEVNULL
        seen.append(path)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(deploy.subprocess, "run", run)
    assert deploy.main() == 0
    assert not seen[0].exists()
    assert "sensitive-test-value" not in capsys.readouterr().out


@pytest.fixture
def signup_db():
    # Execute the real handler SQL against a minimal relational schema. PostgreSQL
    # trigger/concurrency behavior is covered separately via UniqueViolation below.
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.create_function("now", 0, lambda: "2026-09-27T00:00:00Z")
    db.executescript('''
        CREATE TABLE personal_info (
            id INTEGER PRIMARY KEY, estate_id INTEGER, name TEXT, id_type TEXT,
            id_num TEXT, contact TEXT, account_type_id INTEGER, access_group_id INTEGER,
            UNIQUE (id_type, id_num, estate_id));
        CREATE TABLE account_holders (
            id INTEGER PRIMARY KEY, user_id INTEGER, personal_info_id INTEGER,
            house_address TEXT, deleted_at TEXT, is_active BOOLEAN DEFAULT FALSE,
            otp TEXT, otp_generated_at TEXT, date_updated TEXT, owner_account_holder_id INTEGER);
        CREATE TABLE logs (target_account_holder_id INTEGER, type TEXT);
        CREATE TABLE account_types (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE access_groups (id INTEGER PRIMARY KEY, estate_id INTEGER, name TEXT);
        INSERT INTO account_types VALUES (1, 'USER_A'), (2, 'ADMIN');
        INSERT INTO access_groups VALUES (1, 10, 'REGULAR'), (2, 20, 'REGULAR');
    ''')
    conn = MagicMock()
    conn.cursor.side_effect = lambda **kwargs: SQLiteCursor(db)
    conn.commit.side_effect = db.commit
    conn.rollback.side_effect = db.rollback
    body = dict(user_id=1, estate_id=10, house_address="House 1", name="Resident",
                id_type="TEST", id_num="123", contact="test contact")
    yield conn, db, body
    db.close()


@pytest.mark.parametrize("handler_name", ["signup", "signupAdmin"])
@pytest.mark.parametrize("claimant", [1, 2])
def test_deleted_identity_signup_keeps_history_and_access_blocked(
        modules, monkeypatch, signup_db, handler_name, claimant):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    monkeypatch.setattr(account, "log", MagicMock())
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    conn, db, body = signup_db
    signup = getattr(account, handler_name)
    created = signup(conn, body)
    assert created["statusCode"] == 201
    account_id = json.loads(created["body"])["account"]["account_holder_id"]
    with conn.cursor() as cur:
        assert account.soft_delete_account_holder(cur, account_id)
    conn.commit()
    before = [tuple(row) for row in db.execute("SELECT * FROM account_holders")]
    identity_before = [tuple(row) for row in db.execute("SELECT * FROM personal_info")]
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": claimant}, None))
    response = signup(conn, dict(body, user_id=claimant))
    if handler_name == "signup" and claimant == 1:
        assert response["statusCode"] == 200
        row = db.execute("SELECT * FROM account_holders").fetchone()
        assert row["id"] == account_id and row["deleted_at"] is None
        assert not row["is_active"]
        assert account.log.call_args.args[1] == "ACCOUNT_REREGISTRATION"
        assert signup(conn, body)["statusCode"] == 409
        assert [tuple(row) for row in db.execute("SELECT * FROM personal_info")] == identity_before
        return
    assert response["statusCode"] == 409
    assert "estate administrator" in json.loads(response["body"])["error"]
    assert [tuple(row) for row in db.execute("SELECT * FROM account_holders")] == before
    assert [tuple(row) for row in db.execute("SELECT * FROM personal_info")] == identity_before
    assert before[0][5] == 0  # is_active stays false
    assert account.log.call_count == 1


@pytest.mark.parametrize("handler_name", ["signup", "signupAdmin"])
def test_signup_duplicate_and_estate_identity_scope(modules, monkeypatch, signup_db, handler_name):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    monkeypatch.setattr(account, "log", MagicMock())
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    conn, db, body = signup_db
    signup = getattr(account, handler_name)
    assert signup(conn, body)["statusCode"] == 201
    assert signup(conn, body)["statusCode"] == 409
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 2}, None))
    assert signup(conn, dict(body, user_id=2))["statusCode"] == 409
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    assert signup(conn, dict(body, estate_id=20))["statusCode"] == 201
    assert db.execute("SELECT COUNT(*) FROM account_holders").fetchone()[0] == 2


@pytest.mark.parametrize("handler_name", ["signup", "signupAdmin"])
@pytest.mark.parametrize("conflict_table", ["personal_info", "account_holders"])
def test_signup_concurrent_duplicate_rolls_back(modules, monkeypatch, handler_name, conflict_table):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    monkeypatch.setattr(account, "log", MagicMock())
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [None, None] + [{"id": 1}] * 4

    def execute(sql, params=()):
        if f"INSERT INTO {conflict_table}" in sql:
            raise account.psycopg2.errors.UniqueViolation("private database detail")

    cur.execute.side_effect = execute
    response = getattr(account, handler_name)(conn, dict(
        user_id=1, estate_id=10, house_address="House 1", name="Resident",
        id_type="TEST", id_num="123", contact="test contact"))
    assert response["statusCode"] == 409
    assert "private database detail" not in response["body"]
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    account.log.assert_not_called()


@pytest.mark.parametrize("payload,error,expected", [
    (None, {"statusCode": 401}, 401),
    ({"gate_id": 1}, None, 403),
    ({"user_id": 2}, None, 403),
])
def test_signup_requires_authenticated_owner(modules, monkeypatch, payload, error, expected):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    monkeypatch.setattr(account, "verify_token", lambda *a: (payload, error))
    conn = MagicMock()
    assert account.signup(conn, {"user_id": 1}, {})["statusCode"] == expected
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("allowed,expected", [(False, 403), (True, 200)])
def test_returning_resident_approval_and_decline(
        modules, monkeypatch, signup_db, allowed, expected):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    conn, db, body = signup_db
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    def record_log(conn, kind, message, actor, target, estate):
        db.execute("INSERT INTO logs VALUES (?, ?)", (target, kind))
    monkeypatch.setattr(account, "log", record_log)
    monkeypatch.setattr(account, "notify_user", MagicMock())
    created = account.signup(conn, body, {})
    account_id = json.loads(created["body"])["account"]["account_holder_id"]
    db.execute("UPDATE account_holders SET otp='old-code', otp_generated_at='old-date' WHERE id=?", (account_id,))
    with conn.cursor() as cur:
        account.soft_delete_account_holder(cur, account_id)
    conn.commit()
    assert account.signup(conn, body, {})["statusCode"] == 200
    row = db.execute("SELECT * FROM account_holders").fetchone()
    assert row["otp"] is None and row["otp_generated_at"] is None
    assert row["deleted_at"] is None and not row["is_active"]
    privileges = MagicMock()
    privileges.can_manage_accounts.return_value = allowed
    privileges.estate_id = 10
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 9}, None))
    monkeypatch.setattr(account, "get_user_privileges", lambda *a, **kw: privileges)
    monkeypatch.setattr(account, "get_user_privileges_for_account_holder", lambda *a, **kw: privileges)
    response = account.activate_account(conn, {
        "account_holder_id": account_id}, {})
    assert response["statusCode"] == expected
    assert bool(db.execute("SELECT is_active FROM account_holders").fetchone()[0]) == (expected == 200)
    if expected == 200:
        assert account.notify_user.call_args.args[0] == "1"
    else:
        account.notify_user.assert_not_called()
    privileges.can_manage_accounts.return_value = True
    assert account.delete_account(conn, {"account_holder_id": account_id}, {})["statusCode"] == 200
    row = db.execute("SELECT * FROM account_holders").fetchone()
    assert row["deleted_at"] is not None and not row["is_active"]
    assert account.activate_account(conn, {"account_holder_id": account_id}, {})["statusCode"] == 404


@pytest.mark.parametrize("ambiguous", [False, True])
def test_signup_does_not_reopen_subaccounts_or_shared_identity(
        modules, monkeypatch, signup_db, ambiguous):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    monkeypatch.setattr(account, "log", MagicMock())
    conn, db, body = signup_db
    assert account.signup(conn, body, {})["statusCode"] == 201
    with conn.cursor() as cur:
        account.soft_delete_account_holder(cur, 1)
    if ambiguous:
        db.execute("INSERT INTO account_holders (user_id, personal_info_id, deleted_at) VALUES (2, 1, 'deleted')")
    else:
        db.execute("UPDATE account_holders SET owner_account_holder_id=9 WHERE id=1")
    conn.commit()
    assert account.signup(conn, body, {})["statusCode"] == 409
    assert db.execute("SELECT deleted_at FROM account_holders WHERE id=1").fetchone()[0] is not None


def test_reregistration_audit_failure_rolls_back(modules, monkeypatch, signup_db):
    account = load_module("test_account_signup", "lambdas/account/handlers/account.py")
    monkeypatch.setattr(account, "verify_token", lambda *a: ({"user_id": 1}, None))
    monkeypatch.setattr(account, "log", MagicMock())
    conn, db, body = signup_db
    assert account.signup(conn, body, {})["statusCode"] == 201
    with conn.cursor() as cur:
        account.soft_delete_account_holder(cur, 1)
    conn.commit()
    account.log.side_effect = RuntimeError("audit failure")
    assert account.signup(conn, body, {})["statusCode"] == 500
    row = db.execute("SELECT * FROM account_holders").fetchone()
    assert row["deleted_at"] is not None and not row["is_active"]
    conn.rollback.assert_called_once()
