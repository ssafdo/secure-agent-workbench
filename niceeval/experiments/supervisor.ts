import { defineExperiment } from "niceeval";

import { supervisorBenchmark } from "../adapters/supervisor-benchmark.ts";

export default defineExperiment({
  description: "Single-agent versus routed-supervisor ablation",
  adapter: supervisorBenchmark,
  evals: ["supervisor/"],
  attempts: 1,
  maxConcurrency: 1,
  timeoutMs: 30_000,
});
