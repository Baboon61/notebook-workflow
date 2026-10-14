#!/usr/bin/env python3
"""Find the installed local tooling interpreter, then run the notebook CLI."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def main():
    if importlib.util.find_spec("notebook_workflow") is not None:
        from notebook_workflow.cli import main as cli
        return cli()
    config = Path(__file__).resolve().parents[1] / "tooling.json"
    if config.exists():
        interpreter = Path(json.loads(config.read_text())["python"])
        if interpreter.is_file():
            return subprocess.run([str(interpreter), "-m", "notebook_workflow.cli", *sys.argv[1:]]).returncode
    print("Local notebook tooling is not installed. Run install.py from the notebook-workflow bundle.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
