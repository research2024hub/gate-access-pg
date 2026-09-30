# MySQL migration

The API targets **MySQL 8.4+**, using PyMySQL. See the
[current compatibility report](mysql-compatibility-review.md) for remaining
database and deployment blockers. The source project and AWS stack
names retain `gate-access-pg` to avoid accidentally creating another stack.
The backup in Downloads remains the original PostgreSQL version.

## Database schema and existing data

This repository does **not** contain the `gate_access_dbsetup` schema/migrations
or a database dump. Converting API queries does not convert the existing database.
The schema owner must port that project's migrations and transfer existing data
into a separate MySQL database before this API is deployed. Do not run PostgreSQL
migration files directly against MySQL or merely change an existing endpoint's URL.

The schema conversion must preserve these contracts:

- All API tables use InnoDB, with the same foreign keys and deletion cascades.
  In particular, deleting `personal_info` must retain the intended dependent-row
  cleanup. User/account soft deletion must retain historical data.
- Generated integer primary keys use `AUTO_INCREMENT`; `faces.id` keeps its
  externally supplied face identifier. Preserve all existing identifiers during
  import and advance the counters past imported values.
- PostgreSQL JSON/JSONB and array columns become JSON where used by the API:
  `guests.other_info`, `system_metrics.running_services`, and
  `system_metrics.offline_camera_ids`. Import arrays as valid JSON arrays.
- Store timestamps in UTC, preferably `DATETIME(6)` for unrestricted date ranges;
  every API connection sets its session timezone to `+00:00`. Convert source
  `timestamptz` values to UTC before import. Gate opening/closing times use TIME.
- Preserve boolean defaults, timestamp defaults, enum/status values, OTP strings,
  and all non-null constraints. Use `utf8mb4`. Review collations for identity and
  email uniqueness; MySQL's default case-insensitive collation may differ from the
  original constraints.
- Preserve unique keys on link-table pairs, `pending_users.email`, and
  `report_status.report_id`. The duplicate handlers only suppress MySQL error 1062;
  foreign-key and other integrity failures remain errors.
- Reproduce live-user email and account uniqueness rules. PostgreSQL partial
  unique indexes need an equivalent MySQL design, such as generated nullable
  columns with unique indexes. Preserve the estate-scoped identity constraint
  `(id_type, id_num, estate_id)` and test returning-resident approval/decline.

`scripts/check_database.py` lists required columns and verifies the MySQL version,
InnoDB engines, generated identifiers, and selected unique keys in a read-only
transaction. This is a deployment prerequisite, **not** proof that every foreign
key, default, index, trigger, or migrated row is correct. PostgreSQL Alembic
revision IDs are no longer accepted as evidence of MySQL compatibility.

## Connection configuration

Set `DATABASE_URL` to an actual MySQL endpoint:

```text
mysql://USER:URL_ENCODED_PASSWORD@MYSQL_HOST:3306/gate_access
```

`mysql+pymysql://` is also accepted. Percent-encode special characters in credentials.
Supported query options are `ssl_ca`, `ssl_cert`, `ssl_key`, `connect_timeout`,
`ssl_disabled`, and `charset=utf8mb4`. Other character sets and repeated URL options
are rejected. TLS certificate and hostname verification are enabled by default.
For a local test server without TLS, explicitly append `?ssl_disabled=true`.
Certificate paths must exist in both the deployment runner and Lambda if used.

The template's DatabaseUrl parameter intentionally has no default. The template deployment
wrapper takes `DATABASE_URL` from its environment, falling back to a nonempty
MySQL template default if one is supplied. JWT and feedback secret behavior is
unchanged. The ignored local `.env` and `env/local-deployment.json` database values
were cleared and must be filled with the new endpoint if those files are used.
The deployment wrappers do not automatically load `.env`.

Allow MySQL TCP port **3306** from both Lambda and the build runner. Configure the
commented VPC settings in `template.yaml` when using a private endpoint.

Apply the database project's migrations through `mysql_0002` and configure the
MySQL server with **READ COMMITTED** transaction isolation. The API inherits this
setting; the membership and event-capacity triggers reject affected writes under
REPEATABLE READ. Pause writers while applying the trigger-replacement migration.
The [Docker retest](mysql-docker-validation.md) passed all 20 database tests and
401 API tests on 2026-09-30 with this configuration; production TLS/networking
and imported data still need validation.

## Build and validation

`POST /user/register-admin` now requires `Authorization: Bearer <login-token>`
from an existing active global admin. The handler verifies the JWT and checks
the caller's current `users.is_admin` value in the database; a passkey no longer
authorizes registration. Clients should send email or phone number and password
in the JSON body, without a passkey. Existing global admins can log in normally;
if none exists, an authorized database operator must bootstrap the first admin
through a controlled database operation. Public signup does not grant admin access.

```bash
python3 -m pip install -r tests/requirements.txt
python3 -m pytest tests/unit -q
python3 scripts/template_deploy.py --check-only
sam build
python3 scripts/template_deploy.py --deploy-only
```

The layer Makefile builds fresh Lambda-compatible dependencies and copies only
application modules, avoiding the old vendored PostgreSQL packages and caches.
Rebuild before deploying; existing `.aws-sam` artifacts are stale.

Run the optional live mutation checks against a **disposable** MySQL 8.4 database:

```bash
MYSQL_TEST_URL='mysql://USER:PASSWORD@localhost:3306/test_db?ssl_disabled=true' \
  python3 -m pytest tests/integration -q
```

Before production cutover, test signup and reregistration, OTP expiry, timed guest
access with UTC and offset entry windows, privilege-link conflicts, update/delete
responses, notifications, monitoring aggregates, and transactional rollback against
the imported schema. No database migration or deployment is performed by this
source conversion.

Driver reference: [PyMySQL connections](https://pymysql.readthedocs.io/en/latest/modules/connections.html).
MySQL reference: [JSON functions](https://dev.mysql.com/doc/refman/8.4/en/json-function-reference.html).
