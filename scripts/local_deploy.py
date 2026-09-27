"""Run the existing deployment flow with credentials from a private JSON file."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("DATABASE_URL", "JWT_SECRET", "FIHANKRA_FEEDBACK_SECRET",
            "GATE_STACK_NAME", "AWS_REGION")


def load_environment(path):
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise ValueError("Cannot read configuration. Supply a readable JSON object.") from None
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object.")
    for name in REQUIRED:
        value = config.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Set {name} in the local configuration file.")
        if any(char in value for char in "\r\n\x00"):
            raise ValueError(f"{name} must be a single-line value.")
    if "YOUR_URL_ENCODED_PASSWORD" in config["DATABASE_URL"]:
        raise ValueError("Replace the password placeholder in DATABASE_URL.")
    if not config["DATABASE_URL"].startswith(("postgresql://", "postgres://")):
        raise ValueError("DATABASE_URL must use postgresql:// or postgres://.")
    environment = os.environ.copy()
    environment.update({name: config[name] for name in REQUIRED})
    environment["AWS_DEFAULT_REGION"] = config["AWS_REGION"]
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "env/local-deployment.json")
    parser.add_argument("--check-only", action="store_true",
                        help="Check database compatibility without building or deploying.")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    commands = [[sys.executable, "scripts/check_database.py"]]
    if not args.check_only:
        commands += [["sam", "build"], [sys.executable, "scripts/deploy.py"]]
    for command in commands:
        try:
            result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        except OSError:
            print("Unable to start a deployment command. Check Python and SAM CLI installation.",
                  file=sys.stderr)
            return 1
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
