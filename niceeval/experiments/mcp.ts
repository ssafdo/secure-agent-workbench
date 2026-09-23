import { defineExperiment } from "niceeval";

import { mcpWorkbench } from "../adapters/mcp-workbench.ts";

export default defineExperiment({
  description: "Official MCP SDK read-only admission and runtime baseline",
  adapter: mcpWorkbench,
  evals: ["mcp/"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 60_000,
});
