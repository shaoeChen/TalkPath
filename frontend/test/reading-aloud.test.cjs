const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  append(...children) {
    children.forEach((child) => { child.parent = this; this.children.push(child); });
  }
  replaceChildren(...children) {
    this.children.forEach((child) => { child.parent = null; });
    this.children = [];
    this.append(...children);
  }
  remove() {
    this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }
  setAttribute() {}
  addEventListener(name, handler) { this.listeners[name] = handler; }
  click() { return this.listeners.click?.(); }
  querySelectorAll(selector) {
    return this.children.flatMap((child) => [
      ...(selector.startsWith(".")
        ? child.className.split(" ").includes(selector.slice(1))
        : child.tagName === selector) ? [child] : [],
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

class Recorder {
  constructor() { this.state = "inactive"; this.listeners = {}; this.mimeType = "audio/webm"; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  start() { this.state = "recording"; }
  stop() { this.state = "inactive"; this.listeners.stop(); }
}

function setup({ micAvailable = true } = {}) {
  const body = new Element();
  const nodes = new Map([["#practice-body", body]]);
  const requests = [];
  const context = vm.createContext({
    document: {
      querySelector: (selector) => selector.startsWith("#practice-body ")
        ? body.querySelector(selector.slice("#practice-body ".length)) : nodes.get(selector) || null,
      querySelectorAll: () => [],
      createElement: (tag) => new Element(tag),
      addEventListener() {},
    },
    window: { MediaRecorder: Recorder },
    navigator: micAvailable
      ? { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } }
      : {},
    Blob: class {},
    FormData: class { append() {} },
    setTimeout: () => 1,
    clearTimeout() {},
    fetch: (path, options) => new Promise((resolve) => {
      requests.push({ path, body: options.body, resolve });
    }),
  });
  const source = fs.readFileSync(require.resolve("../app.js"), "utf8");
  vm.runInContext(source.replace('  document.addEventListener("DOMContentLoaded", init);',
    '  globalThis.app = { state, renderActivity };'), context);
  const activity = {
    activity_id: "reading-1", lesson_id: "lesson-1", type: "reading_aloud",
    items: [{ activity_id: "item-1", prompt: "I like apples.", choices: ["wrong option"] }],
  };
  Object.assign(context.app.state, {
    sessionId: "session-1", activity, practiceQueue: [0], currentQuestionIndex: 0,
  });
  context.app.renderActivity(activity, { audio_url: "data:audio/mpeg;base64,example" });
  return { body, requests };
}

async function flush() { await new Promise(setImmediate); }

async function respond(request, payload) {
  request.resolve({ ok: true, status: 200, text: async () => JSON.stringify(payload) });
  await flush();
}

test("reading aloud shows spoken prompt and record control without typed answers", () => {
  const { body } = setup();
  assert.equal(body.querySelector(".practice-prompt").textContent, "I like apples.");
  assert.ok(body.querySelector("audio"));
  assert.ok(body.querySelector(".speech-button"));
  assert.equal(body.querySelector(".answer-input"), null);
  assert.equal(body.querySelector(".choice-button"), null);
  assert.equal(body.querySelector(".answer-button"), null);
});

test("reading aloud sends recognized words as the activity answer and allows another try", async () => {
  const { body, requests } = setup();
  body.querySelector(".speech-button").click();
  await flush();
  body.querySelector(".speech-button").click();
  await flush();
  assert.match(requests[0].path, /speech\/transcribe$/);
  await respond(requests[0], { transcript: { text: "I like bananas." } });
  assert.match(requests[1].path, /activities\/reading-1\/answer$/);
  assert.equal(JSON.parse(requests[1].body).answer, "I like bananas.");
  await respond(requests[1], { evaluation: { passed: false, feedback: "Try again." } });
  assert.ok(body.querySelector(".speech-button"));
  assert.equal(body.querySelector(".answer-input"), null);
});

test("reading aloud does not submit an empty transcript", async () => {
  const { body, requests } = setup();
  body.querySelector(".speech-button").click();
  await flush();
  body.querySelector(".speech-button").click();
  await flush();
  await respond(requests[0], { transcript: { text: "" } });
  assert.equal(requests.length, 1);
  assert.match(body.querySelector(".speech-feedback").textContent, /could not read/);
});

test("reading aloud explains when recording is unavailable without offering a text answer", () => {
  const { body, requests } = setup({ micAvailable: false });
  body.querySelector(".speech-button").click();
  assert.match(body.querySelector(".speech-feedback").textContent, /Recording is not available/);
  assert.doesNotMatch(body.querySelector(".speech-feedback").textContent, /text alternative/);
  assert.equal(body.querySelector(".answer-input"), null);
  assert.equal(requests.length, 0);
});
