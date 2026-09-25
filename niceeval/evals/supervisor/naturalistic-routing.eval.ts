import { equals } from "niceeval/expect";

import { supervisorBenchmark } from "../../adapters/supervisor-benchmark.ts";

export default supervisorBenchmark.defineEval({
  description: "Naturalistic bilingual development routing without private holdout reuse",
  tags: ["multi-agent", "supervisor", "routing", "bilingual", "development"],
  async test(t) {
    const result = await t.runNaturalisticDevelopmentBenchmark();

    t.check(result.schemaVersion, equals(1)).gate().label("Development schema is stable");
    t.check(result.cases, equals(60)).gate().label("Development denominator is fixed");
    t.check(result.accuracy, equals(1)).gate().label("Development routing is exact");
    t.check(result.weightedError, equals(0))
      .gate()
      .label("Development set has no weighted routing error");
    t.check(result.languageSlices.en.cases, equals(30))
      .gate()
      .label("Development English slice is fixed");
    t.check(result.languageSlices.zh.cases, equals(30))
      .gate()
      .label("Development Chinese slice is fixed");
    t.check(result.languageSlices.en.accuracy, equals(1))
      .gate()
      .label("Development English routing is exact");
    t.check(result.languageSlices.zh.accuracy, equals(1))
      .gate()
      .label("Development Chinese routing is exact");
    t.check(result.conflictCorrect, equals(result.conflictCases))
      .gate()
      .label("Strong synthesis wins every development conflict");
    t.check(result.errors.length, equals(0)).gate().label("Development error list is empty");
  },
});
