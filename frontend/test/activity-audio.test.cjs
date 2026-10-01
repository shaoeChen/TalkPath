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
    this.paused = false;
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
  pause() { this.paused = true; }
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

function setup(type = "listening_practice") {
  const body = new Element();
  const nodes = new Map([["#practice-body", body]]);
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    document: {
      querySelector: (selector) => selector.startsWith("#practice-body ")
        ? body.querySelector(selector.slice("#practice-body ".length)) : nodes.get(selector) || null,
      querySelectorAll: () => [],
      createElement: (tag) => new Element(tag),
      addEventListener() {},
    },
    window: {},
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    fetch: (path, options) => new Promise((resolve) => {
      requests.push({ path, payload: JSON.parse(options.body), resolve });
    }),
  });
  const source = fs.readFileSync(require.resolve("../app.js"), "utf8");
  vm.runInContext(source.replace('  document.addEventListener("DOMContentLoaded", init);',
    '  globalThis.app = { state, renderActivity, advancePracticeQuestion, invalidateNavigation, requestActivityAudio };'), context);
  const app = context.app;
  const activity = {
    activity_id: "activity-1", type,
    items: ["First prompt", "Second prompt", "Third prompt"].map((prompt, index) => ({
      activity_id: `item-${index}`, prompt, choices: ["yes", "no"],
    })),
  };
  Object.assign(app.state, { sessionId: "session-1", activity, practiceQueue: [0, 1, 2] });
  app.renderActivity(activity, { audio_url: "data:audio/mpeg;base64,first" });
  return { app, activity, body, requests, timers };
}

async function respond(request, payload, status = 200) {
  assert.ok(request, "expected an API request");
  request.resolve({ ok: status === 200, status, text: async () => JSON.stringify(payload) });
  await new Promise(setImmediate);
}

async function answerCorrectly(harness) {
  harness.body.querySelector(".choice-button").click();
  harness.body.querySelector(".answer-button").click();
  await respond(harness.requests.at(-1), { evaluation: { passed: true } });
}

for (const type of ["listening_practice", "listening_quiz"]) {
  test(`${type}: manual next question replaces first audio with the current prompt`, async () => {
    const h = setup(type);
    const firstPlayer = h.body.querySelector("audio");
    assert.ok(firstPlayer);
    await answerCorrectly(h);
    assert.equal(h.requests.length, 1, "answer feedback must preserve current audio");
    h.body.querySelector(".practice-actions").children[0].click();
    assert.equal(h.app.state.currentQuestionIndex, 1);
    assert.equal(h.requests.at(-1).payload.text, "Second prompt");
    assert.equal(firstPlayer.paused, true);
    assert.equal(h.body.querySelector("audio"), null, "old audio must be removed while loading");
    await respond(h.requests.at(-1), { audio_url: "data:audio/mpeg;base64,second" });
    assert.equal(h.body.querySelector("audio").src, "data:audio/mpeg;base64,second");
    assert.equal(h.body.querySelector(".practice-prompt").textContent, "Second prompt");
  });
}

test("reading_aloud refreshes audio for the next spoken prompt", async () => {
  const h = setup("reading_aloud");
  const firstPlayer = h.body.querySelector("audio");
  h.app.advancePracticeQuestion(h.activity);
  assert.equal(h.app.state.currentQuestionIndex, 1);
  assert.equal(h.requests.at(-1).payload.text, "Second prompt");
  assert.equal(firstPlayer.paused, true);
  assert.equal(h.body.querySelector("audio"), null);
  await respond(h.requests.at(-1), { audio_url: "data:audio/mpeg;base64,second" });
  assert.equal(h.body.querySelector("audio").src, "data:audio/mpeg;base64,second");
  assert.equal(h.body.querySelector(".practice-prompt").textContent, "Second prompt");
});

test("automatic advance uses the queued question and ignores late previous audio", async () => {
  const h = setup();
  h.app.state.practiceQueue = [0, 2, 1];
  await answerCorrectly(h);
  [...h.timers.values()][0]();
  assert.equal(h.requests.at(-1).payload.text, "Third prompt");
  const delayed = h.requests.at(-1);
  h.app.advancePracticeQuestion(h.activity);
  await respond(h.requests.at(-1), { audio_url: "data:audio/mpeg;base64,second" });
  await respond(delayed, { audio_url: "data:audio/mpeg;base64,third" });
  assert.equal(h.body.querySelector("audio").src, "data:audio/mpeg;base64,second");
});

test("leaving practice ignores pending audio", async () => {
  const h = setup();
  h.app.advancePracticeQuestion(h.activity);
  h.app.invalidateNavigation();
  await respond(h.requests.at(-1), { audio_url: "data:audio/mpeg;base64,second" });
  assert.equal(h.body.querySelector("audio"), null);
});

test("leaving practice stops the playing activity audio", () => {
  const h = setup();
  const player = h.body.querySelector("audio");
  h.app.invalidateNavigation();
  assert.equal(player.paused, true);
});

test("text activities do not request audio on advance", () => {
  const h = setup("grammar_practice");
  h.app.advancePracticeQuestion(h.activity);
  assert.equal(h.requests.length, 0);
  assert.equal(h.body.querySelector("audio"), null);
  assert.equal(h.body.querySelector(".practice-prompt").textContent, "Second prompt");
});

test("failed next-question audio preserves the question and retries that question", async () => {
  const h = setup();
  h.app.advancePracticeQuestion(h.activity);
  await respond(h.requests.at(-1), { detail: "Audio unavailable" }, 503);
  assert.equal(h.body.querySelector("audio"), null);
  assert.equal(h.body.querySelector(".practice-prompt").textContent, "Second prompt");
  const fallback = h.body.querySelector(".audio-fallback");
  assert.ok(fallback);
  fallback.querySelector("button").click();
  assert.equal(h.requests.at(-1).payload.text, "Second prompt");
  await respond(h.requests.at(-1), { audio_url: "data:audio/mpeg;base64,second" });
  assert.equal(h.body.querySelector("audio").src, "data:audio/mpeg;base64,second");
});
