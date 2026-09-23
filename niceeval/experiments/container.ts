import { defineExperiment } from "niceeval";

import { containerWorkbench } from "../adapters/container-workbench.ts";

export default defineExperiment({
  description: "Real local Docker executor security baseline",
  adapter: containerWorkbench,
  evals: ["container/"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 30_000,
});
