import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineAdapter } from "niceeval";

export interface ContainerSmokeResult {
  status: "completed" | "failed";
  doctor: {
    dockerCliPresent: boolean;
    daemonReachable: boolean;
    imageConfigured: boolean;
    imageDigestPinned: boolean;
    imageAvailableLocally: boolean;
    allowlistConfigured: boolean;
    executorEnabled: boolean;
    ready: boolean;
    image: string | null;
  };
  toolStatus?: "succeeded" | "failed" | "denied";
  container?: {
    exit_code: number;
    stdout: string;
    stderr: string;
    stdout_truncated: boolean;
    stderr_truncated: boolean;
  };
  artifact?: string | null;
  residualContainers?: string[];
  traceEvents?: number;
  error?: string;
}

function capture(
  command: string,
  args: string[],
  options: { signal: AbortSignal; cwd?: string; env?: NodeJS.ProcessEnv },
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ["ignore", "pipe", "pipe"],
      signal: options.signal,
      ...(options.cwd === undefined ? {} : { cwd: options.cwd }),
      ...(options.env === undefined ? {} : { env: options.env }),
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function parseSmoke(
  processResult: { code: number | null; stdout: string; stderr: string },
): ContainerSmokeResult {
  const lines = processResult.stdout.trim().split(/\r?\n/).filter(Boolean);
  const lastLine = lines.at(-1);
  if (lastLine === undefined) {
    throw new Error(
      `Container smoke emitted no JSON (exit ${processResult.code}): ${processResult.stderr}`,
    );
  }
  const result = JSON.parse(lastLine) as ContainerSmokeResult;
  if (processResult.code !== 0) {
    throw new Error(
      `Container smoke failed with exit ${processResult.code}: ${result.error ?? processResult.stderr}`,
    );
  }
  return result;
}

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));

async function runSmoke(signal: AbortSignal): Promise<ContainerSmokeResult> {
  const bridgeUrl = process.env.AGENT_WORKBENCH_CONTAINER_BRIDGE_URL;
  const bridgeToken = process.env.AGENT_WORKBENCH_CONTAINER_BRIDGE_TOKEN;
  if ((bridgeUrl === undefined) !== (bridgeToken === undefined)) {
    throw new Error("Container bridge URL and token must be configured together.");
  }
  if (bridgeUrl !== undefined && bridgeToken !== undefined) {
    const response = await fetch(`${bridgeUrl}/smoke`, {
      method: "POST",
      headers: { authorization: `Bearer ${bridgeToken}` },
      signal,
    });
    const result = (await response.json()) as ContainerSmokeResult;
    if (!response.ok) {
      throw new Error(result.error ?? `Container bridge failed with ${response.status}.`);
    }
    return result;
  }
  if (/^\/mnt\/[a-zA-Z]\//.test(repositoryRoot)) {
    throw new Error(
      "WSL container evaluation requires scripts/run_container_niceeval.py.",
    );
  }

  const docker = process.env.DOCKER ?? "docker";
  const inspected = await capture(
    docker,
    ["image", "inspect", "--format", "{{.Id}}", "secure-agent-runner:dev"],
    { signal, cwd: repositoryRoot },
  );
  if (inspected.code !== 0 || inspected.stdout.trim() === "") {
    throw new Error(`The local runner image is unavailable: ${inspected.stderr}`);
  }
  const python = process.env.PYTHON ?? "python3";
  return parseSmoke(
    await capture(python, ["-B", "-m", "agent_workbench", "container-smoke"], {
      signal,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        PYTHONPATH: join(repositoryRoot, "src"),
        PYTHONDONTWRITEBYTECODE: "1",
        AGENT_WORKBENCH_CONTAINER_ENABLED: "true",
        AGENT_WORKBENCH_CONTAINER_IMAGE: inspected.stdout.trim(),
        AGENT_WORKBENCH_CONTAINER_EXECUTABLES: "agent-runner",
      },
    }),
  );
}

export const containerWorkbench = defineAdapter({
  name: "secure-agent-workbench-container",
  behaviorRevision: "phase-10-container-ci-v5",
  create(context) {
    return {
      runSmoke: () => runSmoke(context.signal),
    };
  },
});
