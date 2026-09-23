import { equals, greaterThan } from "niceeval/expect";

import { supervisorBenchmark } from "../../adapters/supervisor-benchmark.ts";

export default supervisorBenchmark.defineEval({
  description: "Bilingual routing reliability, confidence and failure attribution",
  tags: ["multi-agent", "supervisor", "routing", "bilingual"],
  async test(t) {
    const result = await t.runRoutingBenchmark();

    t.check(result.schemaVersion, equals(1)).gate().label("Routing schema is stable");
    t.check(result.cases, equals(50)).gate().label("Routing denominator is fixed");
    t.check(result.accuracy, greaterThan(0.959999))
      .gate()
      .label("Routing accuracy meets the declared threshold");
    t.check(result.weightedError, equals(0))
      .gate()
      .label("No weighted routing error remains");
    t.check(result.languageSlices.en.cases, equals(25))
      .gate()
      .label("English slice is fixed");
    t.check(result.languageSlices.zh.cases, equals(25))
      .gate()
      .label("Chinese slice is fixed");
    t.check(result.languageSlices.en.accuracy, greaterThan(0.959999))
      .gate()
      .label("English routing meets the threshold");
    t.check(result.languageSlices.zh.accuracy, greaterThan(0.959999))
      .gate()
      .label("Chinese routing meets the threshold");
    t.check(result.conflictCorrect, equals(result.conflictCases))
      .gate()
      .label("Synthesis wins every mixed-intent conflict");
    t.check(result.defaultCases, equals(4))
      .gate()
      .label("Unknown-intent denominator is fixed");
    t.check(result.lowConfidenceDefaults, equals(4))
      .gate()
      .label("Unknown intents expose low-confidence fallback");
    t.check(result.errors.length, equals(0)).gate().label("Error list remains empty");
  },
});
