# Deployment configuration

This API now requires MySQL 8.4+. Complete the schema/data migration described in
[MySQL migration notes](mysql-migration.md) before deploying.

Set `DATABASE_URL` in the build or shell environment to the new MySQL URL. The
`DatabaseUrl` parameter in `template.yaml` has no default; a MySQL URL default
can alternatively be supplied. An environment URL takes precedence. `JwtSecret` and
`FeedbackSecret` still come from template defaults. `NoEcho` masks parameter
displays, not template contents or Git history.

CodeBuild installs `tests/requirements.txt`, runs unit tests, checks the database,
builds SAM artifacts, and deploys through `scripts/template_deploy.py`. The shared
layer is rebuilt from requirements and application sources with its Makefile.
The wrapper passes configuration without printing credentials.

```bash
python3 -m pip install -r tests/requirements.txt
python3 -m pytest tests/unit -q
python3 scripts/template_deploy.py --check-only
sam build
python3 scripts/template_deploy.py --deploy-only
```

`--check-only` checks schema and connectivity in a read-only transaction. It does
not migrate data or deploy. The target remains `GATE_STACK_NAME` when provided,
otherwise `gate-access-pg-stack`. AWS region/permissions come from the runner.

For local deployment, populate `DATABASE_URL` in the ignored
`env/local-deployment.json`, along with the existing signing keys, stack name, and
region, then use `python3 scripts/local_deploy.py`. This path does not use template
credential defaults or load `.env`.

Both the build runner and Lambda need access to MySQL on port 3306. VPC settings
are still commented out; enable the appropriate networking for private databases.
