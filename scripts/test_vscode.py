#!/usr/bin/env python3
"""Run notebook bridge tests in a real VS Code extension host with temporary profiles."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile


BUNDLE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path,
        default=Path("/Applications/Visual Studio Code.app/Contents/MacOS/Code"))
    parser.add_argument("--python", type=Path,
        default=Path.home() / ".local/share/notebook-workflow/venv/bin/python")
    args = parser.parse_args()
    environment = dict(os.environ)
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    environment.pop("VSCODE_IPC_HOOK_CLI", None)
    environment["NOTEBOOK_WORKFLOW_TEST_PYTHON"] = str(args.python)
    with tempfile.TemporaryDirectory(prefix="workflow-vscode-host-") as folder:
        root = Path(folder)
        result = subprocess.run([str(args.executable),
            "--user-data-dir", str(root / "profile"), "--extensions-dir", str(root / "extensions"),
            "--extensionDevelopmentPath", str(BUNDLE / "vscode"),
            "--extensionTestsPath", str(BUNDLE / "vscode/tests/extension-host.js"),
            "--disable-workspace-trust", "--disable-extensions", "--skip-welcome", "--skip-release-notes"],
            env=environment, text=True, capture_output=True, timeout=60)
        output = result.stdout + result.stderr
        if result.returncode:
            print(output[-6000:])
        else:
            print("\n".join(line for line in output.splitlines() if line.startswith("PASS actual VS Code:")))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
