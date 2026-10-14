"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

function registryDirectory() {
  const user = process.getuid ? String(process.getuid()) : (process.env.USERNAME || "user");
  return path.join(os.tmpdir(), `notebook-workflow-bridges-${user}`);
}

async function startBridge(handler, registry = registryDirectory()) {
  const token = crypto.randomBytes(32).toString("hex");
  let queue = Promise.resolve();
  const server = http.createServer(async (request, response) => {
    const send = (code, value) => {
      response.writeHead(code, { "Content-Type": "application/json" });
      response.end(JSON.stringify(value));
    };
    if (request.method !== "POST" || request.url !== "/workflow" ||
        request.headers.authorization !== `Bearer ${token}` || request.headers.origin) {
      send(403, { error: "Unauthorized local bridge request." });
      request.resume();
      return;
    }
    try {
      const chunks = [];
      let length = 0;
      for await (const chunk of request) {
        length += chunk.length;
        if (length > 16384) throw new Error("Bridge request is too large.");
        chunks.push(chunk);
      }
      const message = JSON.parse(Buffer.concat(chunks).toString());
      if (!["inspect", "save", "check", "refresh"].includes(message.operation) ||
          typeof message.notebook !== "string" || !path.isAbsolute(message.notebook) ||
          path.extname(message.notebook) !== ".ipynb") throw new Error("Invalid notebook bridge operation.");
      // Serialize editor operations from independent CLI processes.
      const operation = queue.then(() => handler(message));
      queue = operation.catch(() => {});
      send(200, await operation);
    } catch (error) {
      send(200, { error: error.message });
    }
  });
  server.requestTimeout = 25000;
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  await fs.mkdir(registry, { recursive: true, mode: 0o700 });
  const descriptor = path.join(registry, `${process.pid}-${crypto.randomUUID()}.json`);
  await fs.writeFile(descriptor, JSON.stringify({ port: server.address().port, token }), { mode: 0o600 });
  return {
    descriptor,
    async dispose() {
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
      await fs.rm(descriptor, { force: true });
    }
  };
}

module.exports = { startBridge, registryDirectory };
