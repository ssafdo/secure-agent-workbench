import { equals, greaterThan, lessThan } from "niceeval/expect";

import { supervisorBenchmark } from "../../adapters/supervisor-benchmark.ts";

export default supervisorBenchmark.defineEval({
  description: "Routed specialists improve mixed-task success without synthesis regression",
  tags: ["multi-agent", "supervisor", "ablation"],
  async test(t) {
    const result = await t.runBenchmark();

    t.check(result.schemaVersion, equals(1)).gate().label("Benchmark schema is stable");
    t.check(result.single.cases, equals(6)).gate().label("Single-agent denominator is fixed");
    t.check(result.supervisor.cases, equals(6)).gate().label("Supervisor denominator is fixed");
    t.check(result.single.successRate, equals(0.5))
      .gate()
      .label("Single-agent baseline remains measured");
    t.check(result.supervisor.successRate, equals(1))
      .gate()
      .label("Supervisor completed every mixed task");
    t.check(result.successRateDelta, greaterThan(0))
      .gate()
      .label("Routing improved end-task success");
    t.check(result.supervisor.averageToolCalls, lessThan(result.single.averageToolCalls))
      .gate()
      .label("Routing reduced average tool calls");
    t.check(
      result.supervisor.caseResults.every((item) => item.passed),
      equals(true),
    )
      .gate()
      .label("No supervisor case regressed");
    t.check(
      result.supervisor.caseResults.every((item) => item.routingCorrect),
      equals(true),
    )
      .gate()
      .label("Every task reached the intended specialist");
  },
});
