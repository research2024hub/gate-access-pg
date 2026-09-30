"""MySQL-specific behavior, including failure paths and API representations."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from unittest.mock import MagicMock

import pytest
import sqlglot

import database

ROOT = Path(__file__).resolve().parents[2]


def test_url_decodes_credentials_and_sets_utc_without_autocommit():
    options = database.connection_options('mysql://user:p%40ss%2Fword@localhost:3307/gate?ssl_disabled=true')
    assert options['password'] == 'p@ss/word'
    assert options['port'] == 3307
    assert options['database'] == 'gate'
    assert options['init_command'] == "SET time_zone = '+00:00'"
    assert options['autocommit'] is False
    assert options['ssl_disabled'] is True


def test_tls_verification_and_encoded_ca_path():
    options = database.connection_options('mysql+pymysql://user:secret@db/gate?ssl_ca=%2Ftmp%2Fca.pem')
    assert options['ssl_ca'] == '/tmp/ca.pem'
    assert options['ssl_verify_cert'] is True
    assert options['ssl_verify_identity'] is True


@pytest.mark.parametrize('url', [
    '', 'postgresql://user:pass@host/db', 'mysql://host',
    'mysql://host/db?sslmode=require', 'mysql://host/db?ssl_disabled=maybe',
    'mysql://host/db?ssl_disabled=true&ssl_ca=/tmp/ca.pem',
    'mysql://host/db?connect_timeout=1&connect_timeout=2',
])
def test_invalid_urls_fail_before_connecting(url):
    with pytest.raises(ValueError):
        database.connection_options(url)


def test_aware_datetime_parameters_are_normalized_to_utc():
    value = datetime(2026, 1, 1, 13, 15, 0, 123456, timezone(timedelta(hours=2)))
    assert database._escape_datetime(value) == "'2026-01-01 11:15:00.123456'"


def test_dictionary_cursor_preserves_json_boolean_and_time_values():
    cursor = database.DictCursor(MagicMock())
    cursor._fields = ['other_info', 'user_emails', 'is_active', 'is_admin', 'opening_time']
    result = cursor._conv_row((' {"otp":"001234"}', '[null,"a@example.com"]', 1, 0, timedelta(hours=8)))
    assert result['other_info'] == {'otp': '001234'}
    assert result['user_emails'] == [None, 'a@example.com']
    assert result['is_active'] is True
    assert result['is_admin'] is False
    assert result['opening_time'] == '08:00:00'


def test_insert_uses_connection_local_insert_id():
    cur = MagicMock(rowcount=1, lastrowid=42)
    cur.fetchone.return_value = {'id': 42, 'name': 'new'}
    row = database.insert_row(cur, 'INSERT INTO gates (name) VALUES (%s)', ('new',), table='gates', columns='id, name')
    assert row == {'id': 42, 'name': 'new'}
    assert cur.execute.call_args.args == ('SELECT id, name FROM `gates` WHERE `id` = %s', (42,))


@pytest.mark.parametrize('code,ignored', [(1062, True), (1452, False), (1048, False)])
def test_link_insert_only_suppresses_duplicate_key(code, ignored):
    cur = MagicMock()
    cur.execute.side_effect = database.IntegrityError(code, 'private detail')
    kwargs = dict(table='personal_info_privilege_links', duplicate_ok=True,
                  key_columns=('personal_info_id', 'privilege_id'), key_values=(1, 2))
    if ignored:
        assert database.insert_row(cur, 'INSERT ...', (1, 2), **kwargs) is None
    else:
        with pytest.raises(database.IntegrityError):
            database.insert_row(cur, 'INSERT ...', (1, 2), **kwargs)
    cur.fetchone.assert_not_called()


def test_update_reads_new_values_by_key_when_where_predicate_changes():
    cur = MagicMock(rowcount=0)
    cur.fetchone.side_effect = [{'id': 7}, {'id': 7, 'is_active': False}]
    row = database.update_row(cur, 'UPDATE users SET deleted_at=NOW() WHERE id=%s AND deleted_at IS NULL', (7,),
                              table='users', where='id=%s AND deleted_at IS NULL', where_count=1,
                              columns='id, is_active')
    assert row == {'id': 7, 'is_active': False}
    calls = cur.execute.call_args_list
    assert calls[0].args[0].endswith('FOR UPDATE')
    assert calls[-1].args == ('SELECT id, is_active FROM `users` WHERE `id` = %s FOR UPDATE', (7,))


def test_update_of_missing_row_does_not_write():
    cur = MagicMock()
    cur.fetchone.return_value = None
    assert database.update_row(cur, 'UPDATE gates SET name=%s WHERE id=%s', ('x', 7),
                               table='gates', where='id=%s', where_count=1) is None
    cur.execute.assert_called_once()


def test_delete_returns_locked_old_values_before_cascade():
    cur = MagicMock()
    cur.fetchone.return_value = {'name': 'removed', 'estate_id': 9}
    row = database.delete_row(cur, 'DELETE FROM gates WHERE id=%s', (7,), table='gates',
                              where='id=%s', where_count=1, columns='name, estate_id')
    assert row == {'name': 'removed', 'estate_id': 9}
    assert cur.execute.call_args_list[0].args[0].endswith('FOR UPDATE')
    assert cur.execute.call_args.args == ('DELETE FROM gates WHERE id=%s', (7,))


def test_bulk_link_insert_continues_after_duplicate_but_propagates_fk_error():
    cur = MagicMock()
    cur.execute.side_effect = [database.IntegrityError(1062, 'duplicate'), None,
                               database.IntegrityError(1452, 'foreign key')]
    with pytest.raises(database.IntegrityError):
        database.insert_links(cur, 'INSERT ...', [(1, 2), (1, 3), (1, 4)])
    assert cur.execute.call_count == 3


def application_sql():
    paths = list((ROOT / 'lambdas').rglob('*.py')) + [ROOT / 'shared/python/utils.py', ROOT / 'shared/python/vehicle.py']
    for path in paths:
        tree = ast.parse(path.read_text())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        constants = {n.targets[0].id: n.value.value for n in ast.walk(tree)
                     if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                     and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
        for node in ast.walk(tree):
            sql = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and not isinstance(parents.get(node), ast.JoinedStr):
                sql = node.value
            elif isinstance(node, ast.JoinedStr):
                parts = []
                for part in node.values:
                    if isinstance(part, ast.Constant):
                        parts.append(part.value)
                    else:
                        name = ast.unparse(part.value)
                        parts.append(constants.get(name, {
                            'where_clause': 'WHERE TRUE', 'filter_sql': 'TRUE',
                            'deleted_filter': 'WHERE deleted_at IS NULL',
                            "','.join(columns)": 'gate_id,access_group_id',
                            "','.join(placeholders)": '%s,%s',
                        }.get(name, 'UNRESOLVED_SQL')))
                sql = ''.join(parts)
            if sql and re.match(r'^\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\s', sql, re.I):
                if sql == 'SELECT id FROM privileges WHERE id IN (':
                    continue  # Runtime parameter count is covered by handler tests.
                yield f'{path.relative_to(ROOT)}:{node.lineno}', sql


@pytest.mark.parametrize('location,sql', list(application_sql()), ids=lambda value: value if len(value) < 100 else None)
def test_queries_use_mysql_syntax(location, sql):
    assert not re.search(r'\b(RETURNING|ILIKE|ON CONFLICT|ARRAY_AGG|BOOL_OR|BOOL_AND)\b|::\w+|=\s*ANY\(', sql, re.I), location
    assert 'UNRESOLVED_SQL' not in sql, location
    assert not re.search(r'COUNT\(\*\)\s+FROM', sql, re.I), location
    sqlglot.parse(sql.replace('%s', '?'), read='mysql', error_level=sqlglot.ErrorLevel.RAISE)
    if 'entry_window' in sql:
        assert '[0-9]{2}' in sql  # F-string braces must survive interpolation.
        assert 'CONVERT_TZ(' in sql


@pytest.mark.parametrize('value', ['2026-01-01T11:00:00Z', '2026-01-01T13:00:00+02:00', '2026-01-01T11:00:00'])
def test_iso_api_timestamps_keep_the_same_utc_instant(value):
    assert database.mysql_datetime(value) == datetime(2026, 1, 1, 11, 0)


def test_nullable_timestamp_update_keeps_none():
    assert database.mysql_datetime(None) is None


@pytest.mark.parametrize('charset', ['utf8mb4', 'UTF8MB4'])
def test_schema_project_url_accepts_utf8mb4(charset):
    options = database.connection_options('mysql+pymysql://user:secret@db/gate?charset=' + charset)
    assert options['charset'] == 'utf8mb4'
    assert options['ssl_verify_cert'] is True
    assert options['ssl_verify_identity'] is True


@pytest.mark.parametrize('query', ['charset=latin1', 'charset=', 'charset=utf8', 'charset=utf8mb4&charset=utf8mb4'])
def test_incompatible_or_repeated_charset_is_rejected(query):
    with pytest.raises(ValueError):
        database.connection_options('mysql+pymysql://user:secret@db/gate?' + query)


def test_sql_collection_includes_privilege_cte():
    assert any('WITH target_account_holder' in sql for _, sql in application_sql())
