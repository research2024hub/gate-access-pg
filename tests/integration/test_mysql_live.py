"""Run explicitly with MYSQL_TEST_URL pointing to a disposable MySQL 8.4 DB."""
import os
from datetime import datetime, timedelta, timezone

import pytest
import database


@pytest.fixture
def connection():
    url = os.environ.get('MYSQL_TEST_URL')
    if not url:
        pytest.skip('Set MYSQL_TEST_URL to run live MySQL integration checks.')
    conn = database.connect(url)
    with conn.cursor() as cur:
        cur.execute('''CREATE TEMPORARY TABLE migration_test_rows (
            id BIGINT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(100) UNIQUE,
            is_active BOOLEAN DEFAULT TRUE, deleted_at DATETIME(6),
            other_info JSON, occurred_at DATETIME(6)
        ) ENGINE=InnoDB''')
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_transactional_mutations(connection):
    with connection.cursor(cursor=database.DictCursor) as cur:
        row = database.insert_row(cur, 'INSERT INTO migration_test_rows (name) VALUES (%s)',
                                  ('first',), table='migration_test_rows', columns='id, is_active')
        assert row['is_active'] is True
        key = row['id']
        for _ in range(2):  # Includes a no-op update; matching rows must still be returned.
            updated = database.update_row(cur, 'UPDATE migration_test_rows SET name=%s WHERE id=%s', ('same', key),
                                          table='migration_test_rows', where='id=%s', where_count=1,
                                          columns='id, name')
            assert updated == {'id': key, 'name': 'same'}
        deleted = database.update_row(cur,
            'UPDATE migration_test_rows SET deleted_at=NOW(), is_active=FALSE WHERE id=%s AND deleted_at IS NULL',
            (key,), table='migration_test_rows', where='id=%s AND deleted_at IS NULL', where_count=1,
            columns='id, is_active')
        assert deleted == {'id': key, 'is_active': False}
        old = database.delete_row(cur, 'DELETE FROM migration_test_rows WHERE id=%s', (key,),
                                  table='migration_test_rows', where='id=%s', where_count=1, columns='name')
        assert old == {'name': 'same'}
        cur.execute('SELECT COUNT(*) AS count FROM migration_test_rows')
        assert cur.fetchone()['count'] == 0


def test_duplicate_and_rollback(connection):
    with connection.cursor(cursor=database.DictCursor) as cur:
        sql = 'INSERT INTO migration_test_rows (name) VALUES (%s)'
        assert database.insert_row(cur, sql, ('same',), table='migration_test_rows')
        assert database.insert_row(cur, sql, ('same',), table='migration_test_rows', duplicate_ok=True) is None
        connection.rollback()
        cur.execute('SELECT COUNT(*) AS count FROM migration_test_rows')
        assert cur.fetchone()['count'] == 0


def test_json_and_utc_parameters(connection):
    with connection.cursor(cursor=database.DictCursor) as cur:
        when = datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=2)))
        row = database.insert_row(cur,
            'INSERT INTO migration_test_rows (name, other_info, occurred_at) VALUES (%s,%s,%s)',
            ('json', '{"otp":"001234"}', when), table='migration_test_rows', columns='other_info, occurred_at')
        assert row['other_info'] == {'otp': '001234'}
        assert row['occurred_at'] == datetime(2026, 1, 1, 11, 0)
