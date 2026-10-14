# Local notebook assistance

The installed skill is project independent. It requires Python 3.10+ and a local
tooling environment containing Jupytext and nbformat. It does not install into
the remote Python/R analysis environment, import project packages, or execute
analysis cells. An R kernel is not needed to export or apply an R notebook.

## Installation and discovery

Run the portable bundle's `install.py`. It creates an isolated environment under
`~/.local/share/notebook-workflow/venv`, installs the tool, and links the maintained
skill into `~/.agents/skills/notebook-refactor` and `~/.codex/skills/notebook-refactor`
(compatibility with older clients). It links agents under `~/.codex/agents`.
The installer respects `CODEX_HOME` for the Codex destination and refuses to
overwrite unrelated files. It does not edit global AGENTS.md or config.toml.

Run `install.py --vscode-only` to package and install the local VS Code extension,
then reload VS Code. It provides automatic save and verified refresh. It runs in
the local UI host with locally stored notebooks and requires a trusted workspace.

Keep the bundle in a stable location: links and the editable tooling installation
point to it. The installer refuses links to a different copy; relocation requires
checking and removing only links owned by the old workflow before reinstalling
from the new copy. See `docs/installation.md` in the bundle for the migration
procedure. Restart Codex if discovery has not refreshed. Clients may list both
compatibility locations; they point to the same source. Disable one discovery
entry if your client displays duplicates.

Current official documentation: [skill discovery](https://learn.chatgpt.com/docs/build-skills)
and [personal custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
Standalone agents use `developer_instructions`, not the older `instructions`
field. Custom-agent availability depends on the client; the skill works without
delegation and does not change agent enablement or model settings.

## Commands

Use the launcher beside this reference's parent SKILL.md:

```text
python <skill>/scripts/workflow.py prepare path/to/analysis.ipynb
python <skill>/scripts/workflow.py sessions path/to/analysis.ipynb
python <skill>/scripts/workflow.py sessions path/to/project
python <skill>/scripts/workflow.py resume <returned-session>
python <skill>/scripts/workflow.py review <returned-session>
python <skill>/scripts/workflow.py status <returned-session>
python <skill>/scripts/workflow.py apply <returned-session> --dry-run
python <skill>/scripts/workflow.py apply <returned-session>
python <skill>/scripts/workflow.py restore <returned-session>
python <skill>/scripts/workflow.py refresh <returned-session>
python <skill>/scripts/workflow.py abort <returned-session>
```

Preparation exports the latest saved notebook into a unique session folder under
the visible `notebook-workflow-sessions/` side folder beside the notebook.
`--session-root <directory>` can choose another local location. Add
`notebook-workflow-sessions/` to project ignore rules
if using the default. Sessions include large backup outputs and should not be
loaded into AI context or committed. They remain available for recovery; there
is no automatic cleanup policy. Old hidden `.notebook-workflow/` sessions
remain discoverable and recoverable; new sessions use the visible location.

Existing paired files are left untouched. The notebook stays the source of truth;
temporary exported scripts are only for the active assistance task. After apply,
normal Jupytext editor integration may regenerate an existing permanent pair;
this tool does not synchronize that separate file. Avoid another synchronization
process writing this notebook during an assistance session.

## Cell matching and output behavior

Each exported boundary carries a temporary `workflow_id` label, including cells
whose original notebook lacks IDs. Existing notebook IDs are preserved; temporary
labels never enter the notebook. Keep labels with their existing cells. New
blocks use an unlabeled `# %%`, `# %% [markdown]`, or `# %% [raw]` boundary.

Jupytext provides conversion, and the tool merges changed cells against an exact
backup. It preserves unrelated cell dictionaries and notebook-level metadata.
Code changes clear that cell's outputs, execution count, and execution timing
metadata. Dependent/uncertain code cells also lose outputs, counts, and timing,
while preserving their source and other metadata. Changed Markdown retains
attachments. Reordering code conservatively invalidates cells whose relative
order changes and their dependents. Deletions remove the full cell. Addition uses fresh notebook IDs
when the notebook format requires them.

Notebook format 4 is supported. Jupytext's trailing-newline normalization is
compared against the exported baseline, so no-op conversion preserves original
bytes. Literal percent-marker comments inside code cells are escaped as
`# notebook-workflow-literal <JSON string>` and restored by the tool. Unusual
content that otherwise fails the initial round-trip check is refused before
preparation. Existing malformed notebook structure is not repaired automatically.

Only affected cells are merged semantically. Saving a changed notebook still
rewrites the JSON file atomically; it is not a byte patch or an in-memory kernel
update. The tool checks the notebook hash before apply and again before writing.
The user must pause editing/execution; concurrent editing is not merged. Sessions
should use one consistent session root for each notebook.

## Dependency invalidation

Preparation records a policy, used by review, dry-run and apply:

- `conservative` (default): clear identifiable direct/transitive dependencies;
  when analysis is uncertain, also clear all code cells from the earliest
  affected position. Warnings explain the uncertainty.
- `identified`: clear identified dependencies and report uncertainty, without
  the broader fallback. Use only when deliberately accepting its limitations.
- `changed-only`: explicitly disable dependency clearing.

Select with `prepare ... --dependency-policy <policy>`. A resumed session keeps
its policy. Legacy sessions without the field use the conservative default.

Analysis reads original and edited sources locally; it does not execute code,
import analysis packages, inspect kernel memory or return outputs to the AI.
The graph tracks definitions/reads and propagates changes through derived
variables. Independent constant reassignment stops the chain. Original edges
also invalidate consumers when definitions are deleted. Ordinary Python
function globals are resolved at callers; mutation and simple object aliases
are handled conservatively. Forward references and changed cell order may
invalidate earlier outputs as well.

Python uses its standard AST. R identifies ordinary straight-line assignments
and expression reads lexically; it does not require a local R runtime.
Unsupported scope/control flow, R functions/nonstandard evaluation, notebook
magics, and dynamic evaluation trigger uncertainty. External files, opaque
library state, runtime aliases and arbitrary execution order cannot be fully
reconstructed from source. This is conservative invalidation, not a guarantee
that all live-kernel dependencies were discovered.

The compact summary uses `changed` for code/narrative edits,
`dependents_cleared` for unedited cells losing outputs, `outputs_cleared`
for the full set, and `dependency_fallback` / `dependency_warnings` for
conservative handling. Cell numbers refer to the resulting notebook;
deletions and warnings tagged `original_cell` refer to original positions.
Comment-only edits clear their own code cell but do not propagate through a
parseable unchanged computation. A label-only output edit similarly preserves
consumers of unchanged variable definitions.

## VS Code and a remote kernel

1. Open the notebook in VS Code before asking for assistance. With the extension
   connected, prepare saves unsaved notebook edits automatically; otherwise save manually.
2. Pause edits and cell execution in that notebook while the assistant works.
3. Let the assistant prepare, edit the script, preview, and apply.
4. The connected extension verifies the refreshed cell contents. Inspect the
   apply summary's `editor` field: errors mean the notebook file was applied but
   refresh needs recovery. Reopen without saving a stale buffer over the update.
5. Rerun changed cells, and downstream cells as required, with the remote kernel.

Applying saved code does not execute it, update live kernel variables, or reset
the remote kernel. Preserved downstream outputs may reflect previous state.
Automatic save and refresh passed a real isolated VS Code extension-host pilot
using Python/R fixtures, including unsaved-save and dirty-conflict refusal.
Remote-kernel connections were not exercised. No extension is required for CLI
use: `--editor auto` is the default, `required` fails if no editor owns the open
notebook, and `off` explicitly disables integration for CLI-only use. Do not use
`off` to bypass a dirty or disconnected editor error on a connected session.

The extension advertises a per-window loopback endpoint in a user-private temp
directory. The CLI discovers open local notebooks and sends save/check/refresh
control messages with a per-window token. Multiple windows owning the same
notebook are refused. No notebook outputs or source are sent to the CLI bridge.
Use one session owner and pause notebook edits/execution; this does not implement
concurrent-edit merging. Restoring a backup checks the connected editor for
unsaved changes and refreshes its restored view. A refresh error after successful apply is reported
separately so the assistant does not retry an already applied session.

## Recovery and interruptions

- `sessions <notebook-or-project>` reads session manifests only, returning paths,
  phases, language and timestamps without notebook outputs. Use `--session-root`
  when discovering a custom location. Malformed manifests are reported separately.
- `resume` validates the saved notebook, original backup, cell mapping and edited
  script. It retains all artifacts. After a VS Code reload, it reconnects only
  to a unique clean editor. A changed notebook or dirty editor prevents resume.
- `review` writes an output-free baseline `.py`/`.R` for comparison with the
  edited script; it does not alter the notebook and can review a conflicted
  session. The extension opens these two scripts in a diff editor.
- `abort` closes a prepared session and retains the script and backup. It never
  modifies the notebook, even if that notebook has newer changes. Use it to
  abandon an obsolete session before preparing the current notebook again.
- `refresh` verifies the notebook matches an applied/restored session, then
  retries editor refresh. It writes no notebook data and refuses newer changes.
- `status` identifies the session phase and whether the notebook differs from
  the prepared version. A prepared session can still be edited and applied.
- After an interrupted or failed task, keep its script. `restore` closes a
  prepared session when the notebook still matches its original backup.
- After apply, `restore` restores the exact original bytes only if the notebook
  still matches the applied hash; it refuses to discard later edits.
- For a concurrent-edit conflict, preserve both current notebook and script.
  Reconcile deliberately, then prepare again. There is no force-overwrite flag.
- Backups and scripts remain after apply/restore. Delete retired session folders
  manually only when recovery is no longer needed.
