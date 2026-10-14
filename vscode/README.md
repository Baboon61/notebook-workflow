# Notebook Workflow for VS Code

Save and refresh local Python/R notebooks around AI assistance through the
portable `notebook-workflow` tooling. Works with local files and an existing
remote Jupyter kernel. The extension executes no notebook cells.

Install the portable Python tool first, then install this extension from its
local VSIX. The bundle's `install.py --vscode-only` packages and installs it using
the `code` CLI. Reload your normal VS Code window after installation.

Open a local notebook and ask for assistance using `$notebook-refactor`. The
CLI's default editor mode discovers this extension automatically:

- **Prepare** saves any unsaved notebook edits before exporting the script.
- **Apply** refuses new unsaved edits, then verifies the refreshed notebook
  contents after cell changes have been written.
- If the file watcher has not refreshed the notebook, the extension focuses
  the target clean notebook and reloads it from disk. It never reloads a dirty
  notebook or runs a cell.

The command palette also offers **Notebook Workflow: Prepare Active Notebook
for AI**, **Apply AI Script Changes**, and **Show Local Bridge Status**. These
are optional; the skill invokes the CLI automatically for normal assistance.

Session folders are visible in `notebook-workflow-sessions/` beside each
notebook. Apply clears direct/transitive dependent outputs as well as changed
cells, preserving independent outputs. Static-analysis uncertainty triggers a
conservative clearing of later code cells; the summary lists these separately.

Recovery commands discover sessions for the active notebook or local workspace:

- **Review AI Script Changes** opens a before/after script diff without outputs.
- **Resume Unfinished Session** keeps the edited script and reconnects to the
  notebook after a reload, requiring a unique clean editor.
- **Close Unfinished Session** ends an abandoned session without changing the
  notebook or deleting its script and backup.
- **Restore Original Notebook** restores and refreshes the backup, refusing
  newer saved or unsaved notebook changes.
- **Retry Notebook Refresh** refreshes an applied/restored result without another
  notebook write.

Preparing a notebook with unfinished changes offers resume or review instead
of replacing its script. Custom session folders can be entered when selecting
a session. Notebook cells are never executed by recovery commands.

The standard local tooling interpreter is discovered under
`~/.local/share/notebook-workflow/venv`. Use the machine-level
`notebookWorkflow.pythonPath` setting if your installation is elsewhere.
The extension runs in the local UI host and requires a trusted workspace.
It supports notebooks stored locally; Remote SSH files and web VS Code are
outside this implementation.

The control bridge listens only on loopback, requires a per-window token, and
handles only save/check/refresh requests for already open local notebooks.
It transmits no outputs or notebook source to the assistant. Pause notebook
editing and cell execution during AI work; it does not merge concurrent edits.

Tested in an actual isolated VS Code extension host using Python and R fixtures:
unsaved-save/export, apply/refresh, unaffected output preservation, and unsaved
conflict refusal. Remote-kernel reconnection is not covered by that test.
Tests also verify visible session discovery and transitive output clearing while
an independent plot stays visible. Recovery tests cover review, reconnection, abort, refresh
retry, and exact backup restoration in the still-open notebook view.

VS Code APIs: [NotebookDocument and editor commands](https://code.visualstudio.com/api/references/vscode-api).
