# Deployment configuration

The repository deployment now reads the `DatabaseUrl`, `JwtSecret`, and
`FeedbackSecret` parameter defaults in `template.yaml`. These were copied from
the existing local deployment configuration. Lambda receives them through the
existing parameter references as environment variables.

The values are plaintext in the tracked template. `NoEcho` masks CloudFormation
parameter displays; it does not hide the template contents or Git history.

## CodeBuild

No CodeBuild credential environment variables are required. `buildspec.yaml`:

1. Installs `tests/requirements.txt`, including PyYAML.
2. Runs the unit tests.
3. Runs `python scripts/template_deploy.py --check-only`.
4. Runs `sam build`.
5. Runs `python scripts/template_deploy.py --deploy-only`.

Include the deployment scripts and requirements in the commit. The wrapper loads
credentials from the source template without printing them, then supplies them to
the existing check/deploy scripts. Template credentials take precedence over any
stale build credential variables. Other environment settings are preserved.
Explicit parameter overrides ensure updates use these values even for an existing
stack. SAM output is suppressed because it can include parameter values.

The deployment target is still `GATE_STACK_NAME` when provided, otherwise
`gate-access-pg-stack`, as configured in `scripts/deploy.py`. Verify this matches
the existing deployment. The region and AWS permissions come from the build's AWS
configuration. This change does not grant deployment permissions.

## Manual commands using the template

```bash
python3 -m pip install -r tests/requirements.txt
python3 scripts/template_deploy.py --check-only
```

After that check passes, build and deploy:

```bash
sam build
python3 scripts/template_deploy.py --deploy-only
```

`--check-only` is read-only. It verifies connectivity and required schema;
it does not deploy or apply migrations.

The separate `scripts/local_deploy.py` remains available for local deployment
using the ignored `env/local-deployment.json` instead of template defaults.
That path still requires the database URL, signing keys, confirmed stack name,
and region in the local file. Changes to that file do not update template defaults.

## Database prerequisites

Apply the reviewed migrations from `gate_access_dbsetup` before deployment. This
API needs the soft-delete columns and uniqueness changes, and
`logs.license_plate_number` (through revision `2047cc35125e`). The reviewed head
is `80651478bdd9`. Follow the database project's maintenance-window notes.
The deployment check accepts these reviewed revisions and does not apply migrations.

The build runner and Lambda must both be able to reach the configured database.
The template's Lambda VPC configuration remains commented out. Switching to a
private Aurora database still requires the appropriate networking; embedding its
URL does not resolve connection timeouts.
