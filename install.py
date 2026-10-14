#!/usr/bin/env python3
"""Install one canonical workflow for all projects, without touching Codex config.

Uses symlinks for maintained instructions and an isolated local Python tooling
environment. Conflicting destinations are refused rather than overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import runpy


BUNDLE = Path(__file__).resolve().parent


def installation_plan(user_home: Path, codex_home: Path) -> tuple[list[tuple[Path, Path]], Path]:
    links = [
        (user_home / ".agents/skills/notebook-refactor", BUNDLE / "skills/notebook-refactor"),
        (codex_home / "skills/notebook-refactor", BUNDLE / "skills/notebook-refactor"),
    ]
    links.extend((codex_home / "agents" / source.name, source) for source in sorted((BUNDLE / "agents").glob("*.toml")))
    return links, user_home / ".local/share/notebook-workflow/venv"


def install(user_home: Path, codex_home: Path, *, skip_environment: bool = False) -> dict:
    links, environment = installation_plan(user_home, codex_home)
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    launcher = BUNDLE / "skills/notebook-refactor/tooling.json"
    for target, source in links:
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != source.resolve():
                raise ValueError(f"Installation destination already belongs to something else: {target}")
    if not skip_environment:
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        subprocess.run([str(interpreter), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(BUNDLE)], check=True)
        subprocess.run([str(interpreter), "-c", "import notebook_workflow, jupytext"], check=True)
    for target, source in links:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_symlink():
            target.symlink_to(source, target_is_directory=source.is_dir())
    if not skip_environment:
        launcher.write_text(json.dumps({"python": str(interpreter)}, indent=2) + "\n")
    return {"bundle": str(BUNDLE), "links": [str(target) for target, _ in links],
            "python": str(interpreter) if not skip_environment else None,
            "environment_installed": not skip_environment}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-home", type=Path, default=Path.home())
    parser.add_argument("--codex-home", type=Path, default=None)
    parser.add_argument("--skip-environment", action="store_true", help="link-only installation for tests or existing tooling")
    parser.add_argument("--vscode-only", action="store_true", help="package and install the VS Code integration only")
    args = parser.parse_args(argv)
    codex_home = args.codex_home or Path(os.environ.get("CODEX_HOME", str(args.user_home / ".codex")))
    try:
        if args.vscode_only:
            code = shutil.which("code")
            if not code:
                raise ValueError("The VS Code 'code' CLI is not installed on PATH.")
            package = runpy.run_path(str(BUNDLE / "scripts/package_vscode.py"))["package"]
            with tempfile.TemporaryDirectory(prefix="notebook-workflow-vsix-") as directory:
                vsix = package(Path(directory))
                subprocess.run([code, "--install-extension", str(vsix)], check=True)
            print(json.dumps({"vscode_extension": "local-notebook-tools.notebook-workflow", "installed": True}))
            return 0
        result = install(args.user_home.resolve(), codex_home.resolve(), skip_environment=args.skip_environment)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
