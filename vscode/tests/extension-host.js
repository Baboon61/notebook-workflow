"use strict";

// Executed by VS Code's actual extension test host, with isolated user data.
// Uses the built-in ipynb serializer; no Jupyter server or analysis kernel.
const vscode = require("vscode");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { promisify } = require("node:util");
const { execFile } = require("node:child_process");
const execute = promisify(execFile);

async function run() {
  const extension = vscode.extensions.getExtension("local-notebook-tools.notebook-workflow");
  assert.ok(extension, "Development extension is discoverable");
  await extension.activate();
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "notebook-vscode-pilot-"));
  const python = process.env.NOTEBOOK_WORKFLOW_TEST_PYTHON || path.join(os.homedir(), ".local/share/notebook-workflow/venv/bin/python");
  const cli = async (...args) => {
    const result = await execute(python, ["-m", "notebook_workflow.cli", ...args], { timeout: 30000 });
    return JSON.parse(result.stdout);
  };
  try {
    for (const language of ["python", "r"]) {
      const filename = path.join(root, `pilot-${language}.ipynb`);
      const initial = language === "python" ? "x = 1" : "x <- 1";
      const latest = language === "python" ? "x = 2" : "x <- 2";
      const edited = language === "python" ? "x = 3" : "x <- 3";
      const original = {
        nbformat: 4, nbformat_minor: 5,
        metadata: { kernelspec: { name: language === "python" ? "python3" : "ir",
          display_name: language, language }, custom: { keep: true } },
        cells: [
          { id: "parameters", cell_type: "code", source: initial, metadata: { tags: ["parameters"] },
            execution_count: 1, outputs: [{ output_type: "stream", name: "stdout", text: "1\n" }] },
          { id: "derived", cell_type: "code", source: language === "python" ? "y = x * 2" : "y <- x * 2",
            metadata: {}, execution_count: 2, outputs: [{ output_type: "stream", name: "stdout", text: "derived" }] },
          { id: "dependent", cell_type: "code", source: "print(y)", metadata: {}, execution_count: 3,
            outputs: [{ output_type: "stream", name: "stdout", text: "result" }] },
          { id: "plot", cell_type: "code", source: "print('independent plot')", metadata: {}, execution_count: 4,
            outputs: [{ output_type: "display_data", data: { "text/plain": "existing plot" }, metadata: {} }] }
        ]
      };
      await fs.writeFile(filename, JSON.stringify(original));
      const document = await vscode.workspace.openNotebookDocument(vscode.Uri.file(filename));
      await vscode.window.showNotebookDocument(document);
      const edit = new vscode.WorkspaceEdit();
      const cellDocument = document.cellAt(0).document;
      edit.replace(cellDocument.uri, new vscode.Range(cellDocument.positionAt(0), cellDocument.positionAt(cellDocument.getText().length)), latest);
      assert.ok(await vscode.workspace.applyEdit(edit));
      assert.ok(document.isDirty, "Notebook has an unsaved editor change");
      const prepared = await cli("prepare", filename, "--editor", "required");
      assert.ok(prepared.editor.saved);
      assert.equal(document.isDirty, false, "prepare saved the unsaved editor buffer");
      const script = await fs.readFile(prepared.script, "utf8");
      assert.ok(script.includes(latest), "Export includes the latest unsaved cell after automatic save");
      await fs.writeFile(prepared.script, script.replace(latest, edited));
      const originalSavedBytes = await fs.readFile(filename);
      const before = JSON.parse(originalSavedBytes);
      const applied = await cli("apply", prepared.session, "--editor", "required");
      assert.deepEqual(applied.changed, [1]);
      assert.deepEqual(applied.dependents_cleared, [2, 3]);
      assert.ok(path.basename(path.dirname(prepared.session)) === "notebook-workflow-sessions");
      assert.ok(applied.editor.refreshed, JSON.stringify(applied.editor));
      const refreshed = vscode.workspace.notebookDocuments.find(nb => nb.uri.fsPath === filename);
      assert.equal(refreshed.cellAt(0).document.getText(), edited, "Open notebook shows applied code");
      assert.equal(refreshed.cellAt(0).outputs.length, 0);
      assert.equal(refreshed.cellAt(1).outputs.length, 0, "Derived variable cell clears in VS Code");
      assert.equal(refreshed.cellAt(2).outputs.length, 0, "Transitive dependent cell clears in VS Code");
      assert.equal(refreshed.cellAt(3).outputs.length, 1, "Independent plot retains its output in VS Code");
      assert.equal(refreshed.isDirty, false);
      const after = JSON.parse(await fs.readFile(filename, "utf8"));
      assert.deepEqual(after.cells[1].source, before.cells[1].source);
      assert.deepEqual(after.cells[2].source, before.cells[2].source);
      assert.deepEqual(after.cells[3], before.cells[3]);
      assert.deepEqual(after.metadata, before.metadata);
      const found = await cli("sessions", filename);
      assert.equal(found.sessions[0].session, prepared.session);
      const reviewed = await cli("review", prepared.session);
      assert.ok((await fs.readFile(reviewed.before_script, "utf8")).includes(latest));
      assert.deepEqual(reviewed.changed, [1]);
      // Retry refresh of an applied result without another notebook mutation.
      const appliedBytes = await fs.readFile(filename);
      assert.ok((await cli("refresh", prepared.session, "--editor", "required")).editor.refreshed);
      assert.deepEqual(await fs.readFile(filename), appliedBytes);
      // Simulate a reload advertising a replacement endpoint. Resume must
      // rebind rather than overwrite the edited script with a new export.
      const interrupted = await cli("prepare", filename, "--editor", "required");
      const connection = JSON.parse(await fs.readFile(path.join(interrupted.session, "editor.json")));
      connection.descriptor = path.join(root, "closed-window.json");
      await fs.writeFile(path.join(interrupted.session, "editor.json"), JSON.stringify(connection));
      const resumed = await cli("resume", interrupted.session, "--editor", "required");
      assert.ok(resumed.editor.connected);
      assert.ok(resumed.can_resume);
      await cli("abort", interrupted.session);
      assert.equal((await cli("status", interrupted.session)).phase, "aborted");
      // Restore the original saved notebook and verify its code/outputs in
      // the still-open editor, without invoking any kernel.
      assert.ok((await cli("restore", prepared.session, "--editor", "required")).editor.refreshed);
      const restoredDocument = vscode.workspace.notebookDocuments.find(nb => nb.uri.fsPath === filename);
      assert.equal(restoredDocument.cellAt(0).document.getText(), latest);
      assert.deepEqual(await fs.readFile(filename), originalSavedBytes);
      // New unsaved editor edits must prevent an otherwise valid apply.
      const next = await cli("prepare", filename, "--editor", "required");
      const dirtyEdit = new vscode.WorkspaceEdit();
      dirtyEdit.insert(restoredDocument.cellAt(0).document.uri, new vscode.Position(0, 0), "# new edit\n");
      await vscode.workspace.applyEdit(dirtyEdit);
      const savedBytes = await fs.readFile(filename);
      await assert.rejects(cli("apply", next.session, "--editor", "required"), error => error.stderr.includes("unsaved"));
      assert.deepEqual(await fs.readFile(filename), savedBytes);
      await vscode.window.showNotebookDocument(restoredDocument);
      await vscode.commands.executeCommand("workbench.action.files.revert");
      await cli("restore", next.session);
      console.log("PASS visible sessions, transitive output clearing, independent plot preservation");
      console.log(`PASS actual VS Code: ${language} save, apply, review, resume/reconnect, abort, refresh retry, restore, unsaved conflict`);
    }
  } finally {
    // Remove only temporary fixtures created by this test; real notebooks are untouched.
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        if (tab.input instanceof vscode.TabInputNotebook && tab.input.uri.fsPath.startsWith(root))
          await vscode.window.tabGroups.close(tab);
      }
    }
    await fs.rm(root, { recursive: true, force: true });
  }
}

module.exports = { run };
