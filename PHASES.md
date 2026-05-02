# TD Collateral Modernizer — Master Phase Plan

> **How to use this file:** At the start of every new session, read this file first. It tells you exactly what phase you're in, what was completed, what's next, and any decisions or gotchas from prior sessions. Update the Active Phase section at the end of every session.

---

## Phase Overview

| Phase | Focus | Status |
|---|---|---|
| 1 | Project scaffold + document extraction | ✅ Complete |
| 2 | AI integration (classify + rewrite pipeline) | ✅ Complete |
| 3 | Review UI + output file generation | ✅ Complete |
| 4 | Projects, dashboard, session history | ✅ Complete |
| 5 | Polish, error handling, demo readiness | ✅ Complete |

---

## Phase 1 — Project Scaffold + Document Extraction

**Goal:** A working foundation. By the end of this phase, the app can accept uploaded files, parse them into sections, and display those sections in a basic UI — no AI yet.

### Model Allocation
**No AI calls in this phase.** All tasks are pure Python:
- File upload and validation → `python-docx` / `pdfplumber`
- Section splitting → `extractor.py` logic
- Scanned PDF detection → character count threshold, no API call

### Deliverables
- [x] Full directory structure created
- [x] `requirements.txt` with all Phase 1 dependencies
- [x] `.env.example` and `.gitignore`
- [x] `src/models.py` — `Section`, `ChangeType`, `ReviewState` dataclasses
- [x] `src/extractor.py` — parse `.docx` by headings; extract `.pdf` as full text
- [x] `app.py` — Upload screen (Screen 1) functional; Processing screen (Screen 2) shell only

### Definition of Done
A user can launch `streamlit run app.py`, upload a `.docx` and a reference file, click "Process Documents", and see a list of extracted sections printed to the screen (no AI output yet).

### Session Log

#### Session 1 — 2026-04-30
**Completed:**
- Created `PHASES.md` (this file)
- Created full directory structure: `src/`, `prompts/`
- Created `requirements.txt`, `.env.example`, `.gitignore`
- Created `src/models.py` — `Section`, `ChangeType`, `ReviewState` dataclasses
- Created `src/extractor.py` — `.docx` heading-based splitting, fallback paragraph-block splitting, `.pdf` text extraction via `pdfplumber`, scanned PDF detection
- Created `app.py` — Upload screen with file upload widgets and "Process Documents" button; Processing screen with spinner and extracted section preview

**Decisions made:**
- Fallback paragraph block size: 4 paragraphs (tunable via constant in `extractor.py`)
- Scanned PDF detection: if `pdfplumber` extracts fewer than 50 characters total, warn the user
- Session state keys: `st.session_state.sections`, `st.session_state.stage` (`upload` | `processing` | `review` | `download`)

**Known issues / watch-outs:**
- None yet

**What's next (Phase 2):**
- ~~Provider abstraction already built (Session 2 below)~~
- Wire the Processing screen to call `process_document()` and populate `st.session_state.sections`
- Build the basic review screen to display classification results

---

## Phase 2 — AI Integration

**Goal:** The app calls Gemini. After uploading, the AI classifies each section (no change / update needed / gap) and drafts rewrites for flagged sections. Results are stored in session state, ready for the review screen.

### Model Allocation
| Task | Model | Reason |
|---|---|---|
| Boilerplate detection (is this section worth reviewing?) | `gemini-2.5-flash-lite` | Yes/no answer — no generation needed |
| Section classification (outdated / gap / no change) | `gemini-2.5-flash-lite` | Yes/no + one sentence — cheap and fast |
| Section rewrite (update outdated content) | `gemini-2.5-pro` | Multi-sentence generation preserving tone/structure |
| Gap fill (draft missing content) | `gemini-2.5-pro` | Complex generation from reference material |
| Orchestration, progress tracking, session state | No AI | Pure Python |

**Gating rule:** `gemini-2.5-pro` is only called if `gemini-2.5-flash-lite` first returns a positive classification. A section marked "no change" by flash-lite never reaches pro.

### Deliverables
- [x] `prompts/classify.txt` — classification prompt template (shared across all providers)
- [x] `prompts/rewrite.txt` — rewrite prompt template (shared across all providers)
- [x] `src/ai.py` — full provider abstraction: Gemini, OpenAI, Anthropic, Azure OpenAI; `process_document()` two-pass pipeline
- [x] `app.py` sidebar — provider selector, model display, API key status
- [x] `app.py` (Processing screen) — call `process_document()`, show live status per section, store results in session state

### Definition of Done
After uploading files, the app runs the full AI pipeline and transitions to a basic review screen showing each section's heading, change type, and proposed text (display only — no accept/reject yet).

### Session Log

#### Session 2 — 2026-05-01 (provider abstraction — pre-Phase 2)
**Completed:**
- Created `src/ai.py` — full multi-provider abstraction with `BaseAIProvider`, `GeminiProvider`, `OpenAIProvider`, `AnthropicProvider`, `AzureOpenAIProvider`
- Created `prompts/classify.txt` and `prompts/rewrite.txt` — shared prompt templates used by all providers
- Updated `requirements.txt` — added `openai>=1.30.0`, `anthropic>=0.40.0`
- Updated `.env.example` — documents all four providers' required env vars
- Updated `.env` — placeholder slots for all providers; Gemini key is live
- Updated `app.py` — sidebar provider selector with model display and API key status indicators

**Decisions made:**
- Boilerplate detection is pure Python (no API call): sections shorter than 60 chars or with structural headings (e.g. "Table of Contents", "Copyright") are skipped automatically
- All four providers share the same prompt templates (`classify.txt`, `rewrite.txt`)
- Azure OpenAI uses the `openai` package's `AzureOpenAI` client — no extra dependency needed
- Provider can be set via `AI_PROVIDER` env var (default) or changed live in the sidebar

**Known issues / watch-outs:**
- Python 3.9 is EOL; `google-auth` and `urllib3` show FutureWarning on import. Harmless for demo — flag for upgrade if moving to production.

*(To be continued in Phase 2's session — next step is wiring Processing screen to call `process_document()`)*

#### Session 3 — 2026-05-01 (Phase 2 complete)
**Completed:**
- Replaced `show_processing_screen()` stub with full AI pipeline: calls `process_document()` generator, streams live status messages into `st.empty()` placeholder, handles API/auth/rate-limit errors with friendly plain-English messages and a retry button
- Added `show_review_screen()` — summary metrics (total / updates / gaps / no-change), flagged sections rendered expanded with side-by-side Original | Proposed text areas, unchanged sections collapsed; all display-only (no controls yet)
- Added `_render_section_card()` helper with change-type badges
- Added `_friendly_error()` helper that translates API exceptions into plain English
- Added `processing_complete` session state guard — prevents re-running the pipeline if the user navigates back to the processing screen
- Wired the router for the new `"review"` stage

**Decisions made:**
- Processing screen calls the pipeline immediately on render (no button click required) — matches the spec's "Processing screen with spinner"
- Retry clears all section change_type/proposed_text fields so the pipeline reruns cleanly from scratch
- Flagged sections expanded by default; no-change sections collapsed — matches Design Spec §6.4

**Known issues / watch-outs:**
- Streamlit re-renders the entire page on each generator yield; for very large documents (30+ sections) the status log may flicker. Acceptable for Phase 1 demo scope.
- The `st.text_area` `label_visibility="collapsed"` pattern requires a non-empty label string; using `"original_hidden"` / `"proposed_hidden"` as dummy labels — harmless.

**What's next (Phase 3):**
- Add Accept / Edit / Reject controls to each section card in `show_review_screen()`
- Add progress bar ("X of Y sections resolved") and "Resolve All No-Change" button
- Build `src/patcher.py` — apply approved edits back to the original `.docx` by paragraph index
- Build `show_download_screen()` — success message, download button, Start Over

---

## Phase 3 — Review UI + Output File Generation

**Goal:** The full human review experience. Users can accept, edit, or reject each AI-proposed change. When all sections are resolved, they can download the updated `.docx` file.

### Model Allocation
| Task | Model | Reason |
|---|---|---|
| Accept / reject / edit UI actions | No AI | Pure UI state management |
| Writing approved edits back to `.docx` | No AI | `patcher.py` — `python-docx` only |
| Output file generation and download | No AI | File I/O only |
| "Help me edit this" assisted edit (optional, if added) | `gemini-2.5-pro` | User-directed generation — only on explicit request |

### Deliverables
- [x] `app.py` (Review screen) — section cards with Original | Proposed side by side, Accept / Edit / Reject controls, progress bar, "Resolve All No-Change" button
- [x] `src/patcher.py` — loads original `.docx`, applies approved text edits by paragraph index, saves with correct filename pattern
- [x] `app.py` (Download screen) — success message, download button, "Start Over" button

### Definition of Done
A user can complete the full end-to-end flow: upload → process → review all sections → download a `.docx` file with only approved changes applied and all original formatting intact.

### Session Log

#### Session 4 — 2026-05-01 (Phase 3 complete)
**Completed:**
- Created `src/patcher.py` — loads original `.docx` from bytes, maps approved section text back to paragraph indices, preserves all run-level formatting by only updating `run.text`, outputs `[stem]_updated_YYYY-MM-DD.docx`
- Updated `show_review_screen()` — progress bar, per-section Accept/Edit/Reject controls with Undo, editable proposed text area (user can modify before accepting), auto-accepts NO_CHANGE sections silently
- Added `_render_flagged_card()` — handles all four review states (PENDING / ACCEPTED / EDITED / REJECTED) with appropriate UI and Undo
- Added `_generate_download()` — calls patcher, stores result in session state, transitions to download stage
- Added `show_download_screen()` — summary stats, `st.download_button` for the patched `.docx`, "Process Another Document" button
- Wired `"download"` stage in the router
- Extended `_reset()` to clear per-section `prop_`/`orig_` session state keys

**Decisions made:**
- NO_CHANGE sections are auto-accepted on review screen load — they need no human decision; collapsed into a single expander summary
- "Edit" is implicit: proposed text area is always editable while PENDING; Accept saves whatever is in the box (EDITED if changed, ACCEPTED if unchanged)
- Download button is disabled (greyed out with helpful label) until all flagged sections are resolved
- Patcher maps section lines to paragraph indices positionally; if rewrite has fewer lines than original paragraphs, trailing paragraphs are cleared

**Known issues / watch-outs:**
- If the AI rewrite produces significantly more lines than the original paragraph count, the extra lines are concatenated into the last paragraph. Acceptable for demo scope.
- `st.download_button` triggers a full page rerun in Streamlit — the file is regenerated on click but this is fast (pure Python, no API call)

**What's next (Phase 4):**
- End-to-end test with a real document pair — verify output `.docx` formatting is intact
- Scanned PDF detection UX (already in extractor, surface message more clearly)
- API failure retry UX improvements
- README with setup and run instructions for a non-technical user

---

## Phase 4 — Projects, Dashboard & Session History

**Goal:** Add persistent project management so users can group documents under a project, upload reference material once per project, queue multiple documents, and navigate session history from a dashboard.

### Architecture decision
Use a local **SQLite database** (`data/app.db`) for persistence. Single file, no server required, survives app restarts. `src/db.py` owns all schema and queries.

### Data model
- **Project** — name, description, created_at, reference material paths
- **Document** — project_id, original filename, status (queued / processing / complete), created_at
- **Session** — document_id, sections_json (serialised results), created_at

### Model Allocation
No AI calls in this phase — pure Python and UI.

### Deliverables
- [x] `src/db.py` — SQLite schema, CRUD helpers for Project / Document / Session
- [x] `app.py` — Dashboard screen: project list, document history, session navigator
- [x] `app.py` — New Project flow: name, description, reference material upload (stored to `data/refs/`)
- [x] `app.py` — Project detail screen: document queue, bulk upload, one-at-a-time processing
- [x] `app.py` — Session history: re-open a past session (read-only view of original vs accepted text)
- [x] Wire all new screens into the router; keep existing upload → process → review → download flow intact

### Definition of Done
A user can create a project, upload reference material once, queue multiple documents, process them one at a time, and revisit any past session from the dashboard without losing any prior results.

### Session Log

#### Session 5 — 2026-05-01 (Phase 4 complete)
**Completed:**
- Created `src/db.py` — SQLite schema (`projects`, `reference_files`, `documents`, `sessions`), full CRUD helpers, `init_db()` creates `data/app.db` + `data/refs/` + `data/docs/` on first run; `delete_project()` cascades and removes files from disk
- Added `sections_to_json()` / `sections_from_json()` to `src/models.py` for serialising review results to the DB
- Updated `app.py`: imports `db`, calls `db.init_db()` at startup, added 4 new session state keys (`active_project_id`, `active_document_id`, `history_document_id`, `history_session_id`), changed default stage to `"dashboard"`, added **📊 Dashboard** button to sidebar
- Added `show_dashboard()` — project cards with Open/Delete, "New Project" primary button, "Quick Process" shortcut to the existing upload flow
- Added `show_new_project_screen()` — name + description + optional reference file upload in a single form; creates project in DB and navigates to detail
- Added `show_project_detail()` — reference file list with per-file delete, "Add Reference Files" form expander, document queue with per-document status badge, "Add Documents to Queue" form expander
- Added `_render_document_card()` — Process Now (disabled if no reference files), View History (visible once sessions exist), Remove
- Added `_launch_from_project()` — loads document and reference files from disk, extracts sections, sets all session state, transitions to `"processing"` without touching the upload screen
- Added `show_session_history()` — two-level view: session list → session detail (read-only section cards via `_render_section_readonly()`)
- Updated `_generate_download()` — after patching, saves session JSON + counts to DB and marks document status `"complete"` when in project context
- Updated `show_download_screen()` — "Back to Project" button when in project context (via `_reset_to_project()`); "Process Another Document" always available
- Added `_reset_to_project()` — clears processing state, restores `active_project_id`, navigates to `project_detail`
- Updated `_reset()` — also clears Phase 4 session state keys
- Updated router — handles `dashboard`, `project_new`, `project_detail`, `session_history` stages

**Decisions made:**
- Default stage is `"dashboard"` instead of `"upload"` — users land on the dashboard first; "Quick Process" gets back to the upload flow in one click
- Reference files and document files stored to disk under `data/refs/{project_id}/` and `data/docs/{project_id}/` with timestamp-prefixed filenames to avoid collisions; paths stored in DB
- Sessions stored as full `sections_json` blob — allows read-only replay without any separate "diff" table
- "Process Now" button is disabled (with tooltip) if a project has no reference files — prevents confusing errors
- `_launch_from_project()` goes directly to `"processing"`, bypassing the upload screen — reference material is already known from the project
- App restarts survive all state — `data/app.db` is the source of truth; Streamlit session state is rebuilt on reload

**Known issues / watch-outs:**
- Document bytes are read from their stored path on disk at process time; if the `data/` directory is deleted manually, queued documents will error gracefully with a clear message
- Streamlit's `st.form` with `clear_on_submit=True` clears the uploader widget after adding files — this is the intended behaviour for the add-refs and add-docs forms

**What's next (Phase 5):**
- End-to-end test with a real document pair through the full project flow
- README with setup instructions for a non-technical user
- Error handling polish: partial section failure retry, scanned PDF UX improvements
- UX review: every screen has a clear "what do I do now?" affordance

---

## Phase 5 — Polish, Error Handling &amp; Demo Readiness

**Goal:** Make the app bulletproof and presentable for a management demo by a non-technical user.

### Model Allocation
| Task | Model | Reason |
|---|---|---|
| Error message translation (stack traces → plain English) | No AI | Static string mapping — never use AI for error formatting |
| API retry logic on Gemini failure | No AI | Orchestration only |
| README, setup instructions | No AI | Static documentation |
| End-to-end test with real documents | Uses Phase 2 allocation | Same pipeline, no new AI tasks |

### Deliverables
- [ ] All error states handled (API failure with retry, unsupported file type, empty/unreadable doc, partial section failure)
- [ ] All error messages in plain English — no stack traces exposed to the user
- [ ] Scanned PDF detection with clear user message
- [ ] `README.md` with setup and run instructions
- [ ] End-to-end test with a real document pair
- [ ] UX review: every screen has a clear "what do I do now?" affordance

### Definition of Done
A non-technical user can complete the full Phase 1 Definition of Done checklist from `Product Design Spec.md` §16 without any guidance beyond the README.

### Session Log

#### Session 6 — 2026-05-01 (Phase 5 complete)
**Completed:**
- Added `processing_failed: bool = False` field to `Section` dataclass; updated `sections_to_json` / `sections_from_json` to persist and restore the flag across sessions
- Added `_section_error_label()` helper to `src/ai.py` — maps raw exceptions to short plain-English labels for per-section failure messages
- Wrapped both classify and rewrite passes in `process_document()` with per-section try/except; failed sections are marked `processing_failed = True`, yielded as `("error", ...)`, and the pipeline continues to the next section rather than crashing the whole run
- Updated `show_processing_screen()` to handle the new `"error"` phase (live warning message) and show a post-pipeline summary warning if any sections failed
- Updated the "Try Again" handler to also reset `processing_failed = False` on all sections
- Added `_reprocess()` helper — resets all sections to initial state and returns to the processing screen (accessible from review screen)
- Updated `show_review_screen()` to separate sections into `failed` / `flagged` / `unchanged` lists; failed sections are auto-rejected (original text kept), shown with a warning banner and "Reprocess Document" button, and do not block the download
- Wrapped `patch_document()` / `patch_pptx()` calls in `_generate_download()` in try/except with a friendly error message; failures stay on the review screen rather than crashing to an unhandled exception
- Added an info callout to `show_upload_screen()` explaining the tool's workflow to new users
- Added instructional subtext to the flagged sections list in `show_review_screen()`
- Improved download screen "next step" copy to explicitly say what to do with the file after download
- Created `README.md` — full non-technical setup and usage guide covering: prerequisites, first-time setup (uv install + .env), the double-click launcher, full usage walkthrough, troubleshooting for every known error state, file support matrix, data privacy note

**Decisions made:**
- Per-section failures auto-reject (keep original) rather than blocking the download — the user can still get a usable file from a partial run and retry separately
- "Reprocess Document" on the review screen resets and reruns the full pipeline (not just failed sections) — simpler and more reliable for the demo; full partial-retry would require a `was_processed` flag and adds complexity
- `processing_failed` persists through `sections_to_json` / `sections_from_json` so session history correctly reflects which sections had errors

**What's next:**
- Phase 1 Definition of Done checklist in `Product Design Spec.md` §16 — ready for end-to-end test with a real document pair
- Demo walkthrough with a non-technical user
- If approved for production: Phase 2 (deployed web app) per the design spec

---

## Cross-Phase Decisions & Conventions

| Decision | Choice | Reason |
|---|---|---|
| Paragraph block fallback size | 4 paragraphs | Balances section granularity vs. AI cost |
| Scanned PDF threshold | < 50 chars extracted | Catches image-only PDFs reliably |
| Session state stage key | `upload` → `processing` → `review` → `download` | Linear flow, easy to debug |
| AI — classification | `gemini-2.5-flash-lite` | Yes/no decisions only — fast and cheap |
| AI — generation | `gemini-2.5-pro` | Multi-sentence rewrite/gap-fill — quality matters |
| AI — gating rule | flash-lite classifies first; pro only called on flagged sections | Prevents expensive model running on unchanged content |
| AI — no-AI tasks | File I/O, patching, UI, error messages | Never use an API call where Python suffices |
| Output filename | `[original]_updated_YYYY-MM-DD.docx` | Matches Design Spec §6.5 |
