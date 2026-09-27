import { defineExperiment } from "niceeval";

import { supervisorBenchmark } from "../adapters/supervisor-benchmark.ts";

export default defineExperiment({
  description: "Supervisor routing regression and public workflow challenges",
  adapter: supervisorBenchmark,
  evals: ["supervisor/"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 30_000,
});
