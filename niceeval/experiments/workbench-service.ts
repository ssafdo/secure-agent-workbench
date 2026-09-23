import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

interface LifecycleContext {
  signal: AbortSignal;
  progress(update: { message: string }): void;
}

export class WorkbenchService {
  private child: ReturnType<typeof spawn> | undefined;
  private runtimeRoot: string | undefined;
  private endpoint: string | undefined;
  private stderrTail = "";

  constructor(private readonly repositoryRoot: string) {}

  baseUrl(): string {
    if (this.endpoint === undefined) throw new Error("Workbench endpoint is not ready.");
    return this.endpoint;
  }

  private firstLine(
    stream: NonNullable<ReturnType<typeof spawn>["stdout"]>,
    processHandle: ReturnType<typeof spawn>,
    signal: AbortSignal,
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      let buffer = "";
      const timeout = setTimeout(
        () => finish(new Error("Workbench readiness timed out.")),
        10_000,
      );
      const onData = (chunk: Buffer) => {
        buffer += chunk.toString("utf8");
        const newline = buffer.indexOf("\n");
        if (newline >= 0) finish(undefined, buffer.slice(0, newline));
      };
      const onExit = (code: number | null) =>
        finish(
          new Error(
            `Workbench exited before readiness (code ${code}): ${this.stderrTail}`,
          ),
        );
      const onError = (error: Error) => finish(error);
      const onAbort = () =>
        finish(signal.reason ?? new Error("Experiment setup aborted."));
      const finish = (error?: unknown, value?: string) => {
        clearTimeout(timeout);
        stream.off("data", onData);
        processHandle.off("exit", onExit);
        processHandle.off("error", onError);
        signal.removeEventListener("abort", onAbort);
        if (error !== undefined) reject(error);
        else resolve(value ?? "");
      };
      stream.on("data", onData);
      processHandle.on("exit", onExit);
      processHandle.on("error", onError);
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  async start(ctx: LifecycleContext, extraEnv: Record<string, string> = {}): Promise<void> {
    ctx.progress({ message: "Starting the real Python workbench service" });
    this.runtimeRoot = await mkdtemp(
      join(tmpdir(), "secure-agent-workbench-niceeval-"),
    );
    const python =
      process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");
    this.child = spawn(
      python,
      ["-B", "-m", "agent_workbench", "serve", "--host", "127.0.0.1", "--port", "0"],
      {
        cwd: this.repositoryRoot,
        env: {
          PYTHONPATH: join(this.repositoryRoot, "src"),
          PYTHONDONTWRITEBYTECODE: "1",
          AGENT_WORKBENCH_ROOT: this.runtimeRoot,
          AGENT_WORKBENCH_SECRET: randomBytes(32).toString("hex"),
          ...(process.env.SYSTEMROOT ? { SYSTEMROOT: process.env.SYSTEMROOT } : {}),
          ...(process.env.TEMP ? { TEMP: process.env.TEMP } : {}),
          ...(process.env.TMP ? { TMP: process.env.TMP } : {}),
          ...extraEnv,
        },
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    this.child.stderr?.on("data", (chunk: Buffer) => {
      this.stderrTail = `${this.stderrTail}${chunk.toString("utf8")}`.slice(-2_000);
    });
    if (this.child.stdout === null) throw new Error("Workbench stdout is unavailable.");
    const ready = JSON.parse(
      await this.firstLine(this.child.stdout, this.child, ctx.signal),
    ) as { status?: unknown; port?: unknown };
    if (ready.status !== "ready" || typeof ready.port !== "number") {
      throw new Error("Workbench emitted an invalid readiness record.");
    }
    this.endpoint = `http://127.0.0.1:${ready.port}`;
    const health = await fetch(`${this.endpoint}/health`, { signal: ctx.signal });
    if (!health.ok) {
      throw new Error(`Workbench health check failed with ${health.status}.`);
    }
  }

  async stop(ctx: LifecycleContext): Promise<void> {
    ctx.progress({ message: "Stopping the Python workbench service" });
    const processHandle = this.child;
    try {
      if (
        processHandle !== undefined &&
        processHandle.exitCode === null &&
        processHandle.signalCode === null
      ) {
        const exited = once(processHandle, "exit");
        processHandle.kill();
        await Promise.race([
          exited,
          new Promise((resolve) => setTimeout(resolve, 5_000)),
        ]);
        if (processHandle.exitCode === null && processHandle.signalCode === null) {
          const killed = once(processHandle, "exit");
          processHandle.kill("SIGKILL");
          await killed;
        }
      }
    } finally {
      if (this.runtimeRoot !== undefined) {
        await rm(this.runtimeRoot, { recursive: true, force: true });
      }
      this.endpoint = undefined;
      this.runtimeRoot = undefined;
      this.child = undefined;
      this.stderrTail = "";
    }
  }
}
