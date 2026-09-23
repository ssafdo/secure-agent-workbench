import { equals, includes } from "niceeval/expect";

import { mcpWorkbench } from "../../adapters/mcp-workbench.ts";

export default mcpWorkbench.defineEval({
  description: "Strict MCP discovery, read-only admission, bounded call, and redacted trace",
  tags: ["mcp", "security"],
  async test(t) {
    const result = await t.runSmoke();

    t.check(result.status, equals("completed")).gate().label("Smoke completed");
    t.check(result.server, equals("smoke")).gate().label("Fixed server was selected");
    t.check(result.sourceTools, equals(["project_summary"]))
      .gate()
      .label("Only the explicit source allowlist was discovered");
    t.check(result.registeredTools, equals(["mcp_smoke_project_summary"]))
      .gate()
      .label("Discovered tool was registered under its namespace");
    t.check(result.permission, equals("read"))
      .gate()
      .label("Registered MCP permission remained read-only");
    t.check(result.toolStatus, equals("succeeded"))
      .gate()
      .label("MCP call passed through AgentRuntime");
    t.check(result.output ?? "", includes("strict schema"))
      .gate()
      .label("Bounded MCP output reached the caller");
    t.check(result.traceEvents, equals(1))
      .gate()
      .label("Runtime recorded exactly one tool event");
    t.check(result.traceRedacted, equals(true))
      .gate()
      .label("Trace omitted MCP argument values");
  },
});
