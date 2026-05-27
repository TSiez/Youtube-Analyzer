// Minimal local server for the YouTube Analyst dashboard.
//   GET  /                → serves youtube-analyst.html
//   GET  /health          → 200 ok
//   GET  /analyze?url=…   → spawns tools/analyze_video.py --url …
//   GET  /run?…           → spawns tools/run_weekly_report.py (legacy batch pipeline)
//   POST /stop            → kills the running pipeline (if any)
//
// No npm dependencies — uses only Node built-ins. Run with:  node serve.mjs

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 5173);
const HTML_PATH = join(HERE, "youtube-analyst.html");
const PYTHON = process.env.PYTHON
  || (process.platform === "win32" ? "python" : "python3");

let currentProcess = null;

function buildAnalyzeArgs(query) {
  const args = ["-u", join("tools", "analyze_video.py")];
  if (query.url) args.push("--url", query.url);
  return args;
}

function buildBatchArgs(query) {
  const args = ["-u", join("tools", "run_weekly_report.py")];
  if (query.channels)   args.push("--channels", query.channels);
  if (query.keywords)   args.push("--keywords", query.keywords);
  if (query.lookback)   args.push("--lookback", String(query.lookback));
  if (query.maxResults) args.push("--max-results", String(query.maxResults));
  if (query.sheets === "0") args.push("--no-sheets");
  if (query.slides === "0") args.push("--no-slides");
  if (query.email  === "0") args.push("--skip-email");
  return args;
}

function sseSend(res, event, data) {
  if (event) res.write(`event: ${event}\n`);
  const payload = typeof data === "string" ? data : JSON.stringify(data);
  for (const line of payload.split(/\r?\n/)) res.write(`data: ${line}\n`);
  res.write("\n");
}

function spawnAndStream(res, args, req, label) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
  });

  sseSend(res, "log", `[serve] ${label}: ${PYTHON} ${args.join(" ")}`);
  sseSend(res, "log", `[serve] cwd: ${HERE}`);

  let child;
  try {
    child = spawn(PYTHON, args, {
      cwd: HERE,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (e) {
    sseSend(res, "log", `[serve] ERROR spawning python: ${e.message}`);
    sseSend(res, "done", { code: 1 });
    res.end();
    return;
  }

  currentProcess = child;

  // Heartbeat: a slow pipeline step (e.g. creating a spreadsheet) can leave the
  // SSE stream idle long enough for a cloud proxy to drop it ("connection
  // closed"). A periodic comment keeps the connection alive without affecting
  // the EventSource data.
  const heartbeat = setInterval(() => {
    try { res.write(`: keepalive ${Date.now()}\n\n`); } catch (_) {}
  }, 15000);

  const emitLines = (buf) => {
    const lines = buf.toString("utf-8").split(/\r?\n/);
    for (const line of lines) {
      if (line.length === 0) continue;
      sseSend(res, "log", line);
    }
  };

  child.stdout.on("data", emitLines);
  child.stderr.on("data", emitLines);

  child.on("error", (err) => {
    sseSend(res, "log", `[serve] process error: ${err.message}`);
  });
  child.on("close", (code) => {
    clearInterval(heartbeat);
    sseSend(res, "done", { code });
    res.end();
    if (currentProcess === child) currentProcess = null;
  });

  req.on("close", () => {
    clearInterval(heartbeat);
    if (currentProcess === child) {
      try { child.kill("SIGTERM"); } catch (_) {}
    }
  });
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/youtube-analyst.html")) {
    try {
      const html = await readFile(HTML_PATH);
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
    } catch (e) {
      res.writeHead(500, { "Content-Type": "text/plain" });
      res.end(`Failed to read dashboard: ${e.message}`);
    }
    return;
  }

  if (req.method === "GET" && url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, running: currentProcess != null }));
    return;
  }

  if (req.method === "GET" && url.pathname === "/analyze") {
    if (currentProcess) {
      res.writeHead(409, { "Content-Type": "text/plain" });
      res.end("A pipeline run is already in progress.");
      return;
    }
    const query = Object.fromEntries(url.searchParams.entries());
    if (!query.url || !query.url.trim()) {
      res.writeHead(400, { "Content-Type": "text/plain" });
      res.end("Missing required ?url= parameter.");
      return;
    }
    spawnAndStream(res, buildAnalyzeArgs(query), req, "spawning analyze");
    return;
  }

  if (req.method === "GET" && url.pathname === "/run") {
    if (currentProcess) {
      res.writeHead(409, { "Content-Type": "text/plain" });
      res.end("A pipeline run is already in progress.");
      return;
    }
    const query = Object.fromEntries(url.searchParams.entries());
    spawnAndStream(res, buildBatchArgs(query), req, "spawning batch");
    return;
  }

  if (req.method === "POST" && url.pathname === "/stop") {
    if (currentProcess) {
      try { currentProcess.kill("SIGTERM"); } catch (_) {}
      currentProcess = null;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, stopped: true }));
    } else {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, stopped: false }));
    }
    return;
  }

  res.writeHead(404, { "Content-Type": "text/plain" });
  res.end("Not found");
});

// Bind 0.0.0.0 so cloud platforms (Render, etc.) detect the open port.
server.listen(PORT, "0.0.0.0", () => {
  console.log(`[serve] YouTube Analyst dashboard → http://0.0.0.0:${PORT}`);
  console.log(`[serve]   /analyze?url=…    URL-mode analyzer (primary)`);
  console.log(`[serve]   /run?channels=…   legacy batch pipeline`);
  console.log(`[serve] python: ${PYTHON}   (override with PYTHON=… env)`);
});
