"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { startBridge } = require("../bridge");
const { createNotebookHandler } = require("../notebooks");

test("bridge authenticates, restricts operations and removes its descriptor", async () => {
  const registry = await fs.mkdtemp(path.join(os.tmpdir(), "workflow-bridge-test-"));
  const seen = [];
  const bridge = await startBridge(async request => { seen.push(request); return { handled: true }; }, registry);
  try {
    const settings = JSON.parse(await fs.readFile(bridge.descriptor));
    assert.equal((await fs.stat(bridge.descriptor)).mode & 0o777, 0o600);
    const send = (body, token = settings.token, extra = {}) => fetch(`http://127.0.0.1:${settings.port}/workflow`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, ...extra }, body: JSON.stringify(body)
    });
    const request = { operation: "save", notebook: "/tmp/analysis.ipynb" };
    assert.equal((await send(request, "wrong")).status, 403);
    assert.equal((await send(request, settings.token, { Origin: "https://example.com" })).status, 403);
    assert.ok((await (await send({ ...request, operation: "execute" })).json()).error);
    assert.deepEqual(await (await send(request)).json(), { handled: true });
    assert.deepEqual(seen, [request]);
  } finally {
    await bridge.dispose();
    await assert.rejects(fs.stat(bridge.descriptor));
    await fs.rm(registry, { recursive: true });
  }
});

function editorMock(filename, text) {
  const cell = { kind: 2, document: { getText: () => text }, outputs: [], executionSummary: {} };
  const document = { uri: { scheme: "file", fsPath: filename }, isClosed: false, isUntitled: false,
    isDirty: false, getCells: () => [cell], async save() { this.isDirty = false; return true; } };
  const calls = [];
  const vscode = {
    NotebookCellKind: { Code: 2, Markup: 1 },
    workspace: { notebookDocuments: [document] },
    window: { activeNotebookEditor: { notebook: document },
      async showNotebookDocument() { calls.push("show"); } },
    commands: { async executeCommand(command) { calls.push(command); } }
  };
  return { vscode, document, cell, calls };
}

test("save handles dirty and clean documents, check refuses new edits", async () => {
  const mock = editorMock("/tmp/analysis.ipynb", "x = 1");
  const handler = createNotebookHandler(mock.vscode);
  mock.document.isDirty = true;
  assert.deepEqual(await handler({ operation: "save", notebook: "/tmp/analysis.ipynb" }), { handled: true, saved: true });
  assert.equal(mock.document.isDirty, false);
  assert.deepEqual(await handler({ operation: "save", notebook: "/tmp/analysis.ipynb" }), { handled: true, saved: true });
  mock.document.isDirty = true;
  await assert.rejects(handler({ operation: "check", notebook: "/tmp/analysis.ipynb" }), /unsaved/);
  assert.deepEqual(await handler({ operation: "inspect", notebook: "/tmp/other.ipynb" }), { handled: false });
});

test("refresh targets only the intended clean notebook and verifies contents", async () => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), "workflow-refresh-test-"));
  const filename = path.join(folder, "test.ipynb");
  await fs.writeFile(filename, JSON.stringify({ cells: [{ cell_type: "code", source: "x = 2" }] }));
  const mock = editorMock(filename, "x = 1");
  const handler = createNotebookHandler(mock.vscode);
  mock.vscode.commands.executeCommand = async command => {
    mock.calls.push(command);
    mock.cell.document.getText = () => "x = 2";
  };
  try {
    assert.deepEqual(await handler({ operation: "refresh", notebook: filename, outputs_cleared: [1] }),
      { handled: true, refreshed: true });
    assert.deepEqual(mock.calls, ["show", "workbench.action.files.revert"]);
    mock.calls.length = 0;
    await handler({ operation: "refresh", notebook: filename, outputs_cleared: [1] });
    assert.deepEqual(mock.calls, []); // External file watching already refreshed it.
    mock.document.isDirty = true;
    await assert.rejects(handler({ operation: "refresh", notebook: filename }), /unsaved/);
    assert.deepEqual(mock.calls, []);
  } finally { await fs.rm(folder, { recursive: true }); }
});
