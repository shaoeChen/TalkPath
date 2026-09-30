# TalkPath Focused Lesson Flow Design

**Date:** 2026-08-13

**Status:** Approved for implementation planning

## 1. Goal

Replace the current long, vertically stacked lesson flow with a focused wizard that shows one primary task at a time. Starting a new lesson must feel like entering a new page, not jumping down the existing page.

The approved flow is:

```text
Home
  → Step 1: Upload textbook page
  → Step 2: Confirm lesson details
  → Step 3: Extract lesson
  → Read-only extraction preview
  → Separate Practice Hub (Pick a practice)
```

## 2. Scope

### Included

- A three-step focused wizard for upload, lesson details, and extraction.
- One visible application screen at a time.
- A shared step indicator on wizard screens only.
- A read-only extraction preview after a successful import.
- A separate Practice Hub screen for activity selection.
- Stable navigation that does not depend on scrolling to locate the next step.
- Existing retry, session, WebSocket, activity, and provider behavior retained.

### Excluded

- Editing extracted lesson content.
- New backend routes or domain states solely for presentation.
- Browser URL routing for each wizard step.
- Parent or teacher workflows.
- Redesigning individual practice activities.
- A full visual-brand redesign.

## 3. Selected approach

Use the existing single-page application state and `data-screen` mechanism, but make each screen behave as a full page. The DOM may retain multiple screen sections, while CSS and JavaScript guarantee that exactly one primary screen is visible and positioned at the top.

This preserves the current API/session architecture and retry safeguards while fixing the interaction problem with the least state-management risk. Separate browser routes were rejected because they would require session restoration, history handling, and deep-link behavior that are unnecessary for this release. A permanent desktop sidebar was rejected because it complicates the mobile layout and gives setup navigation too much visual weight.

## 4. Screen architecture

### 4.1 Home

The Home screen remains the entry point. Selecting **Start a new lesson** resets any prior lesson setup state and replaces Home with Step 1.

The action must not scroll to another section. It calls the screen transition mechanism and moves focus/scroll position to the new screen heading.

### 4.2 Step 1 — Upload

Purpose: choose one textbook image.

Visible content:

- Step indicator: `1 Upload / 2 Details / 3 Create`.
- Page heading and short instruction.
- Image picker and selected-file label.
- Primary **Continue** action.
- Exit/back-to-home action.

Successful upload replaces Step 1 with Step 2. Validation errors stay within Step 1 and do not expose later screens.

### 4.3 Step 2 — Lesson details

Purpose: confirm program, grade, subject, lesson, and the existing optional scope fields.

Visible content:

- Step 1 marked complete, Step 2 active, Step 3 pending.
- Existing scope form.
- Primary **Create my lesson** action.
- Back action to Step 1. Returning to Step 1 must not silently upload again; the selected local file may remain available until import succeeds or the flow is reset.

Only a successfully confirmed scope advances to Step 3.

### 4.4 Step 3 — Extraction

Purpose: show that TalkPath is reading the page and building the lesson.

Visible content:

- Steps 1 and 2 complete, Step 3 active.
- Current extraction status and existing agent/status messages.
- Progress treatment that communicates activity without claiming a precise percentage unless the backend supplies one.
- Existing retry and reconnect actions when applicable.

The user remains on this screen until import succeeds or fails. A failure retry creates a fresh session using the existing retained upload/scope safeguards. It must not return to a failed session.

### 4.5 Extraction preview

Purpose: show what TalkPath extracted before the learner chooses an activity.

This is a separate, read-only screen without the three-step indicator. It shows the information already available in the lesson response:

- Lesson title and identity/scope summary.
- Extracted passage or primary lesson text.
- Extracted content items grouped by their existing type where practical, including vocabulary and grammar information.
- Source-image count or summary without exposing filesystem paths or image bytes.
- Extraction status when useful.
- Primary **Choose a practice** action.

No inline editing, correction form, or re-extraction controls are introduced in this release. If content is unsuitable, the learner can exit and start a new lesson.

### 4.6 Practice Hub

Purpose: select an activity after reviewing the extracted lesson.

This is a separate screen titled **Pick a practice**. It contains the existing practice choices and retains the current activity-generation behavior. It does not share space with the extraction preview.

The header keeps the current lesson context visible. A learner may return to the read-only preview without recreating the lesson. Selecting a practice opens the existing activity experience; the practice redesign itself is out of scope.

## 5. Navigation and viewport behavior

- `showScreen(name)` remains the single screen-transition boundary.
- Exactly one `[data-screen]` section is visible after every transition.
- Transitions use immediate top positioning rather than smooth scrolling. Smooth scrolling is the source of the perceived upward jumping and makes a replacement screen feel like another section on the same page.
- After a transition, focus moves to the destination screen heading or a dedicated screen container using a programmatic-focus pattern that does not add it to normal tab order.
- Global header actions must not accidentally reveal hidden screens or revive stale async flows.
- The wizard step indicator appears only on upload, details, and extraction screens.
- Preview and Practice Hub are destination pages, not Step 4 and Step 5.
- Mobile and desktop use the same top step indicator; no separate sidebar navigation is required.

## 6. State and data flow

The change is presentation-focused and retains the existing backend flow:

```text
create session
  → upload image
  → confirm scope
  → import lesson
  → render read-only preview
  → generate selected activity
```

Frontend state continues to hold the active session, lesson, activity, retained retry inputs, socket identity, flow generation, and retry owner. The existing generation/session guards remain mandatory so a stale HTTP response or WebSocket event cannot change the visible page after reset or navigation.

On successful import:

1. Validate the response belongs to the expected session and current flow generation.
2. Store the lesson.
3. Clear retry-only file/scope data as currently designed.
4. Render the extraction preview.
5. Replace the extraction screen with the preview screen.

The Practice Hub is entered only through the preview's primary action or an explicit lesson-context navigation action after a lesson exists.

## 7. Error and recovery behavior

- Upload errors remain on Step 1.
- Scope validation/confirmation errors remain on Step 2.
- Import/provider errors remain on Step 3 and expose the existing safe retry action.
- WebSocket reconnect errors remain on Step 3 while extraction is active.
- Activity-generation errors remain within the Practice Hub/activity surface.
- Error text must remain secret-safe and must not reveal provider responses, prompts, image bytes, filesystem paths, or credentials.
- Starting a new lesson invalidates pending async work through the existing flow-generation mechanism.

## 8. Accessibility

- Each screen has one clear `h1` or primary `h2` destination heading.
- Step state is conveyed in text as well as visual styling, with current-step semantics such as `aria-current="step"`.
- Hidden screens use the native `hidden` attribute and are not keyboard reachable.
- Screen changes announce the new heading/status through focus management and existing live regions where appropriate.
- Back, exit, retry, and continue controls use descriptive visible labels.
- Reduced-motion preferences are respected; the design does not require transition animation.

## 9. Responsive behavior

- The wizard remains a single focused column on desktop and mobile.
- The three-step indicator stays horizontal with short labels and may wrap only as a whole component, not into a sidebar.
- Preview content can use two columns on wider screens and collapses to one column on narrow screens.
- Practice choices can use a responsive card grid, but the Practice Hub itself remains one page with no horizontal scrolling.

## 10. Testing strategy

### Static and unit contracts

- The Home action transitions to Step 1 without direct scrolling to an element.
- Wizard screens contain the shared three-step indicator with the correct active/completed state.
- Preview and Practice Hub do not contain the wizard step indicator.
- The preview action transitions to the Practice Hub.
- Exactly one screen is visible after initialization and each scripted transition.
- Successful import displays preview before Practice Hub.
- Existing fresh-session retry callbacks remain intact.

### Executable frontend behavior

Add a minimal JavaScript behavior harness using the project's available tooling or a dependency-free DOM/mock boundary where practical. It should verify:

- No stale WebSocket or HTTP continuation can replace the active screen.
- Reset returns to the intended screen and invalidates the prior flow.
- Upload, scope, extraction, preview, and Practice Hub occur in order.
- Transition focus and top-position behavior are invoked once per screen change.

If an executable DOM harness cannot be added without introducing disproportionate infrastructure, retain the current static contracts and record the limitation in `docs/PROGRESS.md`; this does not relax the session/generation regression requirements.

### Regression

- Existing API, import, failure-recovery, activity, and static UI tests remain green.
- `node --check frontend/app.js` passes.
- Responsive layout receives manual browser verification at desktop and narrow mobile widths.

## 11. Acceptance criteria

- Clicking **Start a new lesson** replaces Home with Step 1 and does not visibly scroll down the page.
- Only one primary screen is visible at any time.
- Step 1, Step 2, and Step 3 use a consistent top progress indicator.
- A successful import always shows a read-only extraction preview before practice selection.
- **Pick a practice** is a separate Practice Hub screen.
- Preview content is not editable.
- Import failures remain retryable through a fresh session without stale-screen races.
- Desktop and mobile layouts do not require horizontal scrolling.
- Existing backend contracts and provider behavior are unchanged.
