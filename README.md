# Notebook workflow

A project-independent local tool and Codex skill for AI assistance with Python
and R Jupyter notebooks. Use the same installation across your projects without
installing analysis libraries or changing their environments. MIT licensed.

Keep working in VS Code's notebook editor and executing cells with your existing
kernel. When notebook assistance starts, the skill exports the saved notebook
to an output-free Jupytext percent script. The AI edits that script, then the
tool applies cell changes to the existing notebook. Changed code cells lose
their outputs and execution counts. Direct and transitive dependent cells also
lose their outputs; unrelated cells retain their state.

Sessions are visible beside each notebook:

```text
notebooks/
  analysis.ipynb
  notebook-workflow-sessions/
    analysis-<session-id>/
      analysis.py       # or analysis.R: AI representation
      original.ipynb    # recovery backup: excluded from AI context
      baseline.json
      session.json
```

## Dependent outputs

Changing a definition of `value` invalidates a later `value2 = value * 10` cell
and cells that display/use `value2`. Independent plots retain their outputs.
A label-only edit does not invalidate consumers of an unchanged definition.
Python uses AST analysis; R uses conservative lexical analysis for ordinary
assignments and expressions. Dynamic code and unsupported constructs trigger
the default fallback: clear all code cells from the earliest affected position.
The dry-run reports dependent cells, fallback cells, and uncertainty.

This is source analysis rather than a reconstruction of live kernel state.
It does not execute cells or guarantee discovery of every hidden dependency.
R functions, control flow, nonstandard evaluation, and Python constructs with
indirect state effects may use the fallback. The detailed
[dependency policy](skills/notebook-refactor/references/workflow.md#dependency-invalidation)
describes the available controls.

## Install for all projects

Download or clone the repository into a stable local directory. From its root,
with Python 3.10 or later:

```bash
python3 install.py
python3 install.py --vscode-only
```

The installer creates a separate local tooling environment and links the skill
and four optional agents into global discovery locations. The second command
installs the VS Code extension using the `code` CLI; reload your VS Code window
to activate it. Restart Codex if the skill does not appear.

The CLI can also be used with manual save/reopen, without VS Code. Installation
paths, CLI-only use, platform scope, and migration from an older copy are covered
in [installation](docs/installation.md). Existing destinations pointing to another
copy are refused, so relocation requires the documented migration steps.

Open your local notebook in VS Code and ask:

```text
Use $notebook-refactor to update notebooks/analysis.ipynb: <your request>
```

The skill can also be selected automatically for notebook editing requests.
It runs preparation and application during normal assistance. The VS Code
extension saves the open notebook before export and refreshes it after apply,
refusing to discard new unsaved edits. Without the extension, save/reopen remain
manual. An interrupted task retains its session for recovery.

## Review and resume

The command palette finds sessions for the active notebook or workspace:

- **Review AI Script Changes** opens a diff of output-free before/after scripts.
- **Resume Unfinished Session** validates the existing script and reconnects after
  a VS Code reload without exporting over AI edits.
- **Close Unfinished Session** retains its script and backup and leaves the
  current notebook unchanged, allowing a fresh session.
- **Restore Original Notebook** restores the exact backup and refreshes its view
  only if no newer saved or unsaved changes would be lost.
- **Retry Notebook Refresh** reloads an already applied/restored result without
  applying edits a second time.

The CLI provides equivalent `sessions`, `review`, `resume`, `abort`, and `refresh`
operations alongside `restore`. No automatic backup deletion is performed.

## Development and tests

Create a separate environment in this repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
node --test vscode/tests/bridge.test.js
```

Tests cover Python/R conversion, unchanged output/metadata preservation,
selective output clearing, cell insertion/deletion/reordering, notebook magics,
cell identity, conflicts, backup restoration, CLI behavior, and global discovery
installation in temporary directories. No analysis code is executed.

See [development](docs/development.md) for the isolated editor pilot, Python/R
examples, packaging, and CI. On Windows use `.venv\Scripts\python.exe` in place
of `.venv/bin/python`; global symlink installation needs platform validation.

The [skill](skills/notebook-refactor/SKILL.md), [agent definitions](agents),
and [usage and recovery documentation](skills/notebook-refactor/references/workflow.md)
are maintained here. Global discovery links point to these maintained sources.

## Try a small example

The [Python example](examples/python.py) and [R example](examples/r.R) are percent
scripts with kernel metadata and no project dependencies. With Jupytext installed:

```bash
.venv/bin/jupytext --to notebook examples/python.py
.venv/bin/jupytext --to notebook examples/r.R
```

Open either generated notebook in VS Code. Select a suitable kernel if you want
to run its cells, then ask `$notebook-refactor` to change `value` from 1 to 2.
Inspect the preview: the parameter, derived value, and display are affected;
the final independent cell retains its state. Conversion itself needs no R runtime.

## Limits

- Supports Python and R kernels in notebook format 4. Other kernels stop before
  conversion. Percent scripts may encode magics and are not always executable
  outside Jupyter.
- AI workers only see scripts. The local converter necessarily reads notebook
  JSON to preserve outputs and metadata; session backups are never AI context.
- Cell-level merging still saves the complete JSON file atomically. No-op apply
  leaves the notebook's original bytes untouched.
- Pause notebook edits and execution while AI works. Saved-file hashes detect
  conflicts; the connected VS Code bridge also rejects new unsaved buffer edits.
- Applying code does not update live remote-kernel variables. Rerun cells and
  dependencies yourself. Unchanged downstream outputs may be stale.
- VS Code save/refresh passed an isolated extension-host pilot for Python and R.
  Existing remote-kernel connections were not exercised by that pilot.
- Visible sessions remain for recovery and contain backup outputs. Ignore them and
  retire them manually when no longer needed.
- macOS is the validated editor platform. CI is configured for Python tests on
  Linux and macOS; Windows, Remote SSH files, and web VS Code need separate validation.
- Output-free scripts reduce stored-output overhead, but savings depend on the
  notebook and client. Markdown and inline image data URLs remain in the script;
  no universal token reduction is promised.
