# API / gate_access_dbsetup compatibility review

Reviewed 2026-09-30 against `/Users/vdowana/Downloads/gate_access_dbsetup`,
including its `mysql_0001` baseline, `mysql_0002` trigger repair, models, triggers, seed script,
connection configuration, and deployment guide.

**Result: source/schema checks and live database/API tests pass with migrations
through `mysql_0002` and READ COMMITTED isolation. Production connectivity,
TLS, imported data, and full application acceptance remain unverified.**

MySQL 8.4.11 was retested in an isolated container on 2026-09-30. No production records
or database-project source files were changed. See [live Docker results](mysql-docker-validation.md).

## Findings and current status

### 1. Privilege aggregation — fixed in API

The 14 PostgreSQL BOOL_OR expressions in `shared/python/utils.py` now use MAX
with the existing outer COALESCE to preserve false/NULL behavior. SQL discovery
includes WITH queries and rejects BOOL_OR/BOOL_AND. Behavioral tests execute the
real privilege CTE against a minimal relational fixture, covering account-type
and personal grants, unrelated/no privileges, and inactive/deleted memberships.
Live MySQL execution passed for both absent and seeded active memberships.

### 2. Guest ownership — fixed in database source

Both `gate_access_dbsetup/app/db/models/guest.py` and its active mysql_0001
migration now reference account_holders.id from guests.creator_id, matching the
API’s inserts, joins, and authorization checks. Database tests cover this contract.
The transfer project now includes ownership mapping/validation and tests for
ambiguous, missing, and explicitly overridden mappings. Actual source records
still require transfer preflight and validation; unit tests do not certify them.

### 3. Report-status uniqueness — fixed in database source

Both the model and mysql_0001 now enforce UNIQUE(report_id), matching the API’s
one-current-status-per-report behavior and predeploy uniqueness check. The
source/schema comparison no longer reports this mismatch.

These constraints were changed in the mysql_0001 baseline. The new mysql_0002
revision repairs triggers only. A fresh database receives the corrected constraints
on upgrade. A database created from an older baseline still needs its actual
constraints checked and any missing ownership/uniqueness fixes migrated separately;
rerunning upgrade head does not reapply an edited baseline.

### 4. OTP resend — fixed in API

`send_user_otp` now locks and updates an existing pending_users row. It changes
only the OTP, expiry, and update timestamp, preserving the password hash and phone
number. Missing pending registrations receive 404 and must register first. Email
is sent only after commit. Regression tests cover existing/missing registrations
and write failure; the schema's required-password contract is preserved.

### 5. The supplied database hosting path is unreachable from Lambda

`gate_access_dbsetup/compose.yaml:11` binds MySQL to 127.0.0.1 on its host. The
hosting guide confirms this is for same-host access or an SSH tunnel. The API runs
in Lambda, and its VPC settings in template.yaml remain commented out.

For an EC2-hosted database, configure a reachable private interface, appropriate
Lambda/build-runner network paths and security groups, and matching TLS trust.
The API enables certificate and hostname verification; a default local container
certificate is not automatically a trusted certificate for an EC2 hostname.
Changing the URL alone does not supply networking or certificates.

### 6. Connection URL charset — fixed in API

The API accepts `charset=utf8mb4` in mysql+pymysql URLs, matching the database
project's generated format. Other character sets and duplicate charset options
are rejected. TLS verification and the utf8mb4 connection encoding are preserved.
Both projects can use the mysql+pymysql scheme with the same database endpoint;
network access and TLS certificate provisioning are still separate requirements.

## Checks completed on recheck

- Inspected 25 application tables and 67 table/index DDL statements.
- Database tests confirm the frozen baseline matches current models (with table
  option ordering normalized) and trigger definitions match exactly.
- All columns in the API’s required-column checklist exist; every unique key
  required by its predeploy checker exists in the baseline.
- Qualified 197 collected SELECT/CTE statements against the current schema, with
  no unresolved table/column references. This does not prove runtime behavior.
- Checked literal insert/update column names and required insert fields; no
  mismatches found.
- Confirmed corrected guest ownership, single report status, JSON/UTC storage,
  ID generation, privilege aggregation, OTP resend, and charset URL handling.
- API suite against Docker MySQL: **401 passed, none skipped**. This includes
  three live mutation/JSON/UTC tests; it is not full end-to-end handler coverage.
- Database suite against Docker MySQL: **20 passed**, including concurrent
  memberships/capacity, isolation enforcement, and preservation of existing records
  across the mysql_0002 trigger migration. Both previous error-1442 cases passed.
- The database project now preserves original visible user/membership columns:
  live-user identity uniqueness uses expression indexes; live membership
  uniqueness uses triggers that raise duplicate-key error 1062, which the API
  handles. Live concurrency tests passed under READ COMMITTED.

The live API schema check, actual privilege CTE with an active membership, and API
helpers creating/updating membership and registering an event guest passed. The
test server enabled log_bin_trust_function_creators for migration installation;
the target still needs suitable trigger-creation permissions/configuration.
Apply mysql_0002 with writers paused as directed in that migration. Configure
READ COMMITTED on the target: the API inherits server isolation and the new
triggers deliberately reject affected writes under REPEATABLE READ.

Production TLS/networking, imported records, and end-to-end application behavior
remain unverified. Compose still binds MySQL to localhost and Lambda VPC settings
remain commented out. Existing mysql_0001 installations need mysql_0002 and a check
that their original baseline already contained the corrected constraints.

## Required joint acceptance check

The fresh mysql_0001 → mysql_0002 installation, seed, and API predeploy schema check
have passed in a disposable MySQL 8.4 database. Complete application acceptance:
Exercise signup/resend, resident approval, guest creation with differing user and
account-holder IDs, guest OTP/vehicle access, privilege checks, report status,
event capacity, and rollback through the real handlers with notifications mocked.
Then rehearse the existing-data transfer and run the same checks on that imported
schema before production cutover.
