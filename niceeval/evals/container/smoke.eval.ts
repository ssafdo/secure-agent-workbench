import { equals, includes } from "niceeval/expect";

import { containerWorkbench } from "../../adapters/container-workbench.ts";

export default containerWorkbench.defineEval({
  description: "Real Docker isolation, project mounts, cleanup, and bounded output",
  tags: ["container", "security"],
  async test(t) {
    const result = await t.runSmoke();

    t.check(result.status, equals("completed")).gate().label("Smoke completed");
    t.check(result.doctor.ready, equals(true)).gate().label("Executor is ready");
    t.check(result.doctor.imageDigestPinned, equals(true))
      .gate()
      .label("Image identity is immutable");
    t.check(result.toolStatus, equals("succeeded"))
      .gate()
      .label("Runtime tool call succeeded");
    t.check(result.container?.exit_code, equals(0))
      .gate()
      .label("Container exited successfully");
    t.check(result.container?.stdout ?? "", includes("container-smoke-ok"))
      .gate()
      .label("Container emitted the success signal");
    t.check(result.container?.stdout_truncated, equals(false))
      .gate()
      .label("Standard output stayed within its bound");
    t.check(result.container?.stderr_truncated, equals(false))
      .gate()
      .label("Standard error stayed within its bound");
    t.check(result.artifact, equals("isolated:phase-8-real"))
      .gate()
      .label("Only the isolated output mount received the artifact");
    t.check(result.residualContainers?.length, equals(0))
      .gate()
      .label("No workbench container remained after execution");
    t.check(result.traceEvents, equals(1))
      .gate()
      .label("The execution attempt produced one policy trace event");
  },
});
