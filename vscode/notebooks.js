"use strict";

const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const path = require("node:path");

function createNotebookHandler(vscode) {
  const canonical = filename => {
    try { return fsSync.realpathSync.native(filename); }
    catch (_) { return path.resolve(filename); }
  };
  const find = filename => vscode.workspace.notebookDocuments.find(document =>
    !document.isClosed && document.uri.scheme === "file" &&
    canonical(document.uri.fsPath) === canonical(filename));
  const assertClean = document => {
    if (document.isDirty) throw new Error("The open notebook has unsaved edits. No notebook changes applied; reconcile the editor before continuing.");
  };
  const source = cell => Array.isArray(cell.source) ? cell.source.join("") : cell.source;
  const matches = (document, saved, cleared = []) => {
    const cells = document.getCells();
    return cells.length === saved.cells.length && cells.every((cell, index) => {
      const before = saved.cells[index];
      const kind = before.cell_type === "markdown" ? vscode.NotebookCellKind.Markup : vscode.NotebookCellKind.Code;
      // Raw cells have serializer-specific representation; only compare text.
      return cell.document.getText() === source(before) &&
        (before.cell_type === "raw" || cell.kind === kind) &&
        (before.cell_type !== "code" || (cell.outputs.length === (before.outputs || []).length &&
          (cell.executionSummary?.executionOrder ?? null) === (before.execution_count ?? null))) &&
        (!cleared.includes(index + 1) || (cell.outputs.length === 0 &&
          cell.executionSummary?.executionOrder === undefined));
    });
  };
  return async message => {
    let document = find(message.notebook);
    if (!document) return { handled: false };
    if (document.isUntitled) throw new Error("Save the notebook to a local file before assistance.");
    if (message.operation === "inspect") return { handled: true, dirty: document.isDirty };
    if (message.operation === "save") {
      if (document.isDirty && !await document.save()) throw new Error("VS Code could not save the notebook.");
      assertClean(document);
      return { handled: true, saved: true };
    }
    assertClean(document);
    if (message.operation === "check") return { handled: true, clean: true };
    const saved = JSON.parse(await fs.readFile(message.notebook, "utf8"));
    if (!matches(document, saved, message.outputs_cleared)) {
      // Revert targets the active editor. Show precisely the requested notebook
      // before invoking it, and never discard an unsaved buffer.
      await vscode.window.showNotebookDocument(document, { preview: false });
      document = find(message.notebook);
      if (!document) throw new Error("Notebook closed before refresh.");
      assertClean(document);
      if (vscode.window.activeNotebookEditor?.notebook !== document)
        throw new Error("The target notebook is not active; refresh refused.");
      await vscode.commands.executeCommand("workbench.action.files.revert");
      // The command completes before extension-host notebook change events are
      // necessarily delivered. Wait for the target model, without saving it.
      for (let attempt = 0; attempt < 60; attempt++) {
        document = find(message.notebook);
        if (document && matches(document, saved, message.outputs_cleared)) break;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      document = find(message.notebook);
      if (!document) throw new Error("Notebook closed during refresh.");
    }
    if (!matches(document, saved, message.outputs_cleared))
      throw new Error("VS Code has not loaded the applied cells. Reopen the notebook without saving a stale buffer.");
    assertClean(document);
    return { handled: true, refreshed: true };
  };
}

module.exports = { createNotebookHandler };
