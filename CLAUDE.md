# TD Collateral Modernizer — Project Instructions

## What This Project Is

An internal tool for modernizing product collateral. It takes outdated Word/PPT/PDF documents alongside updated internal specs and uses AI (Claude) to draft content updates while preserving the existing look, branding, and structure. A human reviews every AI-drafted change before a final file is produced.

## Tech Stack

| Layer | Tool | Why |
|---|---|---|
| UI | Streamlit (Python) | Runs in browser locally, zero frontend coding needed |
| AI | Google Gemini API (`google-genai` SDK) | High-quality document understanding and rewriting |
| Word files | `python-docx` | Read and write .docx without opening Word |
| PPT files | `python-pptx` | Read and write .pptx |
| PDF reading | `pdfplumber` | Extract clean text from PDF source docs |
| Env vars | `python-dotenv` | Load `GEMINI_API_KEY` from `.env` file |
| Package mgr | `uv` | Fast, simple Python dependency management |

## Project Structure

```
TD Collateral Modernizer/
├── CLAUDE.md                  ← this file
├── Product Design Spec.md     ← plain-English design spec
├── app.py                     ← Streamlit app entry point
├── src/
│   ├── extractor.py           ← pulls text/structure from source documents
│   ├── ai.py                  ← Claude API calls, prompt logic
│   ├── patcher.py             ← applies approved edits back into Word/PPT files
│   └── models.py              ← data models: Section, ChangeType, ReviewState
├── prompts/
│   ├── classify.txt           ← Haiku classification prompt template
│   └── rewrite.txt            ← Sonnet rewrite prompt template
├── .env.example               ← shape of required env vars (no secrets)
├── .env                       ← actual secrets (gitignored)
├── .gitignore
├── requirements.txt
└── README.md                  ← setup and run instructions
```

## Key Commands

```bash
# Install dependencies (first time)
python3 -m pip install uv          # install uv if not present
python3 -m uv venv .venv           # create virtual environment
python3 -m uv pip install -r requirements.txt --python .venv/bin/python3

# Run the app
source .venv/bin/activate
streamlit run app.py

# Run with specific port (for demos)
streamlit run app.py --server.port 8080
```

## Critical Rules

- **Never commit `.env`** — it contains the Gemini API key. `.gitignore` must cover it.
- **AI drafts, human approves** — the tool must never auto-apply changes without a human reviewing each section.
- **Preserve formatting** — updates touch text content only. Do not alter styles, fonts, colors, or layout.
- **No data leaves the machine** — source documents and generated content stay local. Nothing is sent to external servers except the text sent to the Gemini API.
- **No `any` in TypeScript** — N/A for this project (Python only), but maintain strict type hints where used.

## AI Model Allocation

**Rule:** never send a task to a more capable (expensive) model than the task requires. Only `gemini-2.5-pro` calls cost real tokens for generation — gate every `pro` call behind a `flash-lite` classification first.

### No AI — pure Python (zero API cost)
These tasks must never make an API call:
- File type validation and upload handling
- `.docx` parsing and section splitting (`extractor.py`)
- PDF text extraction and scanned-PDF detection (`pdfplumber`)
- Writing approved edits back to `.docx` (`patcher.py`)
- All UI state transitions, progress tracking, download generation
- Session history and audit logging (Phase 2+)
- SharePoint file browse/save (Phase 3)

### `gemini-2.5-flash-lite` — fast, cheap (simple decisions only)
Use for any task that produces a short, structured answer (yes/no, a label, a single sentence):
- **Section classification:** "Is this section outdated given the reference material? Answer yes or no, then one sentence explaining why."
- **Gap detection:** "Does the reference material contain information on topics entirely absent from this section? Answer yes or no."
- **Boilerplate detection:** "Does this section contain meaningful product content (not a copyright notice, table of contents entry, or page header)? Answer yes or no." — skip boilerplate sections entirely to avoid wasting pro tokens.

### `gemini-2.5-pro` — high quality (complex generation only)
Use only when generating multi-sentence content that must match an existing document's tone and structure. Always gated behind a `flash-lite` classification — `pro` is never called on a section unless `flash-lite` confirmed it needs work:
- **Section rewrite:** produce updated content that preserves original sentence structure, length, and tone while reflecting new reference material.
- **Gap fill:** draft new content for a topic present in the reference material but absent from the document section.
- **Phase 2+ — multi-file synthesis:** when multiple reference files are provided, `pro` reconciles conflicting information across sources before drafting.
- **Phase 3 — assisted edit:** if a user clicks "Help me edit this" on a proposed section, `pro` produces an alternative draft based on user instructions.

### Prompt construction rules (all models)
- Pass the full reference material **once** as a system-level context block. Never repeat it per section.
- Pass each document section as a separate user-level query against that shared context.
- Instruct the model explicitly to preserve original sentence structure and length — this is a content update, not a rewrite.
- API key env var: `GEMINI_API_KEY`. SDK: `google-genai` (not the legacy `google-generativeai`).

## Session Protocol

- **Start of session:** Check `Product Design Spec.md` for current phase and what was last completed.
- **End of session:** Update `Product Design Spec.md` with what was completed and what's next. Update `CHANGELOG.md` if a feature shipped.
- **Before any commit:** Run `git status` and verify no `.env` or credential files are staged.

## Subagent Policy

- Use **Haiku** for: file discovery, codebase exploration, quick lookups.
- Use **Sonnet** for: implementation, AI prompt writing, document logic.
- Keep subagents scoped to one task. Never give a subagent ambiguous multi-step work.

## Deployment (if approved post-demo)

- Backend (FastAPI version): Render starter plan
- Frontend (React version): Cloudflare Pages free tier
- For demo phase: run locally with `streamlit run app.py`

## Identity

- Git author: **SystemZeroized** / `258656414+SystemZeroized@users.noreply.github.com`
- Never use real name in commits, code, or package metadata.
