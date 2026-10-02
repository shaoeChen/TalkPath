const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const { retryAllowed, completionMessage, createPageImportController, buildSubmission } = require("../lesson-page-import.js");

function job(overrides = {}) {
  return { job_id: "job-a", lesson_id: "lesson-a", revision: 1, completion_revision: 0,
    status: "processing", counts: { succeeded: 0, failed: 0, interrupted: 0 }, pages: [], ...overrides };
}

test("the module is also available on window", () => {
  const context = { window: {} };
  vm.runInNewContext(fs.readFileSync(require.resolve("../lesson-page-import.js"), "utf8"), context);
  assert.equal(typeof context.window.TalkPathPageImport.createPageImportController, "function");
});

test("only failed and interrupted pages permit retry", () => {
  for (const status of ["failed", "interrupted"]) assert.equal(retryAllowed({ status }), true);
  for (const status of ["queued", "running", "succeeded", "completed", undefined]) {
    assert.equal(retryAllowed({ status }), false);
  }
  assert.equal(retryAllowed(null), false);
});

test("completion combines failed and interrupted counts and handles singular and zero", () => {
  assert.equal(completionMessage(job({ counts: { succeeded: 4, failed: 1, interrupted: 0 } })), "Added 4 pages. 1 page needs retry.");
  assert.equal(completionMessage(job({ counts: { succeeded: 1, failed: 1, interrupted: 1 } })), "Added 1 page. 2 pages need retry.");
  assert.equal(completionMessage(job()), "Added 0 pages. 0 pages need retry.");
});

test("only strictly newer revisions update state even when stale completion arrives", () => {
  const updates = [];
  const completions = [];
  const controller = createPageImportController({ onUpdate: (value) => updates.push(value), onComplete: (value) => completions.push(value) });
  assert.equal(controller.merge(job({ revision: 5 })), true);
  assert.equal(controller.merge(job({ revision: 5, status: "completed", completion_revision: 5 })), false);
  assert.equal(controller.merge(job({ revision: 4, status: "completed", completion_revision: 4 })), false);
  assert.equal(updates.length, 1);
  assert.equal(completions.length, 0);
  assert.equal(controller.jobs()[0].status, "processing");
});

test("a processing snapshot never announces an older completion revision", () => {
  const completions = [];
  const controller = createPageImportController({ onComplete: (...args) => completions.push(args) });
  controller.snapshot([job({ revision: 8, completion_revision: 6 })]);
  assert.equal(completions.length, 0);
  assert.equal(controller.jobs().length, 1);
});

test("completion replay is announced once and persists its seen revision", () => {
  const persisted = new Map();
  const seenStore = { get: (id) => persisted.get(id), set: (id, revision) => persisted.set(id, revision) };
  const completions = [];
  const completed = job({ revision: 3, status: "completed", completion_revision: 3 });
  const controller = createPageImportController({ seenStore, onComplete: (...args) => completions.push(args) });
  controller.snapshot([completed]);
  controller.merge(completed);
  controller.merge({ ...completed, revision: 4 });
  assert.equal(completions.length, 1);
  assert.equal(completions[0][0].job_id, "job-a");
  assert.equal(completions[0][1], "Added 0 pages. 0 pages need retry.");
  assert.equal(persisted.get("job-a"), 3);
  const reloaded = createPageImportController({ seenStore, onComplete: (...args) => completions.push(args) });
  reloaded.snapshot([completed]);
  assert.equal(completions.length, 1);
});

test("a retry round announces its new completion and snapshots never regress jobs", () => {
  const completions = [];
  const controller = createPageImportController({ onComplete: (value) => completions.push(value) });
  controller.merge(job({ revision: 3, status: "completed", completion_revision: 3 }));
  controller.merge(job({ revision: 4, completion_revision: 3 }));
  controller.snapshot([job({ revision: 2 })]);
  assert.equal(controller.jobs()[0].revision, 4);
  controller.merge(job({ revision: 5, status: "completed", completion_revision: 5 }));
  assert.deepEqual(completions.map((value) => value.completion_revision), [3, 5]);
});

test("failed storage uses memory deduplication without preventing state updates", () => {
  const completions = [];
  const seenStore = { get() { throw new Error("blocked"); }, set() { throw new Error("quota"); } };
  const controller = createPageImportController({ seenStore, onComplete: (value) => completions.push(value) });
  controller.merge(job({ revision: 1, status: "completed", completion_revision: 1 }));
  controller.merge(job({ revision: 2, status: "completed", completion_revision: 1 }));
  controller.merge(job({ revision: 3, status: "completed", completion_revision: 3 }));
  assert.equal(completions.length, 2);
  assert.equal(controller.jobs()[0].revision, 3);
});

test("global state keeps jobs for different lessons and no completion at revision zero", () => {
  const completions = [];
  const controller = createPageImportController({ onComplete: (value) => completions.push(value) });
  controller.snapshot([job(), job({ job_id: "job-b", lesson_id: "other-lesson", status: "completed", completion_revision: 1 })]);
  controller.merge(job({ revision: 2, status: "completed" }));
  assert.equal(controller.jobs().length, 2);
  assert.deepEqual(completions.map((value) => value.lesson_id), ["other-lesson"]);
});

test("submission contains ordered page labels and actual uploaded files", async () => {
  const image = new Blob(["image-one"], { type: "image/png" });
  const image2 = new Blob(["image-two"], { type: "image/jpeg" });
  const form = buildSubmission({ lessonId: "lesson-a", operationId: "submit-1", allowOverlap: true,
    entries: [{ file: image, pageLabel: " 7 " }, { file: image2, pageLabel: "8-9" }] });
  assert.ok(form instanceof FormData);
  assert.equal(form.get("operation_id"), "submit-1");
  assert.equal(form.get("pages"), '["7","8-9"]');
  assert.equal(form.get("allow_overlap"), "true");
  const files = form.getAll("files");
  assert.equal(files.length, 2);
  assert.equal(await files[0].text(), "image-one");
  assert.equal(files[1].type, "image/jpeg");
  assert.equal(buildSubmission({ lessonId: "lesson-a", operationId: "op", entries: [{ file: image, pageLabel: "1" }] }).get("allow_overlap"), "false");
});

test("submission rejects missing entries or page labels before creating upload data", () => {
  const base = { lessonId: "lesson-a", operationId: "op" };
  assert.throws(() => buildSubmission({ ...base, entries: [] }), /page|image|entry/i);
  assert.throws(() => buildSubmission({ ...base, entries: [{ file: new Blob(["x"]), pageLabel: " " }] }), /page/i);
  assert.throws(() => buildSubmission({ ...base, entries: [{ pageLabel: "2" }] }), /file|image/i);
});
