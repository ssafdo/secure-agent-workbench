import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineAdapter } from "niceeval";

export interface McpSmokeResult {
  status: "completed" | "failed";
  server?: string;
  sourceTools?: string[];
  registeredTools?: string[];
  permission?: string;
  toolStatus?: "succeeded" | "failed" | "denied";
  output?: string;
  traceEvents?: number;
  traceRedacted?: boolean;
  error?: string;
}

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const MAX_PROCESS_OUTPUT = 256 * 1024;

function runSmoke(signal: AbortSignal): Promise<McpSmokeResult> {
  const python = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-B", "-m", "agent_workbench", "mcp-smoke"], {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        PYTHONPATH: [join(repositoryRoot, "src"), process.env.PYTHONPATH]
          .filter((entry): entry is string => entry !== undefined && entry !== "")
          .join(process.platform === "win32" ? ";" : ":"),
        PYTHONDONTWRITEBYTECODE: "1",
      },
      signal,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let oversized = false;
    const append = (current: string, chunk: Buffer) => {
      const next = current + chunk.toString("utf8");
      if (Buffer.byteLength(next, "utf8") > MAX_PROCESS_OUTPUT) {
        oversized = true;
        child.kill();
      }
      return next;
    };
    child.stdout.on("data", (chunk: Buffer) => {
      stdout = append(stdout, chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr = append(stderr, chunk);
    });
    child.once("error", reject);
    child.once("close", (code) => {
      if (oversized) {
        reject(new Error("MCP smoke process output exceeded its bound."));
        return;
      }
      const lastLine = stdout.trim().split(/\r?\n/).filter(Boolean).at(-1);
      if (lastLine === undefined) {
        reject(new Error(`MCP smoke emitted no JSON (exit ${code}): ${stderr}`));
        return;
      }
      const result = JSON.parse(lastLine) as McpSmokeResult;
      if (code !== 0) {
        reject(new Error(result.error ?? `MCP smoke failed with exit ${code}.`));
        return;
      }
      resolve(result);
    });
  });
}

export const mcpWorkbench = defineAdapter({
  name: "secure-agent-workbench-mcp",
  behaviorRevision: "phase-14-mcp-v3",
  create(context) {
    return {
      runSmoke: () => runSmoke(context.signal),
    };
  },
});
