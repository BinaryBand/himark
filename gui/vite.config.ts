import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin, type ViteDevServer } from "vite";

const REPO_ROOT = resolve(__dirname, "..");
const BRIDGE = resolve(__dirname, "bridge.py");

// Prefer the repo's virtualenv interpreter (it has himark + deps installed);
// fall back to whatever `python3` is on PATH. Override with HIMARK_PYTHON.
function pythonBin(): string {
  if (process.env.HIMARK_PYTHON) return process.env.HIMARK_PYTHON;
  const venv = resolve(REPO_ROOT, ".venv/bin/python");
  return existsSync(venv) ? venv : "python3";
}

// POST /api/run -> bridge.py (stdin: the request JSON, stdout: the response).
function engineBridge(): Plugin {
  return {
    name: "himark-engine-bridge",
    configureServer(server: ViteDevServer) {
      server.middlewares.use("/api/run", (req, res) => {
        if (req.method !== "POST") {
          res.statusCode = 405;
          res.end("POST only");
          return;
        }
        const chunks: Buffer[] = [];
        req.on("data", (c) => chunks.push(c));
        req.on("end", () => {
          const proc = spawn(pythonBin(), [BRIDGE], { cwd: REPO_ROOT });
          let out = "";
          let err = "";
          proc.stdout.on("data", (d) => (out += d));
          proc.stderr.on("data", (d) => (err += d));
          proc.on("close", (code) => {
            res.setHeader("Content-Type", "application/json");
            if (code !== 0 && !out) {
              res.statusCode = 200;
              res.end(
                JSON.stringify({ error: err.trim() || "engine crashed" }),
              );
            } else {
              res.end(out || "{}");
            }
          });
          proc.stdin.write(Buffer.concat(chunks));
          proc.stdin.end();
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), engineBridge()],
  server: {
    // Pin the port so a Cloudflare tunnel can target a stable address; fail loud
    // rather than drifting to a random port if it's taken. Override with PORT.
    port: Number(process.env.PORT) || 5174,
    strictPort: true,
    // Listen on all interfaces and accept any Host header, so a tunnel (or a LAN
    // device) reaching the dev server isn't rejected as a "blocked host".
    host: true,
    allowedHosts: ["himark.doreeto.com", "localhost"],
    // The default scripts and demo targets live outside gui/; let Vite read them
    // so `import.meta.glob` can bundle them as defaults.
    fs: { allow: [REPO_ROOT] },
  },
});
