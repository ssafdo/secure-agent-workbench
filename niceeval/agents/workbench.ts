import { randomUUID } from "node:crypto";

import {
  createSessionSlot,
  defineAgent,
  type EvidenceCoverage,
} from "niceeval/adapter";
import type { JsonValue, StreamEvent } from "niceeval";

interface ResearchRequest {
  task: string;
  sources: Array<{ path: string; content: string }>;
  engine?: "deterministic" | "retrieval" | "react" | "react-recovery" | "hosted";
  persistSession?: boolean;
}

interface ResearchAction {
  id: string;
  name: string;
  input: JsonValue;
  status: "succeeded" | "failed" | "denied";
}

interface ResearchResponse {
  status: "completed";
  projectId: string;
  report: {
    artifactPath: string;
    content: string;
    sourceFiles: string[];
    retrievalMode?: "lexical" | "hybrid" | "lexical-fallback";
    citations?: Array<{
      citation: string;
      path: string;
      startLine: number;
      endLine: number;
      text: string;
      score: number;
      instructionRisk: boolean;
      riskSignals: string[];
    }>;
  };
  actions: ResearchAction[];
  modelUsage?: {
    calls: number;
    inputTokens: number | null;
    outputTokens: number | null;
    costUSD: number | null;
  } | null;
  agentDiagnostics?: {
    contextCompactions: number;
    compactedMessages: number;
    truncatedMessages: number;
    reflections: number;
  };
  session?: {
    id: string;
    version: number;
    expiresAt: string;
  };
}

function evidenceCoverage(reportUsage: boolean): EvidenceCoverage {
  return {
    events: { status: "complete" },
    actions: { status: "complete" },
    messages: { status: "complete" },
    usage: reportUsage
      ? { status: "complete" }
      : {
          status: "unavailable",
          reason: "This experiment does not use metered model usage.",
        },
    status: { status: "complete" },
    data: { status: "complete" },
  };
}

function parseRequest(text: string): ResearchRequest {
  const value: unknown = JSON.parse(text);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Research eval input must be a JSON object.");
  }
  const request = value as Partial<ResearchRequest>;
  if (typeof request.task !== "string" || !Array.isArray(request.sources)) {
    throw new TypeError("Research eval input requires task and sources.");
  }
  if (
    request.engine !== undefined &&
    request.engine !== "deterministic" &&
    request.engine !== "retrieval" &&
    request.engine !== "react" &&
    request.engine !== "react-recovery" &&
    request.engine !== "hosted"
  ) {
    throw new TypeError(
      "Research eval engine must be deterministic, retrieval, react, react-recovery or hosted.",
    );
  }
  if (
    request.persistSession !== undefined &&
    typeof request.persistSession !== "boolean"
  ) {
    throw new TypeError("persistSession must be boolean when provided.");
  }
  return {
    task: request.task,
    sources: request.sources,
    ...(request.engine === undefined ? {} : { engine: request.engine }),
    ...(request.persistSession === undefined
      ? {}
      : { persistSession: request.persistSession }),
  } as ResearchRequest;
}

const sessionSlot = createSessionSlot<{ id: string; version: number }>(
  "secure-agent-workbench/session",
);

function parseResponse(value: unknown): ResearchResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Workbench returned a non-object response.");
  }
  const response = value as Partial<ResearchResponse>;
  if (
    response.status !== "completed" ||
    typeof response.projectId !== "string" ||
    typeof response.report !== "object" ||
    response.report === null ||
    !Array.isArray(response.actions)
  ) {
    throw new TypeError("Workbench response does not match the research protocol.");
  }
  return response as ResearchResponse;
}

function actionStatus(
  status: ResearchAction["status"],
): "completed" | "failed" | "rejected" {
  if (status === "succeeded") return "completed";
  if (status === "denied") return "rejected";
  return "failed";
}

export function workbenchAgent(options: {
  baseUrl: () => string;
  reportUsage: boolean;
}) {
  return defineAgent({
    name: "secure-agent-workbench",
    evidenceCoverage: evidenceCoverage(options.reportUsage),
    async send(input, ctx) {
      const request = parseRequest(input.text);
      const session = request.persistSession
        ? (ctx.session.get(sessionSlot) ?? { id: randomUUID(), version: 0 })
        : undefined;
      ctx.progress({ message: "Running the isolated research workflow" });
      const response = await fetch(`${options.baseUrl()}/v1/research`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          task: request.task,
          sources: request.sources,
          ...(request.engine === undefined ? {} : { engine: request.engine }),
          ...(session === undefined
            ? {}
            : { sessionId: session.id, expectedVersion: session.version }),
        }),
        signal: ctx.signal,
      });
      const raw: unknown = await response.json();
      if (!response.ok) {
        const error = raw as { error?: unknown; message?: unknown };
        const message =
          typeof error.message === "string"
            ? error.message
            : "The workbench rejected the research request.";
        return {
          status: "failed" as const,
          events: [
            { type: "error" as const, message },
            { type: "message" as const, role: "assistant" as const, text: message },
          ],
        };
      }

      const body = parseResponse(raw);
      if (session !== undefined) {
        if (
          body.session === undefined ||
          body.session.id !== session.id ||
          body.session.version !== session.version + 1
        ) {
          throw new TypeError("Workbench returned invalid session continuation data.");
        }
        ctx.session.set(sessionSlot, {
          id: body.session.id,
          version: body.session.version,
        });
      }
      const events: StreamEvent[] = [];
      for (const action of body.actions) {
        events.push({
          type: "operation.started",
          operationId: action.id,
          operation: { kind: "tool", name: action.name, input: action.input },
        });
        events.push({
          type: "operation.finished",
          operationId: action.id,
          kind: "tool",
          status: actionStatus(action.status),
        });
      }
      events.push({
        type: "message",
        role: "assistant",
        text: body.report.content,
      });
      return {
        status: "completed" as const,
        events,
        data: {
          ...body.report,
          projectId: body.projectId,
          ...(body.session === undefined ? {} : { session: body.session }),
          ...(body.agentDiagnostics === undefined
            ? {}
            : { diagnostics: body.agentDiagnostics }),
        },
        ...(options.reportUsage && body.modelUsage
          ? {
              usage: {
                requests: body.modelUsage.calls,
                ...(typeof body.modelUsage.inputTokens === "number"
                  ? { inputTokens: body.modelUsage.inputTokens }
                  : {}),
                ...(typeof body.modelUsage.outputTokens === "number"
                  ? { outputTokens: body.modelUsage.outputTokens }
                  : {}),
                ...(typeof body.modelUsage.costUSD === "number"
                  ? { costUSD: body.modelUsage.costUSD }
                  : {}),
              },
            }
          : {}),
      };
    },
  });
}
