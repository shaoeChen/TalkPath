const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const pageModule = require("../lesson-page-import.js");

class Element {
  constructor() { this.children = []; this.listeners = {}; this.dataset = {}; this.value = ""; this.hidden = false; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll() { return []; }
}

function setup({ respond } = {}) {
  const nodes = new Map();
  const html = fs.readFileSync(require.resolve("../index.html"), "utf8");
  for (const match of html.matchAll(/id="([^"]+)"/g)) nodes.set(`#${match[1]}`, new Element());
  const requests = [];
  const sockets = [];
  const documentListeners = {};
  let nextOperation = 0;
  let screen = "lesson-detail";
  const screens = { current: () => screen, show: (name) => { screen = name; } };
  class Socket { constructor(url) { this.url = url; sockets.push(this); } close() {} }
  const context = vm.createContext({
    document: { querySelector: (s) => nodes.get(s) || null, querySelectorAll: () => [], createElement: () => new Element(), addEventListener: (name, callback) => { documentListeners[name] = callback; } },
    window: { TalkPathPageImport: pageModule, TalkPathScreenFlow: { createScreenController: () => screens }, crypto: { randomUUID: () => `unique-${++nextOperation}` }, location: { protocol: "https:", host: "talkpath.test" }, addEventListener() {}, localStorage: { getItem() { return null; }, setItem() {} } },
    WebSocket: Socket,
    URL: { createObjectURL: () => "blob:photo", revokeObjectURL() {} },
    FormData, Blob, setTimeout, clearTimeout,
    fetch: async (path, options = {}) => {
      requests.push({ path, options });
      if (respond) {
        const response = await respond(path, options);
        if (response !== undefined) return response;
      }
      const payload = path.endsWith("/check") ? { overlapping_pages: [] }
        : options.method === "POST" ? { job_id: "job1", lesson_id: "original-id", revision: 1, completion_revision: 0, status: "processing", counts: { total: 1, succeeded: 0, failed: 0, interrupted: 0 }, pages: [] } : [];
      return { ok: true, status: options.method === "POST" ? 202 : 200, text: async () => JSON.stringify(payload) };
    },
  });
  const source = fs.readFileSync(require.resolve("../app.js"), "utf8");
  vm.runInContext(source.replace('  document.addEventListener("DOMContentLoaded", init);',
    '  globalThis.app = { state, openAddPages, addPageFiles, submitPageDraft, clearPageDraft, enterSavedLesson, showPageImportMessage, renderPageImportDetails, setController: (c) => { pageImportController = c; }, setScreen: (c) => { screenController = c; } };\n  document.addEventListener("DOMContentLoaded", init);'), context);
  context.app.setScreen(screens);
  const controller = pageModule.createPageImportController({});
  context.app.setController(controller);
  return { app: context.app, nodes, requests, controller, sockets, documentListeners, screen: () => screen };
}

function response(payload, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(payload) };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("Add pages uses original identity and sends only photos/page labels", async () => {
  const ui = setup();
  ui.app.state.detailLesson = { lesson_id: "original-id", title: "My lesson", scope: { program: "School", grade: "7", subject: "English", lesson: "1", textbook: "Book" } };
  ui.app.openAddPages();
  assert.equal(ui.screen(), "add-pages");
  const file = new Blob(["photo"], { type: "image/png" });
  ui.app.addPageFiles([file]);
  ui.app.state.pageDraft.entries[0].pageLabel = "12";
  await ui.app.submitPageDraft();
  const request = ui.requests.find((r) => r.path.endsWith("/page-imports"));
  assert.equal(request.path, "/api/lessons/original-id/page-imports");
  assert.equal(request.options.body.get("pages"), '["12"]');
  assert.equal(request.options.body.has("textbook"), false);
  assert.equal(ui.screen(), "lessons");
  assert.equal(ui.app.state.pageDraft, null);
});

test("leaving during an upload does not redirect the newer screen", async () => {
  const ui = setup();
  ui.app.state.detailLesson = { lesson_id: "original-id", scope: {} };
  ui.app.openAddPages();
  ui.app.addPageFiles([new Blob(["photo"], { type: "image/png" })]);
  ui.app.state.pageDraft.entries[0].pageLabel = "12";
  const uploading = ui.app.submitPageDraft();
  ui.app.state.navigationEpoch += 1;
  ui.app.clearPageDraft();
  await uploading;
  assert.notEqual(ui.screen(), "lessons");
});

test("DOMContentLoaded starts the independent import socket and restores jobs", async () => {
  const ui = setup();
  ui.documentListeners.DOMContentLoaded();
  await Promise.resolve();
  assert.equal(ui.sockets[0].url, "wss://talkpath.test/ws/lesson-page-imports");
  assert.ok(ui.requests.some((item) => item.path === "/api/lesson-page-imports"));
  ui.sockets[0].onmessage({ data: JSON.stringify({ type: "page_import_updated", job: { job_id: "job", lesson_id: "lesson", revision: 1, completion_revision: 0, status: "processing", counts: { total: 1, succeeded: 0 }, pages: [] } }) });
  assert.equal(ui.nodes.get("#page-import-status").children.length, 1);
});

test("completion refresh does not cancel a pending Start practice navigation", async () => {
  const session = deferred();
  const lesson = { lesson_id: "original-id", title: "Lesson", scope: {}, content_items: [] };
  const ui = setup({ respond: (path) => {
    if (path === "/api/sessions") return session.promise;
    if (path === "/api/lessons/original-id") return response(lesson);
    if (path.endsWith("/batches")) return response([]);
  } });
  ui.app.state.detailLesson = lesson;
  const entering = ui.app.enterSavedLesson(lesson);
  const epoch = ui.app.state.navigationEpoch;
  const owner = ui.app.state.savedLessonOwner;
  ui.app.showPageImportMessage({ lesson_id: lesson.lesson_id }, "Added 1 page.");
  assert.equal(ui.app.state.navigationEpoch, epoch);
  assert.equal(ui.app.state.savedLessonOwner, owner);
  session.resolve(response({ session_id: "session", lesson_id: lesson.lesson_id, state: "ready" }));
  await entering;
  assert.equal(ui.screen(), "overview");
});

test("Retry stays pending across row rebuilds and keeps its id after ambiguous failure", async () => {
  const first = deferred();
  let retries = 0;
  const ui = setup({ respond: (path) => {
    if (path.endsWith("/retry")) { retries += 1; return retries === 1 ? first.promise : response({}, 500); }
  } });
  ui.app.state.detailLesson = { lesson_id: "original-id", scope: {} };
  const job = { job_id: "job", lesson_id: "original-id", revision: 1, completion_revision: 1, status: "completed", pages: [{ page_id: "page", page_label: "1", status: "failed" }] };
  ui.controller.merge(job);
  ui.app.renderPageImportDetails();
  const button = () => ui.nodes.get("#detail-page-imports").children[0].children[2];
  const retrying = button().listeners.click();
  ui.app.renderPageImportDetails();
  assert.equal(button().disabled, true);
  await button().listeners.click();
  assert.equal(retries, 1);
  first.resolve(response({ detail: "Response lost" }, 500));
  await retrying;
  ui.app.renderPageImportDetails();
  assert.equal(button().disabled, false);
  await button().listeners.click();
  const attempts = ui.requests.filter((item) => item.path.endsWith("/retry"));
  assert.equal(attempts.length, 2);
  assert.equal(JSON.parse(attempts[0].options.body).operation_id, JSON.parse(attempts[1].options.body).operation_id);
});

test("overlap Cancel preserves photos and Add anyway accepts the same submission", async () => {
  const ui = setup({ respond: (path) => path.endsWith("/check") ? response({ overlapping_pages: ["12"] }) : undefined });
  ui.documentListeners.DOMContentLoaded();
  ui.app.state.detailLesson = { lesson_id: "original-id", scope: {} };
  ui.app.openAddPages();
  ui.app.addPageFiles([new Blob(["photo"], { type: "image/png" })]);
  ui.app.state.pageDraft.entries[0].pageLabel = "12";
  const draft = ui.app.state.pageDraft;
  await ui.app.submitPageDraft();
  const id = draft.operationId;
  assert.equal(ui.nodes.get("#add-pages-notice").hidden, false);
  assert.equal(ui.requests.filter(r => r.path.endsWith("/page-imports")).length, 0);
  ui.nodes.get("#add-pages-cancel-overlap").listeners.click();
  assert.equal(ui.nodes.get("#add-pages-notice").hidden, true);
  assert.equal(ui.app.state.pageDraft.entries.length, 1);
  draft.allowOverlap = true;
  await ui.app.submitPageDraft();
  const accepted = ui.requests.find(r => r.path.endsWith("/page-imports"));
  assert.equal(accepted.options.body.get("allow_overlap"), "true");
  assert.equal(accepted.options.body.get("operation_id"), id);
  assert.equal(ui.screen(), "lessons");
});
