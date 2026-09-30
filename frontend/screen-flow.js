(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.TalkPathScreenFlow = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function createScreenController({ screens, scrollTo }) {
    const screenList = Array.from(screens);

    if (screenList.length === 0) {
      throw new Error("screens must not be empty");
    }
    if (typeof scrollTo !== "function") {
      throw new TypeError("scrollTo must be a function");
    }

    const visibleScreen = screenList.find((screen) => !screen.hidden);
    let activeName = visibleScreen ? visibleScreen.dataset.screen : null;

    function show(name) {
      const destination = screenList.find((screen) => screen.dataset.screen === name);
      if (!destination) {
        throw new Error(`unknown screen: ${name}`);
      }

      for (const screen of screenList) {
        screen.hidden = screen !== destination;
      }
      activeName = name;
      scrollTo({ top: 0, left: 0, behavior: "auto" });

      const heading = destination.querySelector("[data-screen-heading]");
      if (heading && typeof heading.focus === "function") {
        heading.focus({ preventScroll: true });
      }

      return activeName;
    }

    return {
      show,
      current: () => activeName,
    };
  }

  return { createScreenController };
});
