import { defineEval } from "niceeval";
import { equals, pattern } from "niceeval/expect";

interface SessionData {
  projectId?: unknown;
  sourceFiles?: unknown;
  session?: { id?: unknown; version?: unknown };
}

function request(task: string, sources: Array<{ path: string; content: string }>) {
  return JSON.stringify({
    engine: "react",
    persistSession: true,
    task,
    sources,
  });
}

export default defineEval({
  description: "Versioned multi-turn session persistence and independent session isolation",
  async test(t) {
    const first = await t.send(
      request("Remember the project isolation decision.", [
        {
          path: "decision.md",
          content: "The selected next boundary is operating-system container isolation.",
        },
      ]),
    );
    first.succeeded().label("First session turn created persistent state");
    const firstData = first.data as SessionData | undefined;
    t.check(firstData?.session?.version, equals(1)).label(
      "First successful turn committed session version one",
    );

    const second = await t.send(
      request("Continue the same project and restate its isolation decision.", []),
    );
    second.succeeded().label("Second turn resumed the stored session");
    const secondData = second.data as SessionData | undefined;
    t.check(secondData?.session?.version, equals(2)).label(
      "Second successful turn committed session version two",
    );
    t.check(secondData?.projectId, equals(firstData?.projectId)).label(
      "Both turns used the same isolated project workspace",
    );
    t.check(secondData?.sourceFiles, equals(["inputs/decision.md"])).label(
      "Second turn retained the prior project source",
    );
    t.check(second.message, pattern(/container isolation/i)).label(
      "Second turn remained grounded in the persisted project evidence",
    );

    const fresh = t.newSession();
    const isolated = await fresh.send(
      request("Start a separate project without prior evidence.", []),
    );
    isolated.succeeded().label("Independent session completed");
    const isolatedData = isolated.data as SessionData | undefined;
    t.check(isolatedData?.session?.version, equals(1)).label(
      "Independent session started at version one",
    );
    t.check(isolatedData?.sourceFiles, equals([])).label(
      "Independent session did not inherit prior project sources",
    );
  },
});
