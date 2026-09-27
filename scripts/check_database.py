"""Read-only deployment check against the same environment configuration used by Lambda."""
import os
import sys

import psycopg2


# These revisions include soft deletion, its uniqueness changes, and log plates.
COMPATIBLE_REVISIONS = {"2047cc35125e", "80651478bdd9"}


def check_database(conn):
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        revisions = {row[0] for row in cur.fetchall()}
        if len(revisions) != 1 or not revisions <= COMPATIBLE_REVISIONS:
            raise ValueError("Apply the reviewed database migrations before deploying this API.")
        # Also detect a stamped revision whose required schema is absent.
        cur.execute("SELECT deleted_at, is_active FROM users LIMIT 0")
        cur.execute("SELECT deleted_at, is_active FROM account_holders LIMIT 0")
        cur.execute("SELECT license_plate_number FROM logs LIMIT 0")


def main():
    required = ("DATABASE_URL", "JWT_SECRET", "FIHANKRA_FEEDBACK_SECRET")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        print("Set deployment environment variables: " + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10,
                               options="-c statement_timeout=10000")
        try:
            check_database(conn)
        finally:
            conn.close()
    except Exception:
        # Connection errors can expose infrastructure details; never print secrets.
        print("Database check failed. Check DATABASE_URL, connectivity, and migrations "
              "through 2047cc35125e (reviewed head: 80651478bdd9).", file=sys.stderr)
        return 1
    print("Database compatibility check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
