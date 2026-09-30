import type {
  AgentToolResult,
  ExtensionAPI,
  ExtensionFactory,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Type, type TSchema } from "typebox";

/**
 * Pi extension surface for TalkPath.
 *
 * This module intentionally imports no shell/filesystem helpers.  The only
 * side effect available to a Pi agent is an allowlisted POST to the Python
 * service over loopback.
 */

export const TOOL_NAMES = [
  "extract_lesson",
  "save_lesson_draft",
  "generate_activity",
  "evaluate_answer",
  "evaluate_pronunciation",
  "transcribe_audio",
  "synthesize_speech",
  "save_learning_result",
] as const;

export type ToolName = (typeof TOOL_NAMES)[number];

export const MAX_PAYLOAD_BYTES = 5 * 1024 * 1024;
const MAX_IMAGE_BYTES = 12 * 1024 * 1024;
const MAX_OPERATION_ID_LENGTH = 128;
const WRITE_TOOL_NAMES = new Set<ToolName>([
  "save_lesson_draft",
  "save_learning_result",
]);

export type ToolPayload = Record<string, unknown>;
export type PiToolResult = AgentToolResult<unknown>;

export class ToolValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ToolValidationError";
  }
}

export type FetchLike = (
  input: string | URL,
  init?: RequestInit,
) => Promise<Response>;

export type ToolBridgeOptions = {
  baseUrl: string;
  fetchImpl?: FetchLike;
};

function defaultFetch(input: string | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, init);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, label: string): ToolPayload {
  if (!isRecord(value)) {
    throw new ToolValidationError(`${label} must be an object`);
  }
  return value;
}

function requireNonBlankString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ToolValidationError(`${label} is required`);
  }
  return value.trim();
}

function rejectCredentialFields(value: unknown, path = "payload"): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectCredentialFields(item, `${path}[${index}]`));
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const [key, nested] of Object.entries(value)) {
    const normalizedKey = key.replace(/[^a-z0-9]/gi, "").toLowerCase();
    const isRequiredIdentityField = key === "image_id" || key === "operation_id";
    const isCredentialField =
      !isRequiredIdentityField &&
      /(credential|secret|token|password|privatekey|apikey|accesskey|authorization|key)/i.test(
        normalizedKey,
      );
    if (isCredentialField) {
      throw new ToolValidationError(`${path}.${key} is not allowed in a Pi tool payload`);
    }
    rejectCredentialFields(nested, `${path}.${key}`);
  }
}

function validateCourseScope(value: unknown): void {
  const scope = requireRecord(value, "course scope");
  for (const field of ["program", "grade", "subject", "lesson"]) {
    requireNonBlankString(scope[field], `course scope.${field}`);
  }
}

function validateImagePath(path: string): void {
  const normalized = path.replaceAll("\\", "/");
  if (
    normalized.includes("\0") ||
    normalized.split("/").some((part) => part === ".." || part === ".")
  ) {
    throw new ToolValidationError("unsafe image reference path component");
  }
}

function validateImageReference(value: unknown): void {
  const image = requireRecord(value, "image reference");
  requireNonBlankString(image.image_id, "image reference.image_id");
  const path = requireNonBlankString(image.path, "image reference.path");
  validateImagePath(path);
  const mimeType = requireNonBlankString(image.mime_type, "image reference.mime_type");
  if (!mimeType.startsWith("image/")) {
    throw new ToolValidationError("image reference.mime_type must be an image type");
  }
  if (
    typeof image.size_bytes !== "number" ||
    !Number.isInteger(image.size_bytes) ||
    image.size_bytes < 0 ||
    image.size_bytes > MAX_IMAGE_BYTES
  ) {
    throw new ToolValidationError("image reference.size_bytes is invalid");
  }
  const expiresAt = new Date(String(image.expires_at));
  if (!Number.isFinite(expiresAt.getTime()) || expiresAt.getTime() <= Date.now()) {
    throw new ToolValidationError("image reference is expired");
  }
}

function validateSerializedPayload(payload: ToolPayload): void {
  const serialized = JSON.stringify(payload);
  if (serialized === undefined) {
    throw new ToolValidationError("tool payload cannot be serialized");
  }
  const byteLength = new TextEncoder().encode(serialized).byteLength;
  if (byteLength > MAX_PAYLOAD_BYTES) {
    throw new ToolValidationError(`tool payload exceeds ${MAX_PAYLOAD_BYTES} bytes`);
  }
}

export function validateToolPayload(toolName: ToolName, value: unknown): ToolPayload {
  const payload = requireRecord(value, `${toolName} payload`);
  rejectCredentialFields(payload);
  validateSerializedPayload(payload);
  requireNonBlankString(payload.operation_id, "operation_id");
  if (
    typeof payload.operation_id !== "string" ||
    payload.operation_id.length > MAX_OPERATION_ID_LENGTH ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(payload.operation_id)
  ) {
    throw new ToolValidationError("operation_id contains unsafe characters or is too long");
  }

  if (toolName === "extract_lesson") {
    requireNonBlankString(payload.session_id, "session_id");
    validateCourseScope(payload.scope);
    if (!Array.isArray(payload.images) || payload.images.length === 0) {
      throw new ToolValidationError("images must contain at least one image reference");
    }
    payload.images.forEach(validateImageReference);
  } else if (["save_lesson_draft", "generate_activity"].includes(toolName)) {
    if (payload.scope !== undefined) {
      validateCourseScope(payload.scope);
    }
    if (toolName === "save_lesson_draft") {
      requireNonBlankString(payload.session_id, "session_id");
    }
  }
  return payload;
}

function parameterSchema(toolName: ToolName): TSchema {
  const properties: Record<string, TSchema> = {
    operation_id: Type.String({ maxLength: MAX_OPERATION_ID_LENGTH }),
  };
  if (["extract_lesson", "save_lesson_draft", "generate_activity"].includes(toolName)) {
    properties.scope = Type.Optional(Type.Object({}, { additionalProperties: true }));
  }
  if (["extract_lesson", "save_lesson_draft"].includes(toolName)) {
    properties.session_id = Type.String({ minLength: 1 });
  }
  if (toolName === "extract_lesson") {
    properties.images = Type.Optional(
      Type.Array(Type.Object({}, { additionalProperties: true })),
    );
  }
  return Type.Object(properties, { additionalProperties: true });
}

function humanLabel(toolName: ToolName): string {
  return toolName.replaceAll("_", " ");
}

function successfulResult(value: unknown): PiToolResult {
  return {
    content: [{ type: "text", text: JSON.stringify(value) ?? String(value) }],
    details: value,
  };
}

function failedResult(error: unknown): PiToolResult {
  const message = error instanceof Error ? error.message : String(error);
  return {
    content: [{ type: "text", text: message }],
    details: { error: message },
  };
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => [key, canonicalize(nested)]),
  );
}

function writeFingerprint(toolName: ToolName, payload: ToolPayload): string {
  return JSON.stringify({ tool: toolName, payload: canonicalize(payload) });
}

export function defaultTalkPathBaseUrl(): string {
  return globalThis.process?.env?.TALKPATH_API_BASE_URL || "http://127.0.0.1:8000";
}

function normalizeBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim().replace(/\/+$/, "");
  if (!/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$/i.test(trimmed)) {
    throw new ToolValidationError("Pi extension API must use a loopback HTTP base URL");
  }
  return trimmed;
}

async function callInternalTool(
  baseUrl: string,
  fetchImpl: FetchLike,
  toolName: ToolName,
  payload: ToolPayload,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetchImpl(`${baseUrl}/internal/tools/${toolName}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  const text = await response.text();
  let body: unknown = text;
  if (text.length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      // Keep the provider's text error readable in the Pi tool result.
    }
  }
  if (!response.ok) {
    const message = isRecord(body) && typeof body.detail === "string" ? body.detail : text;
    throw new Error(`TalkPath internal tool ${toolName} failed (${response.status}): ${message}`);
  }
  return body;
}

export function createToolDefinitions(options: ToolBridgeOptions): Record<ToolName, ToolDefinition> {
  const baseUrl = normalizeBaseUrl(options.baseUrl);
  const fetchImpl = options.fetchImpl ?? defaultFetch;
  const writeOperations = new Map<
    string,
    { fingerprint: string; promise: Promise<PiToolResult> }
  >();

  const definitions = {} as Record<ToolName, ToolDefinition>;
  for (const toolName of TOOL_NAMES) {
    definitions[toolName] = {
      name: toolName,
      label: humanLabel(toolName),
      description: `TalkPath learning operation: ${humanLabel(toolName)}.`,
      parameters: parameterSchema(toolName),
      execute: async (toolCallId, params, signal, _onUpdate, _ctx) => {
        void toolCallId;
        let payload: ToolPayload;
        try {
          payload = validateToolPayload(toolName, params);
        } catch (error) {
          return failedResult(error);
        }

        const perform = async (): Promise<PiToolResult> => {
          const result = await callInternalTool(baseUrl, fetchImpl, toolName, payload, signal);
          return successfulResult(result);
        };

        if (!WRITE_TOOL_NAMES.has(toolName)) {
          try {
            return await perform();
          } catch (error) {
            return failedResult(error);
          }
        }
        const operationId = String(payload.operation_id);
        const fingerprint = writeFingerprint(toolName, payload);
        const existing = writeOperations.get(operationId);
        if (existing) {
          if (existing.fingerprint !== fingerprint) {
            return failedResult(
              new ToolValidationError("operation_id reused for a different write request"),
            );
          }
          return existing.promise;
        }
        const operation = perform().catch((error): PiToolResult => {
          const current = writeOperations.get(operationId);
          if (current?.fingerprint === fingerprint) {
            writeOperations.delete(operationId);
          }
          return failedResult(error);
        });
        writeOperations.set(operationId, { fingerprint, promise: operation });
        return operation;
      },
    };
  }
  return definitions;
}

export function registerTalkPathTools(
  pi: Pick<ExtensionAPI, "registerTool">,
  options: ToolBridgeOptions = { baseUrl: defaultTalkPathBaseUrl() },
): void {
  const definitions = createToolDefinitions(options);
  for (const toolName of TOOL_NAMES) {
    pi.registerTool(definitions[toolName]);
  }
}

const talkPathExtension: ExtensionFactory = (pi) => {
  registerTalkPathTools(pi, { baseUrl: defaultTalkPathBaseUrl() });
};

export default talkPathExtension;
