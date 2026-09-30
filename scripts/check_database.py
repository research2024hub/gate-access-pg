"""Read-only MySQL schema checks; never migrates or changes application data."""
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shared/python'))
import database

# The database schema is owned by gate_access_dbsetup. PostgreSQL Alembic
# revision IDs cannot establish compatibility with a converted MySQL schema.
REQUIRED_COLUMNS = {
    'users': 'id email password phone_number is_admin is_active deleted_at reset_otp reset_expiry date_created date_updated',
    'account_holders': 'id user_id personal_info_id house_address owner_account_holder_id is_active deleted_at otp otp_generated_at date_updated',
    'personal_info': 'id estate_id name id_type id_num contact expiry account_type_id access_group_id date_created date_updated',
    'estates': 'id name location_coordinates date_created date_updated',
    'account_types': 'id name date_updated',
    'privileges': 'id name date_updated',
    'access_groups': 'id estate_id name',
    'gates': 'id estate_id name opening_time closing_time active last_controller_heartbeat last_alert_sent_at snr rssi date_updated',
    'vehicles': 'id personal_info_id license_plate_number make model color date_created date_updated',
    'guests': 'id personal_info_id creator_id other_info status',
    'events': 'id creator_id name max_num_of_attendees start_time end_time',
    'event_registers': 'id event_id guest_id',
    'faces': 'id guest_id',
    'logs': 'id estate_id actor_user_id target_account_holder_id type message license_plate_number date_created',
    'pending_users': 'email otp otp_expiry date_updated',
    'pending_account_holders': 'id email owner_account_holder_id personal_info_id house_address otp otp_generated_at',
    'account_type_privilege_links': 'account_type_id privilege_id',
    'personal_info_privilege_links': 'personal_info_id privilege_id',
    'gate_access_group_links': 'gate_id access_group_id opening_time closing_time',
    'user_reports': 'id user_id subject description',
    'report_status': 'report_id status',
    'accesslog': 'id gate_id license_plate_number event timestamp',
    'system_metrics': 'id gate_id device_timestamp temperature_celsius total_cameras online_cameras running_services storage_used_gb storage_total_gb offline_camera_ids received_at',
}
AUTO_ID_TABLES = set(REQUIRED_COLUMNS) - {
    'faces', 'pending_users', 'account_type_privilege_links',
    'personal_info_privilege_links', 'gate_access_group_links', 'report_status',
}
UNIQUE_KEYS = {
    'pending_users': ('email',),
    'account_type_privilege_links': ('account_type_id', 'privilege_id'),
    'personal_info_privilege_links': ('personal_info_id', 'privilege_id'),
    'gate_access_group_links': ('gate_id', 'access_group_id'),
    'report_status': ('report_id',),
}


def check_database(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT VERSION()')
        version = cur.fetchone()[0]
        match = re.match(r'(\d+)\.(\d+)', version)
        if not match or 'mariadb' in version.lower() or tuple(map(int, match.groups())) < (8, 4):
            raise ValueError('MySQL 8.4 or newer is required.')
        cur.execute('START TRANSACTION READ ONLY')
        try:
            for table, columns in REQUIRED_COLUMNS.items():
                projection = ', '.join('`' + name + '`' for name in columns.split())
                cur.execute(f'SELECT {projection} FROM `{table}` LIMIT 0')
            cur.execute('SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()')
            engines = dict(cur.fetchall())
            if any(engines.get(table) != 'InnoDB' for table in REQUIRED_COLUMNS):
                raise ValueError('Every API table must use InnoDB.')
            cur.execute("SELECT TABLE_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                        "AND COLUMN_NAME = 'id' AND EXTRA LIKE '%%auto_increment%%'")
            if not AUTO_ID_TABLES <= {row[0] for row in cur.fetchall()}:
                raise ValueError('API inserts require AUTO_INCREMENT identifiers.')
            cur.execute('SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS '
                        'WHERE TABLE_SCHEMA = DATABASE() AND NON_UNIQUE = 0 ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX')
            indexes = {}
            for table, index, column in cur.fetchall():
                indexes.setdefault((table, index), []).append(column)
            for table, columns in UNIQUE_KEYS.items():
                if not any(t == table and tuple(names) == columns for (t, _), names in indexes.items()):
                    raise ValueError(f'Missing required unique key on {table}.')
        finally:
            conn.rollback()


def main():
    required = ('DATABASE_URL', 'JWT_SECRET', 'FIHANKRA_FEEDBACK_SECRET')
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        print('Set deployment environment variables: ' + ', '.join(missing), file=sys.stderr)
        return 1
    try:
        conn = database.connect(os.environ['DATABASE_URL'], connect_timeout=10, read_timeout=10)
        try:
            check_database(conn)
        finally:
            conn.close()
    except Exception:
        print('Database check failed. Check the MySQL URL, connectivity, and schema requirements '
              'in docs/mysql-migration.md.', file=sys.stderr)
        return 1
    print('MySQL database compatibility check passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
