import { defineEval } from "niceeval";
import { hasSections, includes } from "niceeval/expect";

export default defineEval({
  description: "Research report generation and no-source refusal",
  async test(t) {
    const positive = await t.send(
      JSON.stringify({
        task: "Identify the highest-priority isolation improvement and summarize the evidence.",
        sources: [
          {
            path: "architecture.md",
            content:
              "The current runtime enforces project paths and approval policy. Operating-system container isolation is still planned.",
          },
          {
            path: "delivery.txt",
            content:
              "Every run must preserve a reviewable tool trace and write its report beneath the project output directory.",
          },
        ],
      }),
    );

    positive.succeeded().label("Research request completed");
    positive.calledTool("list_files").label("Enumerated project sources");
    positive.calledTool("read_text").label("Read at least one source");
    positive.calledTool("write_text").label("Wrote the report artifact");
    positive.noFailedActions().label("All research tools succeeded");
    t.check(positive.message, hasSections(4)).label("Report has a stable Markdown structure");
    t.check(
      positive.message,
      includes("This deterministic baseline proves workspace, policy, tool, and trace flow."),
    ).label("Report includes the baseline conclusion");

    const emptySession = t.newSession();
    const negative = await emptySession.send(
      JSON.stringify({
        task: "Prepare a report from the project sources without inventing evidence.",
        sources: [],
      }),
    );

    negative.succeeded().label("No-source request completed without infrastructure error");
    negative.calledTool("list_files").label("Checked for available sources");
    negative.notCalledTool("read_text").label("Did not fabricate a source read");
    negative.calledTool("write_text").label("Still produced an auditable artifact");
    t.check(
      negative.message,
      includes("No readable Markdown or text sources were found."),
    ).label("Explicitly reports that no evidence was available");
  },
});
