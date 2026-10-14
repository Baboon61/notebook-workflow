# Development

Work on the standalone tool in an isolated local environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
node --test vscode/tests/bridge.test.js
```

Python 3.10+ is supported. The development extra includes a TOML parser for Python
3.10; later interpreters use `tomllib`. Node 18+ runs the bridge tests without npm
dependencies. Synthetic Python/R fixtures test conversion, cell matching, output
and metadata preservation, conservative dependency clearing, saved/unsaved
conflicts, recovery, and installation into temporary user directories.
Tests never execute analysis cells or modify a global installation.

## Isolated VS Code pilot

Run the actual extension-host check with an absolute path to this repository's
tooling interpreter:

```bash
.venv/bin/python scripts/test_vscode.py --python /absolute/path/to/notebook-workflow/.venv/bin/python
```

The macOS executable defaults to `/Applications/Visual Studio Code.app/Contents/MacOS/Code`.
Use `--executable /path/to/VS-Code-executable` on another platform. The launcher
uses temporary user-data and extension directories, loads the development
extension, and opens only its synthetic notebooks. GUI/loopback access may require
sandbox approval. No Jupyter server or Python/R analysis kernel is launched.

The pilot checks save, apply/refresh, unchanged independent outputs, transitive
clearing, review, resume/reconnection, abort, refresh retry, exact restore, and
dirty-buffer refusal for both languages. Remote-kernel connections are outside
this pilot's coverage.

## Source layout

| Path | Responsibility |
| --- | --- |
| `src/notebook_workflow/` | Conversion, merging, dependencies, editor client, CLI |
| `skills/notebook-refactor/` | Skill instructions, launcher, UI metadata, recovery reference |
| `agents/` | Optional project-independent Codex agent roles |
| `vscode/` | Local editor bridge and extension-host tests |
| `tests/` | Synthetic Python/R and isolated installation tests |
| `scripts/` | Extension packaging and isolated editor pilot |
| `examples/` | Small output-free Python/R percent scripts with kernel metadata |

The token benchmark, external-notebook pilot, unused inventory helper, copied
interpreter configuration, and generated package metadata are excluded from the
maintained standalone bundle. Conversion dependencies remain unchanged.

## Packaging

Build a Python source archive and CLI wheel, plus the local extension:

```bash
.venv/bin/python -m pip install build
.venv/bin/python -m build
.venv/bin/python scripts/package_vscode.py dist
```

`MANIFEST.in` includes the installer, skill, agents, editor integration,
documentation, tests, and examples in the source archive. The wheel provides the
Python CLI package. The VSIX contains only the extension's maintained runtime
files, README, and MIT license. Local configuration, backups, caches, and the private handoff
are excluded. Building packages does not install or publish them.

GitHub Actions is configured for Python 3.10 and 3.14 on Linux/macOS, a Node bridge
job, and a packaging job. The GUI pilot runs locally. A configured workflow is not
evidence that every platform or remote-kernel setup has been tested.

Review [AGENTS.md](../AGENTS.md) before changing behavior. Keep saved-file hashes,
dirty-editor checks, conservative dependency invalidation, and exact no-op
preservation intact. Obtain explicit approval for each Git command before running
it in an assistant session. The project uses the [MIT license](../LICENSE).
