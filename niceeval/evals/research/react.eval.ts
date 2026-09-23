import { defineEval } from "niceeval";
import { hasSections, includes } from "niceeval/expect";

export default defineEval({
  description: "Offline ReAct model protocol and policy-enforced tool loop",
  async test(t) {
    const result = await t.send(
      JSON.stringify({
        engine: "react",
        task: "Identify the next isolation priority and preserve an auditable report.",
        sources: [
          {
            path: "architecture.md",
            content:
              "Application path guards exist, but operating-system container isolation is not implemented.",
          },
          {
            path: "delivery.txt",
            content:
              "Every workflow must expose its tool trace and keep artifacts inside the project output directory.",
          },
        ],
      }),
    );

    result.succeeded().label("ReAct research request completed");
    result.calledTool("list_files").label("Model enumerated project sources");
    result.calledTool("read_text").label("Model read isolated source files");
    result.calledTool("write_text").label("Model wrote through the approved tool");
    result.noFailedActions().label("All ReAct tool calls succeeded");
    t.check(result.message, hasSections(4)).label("ReAct report has stable structure");
    t.check(
      result.message,
      includes(
        "This offline ReAct baseline proves model protocol, workspace, policy, tool, budget, and trace flow.",
      ),
    ).label("Report confirms the model-loop control boundary");
  },
});
