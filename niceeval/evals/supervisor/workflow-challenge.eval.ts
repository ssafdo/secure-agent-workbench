import { equals, greaterThan, lessThan } from "niceeval/expect";

import { supervisorBenchmark } from "../../adapters/supervisor-benchmark.ts";

export default supervisorBenchmark.defineEval({
  description: "Larger bilingual workflow challenge preserves failures and measures routing benefit",
  tags: ["multi-agent", "supervisor", "workflow", "challenge"],
  async test(t) {
    const result = await t.runWorkflowChallenge();

    t.check(result.schemaVersion, equals(1)).gate().label("Benchmark schema is stable");
    t.check(result.single.cases, equals(24)).gate().label("Single-agent denominator is frozen");
    t.check(result.supervisor.cases, equals(24)).gate().label("Supervisor denominator is frozen");
    t.check(result.supervisor.successRate, greaterThan(result.single.successRate))
      .gate()
      .label("Supervisor improves workflow completion");
    t.check(result.supervisor.successRate, greaterThan(0.7))
      .gate()
      .label("Supervisor clears the preregistered public challenge floor");
    t.check(result.supervisor.averageToolCalls, lessThan(result.single.averageToolCalls))
      .gate()
      .label("Supervisor reduces average tool calls");
    t.check(Array.isArray(result.supervisor.failures), equals(true))
      .gate()
      .label("Per-case failures remain available for diagnosis");
  },
});
