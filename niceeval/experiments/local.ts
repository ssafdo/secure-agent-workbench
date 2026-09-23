import { createServer, type Server } from "node:http";
import { fileURLToPath } from "node:url";

import { defineExperiment } from "niceeval";

import { workbenchAgent } from "../agents/workbench.ts";
import { WorkbenchService } from "./workbench-service.ts";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const workbench = new WorkbenchService(repositoryRoot);
const mockKey = "niceeval-local-mock-key";
let mockServer: Server | undefined;

function responseItem(callId: string, name: string, args: Record<string, unknown>) {
  return {
    type: "function_call",
    id: `fc-${callId}`,
    call_id: callId,
    name,
    arguments: JSON.stringify(args),
    status: "completed",
  };
}

function parseToolOutput(value: unknown): { output?: unknown } {
  if (typeof value !== "string") return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function mockResponse(body: unknown): object {
  if (typeof body !== "object" || body === null) throw new Error("invalid request");
  const input = (body as { input?: unknown }).input;
  if (!Array.isArray(input)) throw new Error("input must be an array");
  const calls = input.filter(
    (item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null && item.type === "function_call",
  );
  const outputs = input.filter(
    (item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null && item.type === "function_call_output",
  );
  const lastCall = calls.at(-1);
  let output: object[];

  if (calls.length === 0) {
    output = [responseItem("mock-list", "list_files", { path: "inputs" })];
  } else if (lastCall?.name === "list_files") {
    const listResult = parseToolOutput(outputs.at(-1)?.output).output;
    const paths = Array.isArray(listResult)
      ? listResult.filter(
          (path): path is string =>
            typeof path === "string" && /\.(md|txt)$/i.test(path),
        )
      : [];
    output = paths.map((path, index) =>
      responseItem(`mock-read-${index + 1}`, "read_text", { path }),
    );
  } else if (lastCall?.name === "read_text") {
    const readCount = calls.filter((call) => call.name === "read_text").length;
    const notes = outputs
      .slice(-readCount)
      .map((item) => String(parseToolOutput(item.output).output ?? ""))
      .join(" ");
    const report = [
      "# Hosted Research Report",
      "",
      "## Task",
      "",
      "Identify the next isolation priority from the supplied evidence.",
      "",
      "## Evidence",
      "",
      notes,
      "",
      "## Risk",
      "",
      "Operating-system container isolation remains necessary before untrusted execution.",
      "",
      "## Recommendation",
      "",
      "Preserve an auditable tool trace and add container isolation as the next boundary.",
      "",
    ].join("\n");
    output = [
      responseItem("mock-write", "write_text", {
        path: "outputs/hosted-research-report.md",
        content: report,
      }),
    ];
  } else if (lastCall?.name === "write_text") {
    output = [
      {
        type: "message",
        id: "msg-final",
        role: "assistant",
        status: "completed",
        content: [{ type: "output_text", text: "Hosted report written." }],
      },
    ];
  } else {
    throw new Error("unexpected mock conversation state");
  }

  return {
    id: `resp-${calls.length + 1}`,
    object: "response",
    status: "completed",
    output,
    usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
  };
}

async function startMockProvider(): Promise<string> {
  mockServer = createServer((request, response) => {
    if (
      request.method !== "POST" ||
      request.url !== "/v1/responses" ||
      request.headers.authorization !== `Bearer ${mockKey}`
    ) {
      response.writeHead(404).end();
      return;
    }
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      try {
        const body: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(mockResponse(body)));
      } catch {
        response.writeHead(400, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: "invalid mock request" }));
      }
    });
  });
  await new Promise<void>((resolve, reject) => {
    mockServer?.once("error", reject);
    mockServer?.listen(0, "127.0.0.1", resolve);
  });
  const address = mockServer.address();
  if (address === null || typeof address === "string") {
    throw new Error("Mock Responses service did not expose a TCP port.");
  }
  return `http://127.0.0.1:${address.port}/v1`;
}

async function stopMockProvider(): Promise<void> {
  const server = mockServer;
  mockServer = undefined;
  if (server === undefined) return;
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
}

export default defineExperiment({
  description: "Deterministic, offline ReAct, and simulated hosted baselines",
  agent: workbenchAgent({ baseUrl: () => workbench.baseUrl(), reportUsage: false }),
  evals: ["research/"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 30_000,
  async setup(ctx) {
    ctx.progress({ message: "Starting the local Responses protocol simulator" });
    const mockBaseUrl = await startMockProvider();
    await workbench.start(ctx, {
      AGENT_WORKBENCH_MODEL_API_KEY: mockKey,
      AGENT_WORKBENCH_MODEL: "niceeval-mock-model",
      AGENT_WORKBENCH_MODEL_BASE_URL: mockBaseUrl,
      AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS: "5",
    });
  },
  async teardown(ctx) {
    try {
      await workbench.stop(ctx);
    } finally {
      await stopMockProvider();
    }
  },
});
