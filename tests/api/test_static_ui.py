import re

from fastapi.testclient import TestClient

from talkpath.api.app import create_app


def _source_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index + len(start))
    return source[start_index:end_index]


def _assert_source_order(source: str, *markers: str) -> None:
    positions = [source.index(marker) for marker in markers]
    assert positions == sorted(positions), f"source markers are out of order: {markers}"


def test_child_ui_homepage_serves_core_flow_sections() -> None:
    client = TestClient(create_app(testing=True))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    for marker in (
        'id="home-screen"',
        'id="new-course-screen"',
        'id="scope-screen"',
        'id="processing-screen"',
        'id="preview-screen"',
        'id="overview-screen"',
        'id="practice-screen"',
        'id="results-screen"',
        'id="progress-screen"',
    ):
        assert marker in html
    assert html.count("data-screen-heading") >= 9
    assert re.search(
        r'<script src="/screen-flow\.js" defer></script>\s*'
        r'<script src="/app\.js" defer></script>',
        html,
    )


def test_child_ui_uses_focused_wizard_then_preview_and_practice_hub() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text

    assert html.count('class="lesson-stepper"') == 3
    assert html.count('aria-label="Lesson setup progress"') == 3
    assert html.count('aria-current="step"') == 3

    new_course = _source_between(html, '<section id="new-course-screen"', '<section id="scope-screen"')
    scope = _source_between(html, '<section id="scope-screen"', '<section id="processing-screen"')
    processing = _source_between(html, '<section id="processing-screen"', '<section id="preview-screen"')
    preview = _source_between(html, '<section id="preview-screen"', '<section id="overview-screen"')
    overview = _source_between(html, '<section id="overview-screen"', '<section id="practice-screen"')
    practice = _source_between(html, '<section id="practice-screen"', '<section id="results-screen"')
    home = _source_between(html, '<section id="home-screen"', '<section id="new-course-screen"')
    results = _source_between(html, '<section id="results-screen"', '<section id="progress-screen"')
    progress = _source_between(html, '<section id="progress-screen"', "</main>")

    for wizard_step in (new_course, scope, processing):
        assert 'class="lesson-stepper"' in wizard_step
        assert "data-screen-heading" in wizard_step

    for destination in (preview, practice):
        assert 'class="lesson-stepper"' not in destination

    new_course_stepper = _source_between(new_course, '<ol class="lesson-stepper"', "</ol>")
    scope_stepper = _source_between(scope, '<ol class="lesson-stepper"', "</ol>")
    processing_stepper = _source_between(processing, '<ol class="lesson-stepper"', "</ol>")
    for stepper in (new_course_stepper, scope_stepper, processing_stepper):
        assert stepper.count("<li") == 3

    assert '<li aria-current="step"><span>1</span><strong>Upload</strong></li>' in new_course_stepper
    assert '<li><span>2</span><strong>Details</strong></li>' in new_course_stepper
    assert '<li><span>3</span><strong>Create</strong></li>' in new_course_stepper
    assert 'class="is-complete"' not in new_course_stepper
    assert '<li class="is-complete"><span aria-hidden="true">✓</span><strong>Upload</strong></li>' in scope_stepper
    assert '<li aria-current="step"><span>2</span><strong>Details</strong></li>' in scope_stepper
    assert '<li><span>3</span><strong>Create</strong></li>' in scope_stepper
    assert scope_stepper.count('class="is-complete"') == 1
    assert '<li class="is-complete"><span aria-hidden="true">✓</span><strong>Upload</strong></li>' in processing_stepper
    assert '<li class="is-complete"><span aria-hidden="true">✓</span><strong>Details</strong></li>' in processing_stepper
    assert '<li aria-current="step"><span>3</span><strong>Create</strong></li>' in processing_stepper
    assert processing_stepper.count('class="is-complete"') == 2

    assert '<p class="eyebrow">Step 1 of 3</p>' in new_course
    assert '<h2 data-screen-heading tabindex="-1">Show me your lesson</h2>' in new_course
    assert '<p class="eyebrow">Step 2 of 3</p>' in scope
    assert '<h2 data-screen-heading tabindex="-1">Is this the right lesson?</h2>' in scope
    assert '<p class="eyebrow">Step 3 of 3</p>' in processing
    assert '<h2 data-screen-heading tabindex="-1">Making your lesson</h2>' in processing
    assert '<button class="secondary-button" type="button" data-action="upload-step">Back</button>' in scope
    assert 'data-action="new-course">Back</button>' not in scope
    extraction_progress = '<div class="extraction-progress" aria-hidden="true"><span></span></div>'
    assert re.search(
        r'<p id="status-label" aria-live="polite">[^<]*</p>\s*' + re.escape(extraction_progress),
        processing,
    )

    for marker in (
        "Extraction result",
        "What we found",
        "Choose a practice",
        'data-action="overview"',
    ):
        assert marker in preview
    assert '<h2 data-screen-heading tabindex="-1">Have a look before we practise</h2>' in preview
    assert '<h3 id="lesson-title">' in preview
    assert '<p id="lesson-passage" class="lesson-passage"></p>' in preview
    assert '<div id="lesson-cards" class="lesson-cards">' in preview
    assert '<div id="card-stage" class="card-stage"' in preview
    assert 'id="card-prev"' in preview
    assert 'id="card-next"' in preview
    assert 'id="card-counter"' in preview
    assert '<p id="preview-error" class="error-message" role="alert" aria-live="polite"></p>' in preview
    preview_actions = _source_between(preview, '<div class="form-actions">', "</div>")
    assert 'data-action="new-course">Start a new lesson</button>' in preview_actions
    assert re.search(
        r'<button id="start-practice" class="primary-button" type="button" data-action="overview">\s*'
        r'Choose a practice\s*<span aria-hidden="true">→</span>\s*</button>',
        preview_actions,
    )

    for marker in ("Pick a practice", 'data-action="preview"'):
        assert marker in overview
    assert '<h2 id="overview-title" data-screen-heading tabindex="-1">Pick a practice</h2>' in overview
    overview_actions = _source_between(overview, '<div class="overview-actions">', "</div>")
    assert re.search(
        r'<button class="text-button" type="button" data-action="preview">\s*← Lesson preview\s*</button>',
        overview_actions,
    )
    assert re.search(
        r'<button class="text-button" type="button" data-action="progress">\s*'
        r'See my progress\s*→\s*</button>',
        overview_actions,
    )

    for marker in ("One question at a time", "← Back to practice list", 'data-action="overview"'):
        assert marker in practice
    assert '<h2 id="practice-title" data-screen-heading tabindex="-1">Let\'s practise</h2>' in practice
    for marker in ('id="practice-dots"', 'id="practice-question-label"', 'id="practice-card"'):
        assert marker in practice

    assert '<h1 data-screen-heading tabindex="-1">Turn a page into a learning adventure.</h1>' in home
    assert '<h2 data-screen-heading tabindex="-1">Your results and review</h2>' in results
    assert '<h2 data-screen-heading tabindex="-1">My learning progress</h2>' in progress


def test_child_ui_wires_checkpoint_navigation_without_missing_processing_action() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )

    assert '[data-action=processing]' not in wire_actions
    assert '$("#start-practice").addEventListener' not in wire_actions
    for selector in ('[data-action="upload-step"]', '[data-action="preview"]'):
        assert f"$$('{selector}').forEach" in wire_actions

    upload_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"upload-step\"]')",
        "    $$('[data-action=\"preview\"]')",
    )
    preview_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"preview\"]')",
        "    $$('[data-action=\"progress\"]')",
    )
    assert 'addEventListener("click"' in upload_action
    assert 'showScreen("new-course")' in upload_action
    assert "resetForNewCourse()" not in upload_action
    assert 'addEventListener("click"' in preview_action
    assert "if (!state.lesson) return" in preview_action
    assert "renderLessonPreview(state.lesson)" in preview_action
    assert 'showScreen("preview")' in preview_action


def test_child_ui_routes_all_major_transitions_through_focused_screens() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    show_screen = _source_between(script, "  function showScreen(name) {", "  function setText(")
    wire_actions = _source_between(script, "  function wireActions() {", "  function init()")
    run_import = _source_between(
        script,
        "  async function runImport(",
        "  function renderLessonPreview(lesson) {",
    )
    init = _source_between(
        script,
        "  function init() {",
        '  document.addEventListener("DOMContentLoaded", init);',
    )

    assert "let screenController = null;" in script
    assert 'throw new Error("screen controller is not initialized")' in show_screen
    assert "return screenController.show(name);" in show_screen
    assert "smooth" not in script

    for selector in (
        '[data-action="home"]',
        '[data-action="new-course"]',
        '[data-action="upload-step"]',
        '[data-action="preview"]',
        '[data-action="overview"]',
    ):
        assert f"$$('{selector}').forEach" in wire_actions

    home_action = _source_between(wire_actions, "    $$('[data-action=\"home\"]')", "    $$('[data-action=\"new-course\"]')")
    new_course_action = _source_between(wire_actions, "    $$('[data-action=\"new-course\"]')", "    $$('[data-action=\"upload-step\"]')")
    upload_action = _source_between(wire_actions, "    $$('[data-action=\"upload-step\"]')", "    $$('[data-action=\"preview\"]')")
    preview_action = _source_between(wire_actions, "    $$('[data-action=\"preview\"]')", "    $$('[data-action=\"progress\"]')")
    overview_action = _source_between(wire_actions, "    $$('[data-action=\"overview\"]')", '    $("#retry-connection")')

    _assert_source_order(home_action, "resetForNewCourse()", 'showScreen("home")')
    _assert_source_order(new_course_action, "resetForNewCourse()", 'showScreen("new-course")')
    assert "resetForNewCourse()" not in upload_action
    assert 'showScreen("new-course")' in upload_action
    _assert_source_order(preview_action, "if (!state.lesson) return", "renderLessonPreview(state.lesson)", 'showScreen("preview")')
    _assert_source_order(overview_action, "if (!state.lesson) return", "renderActivityCards()", 'showScreen("overview")')

    _assert_source_order(
        run_import,
        "updateFromSession(result.session)",
        "state.lesson = result.lesson",
        "renderLessonPreview(result.lesson)",
        "state.uploadFile = null",
        "state.confirmedScope = null",
        'const fileInput = $("#course-image")',
        'fileInput.value = ""',
        'showScreen("preview")',
    )
    assert "renderActivityCards()" not in run_import
    assert 'showScreen("overview")' not in run_import

    assert "window.TalkPathScreenFlow?.createScreenController" in init
    assert 'throw new Error("TalkPath screen flow controller is unavailable")' in init
    _assert_source_order(
        init,
        "window.TalkPathScreenFlow?.createScreenController",
        'throw new Error("TalkPath screen flow controller is unavailable")',
        "screenController = createScreenController({",
        'screens: $$("[data-screen]")',
        "scrollTo: options => window.scrollTo(options)",
        "renderActivityCards()",
        "wireActions()",
    )


def test_child_ui_activity_generation_ignores_stale_async_continuations() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    request_audio = _source_between(
        script,
        "  async function requestActivityAudio(",
        "  function showAnswerResult(",
    )
    generate_activity = _source_between(
        script,
        "  async function generateActivity(",
        "  function resetForNewCourse()",
    )

    assert "async function requestActivityAudio(activity, sessionId)" in request_audio
    assert "`/api/sessions/${sessionId}/speech/synthesize`" in request_audio
    before_audio, after_audio = generate_activity.split("const audioResult =", 1)
    # Resume path reuses the already generated activity for the same type
    # instead of calling the generate endpoint again.
    resume_path = _source_between(
        before_audio,
        "const existingActivity = state.generatedActivities[definition.type]",
        "    try {",
    )
    _assert_source_order(
        resume_path,
        "const existingActivity = state.generatedActivities[definition.type]",
        "existingActivity && existingActivity.type === definition.type",
        "renderActivity(existingActivity, resumeAudio)",
    )
    # Fresh generation path still guards stale continuations before touching
    # session or activity state.
    fresh_generation = _source_between(
        generate_activity,
        "    try {",
        "    } catch (error) {",
    )
    _assert_source_order(
        fresh_generation,
        "`/api/sessions/${sessionId}/activities/generate`",
        'if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;',
        "if (!result.session || result.session.session_id !== sessionId)",
    )
    assert "updateFromSession(" not in before_audio
    fresh_generation_start = before_audio[before_audio.index("    try {") :]
    assert "updateFromSession(" not in fresh_generation_start
    assert "state.activity =" not in fresh_generation_start
    _assert_source_order(
        after_audio,
        "await requestActivityAudio(result.activity, sessionId)",
        'if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;',
        "result.audio = audioResult",
        "updateFromSession(result.session)",
        "state.activity = result.activity",
        "renderActivity(result.activity, result.audio)",
    )
    generate_catch = generate_activity[generate_activity.index("    } catch (error) {") :]
    _assert_source_order(
        generate_catch,
        'if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;',
        "isAudioProviderFallbackError(error)",
        'showError("#practice-error"',
    )


def test_child_ui_answer_submission_ignores_stale_async_continuations() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    submit_answer = _source_between(
        script,
        "  async function submitActivityAnswer(",
        "  async function transcribeSpeaking(",
    )

    answer_try = submit_answer[: submit_answer.index("    } catch (error) {")]
    _assert_source_order(
        answer_try,
        "const generation = state.flowGeneration",
        "const sessionId = state.sessionId",
        "setBusy(button, true",
        "`/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`",
        'if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;',
        "state.practiceResult = result",
        "state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed)",
        "state.practiceWrongChoices.push(value)",
        "renderPracticeQuestion(activity)",
        "state.practiceAutoAdvance = setTimeout",
    )
    answer_catch = submit_answer[submit_answer.index("    } catch (error) {") :]
    _assert_source_order(
        answer_catch,
        'if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;',
        "feedback.textContent = error.message",
        'if (ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch))',
        "setBusy(button, false)",
    )


def test_child_ui_practice_is_a_separate_screen_without_inline_activity_panel() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    script = client.get("/app.js").text

    assert html.count('id="activity-panel"') == 0
    assert 'id="activity-error"' not in html
    assert html.count('id="practice-card"') == 1
    for label in (
        "Vocabulary practice",
        "Vocabulary quiz",
        "Grammar explanation & practice",
        "Grammar quiz",
        "Listening practice",
        "Listening quiz",
        "Reading / read aloud",
    ):
        assert label in script
    assert "Speaking practice" not in script


def test_child_ui_client_contract_covers_upload_scope_and_import_gate() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text

    for marker in (
        "new FormData()",
        '"/api/sessions"',
        'images`,',
        'scope`,',
        'import`,',
        "scope_confirmed",
        "message_update",
        "assistantMessageEvent",
        "extracting",
        "generating",
        "ready",
        "failed",
    ):
        assert marker in script
    assert "innerHTML" not in script
    assert "textContent" in script

    scope_handler = _source_between(
        script,
        '  $("#scope-form").addEventListener("submit", async (event) => {',
        "  }\n\n  function init()",
    )
    assert re.search(r"if\s*\(\s*!session\.scope_confirmed\s*\)", scope_handler)
    _assert_source_order(scope_handler, "scope_confirmed", "runImport(sessionId, generation, navigationEpoch)")


def test_child_ui_websocket_contract_handles_status_agent_error_and_retry_events() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    websocket_section = _source_between(
        script,
        "  const directStatusEvents = new Set([",
        "  async function createSessionAndUpload(",
    )

    assert "directStatusEvents" in websocket_section
    assert "directStatusEvents.has(eventType)" in websocket_section
    for marker in ('"extracting"', '"generating"', '"ready"', '"failed"', '"error"'):
        assert marker in websocket_section
    assert 'event.type === "agent_event"' in websocket_section
    assert "message_update" in websocket_section
    assert "assistantMessageEvent" in websocket_section
    assert ".delta" in websocket_section
    assert "showError(\"#processing-error\"" in websocket_section
    assert "setRetry(\"Try the lesson again\"" in websocket_section
    assert "setRetry(\"Reconnect\"" in websocket_section
    assert "Your uploaded lesson is still safe." in websocket_section
    assert "if (state.socket !== socket) return;" in websocket_section
    assert "handleSocketEvent(event)" in websocket_section


def test_child_ui_failed_import_retry_recreates_session_and_replays_retained_input() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    retry_helper = _source_between(
        script,
        "  async function retryFailedImport() {",
        "  async function runImport(",
    )
    reset_handler = _source_between(
        script,
        "  function resetForNewCourse() {",
        "  function wireActions()",
    )
    course_submit = _source_between(
        script,
        '    $("#course-form").addEventListener("submit", async (event) => {',
        '    $("#scope-form").addEventListener("submit", async (event) => {',
    )
    scope_submit = _source_between(
        script,
        '    $("#scope-form").addEventListener("submit", async (event) => {',
        "  }\n\n  function init()",
    )
    create_upload = _source_between(
        script,
        "  async function createSessionAndUpload(",
        "  function scopePayload(form) {",
    )
    detach_socket = _source_between(
        script,
        "  function detachWebSocket() {",
        "  function connectWebSocket(",
    )
    connect_socket = _source_between(
        script,
        "  function connectWebSocket(",
        "  async function createSessionAndUpload(",
    )

    assert "flowGeneration: 0" in script
    assert "retryOwner: null" in script
    assert "uploadFile: null" in script
    assert "confirmedScope: null" in script
    assert re.search(
        r"function resetForNewCourse\(\)\s*\{\s*state\.flowGeneration \+= 1;",
        reset_handler,
    )
    _assert_source_order(
        reset_handler,
        "state.flowGeneration += 1",
        "detachWebSocket()",
        "state.retryOwner = null",
    )

    _assert_source_order(
        course_submit,
        "const generation = ++state.flowGeneration",
        "state.retryOwner = null",
        "state.uploadFile = file",
        "createSessionAndUpload(file, generation)",
    )
    assert course_submit.count("if (!isCurrentFlow(generation))") >= 2

    assert scope_submit.count("scopePayload(event.currentTarget)") == 1
    _assert_source_order(
        scope_submit,
        "const generation = state.flowGeneration",
        "const sessionId = state.sessionId",
        "const navigationEpoch = state.navigationEpoch",
        "const confirmedScope = scopePayload(event.currentTarget)",
        "/scope`,",
        'ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)',
        "if (!session || session.session_id !== sessionId)",
        "updateFromSession(session)",
        "if (!session.scope_confirmed)",
        "state.confirmedScope = confirmedScope",
        "connectWebSocket(sessionId)",
        "runImport(sessionId, generation, navigationEpoch)",
    )
    assert 'ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)' in scope_submit.split("catch (error)", 1)[1]

    _assert_source_order(
        detach_socket,
        "const socket = state.socket",
        "state.socketClosedByUser = true",
        "state.socket = null",
        "socket.close()",
    )
    assert "function connectWebSocket(sessionId = state.sessionId)" in connect_socket
    assert "state.sessionId !== sessionId" in connect_socket
    assert "/ws/sessions/${sessionId}" in connect_socket
    assert connect_socket.count("if (state.socket !== socket) return;") >= 2

    assert "async function createSessionAndUpload(file, generation)" in create_upload
    _assert_source_order(
        create_upload,
        'const session = await api("/api/sessions"',
        "if (!isCurrentFlow(generation)) return null",
        "const newSessionId = session.session_id",
        "updateFromSession(session)",
        "`/api/sessions/${newSessionId}/images`",
    )
    after_image = create_upload[create_upload.index("const image = await api") :]
    _assert_source_order(
        after_image,
        "if (!isCurrentFlow(generation)) return null",
        "if (state.sessionId !== newSessionId)",
        "state.session = state.session || {}",
    )
    assert "return { sessionId: newSessionId, image }" in create_upload

    _assert_source_order(
        retry_helper,
        "if (state.retryOwner !== null) return",
        "const uploadFile = state.uploadFile",
        "const confirmedScope = state.confirmedScope",
        "const generation = ++state.flowGeneration",
        "invalidateNavigation()",
        "const navigationEpoch = state.navigationEpoch",
        'const retryOwner = Symbol("retry")',
        "state.retryOwner = retryOwner",
        "detachWebSocket()",
        "createSessionAndUpload(uploadFile, generation)",
        "state.navigationEpoch !== navigationEpoch || !created",
        "sessionId: newSessionId",
        "`/api/sessions/${newSessionId}/scope`",
        "state.navigationEpoch !== navigationEpoch) return",
        "if (!session || session.session_id !== newSessionId)",
        "updateFromSession(session)",
        "if (!session.scope_confirmed)",
        "connectWebSocket(newSessionId)",
        "runImport(newSessionId, generation, navigationEpoch)",
    )
    assert "state.confirmedScope =" not in retry_helper
    retry_catch = retry_helper[retry_helper.index("    } catch (error) {") :]
    _assert_source_order(
        retry_catch,
        "state.navigationEpoch !== navigationEpoch) return",
        'showScreen("processing")',
        'updateStatus("FAILED")',
        'showError("#processing-error"',
        'setRetry("Try the lesson again", () => retryFailedImport())',
        "if (state.retryOwner === retryOwner)",
        "state.retryOwner = null",
    )

    processing_failure = _source_between(
        script,
        "  function handleProcessingFailure(message) {",
        "  function handleAgentEvent(event) {",
    )
    import_helper = _source_between(
        script,
        "  async function runImport(",
        "  function renderLessonPreview(lesson) {",
    )
    assert "async function runImport(sessionId = state.sessionId, generation = state.flowGeneration, navigationEpoch = state.navigationEpoch)" in import_helper
    _assert_source_order(
        import_helper,
        "isCurrentFlow(generation)",
        "`/api/sessions/${sessionId}/import`",
        'ownsRequest("importOwner", importOwner, generation, sessionId, navigationEpoch)',
        "if (!result.session || result.session.session_id !== sessionId)",
        "updateFromSession(result.session)",
        "renderLessonPreview(result.lesson)",
        "state.uploadFile = null",
        "state.confirmedScope = null",
        '$("#course-image")',
        'fileInput.value = ""',
        'showScreen("preview")',
    )
    assert 'ownsRequest("importOwner", importOwner, generation, sessionId, navigationEpoch)' in import_helper.split("catch (error)", 1)[1]
    assert 'setRetry("Try the lesson again", () => retryFailedImport())' in processing_failure
    assert 'setRetry("Try the lesson again", () => retryFailedImport())' in import_helper
    assert 'setRetry("Try the lesson again", () => runImport())' not in script

def test_child_ui_audio_failure_has_retry_and_text_fallback() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text

    assert "audio" in script
    assert "Retry audio activity" in script
    assert "Text alternative" in script

    audio_helper = _source_between(
        script,
        "  function audioFallbackMessage(",
        "  function renderActivity(",
    )
    audio_error_helper = _source_between(
        script,
        "  function isAudioProviderFallbackError(",
        "  function audioFallbackMessage(",
    )
    render_activity = _source_between(
        script,
        "  function renderActivity(",
        "  async function generateActivity(",
    )
    assert "provider" in audio_helper
    assert "unavailable" in audio_helper
    assert "timeout" in audio_helper
    assert "timeout" in audio_error_helper
    assert "408" in audio_error_helper
    assert "503" in audio_error_helper
    assert "504" in audio_error_helper
    assert "audio_bytes" in audio_helper
    assert "audio_data" in audio_helper
    assert "Audio playback is not connected yet." in audio_helper
    assert "audioFallbackMessage" in render_activity
    assert "showAudioFallback" in render_activity
    assert "renderActivity(result.activity, result.audio)" in script

    generate_activity = _source_between(
        script,
        "  async function generateActivity(",
        "  function resetForNewCourse()",
    )
    assert "isAudioProviderFallbackError(error)" in generate_activity
    assert 'showError("#practice-error"' in generate_activity
    assert "I could not make that activity yet." in generate_activity


def test_child_ui_new_course_reset_clears_course_forms_and_file_label() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    reset_handler = _source_between(
        script,
        "  function resetForNewCourse() {",
        "  function wireActions()",
    )

    for marker in (
        '$("#course-form")',
        '$("#scope-form")',
        ".reset()",
        '$("#course-image")',
        'setText("#selected-file"',
        "No image selected yet",
        '$("#course-form button[type=submit]")',
        '$("#scope-form button[type=submit]")',
        "setBusy(courseButton, false)",
        "setBusy(scopeButton, false)",
    ):
        assert marker in reset_handler


def test_child_ui_activity_render_defers_answer_evaluation_to_activity_service() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    stylesheet = client.get("/styles.css").text
    activity_render = _source_between(
        script,
        "  function renderActivity(",
        "  async function generateActivity(",
    )
    practice_question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )

    for forbidden in ("item.answer", "expected", "handleAnswer"):
        assert forbidden not in script
    assert "choice-button" in practice_question
    assert "aria-pressed" in practice_question
    assert ".choice-button.selected" in stylesheet
    assert "renderPracticeQuestion(activity)" in activity_render
    assert "renderPracticeProgress(activity)" in activity_render
    assert "items.forEach" not in activity_render
    assert 'showScreen("results")' not in activity_render
    assert "updateProgress" not in script


def test_child_ui_serves_javascript_and_stylesheet() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js")
    stylesheet = client.get("/styles.css")

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "WebSocket" in script.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert ":root" in stylesheet.text


def test_child_ui_styles_focused_lesson_flow_and_preview_layout() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    stylesheet = client.get("/styles.css").text
    preview = _source_between(
        html,
        '<section id="preview-screen"',
        '<section id="overview-screen"',
    )
    extraction_keyframes = _source_between(
        stylesheet,
        "@keyframes extraction-slide",
        ".hero-screen",
    )
    mobile_styles = _source_between(
        stylesheet,
        "@media (max-width: 600px)",
        "@media (prefers-reduced-motion: reduce)",
    )
    reduced_motion_styles = stylesheet[
        stylesheet.index("@media (prefers-reduced-motion: reduce)") :
    ]

    for contract in (
        "main { min-height: calc(100vh - 130px); min-height: calc(100svh - 130px); }",
        ".screen { min-height: calc(100vh - 150px); min-height: calc(100svh - 150px); padding: 42px 0 70px; }",
        ".screen[hidden] { display: none !important; }",
        ".screen [data-screen-heading]:focus { outline: none; }",
        ".lesson-stepper { display: grid; max-width: 720px; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0 auto 30px; padding: 0; list-style: none; }",
        ".lesson-stepper li { display: flex; align-items: center; justify-content: center; gap: 8px; min-width: 0; padding: 10px 12px; color: var(--muted); background: #edf1f5; border-radius: 999px; }",
        ".lesson-stepper li span { display: grid; width: 24px; height: 24px; place-items: center; flex: 0 0 auto; background: #fff; border-radius: 50%; font-size: 0.78rem; }",
        '.lesson-stepper [aria-current="step"] { color: #fff; background: var(--blue-dark); }',
        '.lesson-stepper [aria-current="step"] span { color: var(--blue-dark); }',
        ".lesson-stepper .is-complete { color: var(--mint-dark); background: var(--mint); }",
        ".extraction-progress { width: min(100%, 520px); height: 10px; margin: 24px auto 0; overflow: hidden; background: #dfe6f0; border-radius: 999px; }",
        ".extraction-progress span { display: block; width: 45%; height: 100%; background: var(--blue); border-radius: inherit; animation: extraction-slide 1.4s ease-in-out infinite alternate; }",
        ".preview-layout { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.75fr); gap: 22px; align-items: start; }",
        ".preview-summary { min-width: 0; }",
        ".preview-findings { min-width: 0; padding: 20px; background: #fff9e7; border-radius: 16px; }",
        "#lesson-title, .lesson-passage, .flashcard, .grammar-card, .note-card { overflow-wrap: anywhere; }",
        ".flashcard.is-flipped .flashcard-inner { transform: rotateY(180deg); }",
        ".flashcard-back { background: #fff9e7; border: 1px solid #f2d493; transform: rotateY(180deg); }",
        ".card-nav { display: flex; align-items: center; justify-content: center; gap: 14px; }",
    ):
        assert contract in stylesheet

    assert extraction_keyframes.strip() == (
        "@keyframes extraction-slide { from { transform: translateX(-10%); } "
        "to { transform: translateX(135%); } }"
    )
    for contract in (
        ".lesson-stepper { gap: 5px; margin-bottom: 22px; }",
        ".lesson-stepper li { flex-direction: column; gap: 4px; padding: 8px 4px; font-size: 0.76rem; }",
        ".lesson-stepper li span { width: 21px; height: 21px; }",
        ".flashcard-word { font-size: 1.8rem; }.flashcard-meaning { font-size: 1.5rem; }",
        ".preview-layout { grid-template-columns: 1fr; }",
    ):
        assert contract in mobile_styles
    assert reduced_motion_styles.strip() == (
        "@media (prefers-reduced-motion: reduce) { "
        ".extraction-progress span { animation: none; width: 68%; }"
        ".status-orbit { animation: none; }"
        ".flashcard-inner { transition: none; }"
        ".primary-button, .secondary-button { transition: none; }"
        ".primary-button:hover, .secondary-button:hover { transform: none; } }"
    )

    preview_layout = _source_between(
        preview,
        '<div class="preview-layout">',
        '<p id="preview-error"',
    )
    assert '<div class="preview-summary">' in preview_layout
    assert '<h3 id="lesson-title">' in preview_layout
    assert '<p id="lesson-passage" class="lesson-passage"></p>' in preview_layout
    assert '<div class="preview-findings">' in preview_layout
    _assert_source_order(
        preview_layout,
        '<div class="preview-summary">',
        '<h3 id="lesson-title">',
        'id="lesson-passage"',
        '<div class="preview-findings">',
        "What we found",
        'id="lesson-cards"',
    )


def test_child_ui_preview_uses_flashcard_deck_and_grammar_cards() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    render_preview = _source_between(
        script,
        "  function renderLessonPreview(lesson) {",
        "  function renderActivityCards()",
    )
    _assert_source_order(
        render_preview,
        "previewDeck.items = items",
        "previewDeck.index = 0",
        "renderCardAt(0)",
    )
    _assert_source_order(
        script,
        "function buildVocabularyCard(contentItem, index)",
        'classList.toggle("is-flipped")',
    )
    assert 'content.english' in script
    assert 'content.chinese' in script
    assert 'content.notes' in script
    assert "function buildGrammarCard(contentItem, index)" in script
    assert 'content.pattern' in script
    assert 'content.explanation' in script
    assert 'content.examples' in script
    assert '"#card-prev"' in script
    assert '"#card-next"' in script
    assert "renderCardAt(previewDeck.index - 1)" in script
    assert "renderCardAt(previewDeck.index + 1)" in script


def test_child_ui_success_path_cannot_skip_preview_for_practice() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    run_import = _source_between(
        script,
        "  async function runImport(",
        "  function renderLessonPreview(lesson) {",
    )
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )
    overview_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"overview\"]')",
        '    $("#retry-connection")',
    )

    assert 'showScreen("overview")' not in run_import
    _assert_source_order(
        run_import,
        "state.lesson = result.lesson",
        "renderLessonPreview(result.lesson)",
        'showScreen("preview")',
    )
    _assert_source_order(
        overview_action,
        "if (!state.lesson) return",
        "renderActivityCards()",
        'showScreen("overview")',
    )


def test_child_ui_async_operations_require_navigation_and_latest_request_ownership() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    scope_submit = _source_between(
        script,
        '    $("#scope-form").addEventListener("submit", async (event) => {',
        "  }\n\n  function init()",
    )
    run_import = _source_between(script, "  async function runImport(", "  function lessonScopeSummary(")
    generate_activity = _source_between(
        script, "  async function generateActivity(", "  function resetForNewCourse()",
    )
    submit_answer = _source_between(
        script, "  async function submitActivityAnswer(", "  async function transcribeSpeaking(",
    )
    speech = _source_between(
        script, "  async function transcribeSpeaking(", "  function renderActivity(",
    )
    wire_actions = _source_between(script, "  function wireActions() {", "  function init()")

    for marker in (
        "navigationEpoch: 0",
        "scopeOwner: null",
        "importOwner: null",
        "activityOwner: null",
        "answerOwner: null",
        "speechOwner: null",
        "function invalidateNavigation()",
        "function ownsRequest(ownerKey, owner, generation, sessionId, navigationEpoch)",
    ):
        assert marker in script

    upload_back = _source_between(
        wire_actions,
        "    $$('[data-action=\"upload-step\"]')",
        "    $$('[data-action=\"preview\"]')",
    )
    _assert_source_order(upload_back, "invalidateNavigation()", 'showScreen("new-course")')
    assert "flowGeneration" not in upload_back
    assert "resetForNewCourse()" not in upload_back

    _assert_source_order(
        scope_submit,
        "const generation = state.flowGeneration",
        "const sessionId = state.sessionId",
        "const navigationEpoch = state.navigationEpoch",
        'const scopeOwner = Symbol("scope")',
        "state.scopeOwner = scopeOwner",
        "await api(`/api/sessions/${sessionId}/scope`",
        'ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)',
        "updateFromSession(session)",
        'showScreen("processing")',
        "runImport(sessionId, generation, navigationEpoch)",
    )
    assert scope_submit.count('ownsRequest("scopeOwner", scopeOwner, generation, sessionId, navigationEpoch)') >= 3
    assert 'state.scopeOwner === scopeOwner' in scope_submit.split("finally", 1)[1]

    assert "async function runImport(sessionId = state.sessionId, generation = state.flowGeneration, navigationEpoch = state.navigationEpoch)" in run_import
    _assert_source_order(
        run_import,
        'const importOwner = Symbol("import")',
        "state.importOwner = importOwner",
        "await api(`/api/sessions/${sessionId}/import`",
        'ownsRequest("importOwner", importOwner, generation, sessionId, navigationEpoch)',
        "state.lesson = result.lesson",
        'showScreen("preview")',
    )
    assert run_import.count('ownsRequest("importOwner", importOwner, generation, sessionId, navigationEpoch)') >= 2

    for source, owner_key, owner_name in (
        (generate_activity, "activityOwner", "activityOwner"),
        (submit_answer, "answerOwner", "answerOwner"),
        (speech, "speechOwner", "speechOwner"),
    ):
        assert f'const {owner_name} = Symbol(' in source
        assert f"state.{owner_key} = {owner_name}" in source
        assert f'ownsRequest("{owner_key}", {owner_name}, generation, sessionId, navigationEpoch)' in source

    attempt_invalidation = _source_between(
        script,
        "  function invalidatePracticeAttempt() {",
        "  function invalidateNavigation() {",
    )
    _assert_source_order(
        attempt_invalidation,
        "state.answerOwner = null",
        "state.speechOwner = null",
        "const recorder = state.speechRecorder",
        "state.speechRecorder = null",
        'recorder.stop()',
    )
    before_attempt_invalidation, after_attempt_invalidation = generate_activity.split(
        "invalidatePracticeAttempt()",
        1,
    )
    _assert_source_order(
        before_attempt_invalidation,
        "const generation = state.flowGeneration",
        "const sessionId = state.sessionId",
        "if (!sessionId || !state.lesson)",
    )
    assert "state.currentActivityType" not in before_attempt_invalidation
    assert "state.activityOwner" not in before_attempt_invalidation
    assert "activities/generate" not in before_attempt_invalidation
    _assert_source_order(
        after_attempt_invalidation,
        "const navigationEpoch = state.navigationEpoch",
        'const activityOwner = Symbol("activity")',
        "state.activityOwner = activityOwner",
        "state.currentActivityType = definition.type",
        "showError(\"#practice-error\"",
        "await api(`/api/sessions/${sessionId}/activities/generate`",
    )
    assert generate_activity.count('ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)') >= 3
    assert submit_answer.count('ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)') >= 3
    assert "`/api/sessions/${sessionId}/speech/transcribe`" in speech
    assert "`/api/sessions/${state.sessionId}/speech/transcribe`" not in speech
    assert speech.count('ownsRequest("speechOwner", speechOwner, generation, sessionId, navigationEpoch)') >= 3

    for selector in ('[data-action="preview"]', '[data-action="progress"]', '[data-action="overview"]'):
        action_start = f"    $$('{selector}')"
        assert action_start in wire_actions
    assert wire_actions.count("invalidateNavigation()") >= 4


def test_child_ui_renders_safe_read_only_lesson_context_in_preview_and_practice() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    script = client.get("/app.js").text
    stylesheet = client.get("/styles.css").text
    preview = _source_between(html, '<section id="preview-screen"', '<section id="overview-screen"')
    overview = _source_between(html, '<section id="overview-screen"', '<section id="practice-screen"')
    renderer = _source_between(script, "  function lessonScopeSummary(", "  function renderActivityCards()")

    for marker in ('id="lesson-scope-summary"', 'id="lesson-source-summary"'):
        assert marker in preview
    for marker in ('id="overview-lesson-title"', 'id="overview-lesson-scope"'):
        assert marker in overview
    assert "function lessonScopeSummary(scope = {})" in renderer
    assert "function renderLessonContext(lesson)" in renderer
    assert 'setText("#lesson-scope-summary", scopeSummary)' in renderer
    assert 'setText("#overview-lesson-title", title)' in renderer
    assert 'setText("#overview-lesson-scope", scopeSummary)' in renderer
    assert "Array.isArray(lesson.source_images) ? lesson.source_images.length : 0" in renderer
    assert "`${sourceCount} source image${sourceCount === 1 ? \"\" : \"s\"}`" in renderer
    assert "source_images.join" not in renderer
    assert "image_id" not in renderer
    assert "path" not in renderer
    assert "renderLessonContext(lesson)" in renderer
    assert ".lesson-context { overflow-wrap: anywhere; }" in stylesheet
    assert ".overview-lesson-context { min-width: 0; }" in stylesheet

def test_child_ui_static_files_do_not_depend_on_current_working_directory(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    response = TestClient(create_app(testing=True)).get("/")

    assert response.status_code == 200
    assert "TalkPath" in response.text


def test_child_ui_adds_my_lessons_nav_link_and_lessons_screen() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    home = _source_between(
        html,
        '<section id="home-screen"',
        '<section id="lessons-screen"',
    )
    lessons_screen = _source_between(
        html,
        '<section id="lessons-screen"',
        '<section id="new-course-screen"',
    )

    assert (
        '<button class="nav-link" type="button" data-action="lessons">My lessons</button>'
        in html
    )
    assert (
        '<section id="lessons-screen" class="screen content-screen" '
        'data-screen="lessons" hidden>'
        in html
    )
    assert '<h2 id="lessons-title" data-screen-heading tabindex="-1">My lessons</h2>' in lessons_screen
    for marker in (
        'id="lessons-list"',
        'id="lessons-empty"',
        'id="lessons-error"',
        "Start a new lesson",
        'data-action="new-course"',
    ):
        assert marker in lessons_screen
    assert "saved" not in home
    assert 'id="saved-lessons"' not in html
    assert "saved-lesson" not in html


def test_child_ui_lessons_page_renders_cards_and_opens_lesson_for_practice() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )
    lessons_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"lessons\"]')",
        "    $$('[data-action=\"upload-step\"]')",
    )
    saved = _source_between(
        script,
        "  async function loadSavedLessons() {",
        "  function wireActions()",
    )
    init_section = _source_between(
        script,
        "  function init() {",
        '  document.addEventListener("DOMContentLoaded", init);',
    )
    home_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"home\"]')",
        "    $$('[data-action=\"new-course\"]')",
    )

    assert '$$(\'[data-action="lessons"]\').forEach' in wire_actions
    _assert_source_order(
        lessons_action,
        "invalidateNavigation()",
        'showScreen("lessons")',
        "loadSavedLessons()",
    )
    assert 'showScreen("lessons")' in script

    assert '"/api/lessons"' in saved
    assert "function renderSavedLessons(lessons)" in saved
    assert "lesson-card" in saved
    assert "lesson-card-continue" in saved
    assert "Continue" in saved
    assert "lessonScopeSummary(lesson.scope || {})" in saved
    assert "lesson.content_item_count" in saved
    assert "enterSavedLesson(lesson)" in saved
    _assert_source_order(
        saved,
        "async function loadSavedLessons()",
        '"/api/lessons"',
        "renderSavedLessons(lessons)",
        "function renderSavedLessons(lessons)",
        "enterSavedLesson(lesson)",
        "async function enterSavedLesson(summary)",
        '"/api/sessions"',
        "lesson_id: summary.lesson_id",
        "updateFromSession(session)",
        "`/api/lessons/${summary.lesson_id}`",
        "state.lesson = lesson",
        "renderLessonContext(state.lesson)",
        "renderActivityCards()",
        'showScreen("overview")',
    )
    assert "state.savedLessonOwner" in saved
    assert "connectWebSocket(sessionId)" in saved
    assert "loadSavedLessons()" not in home_action
    assert "loadSavedLessons()" not in init_section
    assert 'showError("#lessons-error"' in saved


def test_child_ui_lessons_page_uses_stacked_cards_with_continue_button() -> None:
    client = TestClient(create_app(testing=True))

    stylesheet = client.get("/styles.css").text
    for contract in (
        ".lessons-list {",
        ".lesson-card {",
        ".lesson-card:hover {",
        ".lesson-card-title {",
        ".lesson-card-scope {",
        ".lesson-card-count {",
        ".lesson-card-continue {",
        ".lessons-empty {",
    ):
        assert contract in stylesheet
    assert ".saved-lessons" not in stylesheet
    assert ".saved-lesson" not in stylesheet


def test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    generate_activity = _source_between(
        script,
        "  async function generateActivity(",
        "  function resetForNewCourse()",
    )

    for marker in (
        "currentQuestionIndex: 0",
        "practiceQueue: []",
        "practiceAnswered: false",
        "practicePassed: false",
        "practiceResult: null",
        'practiceFeedback: ""',
        "practiceWrongChoices: []",
        "practiceAutoAdvance: null",
        "PRACTICE_AUTO_ADVANCE_MS = 500",
    ):
        assert marker in script
    _assert_source_order(
        generate_activity,
        "state.currentActivityType = definition.type",
        "state.currentQuestionIndex = 0",
        "state.practiceQueue = []",
        'showError("#practice-error", "")',
        'showScreen("practice")',
        "Making your activity…",
    )
    assert 'showError("#activity-error"' not in generate_activity
    assert 'showScreen("overview")' not in generate_activity
    _assert_source_order(
        generate_activity,
        "state.activity = result.activity",
        'result.activity.type === "vocabulary_practice"',
        '|| result.activity.type === "vocabulary_quiz"',
        "renderActivity(result.activity, result.audio)",
    )
    for marker in (
        "function shufflePracticeQueue(items)",
        "Math.floor(Math.random()",
        "items.map((_, index) => index)",
    ):
        assert marker in script


def test_child_ui_generate_activity_resumes_existing_same_type_activity() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    generate_activity = _source_between(
        script,
        "  async function generateActivity(",
        "  function resetForNewCourse()",
    )

    for marker in (
        "const existingActivity = state.generatedActivities[definition.type]",
        "existingActivity && existingActivity.type === definition.type",
        "existingActivity.lesson_id === state.lesson.lesson_id",
        "state.generatedActivities[result.activity.type] = result.activity",
        "renderActivity(existingActivity, resumeAudio)",
    ):
        assert marker in generate_activity
    _assert_source_order(
        generate_activity,
        "const existingActivity = state.generatedActivities[definition.type]",
        "existingActivity && existingActivity.type === definition.type",
        "renderActivity(existingActivity, resumeAudio)",
        "`/api/sessions/${sessionId}/activities/generate`",
    )


def test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    activity_render = _source_between(
        script,
        "  function renderActivity(",
        "  async function generateActivity(",
    )
    progress = _source_between(
        script,
        "  function renderPracticeProgress(",
        "  function renderPracticeQuestion(",
    )
    question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )
    advance = _source_between(
        script,
        "  function advancePracticeQuestion(",
        "  async function submitActivityAnswer(",
    )

    for marker in (
        "function renderPracticeProgress(activity)",
        "function renderPracticeQuestion(activity)",
        "function renderPracticeResultActions(activity, actions)",
        "function isLastPracticeQuestion(activity)",
        "function advancePracticeQuestion(activity)",
    ):
        assert marker in script
    assert "Question ${current + 1}" in progress
    assert 'className = "practice-dot"' in progress
    assert "is-done" in progress
    assert "is-current" in progress
    assert "renderPracticeProgress(activity)" in activity_render
    assert "renderPracticeQuestion(activity)" in activity_render
    assert "items.forEach" not in activity_render
    assert "Check my answer" in question
    assert "practice-question" in question
    assert 'showScreen("results")' not in activity_render
    assert "const total = state.practiceQueue.length" in progress
    assert "const item = items[queue[index]]" in question
    assert "state.practiceQueue.length - 1" in advance
    assert "state.practiceQueue.length - 1" in _source_between(
        script,
        "  function isLastPracticeQuestion(",
        "  function advancePracticeQuestion(",
    )


def test_child_ui_speaking_practice_is_removed() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    definitions = _source_between(
        script,
        "  const activityDefinitions = [",
        "  ];",
    )

    assert "speaking_practice" not in definitions
    assert 'activity.type === "speaking_practice"' not in script
    assert "Say it out loud and have a go." not in script


def test_child_ui_vocabulary_practice_is_speaking_drill() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    styles = client.get("/styles.css").text
    definitions = _source_between(
        script,
        "  const activityDefinitions = [",
        "  ];",
    )
    question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )
    speech = _source_between(
        script,
        "  async function transcribeSpeaking(",
        "  function renderActivity(",
    )

    assert "Listen to the word, then say it out loud." in definitions
    for marker in (
        'activity.type === "vocabulary_practice"',
        "practice-word",
        '"Listen"',
        '"Record your voice"',
        "playPracticeWord(item.prompt, feedback)",
        "state.practiceTranscript",
        "submitActivityAnswer(activity, item, () => state.practiceTranscript",
    ):
        assert marker in question
    assert "`/api/sessions/${sessionId}/speech/synthesize`" in script
    assert "text: word" in script
    assert "onTranscript" in speech
    assert 'practiceTranscript: ""' in script
    assert script.count('state.practiceTranscript = ""') >= 3
    assert ".practice-word" in styles
    assert ".practice-speech-actions" in styles


def test_child_ui_speech_synthesis_does_not_hardcode_a_voice() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text

    assert 'voice: "child"' not in script


def test_child_ui_vocabulary_word_wall_screen_lists_lesson_words() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    script = client.get("/app.js").text
    styles = client.get("/styles.css").text
    words_screen = _source_between(
        html,
        '<section id="words-screen"',
        '<section id="results-screen"',
    )
    definitions = _source_between(
        script,
        "  const activityDefinitions = [",
        "  ];",
    )
    activity_cards = _source_between(
        script,
        "  function renderActivityCards() {",
        "  function showAudioFallback(",
    )
    word_wall = _source_between(
        script,
        "  function openWordWall() {",
        "  function openWordPractice(",
    )
    overview_handler = _source_between(
        script,
        "    $$('[data-action=\"overview\"]')",
        "    $(\"#retry-connection\")",
    )

    for marker in (
        'data-screen="words"',
        'id="word-search"',
        'id="word-grid"',
        'id="words-practice-all"',
        'data-action="overview"',
    ):
        assert marker in words_screen
    assert "words: true" in definitions
    assert "if (definition.words) {" in activity_cards
    assert "openWordWall();" in activity_cards
    assert "generateActivity(definition);" in activity_cards
    for marker in (
        "function openWordWall()",
        'showScreen("words")',
        "function renderWordWall()",
        '"word-card"',
        '"word-en"',
        '"word-zh"',
        '"word-speaker"',
        "playPracticeWord(word,",
        "openWordPractice(item)",
        "word-badge is-",
    ):
        assert marker in word_wall
    assert "wordStatus: {}" in script
    assert "wordPractice: null" in script
    assert "state.wordStatus = {}" in script
    assert "state.wordPractice = null" in script
    assert 'if (state.wordPractice)' in overview_handler
    assert "openWordWall()" in overview_handler
    assert '$("#word-search")' in script
    assert '("#words-practice-all")' in script
    assert ".word-grid" in styles
    assert ".word-card" in styles
    assert ".word-speaker" in styles
    assert ".word-badge" in styles


def test_child_ui_word_practice_submits_transcript_to_vocabulary_answer() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    word_practice = _source_between(
        script,
        "  function openWordPractice(",
        "  async function submitWordAnswer(",
    )
    submit = _source_between(
        script,
        "  async function submitWordAnswer(",
        "  function backToWordWall()",
    )

    for marker in (
        "function openWordPractice(item)",
        "state.wordPractice = {",
        "contentId:",
        'showScreen("practice")',
        "transcribeSpeaking(record, speechFeedback, (transcript)",
        "submitWordAnswer(transcript,",
    ):
        assert marker in word_practice
    for marker in (
        "async function submitWordAnswer(answer, feedback, button)",
        "`/api/sessions/${sessionId}/vocabulary/${practice.contentId}/answer`",
        "state.wordStatus[practice.contentId] =",
        '"done"',
        '"again"',
        "Great job!",
        "Try again.",
        "Back to words",
    ):
        assert marker in submit


def test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    practice_helpers = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  async function submitActivityAnswer(",
    )
    submit_answer = _source_between(
        script,
        "  async function submitActivityAnswer(",
        "  async function transcribeSpeaking(",
    )

    for marker in (
        "Check my answer",
        "Next question",
        "Finish",
        'textContent = last ? "Finish" : "Next question"',
        "state.practiceWrongChoices.includes(choice)",
        'button.classList.add("is-wrong")',
    ):
        assert marker in practice_helpers
    result_actions = _source_between(
        practice_helpers,
        "  function renderPracticeResultActions(",
        "  function isLastPracticeQuestion(",
    )
    assert 'if (isQuiz && !state.practicePassed)' in result_actions
    assert 'textContent = "Try again"' in result_actions
    _assert_source_order(
        practice_helpers,
        "function renderPracticeQuestion(",
        "function renderPracticeResultActions(",
        "function advancePracticeQuestion(",
    )
    _assert_source_order(
        submit_answer,
        'const value = String(readAnswer() || "").trim()',
        "setBusy(button, true",
        "`/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`",
        'ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)',
        "state.practiceResult = result",
        "state.practicePassed = Boolean(evaluation.passed)",
        "state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed)",
        "state.practiceWrongChoices.push(value)",
        'activity.type === "vocabulary_practice"',
        "state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex])",
        "renderPracticeQuestion(activity)",
        "state.practiceAutoAdvance = setTimeout",
    )
    for marker in (
        "That was a strong try!",
        "Good try! Check the word again.",
        "state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex])",
        "state.practiceAutoAdvance = setTimeout",
        "PRACTICE_AUTO_ADVANCE_MS",
    ):
        assert marker in submit_answer
    assert "showAnswerResult(result)" not in submit_answer
    assert 'showScreen("results")' in script
    for forbidden in ("item.answer", "expected", "handleAnswer"):
        assert forbidden not in script


def test_child_ui_practice_wiring_removes_inline_panel_controls() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )
    reset_handler = _source_between(
        script,
        "  function resetForNewCourse() {",
        "  function wireActions()",
    )

    assert '$("#close-activity")' not in script
    assert '"#activity-panel"' not in script
    assert '"#activity-error"' not in script
    assert "function showAudioFallback(definition, errorMessage)" in script
    assert '"#practice-body"' in script
    assert 'showError("#practice-error"' in reset_handler
    assert "clearTimeout(state.practiceAutoAdvance)" in reset_handler
    assert "state.practiceQueue = []" in reset_handler
    assert "practiceBody.replaceChildren()" in reset_handler
    assert "practiceDots.replaceChildren()" in reset_handler
    _assert_source_order(
        reset_handler,
        "state.currentQuestionIndex = 0",
        "state.practiceQueue = []",
        "state.practiceAnswered = false",
        'state.practiceFeedback = ""',
        'showError("#practice-error"',
        'const practiceBody = $("#practice-body")',
    )
    assert "invalidateNavigation()" in wire_actions


def test_child_ui_practice_styles_use_single_card_and_dot_progress() -> None:
    client = TestClient(create_app(testing=True))

    stylesheet = client.get("/styles.css").text

    for contract in (
        ".practice-heading {",
        ".practice-progress {",
        ".practice-dots {",
        ".practice-dot {",
        ".practice-dot.is-done {",
        ".practice-dot.is-current {",
        ".practice-card { max-width: 720px;",
        ".practice-question {",
        ".practice-actions {",
        ".answer-feedback.is-passed {",
        ".answer-feedback.is-try-again {",
    ):
        assert contract in stylesheet
    assert ".activity-panel" not in stylesheet
    assert ".icon-button" not in stylesheet


def test_child_ui_choice_buttons_have_generous_tap_targets() -> None:
    client = TestClient(create_app(testing=True))

    stylesheet = client.get("/styles.css").text

    for contract in (
        "min-height: 58px;",
        "padding: 16px 18px;",
        "font-size: 1.05rem;",
        ".choice-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;",
        ".choice-button.is-wrong {",
        ".choice-button:disabled {",
    ):
        assert contract in stylesheet


def test_child_ui_vocabulary_quiz_renders_question_type_branches() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )

    for marker in (
        'const isQuiz = activity.type === "vocabulary_quiz"',
        'const questionType = isQuiz ? (item.question_type || "") : ""',
        'questionType === "dictation"',
        'questionType === "listen_to_meaning"',
        "Listen and write the word.",
        "Listen and choose the meaning.",
        "playPracticeWord(item.prompt",
        "Show the word",
        "answer-correction",
    ):
        assert marker in question
    assert "state.quizResults = []" in script
    assert 'state.practiceCorrection = ""' in script


def test_child_ui_vocabulary_quiz_allows_retry_after_wrong_answer() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    submit = _source_between(
        script,
        "  async function submitActivityAnswer(",
        "  async function transcribeSpeaking(",
    )

    for marker in (
        'const isQuiz = activity.type === "vocabulary_quiz"',
        "state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed)",
        "state.quizResults[state.currentQuestionIndex]",
        "state.practiceWrongChoices.push(value)",
        'correction: result.correction || ""',
        "Good try! Check the word again.",
    ):
        assert marker in submit
    assert "Correct spelling" not in submit
    assert "Correct answer" not in submit


def test_child_ui_vocabulary_quiz_results_show_score_and_review() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    results = _source_between(
        script,
        "  function showAnswerResult(",
        "  function shufflePracticeQueue(",
    )
    index_html = client.get("/index.html").text
    styles = client.get("/styles.css").text

    for marker in (
        'state.currentActivityType === "vocabulary_quiz"',
        "state.quizResults.filter",
        "quiz-practice-words",
        '"#review-list"',
    ):
        assert marker in results
    assert 'id="quiz-practice-words"' in index_html
    assert "Practice these words" in index_html
    assert ".answer-correction" in styles


def test_child_ui_scope_screen_warns_before_appending_to_an_existing_lesson() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    script = client.get("/app.js").text
    stylesheet = client.get("/styles.css").text
    scope = _source_between(html, '<section id="scope-screen"', '<section id="processing-screen"')
    preview = _source_between(html, '<section id="preview-screen"', '<section id="overview-screen"')
    scope_submit = _source_between(
        script,
        '    $("#scope-form").addEventListener("submit", async (event) => {',
        "  }\n\n  function init()",
    )
    run_import = _source_between(script, "  async function runImport(", "  function lessonScopeSummary(")

    for marker in (
        'id="scope-notice"',
        'id="scope-notice-text"',
        'id="scope-notice-cancel"',
        'id="scope-notice-confirm"',
        "Add anyway",
        'placeholder="Publisher, e.g. 康軒"',
    ):
        assert marker in scope
    assert 'id="import-note"' in preview

    _assert_source_order(
        scope_submit,
        "state.scopeOwner = scopeOwner",
        '"/api/lessons/import-check"',
        "appendWarning(",
        "await api(`/api/sessions/${sessionId}/scope`",
    )
    assert "state.appendWarningAccepted" in scope_submit
    assert "function appendWarning(check, scope)" in script
    assert "requestSubmit(" in script
    _assert_source_order(run_import, "state.lesson = result.lesson", "setImportNote(result)", 'showScreen("preview")')
    assert "function setImportNote(result)" in script
    assert "skipped_duplicates" in script

    for contract in (".scope-notice {", ".scope-notice-actions {", ".import-note {"):
        assert contract in stylesheet
    # A display rule would override the hidden attribute and leave the notice always visible.
    assert ".scope-notice[hidden] { display: none; }" in stylesheet


def test_child_ui_lesson_detail_screen_shows_each_import_with_its_photos() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    script = client.get("/app.js").text
    stylesheet = client.get("/styles.css").text
    detail = _source_between(html, '<section id="lesson-detail-screen"', '<section id="new-course-screen"')
    saved = _source_between(script, "  async function loadSavedLessons() {", "  function wireActions()")
    open_detail = _source_between(
        script,
        "  async function openLessonDetail(",
        "  function wireActions()",
    )

    for marker in (
        'data-screen="lesson-detail"',
        'id="detail-title" data-screen-heading tabindex="-1"',
        'id="detail-scope"',
        'id="detail-batches"',
        'id="detail-error"',
        'id="detail-start"',
        'data-action="lessons"',
        "Start practice",
    ):
        assert marker in detail
    assert "saved" not in detail.lower()

    assert "lesson-card-view" in saved
    assert "openLessonDetail(lesson)" in saved
    assert "lesson-card-continue" in saved
    assert "enterSavedLesson(lesson)" in saved

    _assert_source_order(
        open_detail,
        "invalidateNavigation()",
        'showScreen("lesson-detail")',
        "`/api/lessons/${summary.lesson_id}`",
        "`/api/lessons/${summary.lesson_id}/batches`",
        "renderLessonDetail(",
    )
    assert "state.navigationEpoch !== navigationEpoch" in open_detail
    assert "function renderLessonDetail(lesson, batches)" in script
    assert "`/api/lessons/${lesson.lesson_id}/images/${imageId}`" in script
    assert 'link.target = "_blank"' in script
    assert 'link.rel = "noopener"' in script
    assert "enterSavedLesson(state.detailLesson)" in script
    assert 'showError("#detail-error"' in script

    for contract in (".detail-batch {", ".detail-thumbs {", ".detail-thumb {", ".detail-items {", ".lesson-card-actions {"):
        assert contract in stylesheet
