(() => {
  "use strict";

  const activityDefinitions = [
    { type: "vocabulary_practice", icon: "Aa", title: "Vocabulary practice", description: "Listen to the word, then say it out loud.", words: true },
    { type: "vocabulary_quiz", icon: "?", title: "Vocabulary quiz", description: "See how many words you know." },
    { type: "grammar_practice", icon: "✎✓", title: "Grammar explanation & practice", description: "Understand the grammar, then use it in a sentence." },
    { type: "grammar_quiz", icon: "?", title: "Grammar quiz", description: "Check what you know about the grammar." },
    { type: "listening_practice", icon: "♫", title: "Listening practice", description: "Listen, look, and find the meaning.", audio: true },
    { type: "listening_quiz", icon: "♪", title: "Listening quiz", description: "Listen carefully and choose an answer.", audio: true },
    { type: "reading_aloud", icon: "◌", title: "Reading / read aloud", description: "Read the lesson with confidence.", audio: true },
  ];

  const directStatusEvents = new Set([
    "extracting",
    "generating",
    "generating_activity",
    "ready",
    "ready_for_practice",
    "failed",
    "error",
  ]);
  const failureStatuses = new Set(["failed", "error"]);
  const PRACTICE_AUTO_ADVANCE_MS = 500;

  const state = {
    sessionId: null,
    session: null,
    lesson: null,
    activity: null,
    generatedActivities: {},
    currentActivityType: null,
    currentQuestionIndex: 0,
    practiceQueue: [],
    practiceAnswered: false,
    practicePassed: false,
    practiceResult: null,
    practiceFeedback: "",
    practiceWrongChoices: [],
    practiceTranscript: "",
    practiceCorrection: "",
    quizResults: [],
    practiceAutoAdvance: null,
    wordStatus: {},
    wordPractice: null,
    socket: null,
    socketClosedByUser: false,
    retryAction: null,
    retryOwner: null,
    flowGeneration: 0,
    navigationEpoch: 0,
    scopeOwner: null,
    importOwner: null,
    activityOwner: null,
    answerOwner: null,
    speechOwner: null,
    speechRecorder: null,
    uploadFile: null,
    confirmedScope: null,
    savedLessonOwner: null,
    importCheck: null,
    appendWarningAccepted: false,
    detailLesson: null,
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  let screenController = null;

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    const raw = await response.text();
    let payload = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch (_error) {
        payload = { detail: raw };
      }
    }
    if (!response.ok) {
      const detail = typeof payload.detail === "string" ? payload.detail : "Something went wrong.";
      throw new ApiError(detail, response.status);
    }
    return payload;
  }

  function operationId(prefix) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return `${prefix}-${window.crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function showScreen(name) {
    if (!screenController) throw new Error("screen controller is not initialized");
    return screenController.show(name);
  }

  function setText(selector, value) {
    const element = $(selector);
    if (element) element.textContent = value == null ? "" : String(value);
  }

  function showError(selector, message = "") {
    setText(selector, message);
  }

  function setBusy(button, busy, busyLabel = "Working…") {
    if (!button) return;
    if (busy) {
      button.dataset.originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = busyLabel;
    } else {
      button.disabled = false;
      if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
    }
  }

  function readableStatus(rawState) {
    const normalizedState = String(rawState || "").trim().toLowerCase();
    const statusKey = {
      generating_activity: "generating",
      ready_for_practice: "ready",
    }[normalizedState] || normalizedState;
    const statuses = {
      upload_image: "Waiting for your textbook page",
      confirm_course_scope: "Checking the lesson details",
      extracting: "Reading the words and sentences on your page",
      preview_draft: "Your lesson draft is ready to preview",
      save_lesson: "Saving your lesson",
      ask_generate_activity: "Your practice path is ready",
      generating: "Making your activity",
      ready: "Ready for practice",
      failed: "Something needs another try",
      error: "Something needs another try",
      retry: "Getting ready to try again",
    };
    return statuses[statusKey] || "TalkPath is working on your lesson";
  }

  function updateStatus(rawState) {
    setText("#status-label", readableStatus(rawState));
    const screen = $("#processing-screen");
    if (screen) screen.dataset.state = rawState || "";
  }

  function setRetry(label, action) {
    const button = $("#retry-connection");
    state.retryAction = action;
    if (!button) return;
    button.textContent = label;
    button.hidden = typeof action !== "function";
  }

  function appendAgentMessage(message) {
    if (!message) return;
    const output = $("#agent-message");
    if (!output) return;
    const current = output.textContent.trim();
    output.textContent = current && current !== "I am ready when you are!"
      ? `${current}\n${message}`
      : message;
  }

  function normalizedEventValue(value) {
    return String(value || "").trim().toLowerCase();
  }

  function eventMessage(event, payload) {
    const candidates = [
      event && event.message,
      event && event.error,
      payload && payload.message,
      payload && payload.error,
      payload && payload.detail,
    ];
    return candidates.find((candidate) => typeof candidate === "string" && candidate.trim())
      || "I could not finish this lesson yet.";
  }

  function handleProcessingFailure(message) {
    updateStatus("failed");
    showError("#processing-error", message || "I could not finish this lesson yet.");
    setRetry("Try the lesson again", () => retryFailedImport());
  }

  function handleAgentEvent(event) {
    const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
    const eventType = normalizedEventValue(event.agent_event_type || payload.type);
    if (eventType === "message_update") {
      const assistantMessageEvent = payload.assistantMessageEvent;
      const assistantDelta = assistantMessageEvent && typeof assistantMessageEvent === "object"
        ? assistantMessageEvent.delta
        : null;
      appendAgentMessage(assistantDelta || payload.delta || payload.message || payload.text || "TalkPath sent an update.");
    }
    const rawState = event.state || payload.state || (failureStatuses.has(eventType) ? eventType : "");
    if (rawState) updateStatus(rawState);
    if (failureStatuses.has(normalizedEventValue(rawState)) || failureStatuses.has(eventType)) {
      handleProcessingFailure(eventMessage(event, payload));
    }
  }

  function handleDirectEvent(event) {
    const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
    const eventType = normalizedEventValue(event && event.type);
    const rawState = event.state || event.status || (directStatusEvents.has(eventType) ? eventType : "");
    if (rawState) updateStatus(rawState);
    if (failureStatuses.has(normalizedEventValue(rawState)) || failureStatuses.has(eventType)) {
      handleProcessingFailure(eventMessage(event, payload));
    }
  }

  function handleSocketEvent(event) {
    if (!event || typeof event !== "object") return;
    if (event.type === "session") {
      updateFromSession(event.session);
      if (event.session && failureStatuses.has(normalizedEventValue(event.session.state))) {
        handleProcessingFailure(event.session.message);
      }
      return;
    }
    if (event.type === "agent_event") {
      handleAgentEvent(event);
      return;
    }
    handleDirectEvent(event);
  }

  function updateFromSession(session) {
    if (!session) return;
    state.session = session;
    state.sessionId = session.session_id || state.sessionId;
    updateStatus(session.state);
  }

  function isCurrentFlow(generation) {
    return state.flowGeneration === generation;
  }

  function ownsRequest(ownerKey, owner, generation, sessionId, navigationEpoch) {
    return isCurrentFlow(generation)
      && state.sessionId === sessionId
      && state.navigationEpoch === navigationEpoch
      && state[ownerKey] === owner;
  }

  function invalidatePracticeAttempt() {
    state.answerOwner = null;
    state.speechOwner = null;
    const recorder = state.speechRecorder;
    state.speechRecorder = null;
    if (recorder && recorder.state === "recording") recorder.stop();
  }

  function invalidateNavigation() {
    state.navigationEpoch += 1;
    state.scopeOwner = null;
    state.importOwner = null;
    state.activityOwner = null;
    state.savedLessonOwner = null;
    invalidatePracticeAttempt();
  }

  function detachWebSocket() {
    const socket = state.socket;
    if (!socket) return;
    state.socketClosedByUser = true;
    state.socket = null;
    socket.close();
  }

  function connectWebSocket(sessionId = state.sessionId) {
    if (!sessionId || state.sessionId !== sessionId || typeof window.WebSocket !== "function") return;
    detachWebSocket();
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new window.WebSocket(`${protocol}://${window.location.host}/ws/sessions/${sessionId}`);
    state.socket = socket;
    state.socketClosedByUser = false;
    socket.addEventListener("open", () => {
      if (state.socket !== socket) return;
      setRetry("Try again", null);
      appendAgentMessage("I am connected and watching your lesson.");
    });
    socket.addEventListener("message", (messageEvent) => {
      if (state.socket !== socket) return;
      let event;
      try {
        event = JSON.parse(messageEvent.data);
      } catch (_error) {
        appendAgentMessage("I received an update I could not read.");
        return;
      }
      handleSocketEvent(event);
    });
    socket.addEventListener("close", () => {
      if (state.socket !== socket || state.socketClosedByUser) return;
      state.socket = null;
      if (state.sessionId === sessionId) {
        appendAgentMessage("The connection took a little break. Your uploaded lesson is still safe.");
        setRetry("Reconnect", () => connectWebSocket(sessionId));
      }
    });
    socket.addEventListener("error", () => {
      if (state.socket !== socket) return;
      appendAgentMessage("I am having trouble reaching the lesson helper.");
      if (state.sessionId === sessionId) {
        setRetry("Reconnect", () => connectWebSocket(sessionId));
      }
    });
  }

  async function createSessionAndUpload(file, generation) {
    const session = await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation_id: operationId("session") }),
    });
    if (!isCurrentFlow(generation)) return null;
    const newSessionId = session.session_id;
    if (!newSessionId) throw new Error("The new lesson session is missing an ID.");
    updateFromSession(session);
    const formData = new FormData();
    formData.append("file", file, file.name);
    const image = await api(`/api/sessions/${newSessionId}/images`, {
      method: "POST",
      body: formData,
    });
    if (!isCurrentFlow(generation)) return null;
    if (state.sessionId !== newSessionId) {
      throw new Error("The lesson session changed while uploading the image.");
    }
    state.session = state.session || {};
    state.session.source_images = [image];
    return { sessionId: newSessionId, image };
  }

  function scopePayload(form) {
    const data = new FormData(form);
    const pages = String(data.get("pages") || "")
      .split(",")
      .map((page) => page.trim())
      .filter(Boolean);
    return {
      program: String(data.get("program") || ""),
      grade: String(data.get("grade") || ""),
      subject: String(data.get("subject") || ""),
      lesson: String(data.get("lesson") || ""),
      textbook: String(data.get("textbook") || "") || null,
      edition: String(data.get("edition") || "") || null,
      pages,
    };
  }

  async function retryFailedImport() {
    if (state.retryOwner !== null) return;
    const uploadFile = state.uploadFile;
    const confirmedScope = state.confirmedScope;
    const generation = ++state.flowGeneration;
    invalidateNavigation();
    const navigationEpoch = state.navigationEpoch;
    const retryOwner = Symbol("retry");
    state.retryOwner = retryOwner;
    detachWebSocket();
    showError("#processing-error", "");
    setRetry("Try again", null);
    try {
      if (!uploadFile || !confirmedScope) {
        resetForNewCourse();
        showScreen("new-course");
        showError("#upload-error", "Choose the textbook image again before retrying the lesson.");
        return;
      }

      showScreen("processing");
      updateStatus("retry");
      const created = await createSessionAndUpload(uploadFile, generation);
      if (!isCurrentFlow(generation) || state.retryOwner !== retryOwner || state.navigationEpoch !== navigationEpoch || !created) return;
      const { sessionId: newSessionId } = created;
      const session = await api(`/api/sessions/${newSessionId}/scope`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirmedScope),
      });
      if (!isCurrentFlow(generation) || state.retryOwner !== retryOwner || state.navigationEpoch !== navigationEpoch) return;
      if (!session || session.session_id !== newSessionId) {
        throw new Error("The lesson session changed while confirming its details.");
      }
      updateFromSession(session);
      if (!session.scope_confirmed) {
        throw new Error("Please confirm the lesson details before importing it.");
      }
      connectWebSocket(newSessionId);
      await runImport(newSessionId, generation, navigationEpoch);
    } catch (error) {
      if (!isCurrentFlow(generation) || state.retryOwner !== retryOwner || state.navigationEpoch !== navigationEpoch) return;
      showScreen("processing");
      updateStatus("FAILED");
      showError("#processing-error", error.message || "I could not retry that lesson yet.");
      setRetry("Try the lesson again", () => retryFailedImport());
    } finally {
      if (state.retryOwner === retryOwner) {
        state.retryOwner = null;
      }
    }
  }
  async function runImport(sessionId = state.sessionId, generation = state.flowGeneration, navigationEpoch = state.navigationEpoch) {
    if (!isCurrentFlow(generation) || !sessionId || state.sessionId !== sessionId || !state.session || !state.session.scope_confirmed) return;
    const importOwner = Symbol("import");
    state.importOwner = importOwner;
    showScreen("processing");
    showError("#processing-error", "");
    setRetry("Try again", null);
    updateStatus("EXTRACTING");
    appendAgentMessage("I am reading your lesson now.");
    try {
      const result = await api(`/api/sessions/${sessionId}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: operationId("import") }),
      });
      if (!ownsRequest("importOwner", importOwner, generation, sessionId, navigationEpoch)) return;
      if (!result.session || result.session.session_id !== sessionId) {
        throw new Error("The lesson session changed while importing the page.");
      }
      updateFromSession(result.session);
      state.lesson = result.lesson;
      renderLessonPreview(result.lesson);
      setImportNote(result);
      state.uploadFile = null;
      state.confirmedScope = null;
      const fileInput = $("#course-image");
      if (fileInput) fileInput.value = "";
      showScreen("preview");
    } catch (error) {
      if (!ownsRequest("importOwner", importOwner, generation, sessionId, navigationEpoch)) return;
      updateStatus("FAILED");
      showError("#processing-error", error.message || "I could not read that page yet.");
      setRetry("Try the lesson again", () => retryFailedImport());
    } finally {
      if (state.importOwner === importOwner) state.importOwner = null;
    }
  }
  function lessonScopeSummary(scope = {}) {
    return [scope.program, scope.grade, scope.subject, scope.lesson ? `Lesson ${scope.lesson}` : "", scope.textbook]
      .filter(Boolean)
      .join(" · ");
  }

  function renderLessonContext(lesson) {
    const title = lesson.title || "Your English lesson";
    const scopeSummary = lessonScopeSummary(lesson.scope || {});
    const sourceCount = Array.isArray(lesson.source_images) ? lesson.source_images.length : 0;
    setText("#lesson-scope-summary", scopeSummary);
    setText("#lesson-source-summary", `${sourceCount} source image${sourceCount === 1 ? "" : "s"}`);
    setText("#overview-lesson-title", title);
    setText("#overview-lesson-scope", scopeSummary);
  }

  const previewDeck = { items: [], index: 0 };

  function renderCardCounter() {
    const counter = $("#card-counter");
    if (!counter) return;
    const total = previewDeck.items.length;
    counter.textContent = total ? `${previewDeck.index + 1} / ${total}` : "0 / 0";
  }

  function renderCardAt(index) {
    const stage = $("#card-stage");
    if (!stage) return;
    const empty = $("#card-empty");
    const nav = $("#card-nav");
    const total = previewDeck.items.length;
    if (!total) {
      if (empty) empty.hidden = false;
      if (nav) nav.hidden = true;
      stage.replaceChildren();
      previewDeck.index = 0;
      renderCardCounter();
      return;
    }
    if (empty) empty.hidden = true;
    if (nav) nav.hidden = false;
    previewDeck.index = Math.max(0, Math.min(index, total - 1));
    stage.replaceChildren();
    stage.append(buildContentCard(previewDeck.items[previewDeck.index], previewDeck.index));
    const prev = $("#card-prev");
    const next = $("#card-next");
    if (prev) prev.disabled = previewDeck.index === 0;
    if (next) next.disabled = previewDeck.index === total - 1;
    renderCardCounter();
  }

  function buildContentCard(contentItem, index) {
    const type = String(contentItem.type || "note").toLowerCase();
    if (type === "vocabulary") return buildVocabularyCard(contentItem, index);
    if (type === "grammar") return buildGrammarCard(contentItem, index);
    return buildNoteCard(contentItem, index);
  }

  function buildVocabularyCard(contentItem, index) {
    const content = contentItem.content && typeof contentItem.content === "object"
      ? contentItem.content
      : {};
    const english = typeof content.english === "string" ? content.english : "";
    const chinese = typeof content.chinese === "string" ? content.chinese : "";
    const notes = typeof content.notes === "string" ? content.notes : "";
    const card = document.createElement("article");
    card.className = "flashcard";
    const inner = document.createElement("button");
    inner.type = "button";
    inner.className = "flashcard-inner";
    inner.setAttribute("aria-pressed", "false");
    inner.setAttribute("aria-label", english ? `Show the meaning of ${english}` : "Show the card meaning");
    inner.addEventListener("click", () => {
      const flipped = card.classList.toggle("is-flipped");
      inner.setAttribute("aria-pressed", String(flipped));
    });
    const front = document.createElement("span");
    front.className = "flashcard-face flashcard-front";
    const typeLabel = document.createElement("span");
    typeLabel.className = "flashcard-type";
    typeLabel.textContent = "Vocabulary";
    const word = document.createElement("strong");
    word.className = "flashcard-word";
    word.textContent = english || "Word";
    const hint = document.createElement("span");
    hint.className = "flashcard-hint";
    hint.textContent = "Tap to flip";
    front.append(typeLabel, word, hint);
    const back = document.createElement("span");
    back.className = "flashcard-face flashcard-back";
    const meaning = document.createElement("strong");
    meaning.className = "flashcard-meaning";
    meaning.textContent = chinese || "Meaning";
    back.append(meaning);
    if (notes) {
      const note = document.createElement("span");
      note.className = "flashcard-notes";
      note.textContent = notes;
      back.append(note);
    }
    inner.append(front, back);
    card.append(inner);
    return card;
  }

  function buildGrammarCard(contentItem, index) {
    const content = contentItem.content && typeof contentItem.content === "object"
      ? contentItem.content
      : {};
    const pattern = typeof content.pattern === "string" ? content.pattern : "";
    const explanation = typeof content.explanation === "string" ? content.explanation : "";
    const card = document.createElement("article");
    card.className = "grammar-card";
    const typeLabel = document.createElement("span");
    typeLabel.className = "flashcard-type";
    typeLabel.textContent = "Grammar";
    card.append(typeLabel);
    if (pattern) {
      const patternEl = document.createElement("h4");
      patternEl.className = "grammar-pattern";
      patternEl.textContent = pattern;
      card.append(patternEl);
    }
    if (explanation) {
      const explain = document.createElement("p");
      explain.className = "grammar-explanation";
      explain.textContent = explanation;
      card.append(explain);
    }
    const examples = Array.isArray(content.examples) ? content.examples : [];
    if (examples.length) {
      const list = document.createElement("ul");
      list.className = "grammar-examples";
      examples.forEach((example) => {
        const li = document.createElement("li");
        if (example && typeof example === "object") {
          if (typeof example.en === "string") {
            const en = document.createElement("span");
            en.className = "example-en";
            en.textContent = example.en;
            li.append(en);
          }
          if (typeof example.zh === "string") {
            const zh = document.createElement("span");
            zh.className = "example-zh";
            zh.textContent = example.zh;
            li.append(zh);
          }
        } else if (typeof example === "string") {
          const en = document.createElement("span");
          en.className = "example-en";
          en.textContent = example;
          li.append(en);
        }
        list.append(li);
      });
      card.append(list);
    }
    return card;
  }

  function buildNoteCard(contentItem, index) {
    const card = document.createElement("article");
    card.className = "note-card";
    const typeLabel = document.createElement("span");
    typeLabel.className = "flashcard-type";
    typeLabel.textContent = contentItem.type || "Lesson note";
    const body = document.createElement("p");
    body.className = "note-card-body";
    body.textContent = typeof contentItem.content === "string"
      ? contentItem.content
      : JSON.stringify(contentItem.content || {});
    card.append(typeLabel, body);
    return card;
  }

  function renderLessonPreview(lesson) {
    renderLessonContext(lesson);
    setText("#lesson-title", lesson.title || "Your English lesson");
    setText("#lesson-passage", lesson.passage || "TalkPath found a lesson without a passage.");
    const items = Array.isArray(lesson.content_items) ? lesson.content_items : [];
    previewDeck.items = items;
    previewDeck.index = 0;
    renderCardAt(0);
  }

  function renderActivityCards() {
    const list = $("#activity-list");
    list.replaceChildren();
    activityDefinitions.forEach((definition) => {
      const card = document.createElement("article");
      card.className = "activity-card";
      const icon = document.createElement("span");
      icon.className = "activity-icon";
      icon.textContent = definition.icon;
      const title = document.createElement("h3");
      title.textContent = definition.title;
      const description = document.createElement("p");
      description.textContent = definition.description;
      const button = document.createElement("button");
      button.className = "secondary-button card-button";
      button.type = "button";
      button.textContent = "Start";
      button.addEventListener("click", () => {
        if (definition.words) {
          openWordWall();
        } else {
          generateActivity(definition);
        }
      });
      card.append(icon, title, description, button);
      list.append(card);
    });
  }

  function openWordWall() {
    if (!state.lesson) {
      showError("#words-error", "Open a lesson before picking words.");
      return;
    }
    const items = vocabularyWordItems(state.lesson);
    setText("#words-lesson-scope", lessonScopeSummary(state.lesson.scope || {}));
    setText("#words-subtitle", items.length
      ? "Tap a card to listen and say the word."
      : "This lesson has no vocabulary words yet.");
    const search = $("#word-search");
    if (search) search.value = "";
    showError("#words-error", "");
    setText("#words-note", "");
    renderWordWall();
    showScreen("words");
  }

  function renderWordWall() {
    const grid = $("#word-grid");
    if (!grid) return;
    const items = vocabularyWordItems(state.lesson);
    const search = $("#word-search");
    const query = search ? search.value.trim().toLowerCase() : "";
    const matches = items.filter((item) => {
      const en = wordEnglish(item);
      const zh = wordChinese(item);
      return !query || en.toLowerCase().includes(query) || zh.toLowerCase().includes(query);
    });
    grid.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "word-empty";
      empty.textContent = "This lesson has no vocabulary words yet.";
      grid.append(empty);
      return;
    }
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "word-empty";
      empty.textContent = "No word matches that search.";
      grid.append(empty);
      return;
    }
    matches.forEach((item) => {
      const word = wordEnglish(item);
      if (!word) return;
      const card = document.createElement("article");
      card.className = "word-card";
      const speaker = document.createElement("button");
      speaker.className = "word-speaker";
      speaker.type = "button";
      speaker.setAttribute("aria-label", `Listen to ${word}`);
      speaker.textContent = "🔊";
      speaker.addEventListener("click", (event) => {
        event.stopPropagation();
        playPracticeWord(word, $("#words-note"));
      });
      const body = document.createElement("button");
      body.className = "word-card-body";
      body.type = "button";
      body.setAttribute("aria-label", `Practise ${word}`);
      const en = document.createElement("span");
      en.className = "word-en";
      en.textContent = word;
      const zh = document.createElement("span");
      zh.className = "word-zh";
      zh.textContent = wordChinese(item);
      body.append(en, zh);
      body.addEventListener("click", () => openWordPractice(item));
      const status = state.wordStatus[item.content_id] || "new";
      const badge = document.createElement("span");
      badge.className = `word-badge is-${status}`;
      badge.textContent = status === "done" ? "✓ practised" : status === "again" ? "again" : "new";
      card.append(speaker, body, badge);
      grid.append(card);
    });
  }

  function vocabularyWordItems(lesson) {
    const items = Array.isArray(lesson && lesson.content_items) ? lesson.content_items : [];
    return items.filter((item) => item && item.type === "vocabulary");
  }

  function wordEnglish(item) {
    const content = item && item.content && typeof item.content === "object" ? item.content : {};
    return String(content.english || content.word || "").trim();
  }

  function wordChinese(item) {
    const content = item && item.content && typeof item.content === "object" ? item.content : {};
    return String(content.chinese || content.meaning || "").trim();
  }

  function openWordPractice(item) {
    const word = wordEnglish(item);
    if (!word) {
      showError("#words-error", "This word is not ready yet.");
      return;
    }
    state.wordPractice = {
      contentId: item.content_id,
      en: word,
      zh: wordChinese(item),
    };
    state.practiceAnswered = false;
    state.practicePassed = false;
    state.practiceResult = null;
    state.practiceFeedback = "";
    state.practiceWrongChoices = [];
    state.practiceTranscript = "";
    clearTimeout(state.practiceAutoAdvance);
    state.practiceAutoAdvance = null;
    const body = $("#practice-body");
    body.replaceChildren();
    const question = document.createElement("article");
    question.className = "practice-question";
    const heading = document.createElement("h3");
    heading.className = "practice-word";
    heading.textContent = word;
    const meaning = document.createElement("p");
    meaning.className = "practice-zh";
    meaning.textContent = wordChinese(item);
    const controls = document.createElement("div");
    controls.className = "practice-speech-actions";
    const listen = document.createElement("button");
    listen.className = "secondary-button listen-button";
    listen.type = "button";
    listen.textContent = "Listen";
    listen.addEventListener("click", () => playPracticeWord(word, $("#words-note")));
    const record = document.createElement("button");
    record.className = "secondary-button speech-button";
    record.type = "button";
    record.textContent = "Record your voice";
    const speechFeedback = document.createElement("p");
    speechFeedback.className = "speech-feedback";
    speechFeedback.setAttribute("aria-live", "polite");
    record.addEventListener("click", () => {
      transcribeSpeaking(record, speechFeedback, (transcript) => {
        if (!transcript) return;
        submitWordAnswer(transcript, feedback, record);
      });
    });
    controls.append(listen, record, speechFeedback);
    const feedback = document.createElement("p");
    feedback.className = "answer-feedback";
    feedback.setAttribute("aria-live", "polite");
    const actions = document.createElement("div");
    actions.className = "practice-actions";
    question.append(heading, meaning, controls, actions, feedback);
    body.append(question);
    setText("#practice-title", "Say it out loud");
    setText("#practice-question-label", "");
    const dots = $("#practice-dots");
    if (dots) dots.replaceChildren();
    showScreen("practice");
  }

  async function submitWordAnswer(answer, feedback, button) {
    const practice = state.wordPractice;
    const sessionId = state.sessionId;
    if (!practice || !sessionId) return;
    const generation = state.flowGeneration;
    const navigationEpoch = state.navigationEpoch;
    const answerOwner = Symbol("word-answer");
    state.answerOwner = answerOwner;
    setBusy(button, true, "Checking...");
    try {
      const result = await api(`/api/sessions/${sessionId}/vocabulary/${practice.contentId}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: operationId("word-answer"),
          answer,
        }),
      });
      if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;
      const passed = Boolean(result && result.passed);
      state.wordStatus[practice.contentId] = passed ? "done" : "again";
      feedback.textContent = passed ? "Great job!" : "Try again.";
      feedback.classList.remove("is-passed", "is-try-again");
      feedback.classList.add(passed ? "is-passed" : "is-try-again");
      if (passed) {
        renderWordPracticeResult(practice);
      }
    } catch (error) {
      if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;
      feedback.textContent = error.message || "I could not check that yet.";
    } finally {
      if (ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) {
        setBusy(button, false);
      }
    }
  }

  function renderWordPracticeResult(practice) {
    const actions = document.querySelector("#practice-body .practice-actions");
    if (!actions) return;
    actions.replaceChildren();
    const back = document.createElement("button");
    back.className = "primary-button";
    back.type = "button";
    back.textContent = "Back to words";
    back.addEventListener("click", backToWordWall);
    actions.append(back);
  }

  function backToWordWall() {
    state.wordPractice = null;
    openWordWall();
  }

  function showAudioFallback(definition, errorMessage) {
    const body = $("#practice-body");
    if (!body) return;
    body.replaceChildren();
    const fallback = document.createElement("div");
    fallback.className = "audio-fallback";
    const title = document.createElement("h4");
    title.textContent = "Audio is taking a break";
    const message = document.createElement("p");
    message.textContent = errorMessage || "The audio helper is not ready yet.";
    const alternative = document.createElement("p");
    alternative.textContent = "Text alternative: read the lesson passage aloud, then tell a grown-up what you heard.";
    const retry = document.createElement("button");
    retry.className = "secondary-button";
    retry.type = "button";
    retry.textContent = "Retry audio activity";
    retry.addEventListener("click", () => generateActivity(definition));
    fallback.append(title, message, alternative, retry);
    body.append(fallback);
  }

  function isAudioProviderFallbackError(error) {
    const status = Number(error && error.status);
    if ([408, 503, 504].includes(status)) return true;
    if (Number.isInteger(status) && status > 0) return false;
    const message = String(error && error.message || "").toLowerCase();
    return /audio\s+provider.*(?:unavailable|not\s+configured)|(?:unavailable|not\s+configured).*audio\s+provider|provider\s+missing|timed?\s*out|timeout/.test(message);
  }

  function audioFallbackMessage(activity, audioResult, definition) {
    if (!definition.audio) return "";

    const sources = [];
    [audioResult, activity && activity.audio].forEach((source) => {
      if (source == null) return;
      sources.push(source);
      if (source && typeof source === "object" && source.audio != null) {
        sources.push(source.audio);
      }
    });
    const statusText = sources
      .flatMap((source) => {
        if (!source || typeof source !== "object") return [String(source || "")];
        return [source.status, source.audio_status, source.error, source.message];
      })
      .filter((value) => value != null)
      .join(" ")
      .toLowerCase();
    if (/(audio\s+)?unavailable|not\s+configured|provider\s+missing|disabled|timed?\s*out|timeout/.test(statusText)) {
      return "The audio provider is not configured or is currently unavailable.";
    }

    const hasAudioData = sources.some((source) => {
      if (typeof source === "string") return Boolean(source.trim());
      if (!source || typeof source !== "object") return false;
      return ["audio_bytes", "audio_data", "audio_base64", "audio_url", "url", "data", "src"]
        .some((field) => {
          const value = source[field];
          return typeof value === "string" ? Boolean(value.trim()) : Boolean(value);
        });
      });
    return hasAudioData ? "" : "Audio playback is not connected yet.";
  }

  function appendAudioPlayer(body, audioResult) {
    const source = audioResult && (audioResult.audio_data_url || audioResult.audio_url);
    if (!source) return;
    const player = document.createElement("audio");
    player.className = "activity-audio-player";
    player.controls = true;
    player.preload = "metadata";
    player.src = source;
    player.setAttribute("aria-label", "Listen to the activity prompt");
    body.append(player);
  }

  async function requestActivityAudio(activity, sessionId) {
    const prompt = activity && Array.isArray(activity.items) && activity.items[0]
      ? activity.items[0].prompt
      : activity && activity.instructions;
    if (!prompt) return null;
    try {
      return await api(`/api/sessions/${sessionId}/speech/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: operationId("activity-audio"),
          text: prompt,
        }),
      });
    } catch (error) {
      return { status: error.status || "unavailable", message: error.message || "Audio is unavailable." };
    }
  }
  async function playPracticeWord(word, feedback, onUnavailable) {
    const sessionId = state.sessionId;
    if (!sessionId || !word) return;
    try {
      const result = await api(`/api/sessions/${sessionId}/speech/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: operationId("practice-word-audio"),
          text: word,
        }),
      });
      const source = result && (result.audio_data_url || result.audio_url);
      if (!source) throw new Error("Audio playback is not connected yet.");
      const player = new Audio(source);
      player.play().catch(() => {
        feedback.textContent = "Tap Listen again to hear the word.";
      });
    } catch (error) {
      feedback.textContent = isAudioProviderFallbackError(error)
        ? "The audio provider is not configured or is currently unavailable."
        : (error.message || "The audio helper is unavailable.");
      if (typeof onUnavailable === "function") onUnavailable();
    }
  }
  function showAnswerResult(result) {
    if (state.currentActivityType === "vocabulary_quiz") {
      const total = state.quizResults.length;
      const wrong = state.quizResults.filter((entry) => !entry.passed);
      const passedCount = total - wrong.length;
      setText("#result-message", `${passedCount} of ${total} correct`);
      setText("#result-title", wrong.length ? "Quiz finished" : "Perfect quiz");
      setText(
        "#result-detail",
        wrong.length
          ? "Check the words below, then practise them."
          : "You spelled and picked every word correctly.",
      );
      const list = $("#review-list");
      if (list) {
        list.replaceChildren();
        if (!wrong.length) {
          const item = document.createElement("li");
          item.textContent = "Every word was correct. Nice work!";
          list.append(item);
        } else {
          wrong.forEach((entry) => {
            const item = document.createElement("li");
            item.textContent = `${entry.prompt}: ${entry.correction || ""}`;
            list.append(item);
          });
        }
      }
      const practiceButton = $("#quiz-practice-words");
      if (practiceButton) practiceButton.hidden = !wrong.length;
      showScreen("results");
      return;
    }
    const evaluation = result && result.evaluation ? result.evaluation : {};
    const passed = Boolean(evaluation.passed);
    setText("#result-message", passed ? "That was a strong try!" : "Keep going; every try helps.");
    setText("#result-title", passed ? "Nice work" : "Good effort");
    setText("#result-detail", evaluation.feedback || "Take a breath and try another question.");
    showScreen("results");
  }

  function shufflePracticeQueue(items) {
    const indexes = items.map((_, index) => index);
    for (let i = indexes.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [indexes[i], indexes[j]] = [indexes[j], indexes[i]];
    }
    return indexes;
  }

  function renderPracticeProgress(activity) {
    const total = state.practiceQueue.length;
    const current = Math.min(state.currentQuestionIndex, Math.max(total - 1, 0));
    setText("#practice-question-label", total ? `Question ${current + 1}` : "");
    const dots = $("#practice-dots");
    if (!dots) return;
    dots.replaceChildren();
    for (let i = 0; i < total; i += 1) {
      const dot = document.createElement("span");
      dot.className = "practice-dot";
      if (i < current) dot.classList.add("is-done");
      if (i === current) dot.classList.add("is-current");
      dot.setAttribute("aria-hidden", "true");
      dots.append(dot);
    }
  }

  function renderPracticeQuestion(activity) {
    const body = $("#practice-body");
    if (!body) return;
    const existing = body.querySelector(".practice-question");
    if (existing) existing.remove();
    const items = Array.isArray(activity && activity.items) ? activity.items : [];
    const queue = Array.isArray(state.practiceQueue) ? state.practiceQueue : [];
    if (!items.length || !queue.length) {
      const empty = document.createElement("p");
      empty.className = "practice-empty";
      empty.textContent = "This activity has no questions yet. Try another activity or try again.";
      body.append(empty);
      return;
    }
    const index = Math.max(0, Math.min(state.currentQuestionIndex, queue.length - 1));
    const item = items[queue[index]];
    const question = document.createElement("article");
    question.className = "practice-question";
    const isVocabularyPractice = activity.type === "vocabulary_practice";
    const isQuiz = activity.type === "vocabulary_quiz";
    const questionType = isQuiz ? (item.question_type || "") : "";
    const prompt = document.createElement("h4");
    prompt.className = "practice-prompt";
    if (isVocabularyPractice) {
      const word = document.createElement("h3");
      word.className = "practice-word";
      word.textContent = item.prompt || "";
      question.append(word);
    } else if (isQuiz && (questionType === "dictation" || questionType === "listen_to_meaning")) {
      prompt.textContent = questionType === "dictation"
        ? "Listen and write the word."
        : "Listen and choose the meaning.";
      question.append(prompt);
    } else {
      prompt.textContent = item.prompt || "Choose an answer.";
      question.append(prompt);
    }
    let readAnswer;
    let speechFeedback = null;
    if (isVocabularyPractice) {
      const controls = document.createElement("div");
      controls.className = "practice-speech-actions";
      const listen = document.createElement("button");
      listen.className = "secondary-button listen-button";
      listen.type = "button";
      listen.textContent = "Listen";
      listen.setAttribute("aria-label", "Hear the word");
      listen.addEventListener("click", () => playPracticeWord(item.prompt, feedback));
      const record = document.createElement("button");
      record.className = "secondary-button speech-button";
      record.type = "button";
      record.textContent = "Record your voice";
      const recordFeedback = document.createElement("p");
      recordFeedback.className = "speech-feedback";
      recordFeedback.setAttribute("aria-live", "polite");
      record.addEventListener("click", () => {
        transcribeSpeaking(record, recordFeedback, (transcript) => {
          if (!transcript) return;
          state.practiceTranscript = transcript;
          submitActivityAnswer(activity, item, () => state.practiceTranscript, feedback, record);
        });
      });
      controls.append(listen, record, recordFeedback);
      question.append(controls);
      readAnswer = () => state.practiceTranscript;
    } else {
      const needsAudio = questionType === "dictation" || questionType === "listen_to_meaning";
      if (needsAudio) {
        const listen = document.createElement("button");
        listen.className = "secondary-button listen-button";
        listen.type = "button";
        listen.textContent = "Listen";
        listen.setAttribute("aria-label", "Hear the word");
        speechFeedback = document.createElement("p");
        speechFeedback.className = "speech-feedback";
        speechFeedback.setAttribute("aria-live", "polite");
        if (questionType === "dictation") {
          const showWord = document.createElement("button");
          showWord.className = "text-button";
          showWord.type = "button";
          showWord.textContent = "Show the word";
          showWord.hidden = true;
          showWord.addEventListener("click", () => {
            prompt.textContent = item.prompt || "";
            showWord.hidden = true;
          });
          listen.addEventListener("click", () => {
            playPracticeWord(item.prompt, speechFeedback, () => { showWord.hidden = false; });
          });
          question.append(listen, showWord, speechFeedback);
        } else {
          listen.addEventListener("click", () => playPracticeWord(item.prompt, speechFeedback));
          question.append(listen, speechFeedback);
        }
      }
      if (Array.isArray(item.choices) && item.choices.length) {
        const choices = document.createElement("div");
        choices.className = "choice-list";
        let selectedChoice = "";
        item.choices.forEach((choice) => {
          const button = document.createElement("button");
          button.className = "choice-button";
          button.type = "button";
          button.setAttribute("aria-pressed", "false");
          const wasWrong = state.practiceWrongChoices.includes(choice);
          button.disabled = state.practiceAnswered || wasWrong;
          if (wasWrong) button.classList.add("is-wrong");
          button.textContent = choice;
          button.addEventListener("click", () => {
            choices.querySelectorAll(".choice-button").forEach((option) => {
              const selected = option === button;
              option.classList.toggle("selected", selected);
              option.setAttribute("aria-pressed", String(selected));
            });
            selectedChoice = choice;
          });
          choices.append(button);
        });
        readAnswer = () => selectedChoice;
        question.append(choices);
      } else {
        const answer = document.createElement("input");
        answer.className = "answer-input";
        answer.type = "text";
        answer.placeholder = "Type your answer";
        answer.disabled = state.practiceAnswered;
        answer.setAttribute("aria-label", `Answer for question ${index + 1}`);
        readAnswer = () => answer.value;
        question.append(answer);
      }
    }
    const feedback = document.createElement("p");
    feedback.className = "answer-feedback";
    feedback.setAttribute("aria-live", "polite");
    feedback.textContent = state.practiceFeedback || "";
    if (state.practiceFeedback) {
      feedback.classList.add(state.practicePassed ? "is-passed" : "is-try-again");
    }
    const correction = document.createElement("p");
    correction.className = "answer-correction";
    correction.setAttribute("aria-live", "polite");
    correction.textContent = state.practiceCorrection || "";
    if (state.practiceCorrection) correction.classList.add("is-try-again");
    const actions = document.createElement("div");
    actions.className = "practice-actions";
    if (state.practiceAnswered) {
      renderPracticeResultActions(activity, actions);
    } else if (!isVocabularyPractice) {
      const check = document.createElement("button");
      check.className = "primary-button answer-button";
      check.type = "button";
      check.textContent = "Check my answer";
      check.addEventListener("click", () => submitActivityAnswer(activity, item, readAnswer, feedback, check));
      actions.append(check);
    }
    question.append(actions);
    question.append(feedback, correction);
    body.append(question);
    if (questionType === "listen_to_meaning" && speechFeedback) {
      playPracticeWord(item.prompt, speechFeedback);
    }
  }

  function renderPracticeResultActions(activity, actions) {
    const isQuiz = activity.type === "vocabulary_quiz";
    if (isQuiz && !state.practicePassed) {
      const retry = document.createElement("button");
      retry.className = "secondary-button";
      retry.type = "button";
      retry.textContent = "Try again";
      retry.addEventListener("click", () => {
        state.practiceAnswered = false;
        state.practicePassed = false;
        state.practiceFeedback = "";
        state.practiceCorrection = "";
        renderPracticeQuestion(activity);
      });
      actions.append(retry);
    }
    const last = isLastPracticeQuestion(activity);
    const next = document.createElement("button");
    next.className = "primary-button";
    next.type = "button";
    next.textContent = last ? "Finish" : "Next question";
    next.addEventListener("click", () => {
      if (last) {
        showAnswerResult(state.practiceResult);
      } else {
        advancePracticeQuestion(activity);
      }
    });
    actions.append(next);
  }

  function isLastPracticeQuestion(activity) {
    return state.currentQuestionIndex >= state.practiceQueue.length - 1;
  }

  function advancePracticeQuestion(activity) {
    if (state.currentQuestionIndex < state.practiceQueue.length - 1) {
      clearTimeout(state.practiceAutoAdvance);
      state.practiceAutoAdvance = null;
      state.currentQuestionIndex += 1;
      state.practiceAnswered = false;
      state.practicePassed = false;
      state.practiceResult = null;
      state.practiceFeedback = "";
      state.practiceWrongChoices = [];
      state.practiceTranscript = "";
      state.practiceCorrection = "";
      renderPracticeProgress(activity);
      renderPracticeQuestion(activity);
    }
  }

  async function submitActivityAnswer(activity, item, readAnswer, feedback, button) {
    const value = String(readAnswer() || "").trim();
    if (!value) {
      feedback.textContent = "Choose or type an answer first.";
      return;
    }
    const generation = state.flowGeneration;
    const sessionId = state.sessionId;
    const navigationEpoch = state.navigationEpoch;
    const answerOwner = Symbol("answer");
    state.answerOwner = answerOwner;
    if (!sessionId) return;
    setBusy(button, true, "Checking...");
    try {
      const result = await api(
        `/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operation_id: operationId("answer"),
            item_id: item.activity_id,
            answer: value,
          }),
        },
      );
      if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;
      const evaluation = result && result.evaluation ? result.evaluation : {};
      const isQuiz = activity.type === "vocabulary_quiz";
      state.practiceResult = result;
      state.practicePassed = Boolean(evaluation.passed);
      state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed);
      state.practiceFeedback = evaluation.feedback
        || (state.practicePassed ? "That was a strong try!" : "Good try! Check the word again.");
      if (isQuiz) {
        state.quizResults[state.currentQuestionIndex] = {
          prompt: item.prompt || "",
          question_type: item.question_type || "",
          passed: state.practicePassed,
          correction: result.correction || "",
        };
      }
      if (!state.practicePassed && !state.practiceWrongChoices.includes(value)) {
        state.practiceWrongChoices.push(value);
      }
      if (state.practicePassed && state.practiceWrongChoices.length > 0 && activity.type === "vocabulary_practice") {
        state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex]);
      }
      feedback.textContent = state.practiceFeedback;
      renderPracticeQuestion(activity);
      if (state.practicePassed && !isQuiz) {
        const autoAdvanceActivity = activity;
        const autoAdvanceIndex = state.currentQuestionIndex;
        state.practiceAutoAdvance = setTimeout(() => {
          if (state.navigationEpoch !== navigationEpoch) return;
          if (!state.activity || state.activity.activity_id !== autoAdvanceActivity.activity_id) return;
          if (state.currentQuestionIndex !== autoAdvanceIndex) return;
          if (!state.practiceAnswered || !state.practicePassed) return;
          if (isLastPracticeQuestion(autoAdvanceActivity)) {
            showAnswerResult(state.practiceResult);
          } else {
            advancePracticeQuestion(autoAdvanceActivity);
          }
        }, PRACTICE_AUTO_ADVANCE_MS);
      }
    } catch (error) {
      if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;
      feedback.textContent = error.message || "I could not check that answer yet.";
    } finally {
      if (ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) {
        setBusy(button, false);
      }
    }
  }
  async function transcribeSpeaking(button, feedback, onTranscript = null) {
    if (button._talkpathRecorder && button._talkpathRecorder.state === "recording") {
      button._talkpathRecorder.stop();
      return;
    }
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function"
      || typeof window.MediaRecorder !== "function") {
      feedback.textContent = "Recording is not available here. Read the sentence aloud as a text alternative.";
      return;
    }
    const generation = state.flowGeneration;
    const sessionId = state.sessionId;
    const navigationEpoch = state.navigationEpoch;
    if (!sessionId) return;
    const speechOwner = Symbol("speech");
    state.speechOwner = speechOwner;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const recorder = new window.MediaRecorder(stream);
      const chunks = [];
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size) chunks.push(event.data);
      });
      recorder.addEventListener("stop", async () => {
        stream.getTracks().forEach((track) => track.stop());
        if (!ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)) return;
        button._talkpathRecorder = null;
        if (state.speechRecorder === recorder) state.speechRecorder = null;
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        const formData = new FormData();
        formData.append("audio", blob, "talkpath-speaking.webm");
        formData.append("operation_id", operationId("speech"));
        try {
          const result = await api(`/api/sessions/${sessionId}/speech/transcribe`, {
            method: "POST",
            body: formData,
          });
          if (!ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)) return;
          const transcript = result.transcript && result.transcript.text
            ? String(result.transcript.text)
            : "";
          feedback.textContent = transcript
            ? `I heard: ${transcript}`
            : "I received your recording, but could not read the words yet.";
          if (onTranscript) onTranscript(transcript);
        } catch (error) {
          if (!ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)) return;
          feedback.textContent = error.message || "The speech helper is unavailable. Use the text alternative instead.";
        } finally {
          if (ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)) {
            button.disabled = false;
            button.textContent = "Record again";
            state.speechOwner = null;
          }
        }
      });
      button.disabled = true;
      button.textContent = "Recording... click stop";
      button.disabled = false;
      button._talkpathRecorder = recorder;
      state.speechRecorder = recorder;
      recorder.start();
    } catch (_error) {
      if (stream) stream.getTracks().forEach((track) => track.stop());
      if (!ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)) return;
      feedback.textContent = "Your microphone could not be opened. Use the text alternative instead.";
      button.disabled = false;
      state.speechOwner = null;
    }
  }
  function renderActivity(activity, audioResult = null) {
    const body = $("#practice-body");
    if (!body) return;
    const definition = activityDefinitions.find((item) => item.type === activity.type) || {};
    setText("#practice-title", activity.title || definition.title || "Let's practise");
    body.replaceChildren();
    const audioMessage = audioFallbackMessage(activity, audioResult, definition);
    if (audioMessage) {
      showAudioFallback(definition, audioMessage);
    } else {
      appendAudioPlayer(body, audioResult);
    }
    const instructions = document.createElement("p");
    instructions.className = "activity-instructions";
    instructions.textContent = activity.instructions || "Take your time and choose your best answer.";
    body.append(instructions);
    renderPracticeProgress(activity);
    renderPracticeQuestion(activity);
  }

  async function generateActivity(definition) {
    const generation = state.flowGeneration;
    const sessionId = state.sessionId;
    if (!sessionId || !state.lesson) {
      showError("#practice-error", "Start a lesson before choosing an activity.");
      return;
    }
    invalidatePracticeAttempt();
    const navigationEpoch = state.navigationEpoch;
    const activityOwner = Symbol("activity");
    state.activityOwner = activityOwner;
    state.currentActivityType = definition.type;
    state.currentQuestionIndex = 0;
    state.practiceQueue = [];
    state.practiceAnswered = false;
    state.practicePassed = false;
    state.practiceResult = null;
    state.practiceFeedback = "";
    state.practiceWrongChoices = [];
    state.practiceTranscript = "";
    state.practiceCorrection = "";
    state.quizResults = [];
    state.wordPractice = null;
    clearTimeout(state.practiceAutoAdvance);
    state.practiceAutoAdvance = null;
    showError("#practice-error", "");
    updateStatus("GENERATING_ACTIVITY");
    showScreen("practice");
    setText("#practice-title", definition.title);
    setText("#practice-question-label", "");
    const dots = $("#practice-dots");
    if (dots) dots.replaceChildren();
    const body = $("#practice-body");
    if (body) {
      body.replaceChildren();
      const loading = document.createElement("p");
      loading.textContent = "Making your activity…";
      body.append(loading);
    }
    // A session keeps one generated activity per type: if the same type was
    // already generated for this lesson, resume it instead of calling the
    // generate endpoint again (the backend rejects same-type regeneration
    // with 409).
    const existingActivity = state.generatedActivities[definition.type];
    if (existingActivity && existingActivity.type === definition.type && existingActivity.lesson_id === state.lesson.lesson_id) {
      const resumeAudio = definition.audio
        ? await requestActivityAudio(existingActivity, sessionId)
        : null;
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      state.activity = existingActivity;
      const items = Array.isArray(existingActivity.items) ? existingActivity.items : [];
      state.practiceQueue = (existingActivity.type === "vocabulary_practice"
        || existingActivity.type === "vocabulary_quiz")
        ? shufflePracticeQueue(items)
        : items.map((_, index) => index);
      renderActivity(existingActivity, resumeAudio);
      return;
    }
    try {
      const result = await api(`/api/sessions/${sessionId}/activities/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: operationId("activity"), activity_type: definition.type }),
      });
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      if (!result.session || result.session.session_id !== sessionId) {
        throw new Error("The lesson session changed while generating the activity.");
      }
      const audioResult = definition.audio
        ? await requestActivityAudio(result.activity, sessionId)
        : null;
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      result.audio = audioResult;
      updateFromSession(result.session);
      state.activity = result.activity;
      state.generatedActivities[result.activity.type] = result.activity;
      const items = Array.isArray(result.activity.items) ? result.activity.items : [];
      state.practiceQueue = (result.activity.type === "vocabulary_practice"
        || result.activity.type === "vocabulary_quiz")
        ? shufflePracticeQueue(items)
        : items.map((_, index) => index);
      renderActivity(result.activity, result.audio);
    } catch (error) {
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      if (definition.audio && isAudioProviderFallbackError(error)) {
        showAudioFallback(definition, "The audio provider is not configured or is currently unavailable.");
      } else {
        showError("#practice-error", error.message || "I could not make that activity yet.");
        const body = $("#practice-body");
        if (body) body.replaceChildren();
      }
    }
  }
  function resetForNewCourse() {
    state.flowGeneration += 1;
    invalidateNavigation();
    detachWebSocket();
    state.sessionId = null;
    state.session = null;
    state.lesson = null;
    state.activity = null;
    state.generatedActivities = {};
    state.currentActivityType = null;
    state.socket = null;
    state.retryAction = null;
    state.retryOwner = null;
    state.scopeOwner = null;
    state.importOwner = null;
    state.activityOwner = null;
    state.answerOwner = null;
    state.speechOwner = null;
    state.speechRecorder = null;
    state.uploadFile = null;
    state.confirmedScope = null;
    state.savedLessonOwner = null;
    state.importCheck = null;
    state.appendWarningAccepted = false;
    state.detailLesson = null;
    hideScopeNotice();
    setImportNote(null);
    state.currentQuestionIndex = 0;
    state.practiceQueue = [];
    state.practiceAnswered = false;
    state.practicePassed = false;
    state.practiceResult = null;
    state.practiceFeedback = "";
    state.practiceWrongChoices = [];
    state.practiceTranscript = "";
    state.practiceCorrection = "";
    state.quizResults = [];
    state.wordStatus = {};
    state.wordPractice = null;
    clearTimeout(state.practiceAutoAdvance);
    state.practiceAutoAdvance = null;
    const courseForm = $("#course-form");
    if (courseForm) courseForm.reset();
    const scopeForm = $("#scope-form");
    if (scopeForm) scopeForm.reset();
    const courseButton = $("#course-form button[type=submit]");
    setBusy(courseButton, false);
    const scopeButton = $("#scope-form button[type=submit]");
    setBusy(scopeButton, false);
    const fileInput = $("#course-image");
    if (fileInput) fileInput.value = "";
    setText("#selected-file", "No image selected yet");
    showError("#upload-error", "");
    showError("#scope-error", "");
    showError("#processing-error", "");
    showError("#preview-error", "");
    showError("#practice-error", "");
    const practiceBody = $("#practice-body");
    if (practiceBody) practiceBody.replaceChildren();
    const practiceDots = $("#practice-dots");
    if (practiceDots) practiceDots.replaceChildren();
    setText("#practice-question-label", "");
  }

  async function loadSavedLessons() {
    const list = $("#lessons-list");
    if (!list) return;
    showError("#lessons-error", "");
    try {
      const lessons = await api("/api/lessons");
      renderSavedLessons(lessons);
    } catch (_error) {
      list.replaceChildren();
      const empty = $("#lessons-empty");
      if (empty) empty.hidden = true;
      showError("#lessons-error", "I could not load your saved lessons.");
    }
  }

  function renderSavedLessons(lessons) {
    const list = $("#lessons-list");
    if (!list) return;
    const empty = $("#lessons-empty");
    const saved = Array.isArray(lessons) ? lessons : [];
    list.replaceChildren();
    if (!saved.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    saved.forEach((lesson) => {
      const card = document.createElement("article");
      card.className = "lesson-card";
      const title = document.createElement("strong");
      title.className = "lesson-card-title";
      title.textContent = lesson.title || "Saved lesson";
      const scope = document.createElement("span");
      scope.className = "lesson-card-scope";
      scope.textContent = lessonScopeSummary(lesson.scope || {});
      const count = document.createElement("span");
      count.className = "lesson-card-count";
      const contentCount = Number(lesson.content_item_count) || 0;
      count.textContent = `${contentCount} content item${contentCount === 1 ? "" : "s"}`;
      const actions = document.createElement("div");
      actions.className = "lesson-card-actions";
      const viewButton = document.createElement("button");
      viewButton.type = "button";
      viewButton.className = "lesson-card-view";
      viewButton.textContent = "View lesson";
      viewButton.addEventListener("click", () => openLessonDetail(lesson));
      const continueLabel = document.createElement("button");
      continueLabel.type = "button";
      continueLabel.className = "lesson-card-continue";
      continueLabel.textContent = "Continue →";
      continueLabel.addEventListener("click", () => enterSavedLesson(lesson));
      actions.append(viewButton, continueLabel);
      card.append(title, scope, count, actions);
      list.append(card);
    });
  }

  async function enterSavedLesson(summary) {
    if (!summary || !summary.lesson_id) return;
    const generation = ++state.flowGeneration;
    invalidateNavigation();
    detachWebSocket();
    state.retryOwner = null;
    const navigationEpoch = state.navigationEpoch;
    const savedLessonOwner = Symbol("saved-lesson");
    state.savedLessonOwner = savedLessonOwner;
    showError("#lessons-error", "");
    showError("#detail-error", "");
    try {
      const session = await api("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: operationId("saved-lesson"),
          lesson_id: summary.lesson_id,
        }),
      });
      if (!isCurrentFlow(generation) || state.savedLessonOwner !== savedLessonOwner
        || state.navigationEpoch !== navigationEpoch) return;
      updateFromSession(session);
      const sessionId = session.session_id;
      if (!ownsRequest("savedLessonOwner", savedLessonOwner, generation, sessionId, navigationEpoch)) return;
      if (!sessionId || session.lesson_id !== summary.lesson_id) {
        throw new Error("I could not open that saved lesson.");
      }
      const lesson = await api(`/api/lessons/${summary.lesson_id}`);
      if (!ownsRequest("savedLessonOwner", savedLessonOwner, generation, sessionId, navigationEpoch)) return;
      state.lesson = lesson;
      state.activity = null;
      state.generatedActivities = {};
      state.currentActivityType = null;
      connectWebSocket(sessionId);
      renderLessonContext(state.lesson);
      renderActivityCards();
      showScreen("overview");
    } catch (error) {
      if (!ownsRequest("savedLessonOwner", savedLessonOwner, generation, state.sessionId, navigationEpoch)) return;
      showError("#lessons-error", error.message || "I could not open that saved lesson.");
      showError("#detail-error", error.message || "I could not open that saved lesson.");
    } finally {
      if (state.savedLessonOwner === savedLessonOwner) state.savedLessonOwner = null;
    }
  }

  async function openLessonDetail(summary) {
    if (!summary || !summary.lesson_id) return;
    invalidateNavigation();
    const navigationEpoch = state.navigationEpoch;
    state.detailLesson = summary;
    showError("#detail-error", "");
    showError("#lessons-error", "");
    setText("#detail-title", summary.title || "Lesson");
    setText("#detail-scope", lessonScopeSummary(summary.scope || {}));
    const batches = $("#detail-batches");
    if (batches) {
      batches.replaceChildren();
      const loading = document.createElement("p");
      loading.className = "detail-empty";
      loading.textContent = "Loading the lesson…";
      batches.append(loading);
    }
    showScreen("lesson-detail");
    try {
      const [lesson, importBatches] = await Promise.all([
        api(`/api/lessons/${summary.lesson_id}`),
        api(`/api/lessons/${summary.lesson_id}/batches`),
      ]);
      if (state.navigationEpoch !== navigationEpoch) return;
      renderLessonDetail(lesson, importBatches);
    } catch (_error) {
      if (state.navigationEpoch !== navigationEpoch) return;
      if (batches) batches.replaceChildren();
      showError("#detail-error", "I could not load this lesson.");
    }
  }

  function renderLessonDetail(lesson, batches) {
    setText("#detail-title", lesson.title || "Lesson");
    setText("#detail-scope", lessonScopeSummary(lesson.scope || {}));
    const container = $("#detail-batches");
    if (!container) return;
    container.replaceChildren();
    const items = Array.isArray(lesson.content_items) ? lesson.content_items : [];
    const itemsById = new Map(items.map((item) => [item.content_id, item]));
    const list = Array.isArray(batches) ? batches : [];
    if (!list.length) {
      const empty = document.createElement("p");
      empty.className = "detail-empty";
      empty.textContent = "This lesson has no content yet.";
      container.append(empty);
      return;
    }
    list.forEach((batch, index) => {
      const section = document.createElement("article");
      section.className = "detail-batch";
      const heading = document.createElement("h3");
      const pages = Array.isArray(batch.pages) ? batch.pages : [];
      heading.textContent = pages.length
        ? `${pages.length === 1 ? "Page" : "Pages"} ${pages.join(", ")}`
        : `Import ${index + 1}`;
      const meta = document.createElement("p");
      meta.className = "detail-batch-meta";
      const added = batch.imported_at ? new Date(batch.imported_at) : null;
      meta.textContent = added && !Number.isNaN(added.getTime())
        ? `Added ${added.toLocaleDateString()}`
        : "Added earlier";
      section.append(heading, meta);

      const imageIds = Array.isArray(batch.source_images) ? batch.source_images : [];
      if (imageIds.length) {
        const thumbs = document.createElement("div");
        thumbs.className = "detail-thumbs";
        imageIds.forEach((imageId) => {
          const url = `/api/lessons/${lesson.lesson_id}/images/${imageId}`;
          const link = document.createElement("a");
          link.className = "detail-thumb";
          link.href = url;
          link.target = "_blank";
          link.rel = "noopener";
          const image = document.createElement("img");
          image.src = url;
          image.alt = "Photo of the textbook page";
          image.loading = "lazy";
          link.append(image);
          thumbs.append(link);
        });
        section.append(thumbs);
      }

      const ids = Array.isArray(batch.content_ids) ? batch.content_ids : [];
      const entries = ids.map((id) => itemsById.get(id)).filter(Boolean);
      if (entries.length) {
        const itemList = document.createElement("ul");
        itemList.className = "detail-items";
        entries.forEach((item) => {
          const row = document.createElement("li");
          const type = document.createElement("span");
          type.className = "detail-item-type";
          type.textContent = item.type || "content";
          const text = document.createElement("span");
          text.textContent = contentItemSummary(item);
          row.append(type, text);
          itemList.append(row);
        });
        section.append(itemList);
      } else {
        const none = document.createElement("p");
        none.className = "detail-empty";
        const skipped = Number(batch.skipped_duplicates) || 0;
        none.textContent = skipped
          ? "Everything on these pages was already in the lesson."
          : "No content was found on these pages.";
        section.append(none);
      }
      container.append(section);
    });
  }

  function contentItemSummary(item) {
    const english = wordEnglish(item);
    if (english) {
      const chinese = wordChinese(item);
      return chinese ? `${english} — ${chinese}` : english;
    }
    const content = item ? item.content : "";
    if (typeof content === "string") return content;
    if (content && typeof content === "object") {
      const text = Object.values(content).filter((value) => typeof value === "string" && value.trim());
      if (text.length) return text.slice(0, 2).join(" — ");
    }
    return item && item.content_id ? item.content_id : "";
  }

  function scopeCheckIsCurrent(scopeOwner, generation, sessionId, navigationEpoch) {
    return ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch);
  }

  function appendWarning(check, scope) {
    if (!check || !check.exists) return null;
    const overlap = Array.isArray(check.overlapping_pages) ? check.overlapping_pages : [];
    if (overlap.length) {
      const noun = overlap.length === 1 ? "Page" : "Pages";
      const verb = overlap.length === 1 ? "was" : "were";
      return `${noun} ${overlap.join(", ")} ${verb} already added to this lesson. Adding ${overlap.length === 1 ? "it" : "them"} again may repeat some content.`;
    }
    const pages = scope && Array.isArray(scope.pages) ? scope.pages : [];
    if (!pages.length) {
      return "This lesson already exists. Without page numbers I cannot check whether these pages were added before.";
    }
    return null;
  }

  function showScopeNotice(message) {
    const notice = $("#scope-notice");
    if (!notice) return;
    setText("#scope-notice-text", message);
    notice.hidden = false;
  }

  function hideScopeNotice() {
    const notice = $("#scope-notice");
    if (notice) notice.hidden = true;
    state.appendWarningAccepted = false;
  }

  function setImportNote(result) {
    const note = $("#import-note");
    if (!note) return;
    const appended = Boolean(result && state.importCheck && state.importCheck.exists);
    if (!appended) {
      note.hidden = true;
      note.textContent = "";
      return;
    }
    const skipped = Number(result.skipped_duplicates) || 0;
    note.textContent = skipped
      ? `Added to your existing lesson. ${skipped} repeated item${skipped === 1 ? " was" : "s were"} skipped.`
      : "Added to your existing lesson.";
    note.hidden = false;
  }

  function wireActions() {
    $$('[data-action="home"]').forEach((button) => button.addEventListener("click", () => {
      resetForNewCourse();
      showScreen("home");
    }));
    $$('[data-action="new-course"]').forEach((button) => button.addEventListener("click", () => {
      resetForNewCourse();
      showScreen("new-course");
    }));
    $$('[data-action="lessons"]').forEach((button) => button.addEventListener("click", () => {
      invalidateNavigation();
      showScreen("lessons");
      loadSavedLessons();
    }));
    $$('[data-action="upload-step"]').forEach((button) => button.addEventListener("click", () => {
      invalidateNavigation();
      setBusy($("#scope-form button[type=submit]"), false);
      showScreen("new-course");
    }));
    $$('[data-action="preview"]').forEach((button) => button.addEventListener("click", () => {
      if (!state.lesson) return;
      invalidateNavigation();
      renderLessonPreview(state.lesson);
      showScreen("preview");
    }));
    $$('[data-action="progress"]').forEach((button) => button.addEventListener("click", () => {
      invalidateNavigation();
      showScreen("progress");
    }));
    $$('[data-action="overview"]').forEach((button) => button.addEventListener("click", () => {
      if (state.wordPractice) {
        state.wordPractice = null;
        openWordWall();
        return;
      }
      if (!state.lesson) return;
      invalidateNavigation();
      renderLessonContext(state.lesson);
      renderActivityCards();
      showScreen("overview");
    }));
    $("#detail-start").addEventListener("click", () => {
      if (state.detailLesson) enterSavedLesson(state.detailLesson);
    });
    $("#scope-notice-cancel").addEventListener("click", hideScopeNotice);
    $("#scope-notice-confirm").addEventListener("click", () => {
      state.appendWarningAccepted = true;
      const form = $("#scope-form");
      form.requestSubmit($("#scope-form button[type=submit]"));
    });
    $("#scope-form").addEventListener("input", hideScopeNotice);
    $("#retry-connection").addEventListener("click", () => {
      if (typeof state.retryAction === "function") state.retryAction();
    });
    $("#word-search").addEventListener("input", renderWordWall);
    $("#words-practice-all").addEventListener("click", () => {
      const definition = activityDefinitions.find((item) => item.type === "vocabulary_practice");
      if (definition) generateActivity(definition);
    });
    $("#quiz-practice-words").addEventListener("click", () => openWordWall());
    $("#card-prev").addEventListener("click", () => renderCardAt(previewDeck.index - 1));
    $("#card-next").addEventListener("click", () => renderCardAt(previewDeck.index + 1));
    $("#course-image").addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      setText("#selected-file", file ? file.name : "No image selected yet");
      showError("#upload-error", "");
    });
    $("#course-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.submitter;
      const file = $("#course-image").files && $("#course-image").files[0];
      if (!file) {
        showError("#upload-error", "Choose a textbook image first.");
        return;
      }
      const generation = ++state.flowGeneration;
      invalidateNavigation();
      state.retryOwner = null;
      detachWebSocket();
      state.uploadFile = file;
      state.confirmedScope = null;
      setBusy(button, true, "Uploading…");
      try {
        const created = await createSessionAndUpload(file, generation);
        if (!isCurrentFlow(generation)) return;
        if (!created) return;
        showScreen("scope");
      } catch (error) {
        if (!isCurrentFlow(generation)) return;
        showError("#upload-error", error.message || "I could not upload that image.");
      } finally {
        if (!isCurrentFlow(generation)) return;
        setBusy(button, false);
      }
    });
    $("#scope-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.submitter;
      const generation = state.flowGeneration;
      const sessionId = state.sessionId;
      const navigationEpoch = state.navigationEpoch;
      if (!sessionId) {
        showError("#scope-error", "Your lesson session is missing. Please upload the image again.");
        return;
      }
      const scopeOwner = Symbol("scope");
      state.scopeOwner = scopeOwner;
      const confirmedScope = scopePayload(event.currentTarget);
      const warningAccepted = state.appendWarningAccepted;
      state.appendWarningAccepted = false;
      setBusy(button, true, "Checking...");
      try {
        if (!warningAccepted) {
          const check = await api("/api/lessons/import-check", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(confirmedScope),
          });
          if (!scopeCheckIsCurrent(scopeOwner, generation, sessionId, navigationEpoch)) return;
          state.importCheck = check;
          const warning = appendWarning(check, confirmedScope);
          if (warning) {
            showScopeNotice(warning);
            return;
          }
        }
        hideScopeNotice();
        const session = await api(`/api/sessions/${sessionId}/scope`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(confirmedScope),
        });
        if (!ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)) return;
        if (!session || session.session_id !== sessionId) {
          throw new Error("The lesson session changed while confirming its details.");
        }
        if (!ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)) return;
        updateFromSession(session);
        if (!session.scope_confirmed) {
          showError("#scope-error", "Please confirm the lesson details before importing it.");
          return;
        }
        state.confirmedScope = confirmedScope;
        connectWebSocket(sessionId);
        if (!ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)) return;
        showScreen("processing");
        await runImport(sessionId, generation, navigationEpoch);
      } catch (error) {
        if (!ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)) return;
        showError("#scope-error", error.message || "Please check the lesson details and try again.");
      } finally {
        if (state.scopeOwner === scopeOwner
          && ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)) {
          setBusy(button, false);
          state.scopeOwner = null;
        }
      }
    });
  }

  function init() {
    const createScreenController = window.TalkPathScreenFlow?.createScreenController;
    if (typeof createScreenController !== "function") {
      throw new Error("TalkPath screen flow controller is unavailable");
    }
    screenController = createScreenController({
      screens: $$("[data-screen]"),
      scrollTo: options => window.scrollTo(options),
    });
    renderActivityCards();
    wireActions();
  }
  document.addEventListener("DOMContentLoaded", init);
})();
