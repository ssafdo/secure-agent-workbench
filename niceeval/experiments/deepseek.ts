import { fileURLToPath } from "node:url";

import { defineExperiment } from "niceeval";

import { workbenchAgent } from "../agents/workbench.ts";
import { WorkbenchService } from "./workbench-service.ts";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const workbench = new WorkbenchService(repositoryRoot);
const model = process.env.DEEPSEEK_MODEL;

export default defineExperiment({
  description: "Real DeepSeek stateless Responses API provider",
  agent: workbenchAgent({ baseUrl: () => workbench.baseUrl(), reportUsage: true }),
  model,
  evals: ["research/hosted"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 180_000,
  async setup(ctx) {
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey || !model) {
      throw new Error(
        "deepseek experiment requires DEEPSEEK_API_KEY and DEEPSEEK_MODEL",
      );
    }
    await workbench.start(ctx, {
      AGENT_WORKBENCH_MODEL_PROVIDER: "deepseek",
      DEEPSEEK_API_KEY: apiKey,
      DEEPSEEK_MODEL: model,
      DEEPSEEK_BASE_URL:
        process.env.DEEPSEEK_BASE_URL ?? "https://api.deepseek.com",
      AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS:
        process.env.AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS ?? "60",
    });
  },
  async teardown(ctx) {
    await workbench.stop(ctx);
  },
});
