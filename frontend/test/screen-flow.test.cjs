const assert = require("node:assert/strict");
const test = require("node:test");

const { createScreenController } = require("../screen-flow.js");

function createFakeScreen(name, hidden) {
  const focusCalls = [];
  const heading = {
    focus(options) {
      focusCalls.push(options);
    },
  };

  return {
    dataset: { screen: name },
    hidden,
    querySelector(selector) {
      return selector === "[data-screen-heading]" ? heading : null;
    },
    focusCalls,
  };
}

test('show("scope") returns scope, leaves exactly scope visible, and updates current', () => {
  const screens = [
    createFakeScreen("upload", false),
    createFakeScreen("scope", true),
    createFakeScreen("preview", true),
  ];
  const controller = createScreenController({ screens, scrollTo() {} });

  assert.equal(controller.show("scope"), "scope");
  assert.deepEqual(
    screens.filter((screen) => !screen.hidden).map((screen) => screen.dataset.screen),
    ["scope"],
  );
  assert.equal(controller.current(), "scope");
});

test('show("preview") scrolls to the top and focuses the destination heading', () => {
  const screens = [
    createFakeScreen("scope", false),
    createFakeScreen("preview", true),
  ];
  const scrollCalls = [];
  const controller = createScreenController({
    screens,
    scrollTo(options) {
      scrollCalls.push(options);
    },
  });

  controller.show("preview");

  assert.deepEqual(scrollCalls, [{ top: 0, left: 0, behavior: "auto" }]);
  assert.deepEqual(screens[1].focusCalls, [{ preventScroll: true }]);
});

test("an unknown screen throws and preserves visibility", () => {
  const screens = [
    createFakeScreen("upload", false),
    createFakeScreen("scope", true),
  ];
  const controller = createScreenController({ screens, scrollTo() {} });
  const visibilityBefore = screens.map((screen) => screen.hidden);

  assert.throws(() => controller.show("missing"), /unknown screen/);
  assert.deepEqual(
    screens.map((screen) => screen.hidden),
    visibilityBefore,
  );
});
