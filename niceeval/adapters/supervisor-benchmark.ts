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
  averageCitationPrecision: number;
  failures: Array<{
    id: string;
    failureType: string | null;
  }>;
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

export interface RoutingBenchmarkResult {
  schemaVersion: number;
  cases: number;
  correct: number;
  accuracy: number;
  weightedError: number;
  weightedAccuracy: number;
  conflictCases: number;
  conflictCorrect: number;
  defaultCases: number;
  lowConfidenceDefaults: number;
  errors: unknown[];
  languageSlices: Record<string, { cases: number; correct: number; accuracy: number }>;
  confidenceCounts: Record<string, number>;
}

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const MAX_OUTPUT_BYTES = 512 * 1024;

function runPythonJson<T>(
  script: string,
  args: string[],
  signal: AbortSignal,
): Promise<T> {
  const python = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      ["-B", script, ...args],
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
        resolve(JSON.parse(stdout) as T);
      } catch (error) {
        reject(new Error("Supervisor benchmark returned invalid JSON.", { cause: error }));
      }
    });
  });
}

function runBenchmark(signal: AbortSignal): Promise<SupervisorBenchmarkResult> {
  return runPythonJson(
    "scripts/benchmark_supervisor.py",
    ["--require-improvement"],
    signal,
  );
}

function runWorkflowChallenge(
  signal: AbortSignal,
): Promise<SupervisorBenchmarkResult> {
  return runPythonJson(
    "scripts/benchmark_supervisor.py",
    [
      "--dataset",
      "benchmarks/supervisor_workflow_challenge_v1.json",
      "--minimum-cases",
      "24",
    ],
    signal,
  );
}

function runRoutingBenchmark(signal: AbortSignal): Promise<RoutingBenchmarkResult> {
  return runPythonJson(
    "scripts/benchmark_supervisor_routing.py",
    ["--minimum-accuracy", "0.96", "--maximum-weighted-error", "0"],
    signal,
  );
}

function runNaturalisticDevelopmentBenchmark(
  signal: AbortSignal,
): Promise<RoutingBenchmarkResult> {
  return runPythonJson(
    "scripts/benchmark_supervisor_routing.py",
    [
      "--dataset",
      "benchmarks/supervisor_naturalistic_dev_cases.json",
      "--minimum-accuracy",
      "1.0",
      "--maximum-weighted-error",
      "0",
    ],
    signal,
  );
}

export const supervisorBenchmark = defineAdapter({
  name: "secure-agent-workbench-supervisor-benchmark",
  behaviorRevision: "phase-27-public-workflow-challenge-v1",
  create(context) {
    return {
      runBenchmark: () => runBenchmark(context.signal),
      runWorkflowChallenge: () => runWorkflowChallenge(context.signal),
      runRoutingBenchmark: () => runRoutingBenchmark(context.signal),
      runNaturalisticDevelopmentBenchmark: () =>
        runNaturalisticDevelopmentBenchmark(context.signal),
    };
  },
});
