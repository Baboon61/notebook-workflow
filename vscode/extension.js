"use strict";

const vscode = require("vscode");
const path = require("node:path");
const os = require("node:os");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { startBridge } = require("./bridge");
const { createNotebookHandler } = require("./notebooks");
const execute = promisify(execFile);
let bridge;

function python() {
  return vscode.workspace.getConfiguration("notebookWorkflow").get("pythonPath") ||
    path.join(os.homedir(), ".local/share/notebook-workflow/venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
}

async function run(args) {
  try {
    const { stdout } = await execute(python(), ["-m", "notebook_workflow.cli", ...args], {
      timeout: 60000, maxBuffer: 1024 * 1024, windowsHide: true
    });
    return JSON.parse(stdout);
  } catch (error) {
    let message = error.message;
    try { message = JSON.parse(error.stderr).error; } catch (_) {}
    throw new Error(message);
  }
}

async function activate(context) {
  if (!vscode.workspace.isTrusted) return;
  const output = vscode.window.createOutputChannel("Notebook Workflow");
  context.subscriptions.push(output);
  try {
    bridge = await startBridge(createNotebookHandler(vscode));
  } catch (error) {
    output.appendLine(`Local bridge failed: ${error.message}`);
    vscode.window.showErrorMessage(`Notebook Workflow: ${error.message}`);
    return;
  }
  const command = (name, callback) => context.subscriptions.push(vscode.commands.registerCommand(name, async () => {
    try { return await callback(); }
    catch (error) { output.appendLine(error.message); vscode.window.showErrorMessage(`Notebook Workflow: ${error.message}`); }
  }));
  const selectSession = async (phases) => {
    const active = vscode.window.activeNotebookEditor?.notebook;
    const roots = active?.uri.scheme === "file" ? [active.uri.fsPath] :
      (vscode.workspace.workspaceFolders || []).filter(folder => folder.uri.scheme === "file").map(folder => folder.uri.fsPath);
    const found = new Map();
    for (const root of roots) {
      const result = await run(["sessions", root]);
      for (const session of result.sessions) {
        if (phases.includes(session.phase)) found.set(session.session, session);
      }
      for (const error of result.errors) output.appendLine(JSON.stringify(error));
    }
    const choices = [...found.values()].map(session => ({
      label: path.basename(session.notebook), description: session.phase,
      detail: `${session.created_at ? new Date(session.created_at).toLocaleString() + " · " : ""}${session.session}`,
      session: session.session
    }));
    choices.push({ label: "Choose another session folder…", session: null });
    const chosen = await vscode.window.showQuickPick(choices, { placeHolder: "Select a notebook editing session" });
    if (!chosen) return;
    if (chosen.session) return chosen.session;
    return vscode.window.showInputBox({ prompt: "Notebook editing session folder",
      value: context.workspaceState.get("notebookWorkflow.session") || "" });
  };
  const openReview = async session => {
    const result = await run(["review", session]);
    output.appendLine(JSON.stringify(result, null, 2));
    await vscode.commands.executeCommand("vscode.diff", vscode.Uri.file(result.before_script),
      vscode.Uri.file(result.script), "Notebook AI changes");
    return result;
  };
  command("notebookWorkflow.prepare", async () => {
    const document = vscode.window.activeNotebookEditor?.notebook;
    if (!document || document.uri.scheme !== "file" || document.isUntitled)
      throw new Error("Open a locally saved notebook first.");
    const unfinished = (await run(["sessions", document.uri.fsPath])).sessions.filter(session => session.phase === "prepared");
    if (unfinished.length) {
      const choice = await vscode.window.showInformationMessage("This notebook has unfinished AI edits.", "Resume session", "Review edits");
      if (choice === "Resume session") {
        const result = await run(["resume", unfinished[0].session, "--editor", "required"]);
        await context.workspaceState.update("notebookWorkflow.session", result.session);
        output.appendLine(JSON.stringify(result, null, 2));
        output.show(true);
        return result;
      }
      if (choice === "Review edits") return openReview(unfinished[0].session);
      return;
    }
    const result = await run(["prepare", document.uri.fsPath, "--editor", "required"]);
    await context.workspaceState.update("notebookWorkflow.session", result.session);
    output.appendLine(JSON.stringify(result, null, 2));
    output.show(true);
    vscode.window.showInformationMessage("Notebook prepared. Ask your AI assistant to edit the exported script shown in Notebook Workflow output.");
    return result;
  });
  command("notebookWorkflow.apply", async () => {
    const session = await selectSession(["prepared"]);
    if (!session) return;
    const preview = await run(["apply", session, "--dry-run", "--editor", "required"]);
    output.appendLine(JSON.stringify(preview, null, 2));
    const result = await run(["apply", session, "--editor", "required"]);
    output.appendLine(JSON.stringify(result, null, 2));
    output.show(true);
    if (result.editor?.error) throw new Error(result.editor.action);
    vscode.window.showInformationMessage("Notebook changes applied and refreshed. Rerun affected cells in your selected kernel.");
    return result;
  });
  command("notebookWorkflow.review", async () => {
    const session = await selectSession(["prepared", "applied", "restored", "aborted"]);
    if (session) return openReview(session);
  });
  command("notebookWorkflow.resume", async () => {
    const session = await selectSession(["prepared"]);
    if (!session) return;
    const result = await run(["resume", session, "--editor", "required"]);
    await context.workspaceState.update("notebookWorkflow.session", session);
    output.appendLine(JSON.stringify(result, null, 2));
    output.show(true);
    vscode.window.showInformationMessage("Session resumed. Continue AI assistance with its existing script.");
    return result;
  });
  command("notebookWorkflow.restore", async () => {
    const session = await selectSession(["prepared", "applied"]);
    if (!session) return;
    const choice = await vscode.window.showWarningMessage("Restore this session's original notebook? AI edits remain available in its script.", "Restore original");
    if (choice !== "Restore original") return;
    const result = await run(["restore", session, "--editor", "required"]);
    output.appendLine(JSON.stringify(result, null, 2));
    if (result.editor?.error) throw new Error(result.editor.action);
    vscode.window.showInformationMessage("Original notebook restored and refreshed.");
    return result;
  });
  command("notebookWorkflow.abort", async () => {
    const session = await selectSession(["prepared"]);
    if (!session) return;
    const result = await run(["abort", session]);
    output.appendLine(JSON.stringify(result, null, 2));
    vscode.window.showInformationMessage("Session closed. The notebook is unchanged; script and backup are retained.");
    return result;
  });
  command("notebookWorkflow.refresh", async () => {
    const session = await selectSession(["applied", "restored"]);
    if (!session) return;
    const result = await run(["refresh", session, "--editor", "required"]);
    output.appendLine(JSON.stringify(result, null, 2));
    if (result.editor?.error) throw new Error(result.editor.action);
    vscode.window.showInformationMessage("Notebook refreshed from the saved result.");
    return result;
  });
  command("notebookWorkflow.status", () => {
    vscode.window.showInformationMessage("Notebook Workflow local bridge is running. AI preparation saves open notebooks and apply refreshes them.");
  });
}

async function deactivate() {
  if (bridge) await bridge.dispose();
}

module.exports = { activate, deactivate };
