# Product Design Spec
## TD Collateral Modernizer

**Version:** 1.0  
**Date:** 2026-04-30  
**Status:** Ready for development

---

## 1. Overview

This is an internal productivity tool for modernizing product collateral documents. The organization has 50–200 outdated product documents (brochures, user guides, proposals) stored in SharePoint. The content inside them is stale — products have changed, messaging has shifted, information is missing — but the visual design and branding remain valid and should be preserved.

The tool allows a non-technical user to upload an old document alongside updated reference material (a new product spec, updated brief, etc.), have an AI draft content updates, review every proposed change, approve or edit them, and download a final updated file ready for management sign-off.

**The AI is a drafting assistant, not an autonomous editor.** Every change requires explicit human approval before it is written to the output file.

---

## 2. Problem Statement

**The pain:** Updating 50–200 documents manually would take hundreds of hours. Hiring a contractor is expensive. The existing tools available on the organization's work devices (Microsoft Copilot) are not capable of this kind of structured, document-level content modernization.

**The constraint:** The user cannot install arbitrary software on their work device. The tool must run on a personal computer for the demo phase, then be accessible via a web browser for team use.

**The goal:** Build a working demo that management can evaluate. If approved, expand to a deployed web application with broader team access.

---

## 3. User Persona

**Primary user:** A non-technical business professional responsible for maintaining product collateral.

- Comfortable with Microsoft Office (Word, PowerPoint, SharePoint)
- Not comfortable with code, terminal commands, or developer tools
- Will use the tool independently after a brief onboarding
- Cannot approve their own content — has a management sign-off requirement

**Secondary users (Phase 2+):** A small team of 2–5 people in the same role.

---

## 4. Scope

### In Scope — Phase 1 (Demo)
- Upload one document at a time (Word `.docx` input and output)
- Upload one or more reference files (Word `.docx`, or PDF as reference material)
- AI identifies outdated or incomplete sections and drafts replacements
- Side-by-side review UI: original vs. proposed, section by section
- Accept / edit / reject controls per section
- Download the final updated `.docx` file
- Runs locally on a personal computer

### In Scope — Phase 2 (Web App)
- Deployed web application (no install required — accessible via browser link)
- PowerPoint `.pptx` input and output support
- Batch processing (multiple documents in one session)
- Session history / audit log (who changed what, when)
- Basic user accounts (email + password or Google SSO)

### In Scope — Phase 3 (SharePoint Integration)
- Browse SharePoint/OneDrive to select files directly
- Save updated files back to SharePoint
- In-tool approval workflow to replace email-based management sign-off

### Out of Scope (all phases)
- Redesigning document visual layout, fonts, colors, or branding
- Auto-publishing or auto-distributing documents
- Working with scanned PDFs (image-only, no text layer)
- Real-time collaboration / multi-user simultaneous editing
- Translation or multi-language support
- Integration with any system other than SharePoint (Phase 3 only)

---

## 5. Core User Flow

```
[User opens app in browser]
        ↓
[Upload: old document + new reference material]
        ↓
[Optional: add a plain-English note about what changed]
        ↓
[App processes documents — progress indicator shown]
        ↓
[Review screen: list of sections, each with Original | Proposed]
        ↓
    For each section:
    ┌─ Accept (use AI's version)
    ├─ Edit   (modify AI's version before accepting)
    └─ Reject (keep original)
        ↓
[All sections resolved → Download updated .docx file]
        ↓
[User takes file through their normal management approval process]
```

---

## 6. Functional Requirements

### 6.1 Document Upload
- Accept `.docx` as the primary document type (Phase 1)
- Accept `.pptx` (Phase 2)
- Accept `.pdf` for reference material only (the tool reads it but does not output PDF)
- Validate file type on upload — show a clear error for unsupported formats
- Detect and warn if a PDF has no readable text layer ("This PDF appears to be a scanned image. Please provide a text-based PDF or Word document.")
- No file size enforcement in Phase 1 (local app), cap at 20MB in Phase 2

### 6.2 Optional Context Note
- A plain-text input field where the user can describe what has changed: e.g., "We launched a new pricing tier in Q1. The product name changed from X to Y."
- This note is passed to the AI as additional context. It is not required.

### 6.3 AI Processing
- The app reads the old document section by section (by heading/paragraph blocks)
- The app reads the full reference material as context
- For each section of the old document, the AI determines:
  1. **No change needed** — content is still accurate
  2. **Update needed** — content is outdated; AI drafts a replacement
  3. **Gap identified** — a topic exists in the reference material that is absent from this section; AI drafts an addition
- Sections flagged as "no change needed" are collapsed by default in the review screen
- The AI must be instructed to preserve the original sentence structure and length as closely as possible — this is a content update, not a rewrite

### 6.4 Review Interface
- Sections are listed in document order
- Each section shows:
  - **Section heading** (e.g., "Product Overview", "Key Features")
  - **Change type badge:** No Change / Updated / Gap Filled
  - **Original text** (left pane or top)
  - **Proposed text** (right pane or bottom) — editable inline
  - **Accept / Edit / Reject** controls
- "No Change" sections are collapsed but expandable
- A progress indicator shows how many sections have been resolved vs. total
- A "Resolve All No-Change Sections" button accepts all unchanged sections at once

### 6.5 Output
- When all sections are resolved, enable the "Download Updated File" button
- Output file is a `.docx` (Phase 1) or `.pptx` (Phase 2)
- The output preserves all original formatting: styles, fonts, colors, images, tables, page layout
- Only the text content of approved sections is modified
- File is named: `[original_filename]_updated_[YYYY-MM-DD].docx`

### 6.6 Error States
- API failure (Claude unavailable): show a retry option, do not lose the uploaded files
- Unsupported file type: clear message before processing begins
- Empty document or unreadable content: warn the user before proceeding
- Partial failure (some sections processed, some not): flag the failed sections clearly; allow the user to retry those sections only

---

## 7. Technical Architecture

### Phase 1 — Local Application

```
┌─────────────────────────────────┐
│         Browser (localhost)     │
│                                 │
│    Streamlit UI (Python)        │
│    ┌───────────┬─────────────┐  │
│    │ Upload    │ Review      │  │
│    │ Panel     │ Panel       │  │
│    └───────────┴─────────────┘  │
└────────────┬────────────────────┘
             │ (same process)
┌────────────▼────────────────────┐
│         Core Python App         │
│                                 │
│  extractor.py  → parse docs     │
│  ai.py         → Claude calls   │
│  patcher.py    → write output   │
│  diff.py       → change display │
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│         Claude API              │
│    (Anthropic, external)        │
└─────────────────────────────────┘
```

### Phase 2 — Deployed Web Application

```
  User's Browser
       │
       ▼
  Cloudflare Pages          ← React/TypeScript frontend
       │
       ▼ (HTTPS API calls)
  Render (FastAPI)          ← Python backend
       │
       ├──► Claude API      ← AI processing
       │
       └──► File storage    ← Temporary session files (in-memory or Render disk)
```

---

## 8. Tech Stack

### Phase 1

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for document manipulation and AI SDKs |
| UI framework | Streamlit | Turns Python into a browser app with zero frontend code |
| AI | Anthropic Python SDK (`anthropic`) | Direct access to Claude models |
| Word handling | `python-docx` | Read/write `.docx` without COM automation or Word install |
| PPT handling | `python-pptx` | Read/write `.pptx` (Phase 2, but install from Phase 1) |
| PDF reading | `pdfplumber` | Reliable text extraction from text-layer PDFs |
| Env management | `python-dotenv` | Load `ANTHROPIC_API_KEY` from `.env` file |
| Package management | `uv` or `pip` | `uv` preferred for speed |

### Phase 2 Additions

| Component | Technology | Rationale |
|---|---|---|
| Frontend | React + TypeScript + Tailwind CSS | Modern, maintainable, easy to style |
| UI components | shadcn/ui | Pre-built accessible components |
| Backend | FastAPI (Python) | Lightweight, async-capable API layer |
| Hosting (frontend) | Cloudflare Pages | Free tier, global CDN, auto-deploys from git |
| Hosting (backend) | Render starter plan | Simple deploys, reasonable free/starter tier |
| Auth | Clerk or Supabase Auth | Managed auth, supports Google SSO |

---

## 9. AI Integration Design

### Model Selection
- **Content analysis and rewriting:** `claude-sonnet-4-6` — best balance of quality and cost for document work
- **Classification only** (is this section outdated? yes/no): `claude-haiku-4-5` — cheaper, faster, sufficient for binary decisions

### Processing Strategy

Documents are processed **section by section**, not as a whole. This:
- Avoids hitting context limits on long documents
- Makes the review UI map cleanly to document structure
- Allows partial failure/retry without reprocessing the entire document

**Step 1 — Classification pass (Haiku)**
For each section: *"Is this content outdated or incomplete given the reference material? Answer yes or no and in one sentence explain why."*

**Step 2 — Rewrite pass (Sonnet, only for flagged sections)**
For each section flagged in Step 1: *"Rewrite this section to reflect the updated information. Preserve the original tone, length, and structure as closely as possible. Do not add new headings or change formatting."*

### Prompt Construction

The reference material is passed once as a system-level context block. Each section of the old document is then passed as a user-level query against that context. This avoids re-sending the reference material for every section.

```
System:
  You are a professional document editor. The following is the updated 
  reference material for [product name]. Use it as the source of truth 
  for all facts, features, and messaging.
  
  [REFERENCE MATERIAL TEXT]
  
  Additional context from the user: [optional user note]

User (per section):
  Here is a section from the existing document. Rewrite it to reflect 
  the current information in the reference material. Preserve the 
  original structure and tone. Only change what is factually outdated 
  or missing.
  
  SECTION HEADING: [heading]
  ORIGINAL TEXT:
  [section text]
```

### Cost Estimates (Claude API)

| Document length | Approx. API cost |
|---|---|
| Short (1–5 pages) | $0.10–$0.40 |
| Medium (5–15 pages) | $0.40–$1.50 |
| Long (15–30 pages) | $1.50–$3.00 |

These are estimates based on `claude-sonnet-4-6` pricing as of 2026. Costs scale with document length and number of sections requiring rewrite.

---

## 10. Document Handling

### Reading `.docx` files
- Parse using `python-docx`
- Split into sections by heading level (Heading 1, Heading 2)
- If no headings exist, split by paragraph blocks (every N paragraphs)
- Preserve the original `Document` object in memory — do not recreate it from scratch

### Reading reference PDFs
- Extract full text using `pdfplumber`
- Strip headers, footers, and page numbers where detectable
- Pass as a single text block to the AI — do not attempt to split PDFs into sections

### Writing output `.docx`
- Load the original document object
- For each approved or edited section: locate the corresponding paragraphs by position index and update their `.text` property
- Do **not** change `paragraph.style`, `run.font`, or any formatting properties
- Save with the new filename pattern

### Edge Cases
- Tables: extract table cell text for AI review, write back only cell text
- Images: pass through untouched — never send image data to the AI
- Text boxes (in Word): attempt to extract and include, note in UI if not supported
- Headers/footers: exclude from AI review (they are branding elements)

---

## 11. UI/UX Requirements

### General Principles
- Designed for a non-technical user — no jargon, no raw error codes
- Every state has a clear next action ("What do I do now?")
- Progress is always visible — the user knows where they are and what's left
- Destructive actions (reject, overwrite) require a confirmation or are reversible within the session

### Phase 1 Screen Inventory

**Screen 1: Upload**
- Drop zone for the old document
- Drop zone for reference material (accepts multiple files)
- Optional text area: "What has changed? (optional)"
- "Process Documents" button — disabled until both required files are uploaded

**Screen 2: Processing**
- Spinner with status messages ("Reading your document...", "Analyzing sections...", "Drafting updates...")
- No cancel button in Phase 1 (acceptable for demo)

**Screen 3: Review**
- Top: summary bar — "12 sections found · 4 need updates · 1 gap identified · 0 resolved"
- Section list below, in document order
- Each section card:
  - Header row: section title + change type badge (color-coded: gray = no change, amber = update, blue = gap)
  - Collapsible body showing Original | Proposed side by side
  - Accept / Edit / Reject buttons
  - "No Change" sections collapsed by default
- Sticky bottom bar: "X of Y sections resolved" + "Download File" button (disabled until all resolved)

**Screen 4: Download**
- Success message
- Download button
- "Start Over" button to process another document

### Accessibility
- All interactive elements keyboard accessible
- Color-coded badges also have text labels (do not rely on color alone)
- Readable at 100% zoom on a standard 1080p display

---

## 12. File & Project Structure

```
td-collateral-modernizer/
├── app.py                  ← Streamlit entry point
├── src/
│   ├── extractor.py        ← parse .docx / .pdf into section objects
│   ├── ai.py               ← all Claude API calls and prompt logic
│   ├── patcher.py          ← apply approved edits back to .docx
│   └── models.py           ← data models: Section, ChangeType, ReviewState
├── prompts/
│   ├── classify.txt        ← Haiku classification prompt template
│   └── rewrite.txt         ← Sonnet rewrite prompt template
├── .env.example            ← ANTHROPIC_API_KEY=your_key_here
├── .env                    ← actual key (gitignored)
├── .gitignore
├── requirements.txt
└── README.md               ← setup and run instructions
```

---

## 13. Environment Setup (for the developer)

```bash
# Prerequisites: Python 3.11+, pip or uv

# Clone the repo
git clone <repo-url>
cd td-collateral-modernizer

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and add your Anthropic API key

# Run the app
streamlit run app.py
```

**Required environment variables:**
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 14. Key Constraints & Non-Negotiables

1. **Human approval is mandatory.** The tool must never write changes to the output file without explicit user acceptance of each changed section. This is a product principle, not a technical limitation.

2. **Formatting must be preserved.** The tool only modifies text content. It must not alter styles, fonts, colors, images, tables structure, or page layout. Any approach that rebuilds the document from scratch is unacceptable.

3. **No data persistence in Phase 1.** Uploaded files and generated content exist in memory only during the session. Nothing is written to disk except the final downloaded file. No database, no cloud storage.

4. **The user is not technical.** The interface must not expose any developer concepts (tokens, API responses, model names, errors as stack traces). All errors must be translated into plain English with a suggested action.

5. **Scanned PDFs are not supported.** If a PDF has no text layer, the tool must detect this and tell the user clearly rather than processing silently and returning garbage.

---

## 15. Open Questions for the Developer

These are decisions that were not resolved in the design phase and are left to developer judgment:

1. **Section splitting strategy:** For documents with no headings, what is the right paragraph block size? Suggested default: every 3–5 paragraphs, but this may need tuning per document type.

2. **Streaming vs. batch AI responses:** Should the review screen populate section by section as AI responses come in (streaming, better UX) or wait until all sections are processed before showing anything (simpler, acceptable for Phase 1)?

3. **Inline editing UX:** When a user clicks "Edit" on a proposed section, should the edit happen inline in the review card, or open a modal? Inline is simpler; modal gives more space for longer content.

4. **Handling very long sections:** If a single document section is extremely long (e.g., a 2,000-word user manual chapter), should it be split further for AI processing, or passed whole? Consider Claude's context window and the cost implications.

5. **Reference material structure:** The current design passes all reference material as a single text block. For Phase 2 with multiple reference files, should the AI be told which file each piece of context comes from? This may improve accuracy for documents that span multiple product lines.

---

## 16. Phase 1 Definition of Done

Phase 1 is complete when a non-technical user can:

- [ ] Launch the app with a single terminal command (`streamlit run app.py`)
- [ ] Upload a `.docx` document and a reference file (`.docx` or `.pdf`)
- [ ] See a review screen with all document sections listed
- [ ] Identify which sections the AI flagged for changes
- [ ] Read original vs. proposed text side by side
- [ ] Accept, edit, or reject each proposed change
- [ ] Download an updated `.docx` file with only approved changes applied
- [ ] Verify that the output file's formatting is visually identical to the original except for the updated text

---

*This document should be considered the authoritative design reference for Phase 1 development. Any significant deviations from this spec should be flagged to the product owner before implementation.*
