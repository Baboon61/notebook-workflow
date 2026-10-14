# Installation

Install the repository once in a stable local directory to use it across Python
and R projects. Python 3.10+ runs conversion; Jupytext and nbformat are its runtime
dependencies. The installer keeps these tools separate from analysis environments.
An R runtime is needed only if you choose to execute R cells.

## Skill and optional agents

From the repository root:

```bash
python3 install.py
```

The installer creates:

| Destination | Purpose |
| --- | --- |
| `~/.local/share/notebook-workflow/venv` | Isolated editable Python installation |
| `~/.agents/skills/notebook-refactor` | Skill discovery link |
| `~/.codex/skills/notebook-refactor` | Compatibility skill discovery link |
| `~/.codex/agents/*.toml` | Four optional agent definitions |
| `skills/notebook-refactor/tooling.json` | Local interpreter path generated in this bundle |

`CODEX_HOME` overrides the Codex destination. `--user-home` and `--codex-home`
allow explicit destinations. Existing matching links are reused; unrelated files
or links to a different source are refused before environment installation.
The installer does not edit `config.toml` or global `AGENTS.md`. Delegation and
model settings remain client/user choices; the skill works without custom agents.

Restart the assistant if discovery has not refreshed. Invoke the skill from any
project with a saved Python/R notebook:

```text
Use $notebook-refactor to update path/to/analysis.ipynb: <your request>
```

The launcher is located beside the loaded skill, so it does not require this
repository to be part of the analysis project. Retain the source directory: both
discovery links and the editable package point to it. Run the installer again
after updating the contents in place.

## VS Code bridge

Install the Python tool first, make the `code` command available on PATH, then run:

```bash
python3 install.py --vscode-only
```

Reload VS Code and open a saved local notebook in a trusted workspace. The bridge
saves before export and verifies refresh after apply. Your existing local or
remote kernel remains responsible for executing cells.

For a custom tooling destination, set the machine-level `notebookWorkflow.pythonPath`
to that environment's Python executable. The bridge uses only the local UI host;
Remote SSH notebook files and web VS Code are outside current support.

## CLI-only use

A package installation provides the CLI; the full repository or source archive
provides the installer, skill, agents, and VS Code bundle. A wheel contains the
Python CLI package only. To use the CLI without global discovery links:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/notebook-workflow prepare path/to/analysis.ipynb --editor off
.venv/bin/notebook-workflow apply <returned-session> --dry-run
.venv/bin/notebook-workflow apply <returned-session>
```

Save the notebook before preparation, edit the returned `.py`/`.R` script, then
reopen the notebook after application. Apply a no-op as well to close its session.
Use editor mode `off` only for a deliberately manual workflow; connected sessions
must retain their dirty-buffer and connection checks.

Ignore `notebook-workflow-sessions/` in each analysis project. Those folders
contain full recovery backups and remain after apply. The tool leaves existing
permanent pairs alone and never executes notebook cells.

## Move an existing installation

Rerunning the installer from a different directory does not migrate old links.
Prepare and test the new copy while retaining the old source and installation.
Then migrate deliberately:

1. Resolve the two skill links and four agent links listed above, accounting for
   a custom `CODEX_HOME`. Confirm each is a symlink to the corresponding file or
   directory in the known old bundle. Preserve any unrelated destination.
2. Remove only those confirmed old workflow symlinks. Retain the old bundle and
   any user-owned files. This enables the installer's normal conflict preflight;
   there is no force-overwrite mode.
3. Run `python3 install.py` from the new repository. It recreates discovery links,
   updates the isolated editable installation, and generates the new launcher
   configuration. Use the same custom destinations if applicable.
4. Check all discovery targets and the imported package path:

   ```bash
   ~/.local/share/notebook-workflow/venv/bin/python -c "import notebook_workflow; print(notebook_workflow.__file__)"
   ```

5. Reinstall the VS Code extension if its contents changed, reload VS Code, and
   restart the assistant. Test a synthetic notebook before retiring the old copy.

If installation fails, keep both sources for recovery and restore only the
confirmed workflow-owned links to the old bundle. Global writes require whatever
authorization your environment applies; preparing a repository does not perform
this migration.

## Platform scope

The actual editor integration is validated on macOS. Linux/macOS Python CI is
configured separately from the GUI pilot. On Windows the tooling interpreter is
`venv\Scripts\python.exe`; creating symlinks may require Developer Mode or elevated
permissions and has not yet been validated. All supported conversions require
notebook format 4 and Python or R kernel metadata.
