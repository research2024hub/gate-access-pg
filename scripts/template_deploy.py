"""Read repository template defaults for the database check and deployment."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = {
    "DatabaseUrl": "DATABASE_URL",
    "JwtSecret": "JWT_SECRET",
    "FeedbackSecret": "FIHANKRA_FEEDBACK_SECRET",
}


def load_environment(path, environ):
    try:
        # Compose the YAML tree without evaluating CloudFormation intrinsic tags.
        document = yaml.compose(Path(path).read_text())
        sections = {key.value: value for key, value in document.value}
        parameters = {key.value: value for key, value in sections["Parameters"].value}
        environment = dict(environ)
        for name, variable in PARAMETERS.items():
            fields = {key.value: value for key, value in parameters[name].value}
            default = fields["Default"]
            if not isinstance(default, yaml.ScalarNode) or default.tag != "tag:yaml.org,2002:str":
                raise ValueError()
            value = default.value
            if not value or any(char in value for char in "\r\n\x00"):
                raise ValueError()
            # The template is the credential source for this deployment path.
            environment[variable] = value
        if not environment["DATABASE_URL"].startswith(("postgresql://", "postgres://")):
            raise ValueError()
        return environment
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
        # Parser errors can include source lines containing credentials.
        raise ValueError("Cannot load valid deployment defaults from template.yaml.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--deploy-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(ROOT / "template.yaml", os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    script = "scripts/check_database.py" if args.check_only else "scripts/deploy.py"
    try:
        return subprocess.run([sys.executable, script], cwd=ROOT,
                              env=environment, check=False).returncode
    except OSError:
        print("Unable to start deployment command.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
