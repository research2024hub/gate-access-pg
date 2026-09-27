"""Pass environment credentials to SAM without putting them in argv or logs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PARAMETERS = {
    "DatabaseUrl": "DATABASE_URL",
    "JwtSecret": "JWT_SECRET",
    "FeedbackSecret": "FIHANKRA_FEEDBACK_SECRET",
}


def deployment_config(environ):
    missing = [key for key in PARAMETERS.values() if not environ.get(key)]
    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))
    # SAM's parameter parser accepts quoted values; escape quotes and backslashes.
    overrides = []
    for parameter, variable in PARAMETERS.items():
        value = environ[variable]
        if any(char in value for char in "\r\n\x00"):
            raise ValueError("Deployment credentials must be single-line values.")
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        overrides.append(f'{parameter}="{escaped}"')
    return {
        "version": 0.1,
        "default": {"deploy": {"parameters": {
            "stack_name": environ.get("GATE_STACK_NAME", "gate-access-pg-stack"),
            "resolve_s3": True,
            "capabilities": "CAPABILITY_IAM",
            "confirm_changeset": False,
            "fail_on_empty_changeset": False,
            "parameter_overrides": " ".join(overrides),
        }}},
    }


def main():
    try:
        config = deployment_config(os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    template = root / ".aws-sam/build/template.yaml"
    if not template.exists():
        print("Run sam build before deployment.", file=sys.stderr)
        return 1
    print("Deploying API; SAM output is suppressed because it can print parameter values.", flush=True)
    # JSON is valid YAML. This file is private, temporary, and outside the repo.
    with tempfile.TemporaryDirectory(prefix="gate-deploy-") as directory:
        config_path = Path(directory) / "samconfig.yaml"
        fd = os.open(str(config_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle)
        try:
            result = subprocess.run(
                ["sam", "deploy", "--template-file", str(template),
                 "--config-file", os.path.relpath(config_path, template.parent)],
                cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            print("Unable to start SAM CLI. Verify that sam is installed.", file=sys.stderr)
            return 1
    if result.returncode:
        print("SAM deployment failed. Check AWS credentials, deployment permissions, "
              "and CloudFormation stack events. Credential-bearing SAM output was not saved.",
              file=sys.stderr)
        return result.returncode
    print("Deployment completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
