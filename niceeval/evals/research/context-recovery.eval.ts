import { defineEval } from "niceeval";
import {
  defineValueMatch,
  equals,
  hasSections,
  pattern,
  toolMatch,
} from "niceeval/expect";

const positiveInteger = defineValueMatch<number>({
  name: "positive integer",
  evaluate: (value) => Number.isInteger(value) && value > 0,
});

interface RecoveryDiagnostics {
  contextCompactions?: unknown;
  compactedMessages?: unknown;
  truncatedMessages?: unknown;
  reflections?: unknown;
}

export default defineEval({
  description: "Bounded context and one-shot recovery after a recoverable tool failure",
  async test(t) {
    const evidence =
      "Container isolation remains the required boundary. ".repeat(1_000) +
      "LATEST-FACT: preserve the auditable trace.";
    const result = await t.send(
      JSON.stringify({
        engine: "react-recovery",
        task: "Recover once, preserve the latest evidence, and write a bounded report.",
        sources: [{ path: "long-evidence.md", content: evidence }],
      }),
    );

    result.succeeded().label("Recovery workflow completed after one injected failure");
    result.calledTool(
      toolMatch("unavailable_research_tool", { status: "failed" }).exactly(1),
    ).label("Recoverable failure was injected exactly once");
    result.calledTool(toolMatch("list_files", { status: "completed" }).exactly(1)).label(
      "Recovery returned to the declared research tools",
    );
    result.calledTool(toolMatch("read_text", { status: "completed" }).exactly(1)).label(
      "Long evidence was read through the policy runtime",
    );
    result.calledTool(toolMatch("write_text", { status: "completed" }).exactly(1)).label(
      "Recovered workflow wrote one approved artifact",
    );
    t.check(result.message, hasSections(4)).label(
      "Recovered report retains stable structure",
    );
    t.check(result.message, pattern(/container isolation/i)).label(
      "Recovered report remains grounded in the latest evidence",
    );

    const data = result.data as
      | { artifactPath?: unknown; diagnostics?: RecoveryDiagnostics }
      | undefined;
    t.check(
      data?.artifactPath,
      equals("outputs/react-research-report.md"),
    ).label("Recovered artifact stays inside the project output directory");
    t.check(data?.diagnostics?.reflections, equals(1)).label(
      "Reflection is bounded to exactly one retry",
    );
    t.check(
      data?.diagnostics?.contextCompactions as number,
      positiveInteger,
    ).label("Long conversation history was compacted");
    t.check(
      data?.diagnostics?.compactedMessages as number,
      positiveInteger,
    ).label("Compaction removed older messages from the active context");
    t.check(
      data?.diagnostics?.truncatedMessages as number,
      positiveInteger,
    ).label("Oversized recent tool output was bounded without aborting the run");
  },
});
