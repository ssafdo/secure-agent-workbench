import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineAdapter } from "niceeval";

export interface StrategyMetrics {
  passed: number;
  cases: number;
  successRate: number;
  averageToolCalls: number;
  averageDurationMs: number;
  caseResults: Array<{
    id: string;
    passed: boolean;
    specialist: string;
    routingCorrect: boolean;
    toolCalls: number;
    durationMs: number;
  }>;
}

export interface SupervisorBenchmarkResult {
  schemaVersion: number;
  single: StrategyMetrics;
  supervisor: StrategyMetrics;
  successRateDelta: number;
}

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const MAX_OUTPUT_BYTES = 512 * 1024;

function runBenchmark(signal: AbortSignal): Promise<SupervisorBenchmarkResult> {
  const python = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      ["-B", "scripts/benchmark_supervisor.py", "--require-improvement"],
      {
        cwd: repositoryRoot,
        env: {
          ...process.env,
          PYTHONPATH: join(repositoryRoot, "src"),
          PYTHONDONTWRITEBYTECODE: "1",
        },
        signal,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let stdout = "";
    let stderr = "";
    let oversized = false;
    let spawnError: Error | undefined;
    const append = (current: string, chunk: Buffer) => {
      const next = current + chunk.toString("utf8");
      if (Buffer.byteLength(next, "utf8") > MAX_OUTPUT_BYTES) {
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
    child.once("error", (error) => {
      spawnError = error;
    });
    child.once("close", (code) => {
      if (spawnError) {
        reject(spawnError);
        return;
      }
      if (oversized) {
        reject(new Error("Supervisor benchmark output exceeded its bound."));
        return;
      }
      if (code !== 0) {
        reject(new Error(`Supervisor benchmark failed with exit ${code}: ${stderr}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout) as SupervisorBenchmarkResult);
      } catch (error) {
        reject(new Error("Supervisor benchmark returned invalid JSON.", { cause: error }));
      }
    });
  });
}

export const supervisorBenchmark = defineAdapter({
  name: "secure-agent-workbench-supervisor-benchmark",
  behaviorRevision: "phase-15-supervisor-v1",
  create(context) {
    return { runBenchmark: () => runBenchmark(context.signal) };
  },
});
