"""MySQL connections and transactional helpers for single-row API mutations.

Callers own commit/rollback. All tables must use InnoDB. SQL identifiers passed
into helpers are source-code constants, never request parameters.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pymysql
from pymysql.constants import FIELD_TYPE
from pymysql.converters import conversions, escape_datetime
from pymysql.cursors import DictCursor as BaseDictCursor
from pymysql.err import DatabaseError, IntegrityError, ProgrammingError


def _escape_datetime(value, mapping=None):
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return escape_datetime(value, mapping)


class DictCursor(BaseDictCursor):
    """Decode JSON results, including aggregate expressions, into Python values."""
    def _conv_row(self, row):
        result = super()._conv_row(row)
        if result is not None:
            for name in ('other_info', 'running_services', 'offline_camera_ids',
                         'user_emails', 'timestamps'):
                value = result.get(name)
                if isinstance(value, (str, bytes)):
                    result[name] = json.loads(value)
            for name in ('is_active', 'is_admin', 'active'):
                if result.get(name) is not None:
                    result[name] = bool(result[name])
            for name, value in result.items():
                if isinstance(value, timedelta):
                    seconds = int(value.total_seconds())
                    hours, seconds = divmod(seconds, 3600)
                    minutes, seconds = divmod(seconds, 60)
                    result[name] = f'{hours:02}:{minutes:02}:{seconds:02}'
                    if value.microseconds:
                        result[name] += f'.{value.microseconds:06}'
        return result


def mysql_datetime(value):
    """Normalize an ISO API timestamp for a UTC MySQL DATETIME column."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def connection_options(url):
    parsed = urlsplit(url or '')
    if parsed.scheme not in ('mysql', 'mysql+pymysql') or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('DATABASE_URL must be mysql://user:password@host:3306/database.')
    options = parse_qs(parsed.query, keep_blank_values=True)
    allowed = {'ssl_ca', 'ssl_cert', 'ssl_key', 'ssl_disabled', 'connect_timeout', 'charset'}
    if set(options) - allowed or any(len(v) != 1 for v in options.values()):
        raise ValueError('Unsupported or repeated MySQL URL options.')
    if options.get('charset', ['utf8mb4'])[0].lower() != 'utf8mb4':
        raise ValueError('DATABASE_URL charset must be utf8mb4.')
    conv = conversions.copy()
    conv[FIELD_TYPE.JSON] = json.loads
    conv[datetime] = _escape_datetime
    result = dict(host=parsed.hostname, port=parsed.port or 3306,
                  user=unquote(parsed.username or ''), password=unquote(parsed.password or ''),
                  database=unquote(parsed.path.lstrip('/')), charset='utf8mb4',
                  autocommit=False, conv=conv, connect_timeout=10,
                  read_timeout=30, write_timeout=30, init_command="SET time_zone = '+00:00'")
    if 'connect_timeout' in options:
        result['connect_timeout'] = int(options['connect_timeout'][0])
    disabled = options.get('ssl_disabled', ['false'])[0].lower()
    if disabled not in ('true', 'false'):
        raise ValueError('ssl_disabled must be true or false.')
    if disabled == 'true':
        if any(k.startswith('ssl_') and k != 'ssl_disabled' for k in options):
            raise ValueError('TLS certificate options conflict with ssl_disabled=true.')
        result['ssl_disabled'] = True
    else:
        # TLS with certificate and hostname verification is the default.
        result.update(ssl_verify_cert=True, ssl_verify_identity=True, ssl={})
        for key in ('ssl_ca', 'ssl_cert', 'ssl_key'):
            if key in options:
                result[key] = options[key][0]
    return result


def connect(url, **kwargs):
    options = connection_options(url)
    options.update(kwargs)
    return pymysql.connect(**options)


def _identifier(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
        raise ValueError('Invalid SQL identifier.')
    return '`' + name + '`'


def insert_row(cur, sql, params, *, table, columns='id', key_value=None,
               duplicate_ok=False, key_columns=('id',), key_values=None):
    try:
        cur.execute(sql, params)
    except IntegrityError as exc:
        if duplicate_ok and exc.args[0] == 1062:
            return None
        raise
    if cur.rowcount == 0:
        return None
    if key_values is None:
        key_values = (cur.lastrowid if key_value is None else key_value,)
    where = ' AND '.join(_identifier(key) + ' = %s' for key in key_columns)
    cur.execute(f'SELECT {columns} FROM {_identifier(table)} WHERE {where}', tuple(key_values))
    return cur.fetchone()


def update_row(cur, sql, params, *, table, where, where_count, columns='id', key_columns=('id',)):
    """Lock a matching row, update it, then return its new values by stable key.

    Selecting the key first handles unchanged updates and predicates such as
    deleted_at IS NULL which may stop matching after the write.
    """
    where_params = tuple(params[-where_count:]) if where_count else ()
    keys = ', '.join(_identifier(key) for key in key_columns)
    cur.execute(f'SELECT {keys} FROM {_identifier(table)} WHERE {where} FOR UPDATE', where_params)
    row = cur.fetchone()
    if row is None:
        return None
    cur.execute(sql, params)
    key_where = ' AND '.join(_identifier(key) + ' = %s' for key in key_columns)
    cur.execute(f'SELECT {columns} FROM {_identifier(table)} WHERE {key_where} FOR UPDATE',
                tuple(row[key] for key in key_columns))
    return cur.fetchone()


def delete_row(cur, sql, params, *, table, where, where_count, columns='id'):
    where_params = tuple(params[-where_count:]) if where_count else ()
    cur.execute(f'SELECT {columns} FROM {_identifier(table)} WHERE {where} FOR UPDATE', where_params)
    row = cur.fetchone()
    if row is not None:
        cur.execute(sql, params)
    return row


def insert_links(cur, sql, rows):
    """Idempotent link inserts; do not suppress FK, truncation, or other errors."""
    for row in rows:
        try:
            cur.execute(sql, row)
        except IntegrityError as exc:
            if exc.args[0] != 1062:
                raise
