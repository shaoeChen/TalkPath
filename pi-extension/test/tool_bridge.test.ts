import { describe, expect, it, vi } from "vitest";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import {
  MAX_PAYLOAD_BYTES,
  TOOL_NAMES,
  ToolValidationError,
  createToolDefinitions,
  defaultTalkPathBaseUrl,
  registerTalkPathTools,
  validateToolPayload,
  type FetchLike,
} from "../talkpath-tools.js";
import talkPathExtension from "../talkpath-tools.js";

const scope = {
  program: "國中",
  grade: "一年級",
  subject: "英文",
  lesson: "第一課",
};

const image = {
  image_id: "image-1",
  path: "uploads/image-1.jpg",
  mime_type: "image/jpeg",
  size_bytes: 1024,
  expires_at: new Date(Date.now() + 60_000).toISOString(),
};

const testContext = {} as ExtensionContext;

describe("TalkPath Pi tool bridge", () => {
  it("exports an official Pi extension factory", () => {
    const registered: string[] = [];
    talkPathExtension({
      registerTool(tool: ToolDefinition) {
        registered.push(tool.name);
      },
    } as unknown as ExtensionAPI);

    expect(registered).toEqual([...TOOL_NAMES]);
  });

  it("registers exactly the allowlisted learning tools", () => {
    const registered: string[] = [];
    const pi = {
      registerTool(tool: ToolDefinition) {
        registered.push(tool.name);
      },
    } as Pick<ExtensionAPI, "registerTool">;
    registerTalkPathTools(pi);

    expect(registered).toEqual([...TOOL_NAMES]);
    expect(registered).not.toContain("read");
    expect(registered).not.toContain("bash");
    expect(registered).not.toContain("write");
    expect(registered).not.toContain("ls");
  });

  it("reads the TalkPath loopback API base URL from the environment", () => {
    vi.stubEnv("TALKPATH_API_BASE_URL", "http://127.0.0.1:8001");
    expect(defaultTalkPathBaseUrl()).toBe("http://127.0.0.1:8001");
    vi.unstubAllEnvs();
  });

  it("validates image references, scope, operation id and payload size", () => {
    expect(() =>
      validateToolPayload("extract_lesson", {
        operation_id: "operation-1",
        session_id: "session-1",
        scope,
        images: [image],
      }),
    ).not.toThrow();

    expect(() => validateToolPayload("extract_lesson", { scope, images: [image] })).toThrow(
      ToolValidationError,
    );
    expect(() =>
      validateToolPayload("extract_lesson", {
        operation_id: "operation-1",
        session_id: "session-1",
        images: [image],
      }),
    ).toThrow(/scope/);
    expect(() =>
      validateToolPayload("extract_lesson", {
        operation_id: "operation-1",
        session_id: "session-1",
        scope,
        images: [{ ...image, path: "..\\outside.jpg" }],
      }),
    ).toThrow(/image reference/);
    expect(() =>
      validateToolPayload("extract_lesson", {
        operation_id: "operation-1",
        session_id: "session-1",
        scope,
        images: [{ ...image, path: "C:\\outside.jpg" }],
      }),
    ).not.toThrow();
    expect(() =>
      validateToolPayload("extract_lesson", {
        operation_id: "operation-1",
        session_id: "session-1",
        scope,
        images: [{ ...image, path: "C:outside.jpg" }],
      }),
    ).not.toThrow();
    expect(() =>
      validateToolPayload("extract_lesson", {
        operation_id: "operation-1",
        session_id: "session-1",
        scope,
        images: [{ ...image, path: "\\\\server\\share\\x.jpg" }],
      }),
    ).not.toThrow();
    expect(() =>
      validateToolPayload("transcribe_audio", {
        operation_id: "operation-1",
        audio_base64: "x".repeat(MAX_PAYLOAD_BYTES + 1),
      }),
    ).toThrow(/payload/);
  });

  it("rejects common credential field variants but keeps identity fields", () => {
    for (const field of [
      "apiKey",
      "access_token",
      "client_secret",
      "password",
      "privateKey",
      "credential_blob",
    ]) {
      expect(() => validateToolPayload("transcribe_audio", { operation_id: "op-1", [field]: "x" })).toThrow(
        /not allowed/,
      );
    }
    expect(() =>
      validateToolPayload("transcribe_audio", { operation_id: "op-1", image_id: "image-1" }),
    ).not.toThrow();
  });

  it("allows optional scope for save and generate bridge payloads", () => {
    expect(() =>
      validateToolPayload("save_lesson_draft", {
        operation_id: "save-1",
        session_id: "session-1",
        draft: {},
      }),
    ).not.toThrow();
    expect(() =>
      validateToolPayload("generate_activity", {
        operation_id: "activity-1",
        lesson: {},
        activity_type: "vocabulary_practice",
      }),
    ).not.toThrow();
  });

  it("maps an allowlisted tool to its loopback endpoint and returns a Pi result", async () => {
    const requests: Array<{ url: string; body: unknown }> = [];
    const fetchImpl: FetchLike = async (input, init) => {
      requests.push({ url: String(input), body: JSON.parse(String(init?.body)) });
      return new Response(JSON.stringify({ ok: true, lesson_id: "lesson-1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    };
    const tools = createToolDefinitions({
      baseUrl: "http://127.0.0.1:8123",
      fetchImpl,
    });

    const result = await tools.extract_lesson.execute(
      "call-1",
      { operation_id: "operation-1", session_id: "session-1", scope, images: [image] },
      undefined,
      undefined,
      testContext,
    );

    expect(requests[0]?.url).toBe("http://127.0.0.1:8123/internal/tools/extract_lesson");
    expect(result.content[0]).toEqual({ type: "text", text: expect.stringContaining("lesson-1") });
  });

  it("exposes no credential fields in the tool payload schema", () => {
    const tools = createToolDefinitions({ baseUrl: "http://127.0.0.1:8123" });
    const serialized = JSON.stringify(tools);

    expect(serialized).not.toMatch(/api[_-]?key|authorization|secret/i);
  });

  it("deduplicates concurrent write tools by operation id", async () => {
    let calls = 0;
    const tools = createToolDefinitions({
      baseUrl: "http://127.0.0.1:8123",
      fetchImpl: async () => {
        calls += 1;
        await Promise.resolve();
        return new Response(JSON.stringify({ saved: true }), { status: 200 });
      },
    });

    await Promise.all([
      tools.save_learning_result.execute("call-1", { operation_id: "save-1", result: "ok" }, undefined, undefined, testContext),
      tools.save_learning_result.execute("call-2", { operation_id: "save-1", result: "ok" }, undefined, undefined, testContext),
    ]);

    expect(calls).toBe(1);
  });

  it("does not cache a failed write result", async () => {
    let calls = 0;
    const tools = createToolDefinitions({
      baseUrl: "http://127.0.0.1:8123",
      fetchImpl: async () => {
        calls += 1;
        if (calls === 1) {
          return new Response(JSON.stringify({ detail: "temporary failure" }), { status: 503 });
        }
        return new Response(JSON.stringify({ saved: true }), { status: 200 });
      },
    });

    await tools.save_learning_result.execute(
      "call-1",
      { operation_id: "retry-1", result: "ok" },
      undefined,
      undefined,
      testContext,
    );
    await tools.save_learning_result.execute(
      "call-2",
      { operation_id: "retry-1", result: "ok" },
      undefined,
      undefined,
      testContext,
    );

    expect(calls).toBe(2);
  });
});
