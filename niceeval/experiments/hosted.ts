import { fileURLToPath } from "node:url";

import { defineExperiment } from "niceeval";

import { workbenchAgent } from "../agents/workbench.ts";
import { WorkbenchService } from "./workbench-service.ts";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const workbench = new WorkbenchService(repositoryRoot);

export default defineExperiment({
  description: "Real server-configured Responses API provider",
  agent: workbenchAgent({ baseUrl: () => workbench.baseUrl(), reportUsage: true }),
  evals: ["research/hosted"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 120_000,
  async setup(ctx) {
    const apiKey = process.env.AGENT_WORKBENCH_MODEL_API_KEY;
    const model = process.env.AGENT_WORKBENCH_MODEL;
    if (!apiKey || !model) {
      throw new Error(
        "hosted experiment requires AGENT_WORKBENCH_MODEL_API_KEY and AGENT_WORKBENCH_MODEL",
      );
    }
    await workbench.start(ctx, {
      AGENT_WORKBENCH_MODEL_API_KEY: apiKey,
      AGENT_WORKBENCH_MODEL: model,
      AGENT_WORKBENCH_MODEL_BASE_URL:
        process.env.AGENT_WORKBENCH_MODEL_BASE_URL ?? "https://api.openai.com/v1",
      AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS:
        process.env.AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS ?? "30",
    });
  },
  async teardown(ctx) {
    await workbench.stop(ctx);
  },
});
