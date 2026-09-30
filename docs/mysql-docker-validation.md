# Live Docker MySQL validation

## Latest retest — 2026-09-30

**Outcome: all database and API tests passed against MySQL 8.4.11.**

The same dedicated container was restarted with a fresh, uniquely named test
database and synthetic records. No production database or database-project source
was changed. The container was stopped after testing.

| Check | Result |
|---|---|
| Fresh Alembic upgrade through `mysql_0002` and seed | Passed |
| Database suite, including live concurrency and migration preservation | 20 passed |
| API read-only schema compatibility check | Passed |
| Actual API privilege CTE with a seeded active membership | Passed |
| API insert/update helpers with membership and event-registration triggers | Passed |
| API unit and live database suite | 401 passed, zero skipped |

The previously failing membership and event-capacity cases now pass. The database
suite also checks concurrent membership creation, concurrent capacity enforcement,
rejection of REPEATABLE READ, guest ownership, and report-status uniqueness.

Deployment must apply `mysql_0002` and configure **READ COMMITTED**: the API inherits
server isolation, and the repaired triggers reject writes under REPEATABLE READ.
Trigger creation was enabled only on the disposable server using
`log_bin_trust_function_creators=1`; the target needs suitable migration permissions
and configuration. Follow the migration's instruction to pause writers while
replacing triggers.

Production network/TLS, imported data, and complete handler workflows remain
separate acceptance checks. Local API connections explicitly disabled TLS.

## Historical run — 2026-09-29

**Outcome: API database tests pass; database business-rule triggers block deployment.**

## Isolation and environment

- Dedicated container: `gate-api-mysql-test-20260929`, image `mysql:8.4`.
- Server reported MySQL **8.4.11**.
- Disposable schema: `gate_access_test`; synthetic data only.
- UTC session/server timezone, READ COMMITTED, utf8mb4_0900_bin.
- No existing database containers, production databases, or source records changed.
- No database-project code changed. Local API integration tests explicitly disabled
  TLS against the loopback-only test server; production TLS was not exercised.

## Results

| Check | Result |
|---|---|
| Migration with normal test user and default server settings | Failed, MySQL 1419 |
| Migration after isolated trigger-creation configuration | Passed |
| Schema seed | Passed |
| API read-only schema compatibility check | Passed |
| Exact API privilege CTE with no matching membership | Passed |
| API unit + live database suite | 400 passed, zero skipped |
| Database unit + integration suite | 12 passed, 2 errors |
| Separate event-registration diagnostic | Failed, MySQL 1442 |

The API live tests cover transactional inserts/updates/deletes, no-op updates,
duplicate handling, rollback, JSON decoding, and UTC parameter conversion.
They do not establish that all handlers work with the full business-rule schema.

## Failure 1: trigger installation permissions (1419)

The database migration failed when creating its first date_updated trigger:

> You do not have the SUPER privilege and binary logging is enabled.

The disposable server was configured with
`SET GLOBAL log_bin_trust_function_creators = 1`, then only its partially created
test schema was recreated. The same migration and seed then succeeded with the
normal test user. Production needs an explicitly reviewed migration-privilege /
server-configuration strategy; this test-server adjustment was not applied to any
real database.

## Failure 2: membership trigger (1442)

`account_holder_estate_insert` / `account_holder_estate_update` in
`gate_access_dbsetup/scripts/schema_rules.py` lock/read account_holders with
`FOR UPDATE` while that table is already being modified by the invoking statement.
MySQL rejects a normal account_holders insert with a personal_info reference:

> Can't update table 'account_holders' in stored function/trigger because it is already used by statement which invoked this stored function/trigger.

Both `test_membership_across_personal_records_and_soft_delete` and
`test_rules_and_concurrent_capacity` stop at this failure. The latter does not
reach its concurrency assertions.

## Failure 3: event-capacity trigger (1442)

A separate rollback-only diagnostic used a soft-deleted synthetic account holder
without personal_info, avoiding the live-membership rule while retaining the
installed schema and triggers. It created an event with one available place and
attempted its first registration. MySQL rejected it:

> Can't update table 'event_registers' in stored function/trigger because it is already used by statement which invoked this stored function/trigger.

The capacity trigger's locking read of event_registers has the same self-table
restriction. This needs correction in the database rules and active migration,
followed by live concurrent-capacity and membership tests. Removing the locking
clause without validating concurrency is not sufficient evidence of correctness.

## Next validation

1. Correct both database trigger designs and their migrations.
2. Recreate only a disposable schema and rerun all database integration tests.
3. Rerun the API suite and schema check.
4. Exercise real signup, guest access, privilege grants, reports, and event capacity
   against the corrected schema, with notification/AWS services mocked.
5. Validate the production network/TLS path and data-transfer rehearsal separately.

For an existing database already on mysql_0001, provide a forward migration;
editing the baseline does not update installed triggers.
