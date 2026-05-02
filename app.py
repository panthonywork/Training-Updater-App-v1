import os
import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

from src.ai import (
    AIProvider,
    PROVIDER_KNOWN_MODELS,
    PROVIDER_LABELS,
    PROVIDER_MODELS,
    PROVIDER_REQUIRED_KEYS,
    process_document,
    provider_is_configured,
)
from src.extractor import (
    extract_docx_sections,
    extract_pdf_sections,
    extract_pptx_sections,
    extract_reference_text,
)
from src.models import ChangeType, ReviewState, Section, sections_from_json, sections_to_json
from src.patcher import patch_document, patch_pptx
from src.reviewer import generate_review_document
from src import db

load_dotenv()
db.init_db()

st.set_page_config(
    page_title="TD Collateral Modernizer",
    page_icon="📄",
    layout="wide",
)

# ── Session state defaults ────────────────────────────────────────────────────
if "stage" not in st.session_state:
    st.session_state.stage = "dashboard"
if "sections" not in st.session_state:
    st.session_state.sections: list[Section] = []
if "reference_text" not in st.session_state:
    st.session_state.reference_text: str = ""
if "original_docx_bytes" not in st.session_state:
    st.session_state.original_docx_bytes: bytes = b""
if "original_filename" not in st.session_state:
    st.session_state.original_filename: str = ""
if "context_note" not in st.session_state:
    st.session_state.context_note: str = ""
if "processing_complete" not in st.session_state:
    st.session_state.processing_complete: bool = False
if "patched_bytes" not in st.session_state:
    st.session_state.patched_bytes: bytes = b""
if "output_filename" not in st.session_state:
    st.session_state.output_filename: str = ""
if "ai_provider" not in st.session_state:
    default = os.getenv("AI_PROVIDER", "gemini").lower()
    st.session_state.ai_provider = next(
        (p for p in AIProvider if p.value == default), AIProvider.GEMINI
    )
if "doc_format" not in st.session_state:
    st.session_state.doc_format: str = "docx"
# Phase 4 — project context
if "active_project_id" not in st.session_state:
    st.session_state.active_project_id = None
if "active_document_id" not in st.session_state:
    st.session_state.active_document_id = None
if "history_document_id" not in st.session_state:
    st.session_state.history_document_id = None
if "history_session_id" not in st.session_state:
    st.session_state.history_session_id = None


# ── Sidebar ───────────────────────────────────────────────────────────────────

def show_sidebar() -> None:
    with st.sidebar:
        if st.button("📊 Dashboard", use_container_width=True):
            for k in ("history_document_id", "history_session_id"):
                st.session_state.pop(k, None)
            st.session_state.stage = "dashboard"
            st.rerun()

        st.divider()
        st.header("AI Provider")

        provider_options = list(AIProvider)
        current_index = provider_options.index(st.session_state.ai_provider)

        selected = st.selectbox(
            "Select provider",
            options=provider_options,
            index=current_index,
            format_func=lambda p: PROVIDER_LABELS[p],
            label_visibility="collapsed",
        )
        st.session_state.ai_provider = selected

        st.divider()
        st.caption("**Model assignment**")

        defaults  = PROVIDER_MODELS[selected]
        known     = PROVIDER_KNOWN_MODELS[selected]
        classify_key = f"model_classify_{selected.value}"
        rewrite_key  = f"model_rewrite_{selected.value}"

        if classify_key not in st.session_state:
            st.session_state[classify_key] = defaults["classify"]
        if rewrite_key not in st.session_state:
            st.session_state[rewrite_key] = defaults["rewrite"]

        # Azure deployment names are user-defined — keep text inputs
        if selected == AIProvider.AZURE_OPENAI:
            st.session_state[classify_key] = st.text_input(
                "Classify deployment", value=st.session_state[classify_key], key=f"input_{classify_key}"
            )
            st.session_state[rewrite_key] = st.text_input(
                "Rewrite deployment", value=st.session_state[rewrite_key], key=f"input_{rewrite_key}"
            )
        else:
            classify_opts = known["classify"]
            rewrite_opts  = known["rewrite"]

            c_default = st.session_state[classify_key]
            r_default = st.session_state[rewrite_key]
            c_idx = classify_opts.index(c_default) if c_default in classify_opts else 0
            r_idx = rewrite_opts.index(r_default)  if r_default in rewrite_opts  else 0

            st.session_state[classify_key] = st.selectbox(
                "Classify model", options=classify_opts, index=c_idx, key=f"input_{classify_key}"
            )
            st.session_state[rewrite_key] = st.selectbox(
                "Rewrite model", options=rewrite_opts, index=r_idx, key=f"input_{rewrite_key}"
            )

        if selected == AIProvider.GEMINI:
            st.caption(
                "⚠️ **Free tier:** `gemini-1.5-flash` and `gemini-1.5-pro` work reliably. "
                "`gemini-2.5-*` models require allow-list or paid access."
            )

        st.divider()
        st.caption("**Your API key**")

        if selected == AIProvider.AZURE_OPENAI:
            st.caption("Azure OpenAI reads keys from the server environment.")
            configured = provider_is_configured(selected)
            st.caption("✅ Configured" if configured else "🔴 Missing — check server env vars")
        else:
            _KEY_PLACEHOLDERS = {
                AIProvider.GEMINI:    "AIza...",
                AIProvider.OPENAI:    "sk-...",
                AIProvider.ANTHROPIC: "sk-ant-...",
            }
            st.text_input(
                "Paste your API key",
                type="password",
                placeholder=_KEY_PLACEHOLDERS.get(selected, ""),
                label_visibility="collapsed",
                key=f"user_key_{selected.value}",
            )
            has_key = bool(st.session_state.get(f"user_key_{selected.value}", "").strip())
            if has_key:
                st.caption("✅ Key entered — ready to process")
            else:
                st.caption("🔴 Enter your key to process documents")


# ── Upload screen ──────────────────────────────────────────────────────────────

def show_upload_screen() -> None:
    st.title("TD Collateral Modernizer")
    st.write("Upload an outdated document and reference material. The AI will draft updates for your review.")

    st.info(
        "**How it works:** Upload the document you want to update (Word, PowerPoint, or PDF) "
        "and one or more reference files containing the latest information. "
        "The AI reads both, identifies what's outdated or missing, and drafts replacements — "
        "which you review and approve before anything is saved. **Nothing is changed without your sign-off.**",
        icon="ℹ️",
    )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Document to Update")
        old_doc = st.file_uploader(
            "Upload the outdated document",
            type=["docx", "pptx", "pdf"],
            key="upload_old_doc",
            label_visibility="collapsed",
        )
        if old_doc:
            st.caption(f"✅ {old_doc.name}")
            if old_doc.name.lower().endswith(".pdf"):
                st.caption("ℹ️ PDF mode: the review document will be generated for manual edits — no updated PDF is produced.")

    with col2:
        st.subheader("Reference Material")
        ref_files = st.file_uploader(
            "Upload updated reference material",
            type=["docx", "pdf"],
            accept_multiple_files=True,
            key="upload_ref_files",
            label_visibility="collapsed",
        )
        if ref_files:
            for f in ref_files:
                st.caption(f"✅ {f.name}")

    st.divider()

    st.subheader("What has changed? (optional)")
    context_note = st.text_area(
        "Describe any known changes — product names, new features, pricing updates, etc.",
        placeholder='e.g. "We launched a new pricing tier in Q1. The product name changed from Acme Pro to Acme Suite."',
        height=100,
        label_visibility="collapsed",
    )

    st.divider()

    ready = old_doc is not None and len(ref_files or []) > 0
    if st.button("Process Documents", disabled=not ready, type="primary", use_container_width=True):
        _start_processing(old_doc, ref_files, context_note)


def _start_processing(old_doc, ref_files, context_note: str) -> None:
    errors: list[str] = []
    ref_texts: list[str] = []

    st.session_state.original_docx_bytes = old_doc.read()
    st.session_state.original_filename = old_doc.name

    for ref_file in ref_files:
        with tempfile.NamedTemporaryFile(suffix=Path(ref_file.name).suffix, delete=False) as tmp:
            tmp.write(ref_file.read())
            tmp_path = Path(tmp.name)

        text, error = extract_reference_text(tmp_path)
        tmp_path.unlink(missing_ok=True)

        if error:
            errors.append(f"**{ref_file.name}:** {error}")
        else:
            ref_texts.append(f"--- {ref_file.name} ---\n{text}")

    if errors:
        for err in errors:
            st.error(err)
        return

    suffix = Path(old_doc.name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(st.session_state.original_docx_bytes)
        tmp_path = Path(tmp.name)

    sections, extract_error = _extract_primary_sections(tmp_path, suffix)
    tmp_path.unlink(missing_ok=True)

    if extract_error:
        st.error(extract_error)
        return
    if not sections:
        st.error("The uploaded document appears to be empty or could not be read. Please check the file and try again.")
        return

    st.session_state.sections = sections
    st.session_state.reference_text = "\n\n".join(ref_texts)
    st.session_state.context_note = context_note
    st.session_state.processing_complete = False
    st.session_state.doc_format = suffix.lstrip(".")
    st.session_state.stage = "processing"
    st.rerun()


def _extract_primary_sections(path: Path, suffix: str) -> tuple[list[Section], Optional[str]]:
    """Return (sections, error_message). error_message is None on success."""
    if suffix == ".docx":
        return extract_docx_sections(path), None
    if suffix == ".pptx":
        sections = extract_pptx_sections(path)
        return sections, None if sections else "No slides with body text found in this presentation."
    if suffix == ".pdf":
        return extract_pdf_sections(path)
    return [], f"Unsupported document type: '{suffix}'."


# ── Processing screen ──────────────────────────────────────────────────────────

def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    if "no" in msg.lower() and "api key provided" in msg.lower():
        return "No API key entered. Paste your key into the sidebar field before processing."
    if "api_key" in msg.lower() or "authentication" in msg.lower() or "401" in msg:
        return "Invalid API key. Double-check the key you entered in the sidebar."
    if "permission_denied" in msg.lower() or "403" in msg:
        return (
            "Access denied (403). The selected model is not available on your API plan or project. "
            "Try a different model — for Gemini free tier, use `gemini-1.5-flash` for both classify and rewrite."
        )
    if "not_found" in msg.lower() or "404" in msg:
        return "Model not found (404). Check the model name in the sidebar — it may be misspelled or unavailable in your region."
    if "503" in msg or "unavailable" in msg.lower():
        return "The API is temporarily overloaded (503). Click Try Again — it usually clears within a few seconds."
    if "rate_limit" in msg.lower() or "429" in msg:
        return "Rate limit reached. Wait a moment, then try again."
    if "quota" in msg.lower():
        return "API quota exceeded. Check your billing status with the AI provider."
    return f"Unexpected error: {msg}"


def show_processing_screen() -> None:
    provider = st.session_state.ai_provider

    if st.session_state.processing_complete:
        st.session_state.stage = "review"
        st.rerun()
        return

    user_key = st.session_state.get(f"user_key_{provider.value}", "")
    if not provider_is_configured(provider, user_key=user_key):
        st.error(
            f"No API key entered for **{PROVIDER_LABELS[provider]}**. "
            f"Paste your key into the sidebar field and try again."
        )
        if st.button("← Back to Upload"):
            st.session_state.stage = "upload"
            st.rerun()
        return

    classify_model = st.session_state.get(f"model_classify_{provider.value}", PROVIDER_MODELS[provider]["classify"])
    rewrite_model  = st.session_state.get(f"model_rewrite_{provider.value}",  PROVIDER_MODELS[provider]["rewrite"])
    PROVIDER_MODELS[provider]["classify"] = classify_model
    PROVIDER_MODELS[provider]["rewrite"]  = rewrite_model

    st.title("Analyzing Your Document")
    st.caption(
        f"Using **{PROVIDER_LABELS[provider]}** · "
        f"Classify: `{classify_model}` · "
        f"Rewrite: `{rewrite_model}`"
    )
    st.divider()

    sections = st.session_state.sections
    reference_text = st.session_state.reference_text
    context_note = st.session_state.context_note

    classify_ph = st.empty()
    summary_ph  = st.empty()
    rewrite_ph  = st.empty()

    pipeline_failed = False
    pipeline_error = ""

    error_ph = st.empty()

    try:
        for phase, msg in process_document(sections, reference_text, context_note, provider, api_key=user_key):
            if phase == "classify":
                classify_ph.markdown(f"🔍 **Classifying sections…** &nbsp; {msg}")
            elif phase == "summary":
                classify_ph.markdown(f"🔍 **Classification complete** &nbsp; {msg}")
                summary_ph.empty()
            elif phase == "rewrite":
                rewrite_ph.markdown(f"✏️ **Drafting rewrites…** &nbsp; {msg}")
            elif phase == "done":
                rewrite_ph.markdown("✏️ **Rewrites complete**")
            elif phase == "error":
                error_ph.warning(f"⚠️ Section skipped — {msg}")
    except Exception as exc:
        pipeline_failed = True
        pipeline_error = _friendly_error(exc)

    if pipeline_failed:
        st.error(f"Something went wrong during processing: **{pipeline_error}**")
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("Try Again", type="primary"):
                for s in sections:
                    s.change_type = ChangeType.NO_CHANGE
                    s.proposed_text = None
                    s.classify_reason = None
                    s.review_state = ReviewState.PENDING
                    s.processing_failed = False
                st.rerun()
        with col2:
            if st.button("← Start Over"):
                _reset()
    else:
        failed_count = sum(1 for s in sections if s.processing_failed)
        if failed_count:
            error_ph.warning(
                f"⚠️ **{failed_count} section(s) could not be analyzed** and will keep their original text. "
                "You can review and download the rest, or start over to try again."
            )
        st.session_state.processing_complete = True
        st.session_state.stage = "review"
        st.rerun()


# ── Review screen ──────────────────────────────────────────────────────────────

_BADGE: dict[ChangeType, str] = {
    ChangeType.UPDATE:    "🟡 Update Needed",
    ChangeType.GAP:       "🔵 Gap Identified",
    ChangeType.NO_CHANGE: "✅ No Change",
}


def _render_flagged_card(section: Section) -> None:
    """Render a section that needs review with Accept / Reject controls."""
    badge = _BADGE[section.change_type]
    resolved = section.review_state != ReviewState.PENDING

    with st.expander(f"**{section.heading}** — {badge}", expanded=not resolved):
        if section.classify_reason:
            st.caption(f"AI assessment: {section.classify_reason}")

        col_orig, col_prop = st.columns(2)

        with col_orig:
            st.markdown("**Original**")
            st.text_area(
                "orig_label",
                value=section.original_text,
                height=220,
                disabled=True,
                label_visibility="collapsed",
                key=f"orig_{section.index}",
            )

        with col_prop:
            if section.review_state == ReviewState.PENDING:
                st.markdown("**Proposed** — edit before accepting if needed")
                prop_key = f"prop_{section.index}"
                # Only set value on first render; after that session_state drives it
                if prop_key not in st.session_state:
                    st.session_state[prop_key] = section.proposed_text or ""
                st.text_area(
                    "prop_label",
                    height=220,
                    label_visibility="collapsed",
                    key=prop_key,
                )
                btn_a, btn_r = st.columns(2)
                with btn_a:
                    if st.button("✅ Accept", key=f"accept_{section.index}", type="primary", use_container_width=True):
                        edited = st.session_state.get(prop_key, "")
                        if edited.strip() == (section.proposed_text or "").strip():
                            section.review_state = ReviewState.ACCEPTED
                        else:
                            section.review_state = ReviewState.EDITED
                            section.final_text = edited
                        st.rerun()
                with btn_r:
                    if st.button("❌ Reject", key=f"reject_{section.index}", use_container_width=True):
                        section.review_state = ReviewState.REJECTED
                        st.rerun()

            elif section.review_state == ReviewState.ACCEPTED:
                st.markdown("**Proposed**")
                st.success("✅ Accepted")
                st.text_area(
                    "prop_label",
                    value=section.proposed_text or "",
                    height=220,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"prop_{section.index}",
                )
                if st.button("↩ Undo", key=f"undo_{section.index}"):
                    section.review_state = ReviewState.PENDING
                    st.rerun()

            elif section.review_state == ReviewState.EDITED:
                st.markdown("**Proposed** (edited)")
                st.success("✅ Accepted with edits")
                st.text_area(
                    "prop_label",
                    value=section.final_text or "",
                    height=220,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"prop_{section.index}",
                )
                if st.button("↩ Undo", key=f"undo_{section.index}"):
                    section.review_state = ReviewState.PENDING
                    section.final_text = None
                    st.rerun()

            elif section.review_state == ReviewState.REJECTED:
                st.markdown("**Proposed**")
                st.error("❌ Rejected — keeping original")
                st.text_area(
                    "prop_label",
                    value=section.proposed_text or "",
                    height=220,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"prop_{section.index}",
                )
                if st.button("↩ Undo", key=f"undo_{section.index}"):
                    section.review_state = ReviewState.PENDING
                    st.rerun()


def show_review_screen() -> None:
    sections: list[Section] = st.session_state.sections

    failed    = [s for s in sections if s.processing_failed]
    flagged   = [s for s in sections if s.change_type != ChangeType.NO_CHANGE and not s.processing_failed]
    unchanged = [s for s in sections if s.change_type == ChangeType.NO_CHANGE and not s.processing_failed]

    # Auto-accept no-change sections — they need no human decision
    for s in unchanged:
        if s.review_state == ReviewState.PENDING:
            s.review_state = ReviewState.ACCEPTED

    # Auto-reject failed sections — keep original text, user is warned below
    for s in failed:
        if s.review_state == ReviewState.PENDING:
            s.review_state = ReviewState.REJECTED

    resolved   = sum(1 for s in flagged if s.review_state != ReviewState.PENDING)
    total_flag = len(flagged)
    all_done   = resolved == total_flag

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("Review Proposed Changes")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Sections", len(sections))
    m2.metric("Needs Review", total_flag)
    m3.metric("Resolved", resolved)
    m4.metric("Remaining", total_flag - resolved)

    if total_flag > 0:
        st.progress(resolved / total_flag, text=f"{resolved} of {total_flag} flagged sections resolved")
    elif not failed:
        st.success("No sections required changes — your document is already up to date.")

    # ── Failed sections warning ────────────────────────────────────────────────
    if failed:
        st.warning(
            f"⚠️ **{len(failed)} section(s) could not be analyzed** due to an AI processing error. "
            "Their original text will be kept. You can download the document as-is, "
            "or click **Reprocess Document** to try the full pipeline again."
        )
        with st.expander(f"Show sections that failed ({len(failed)})"):
            for s in failed:
                st.caption(f"**{s.heading}** — {s.classify_reason or 'Unknown error'}")
        if st.button("🔄 Reprocess Document", key="btn_reprocess_top"):
            _reprocess()

    st.divider()

    # ── Flagged sections ───────────────────────────────────────────────────────
    if flagged:
        st.subheader(f"Sections to Review ({total_flag})")
        st.caption("Review each proposed change below. Accept the AI draft, edit it before accepting, or reject it to keep the original.")
        for section in flagged:
            _render_flagged_card(section)
        st.divider()

    # ── No-change sections (collapsed summary) ─────────────────────────────────
    if unchanged:
        with st.expander(f"No Changes Needed — {len(unchanged)} section(s)", expanded=False):
            for s in unchanged:
                st.caption(f"✅ **{s.heading}** — {s.classify_reason or 'Content is current.'}")

    st.divider()

    # ── Bottom action bar ──────────────────────────────────────────────────────

    # Export review doc — always available once there are flagged sections
    if flagged:
        review_bytes, review_filename = generate_review_document(
            st.session_state.sections,
            st.session_state.original_filename,
        )
        st.download_button(
            label="🖨️ Export Review Document (for partner sign-off)",
            data=review_bytes,
            file_name=review_filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    col_dl, col_reset = st.columns([2, 1])

    with col_dl:
        if all_done:
            if st.button("📥 Generate & Download Updated Document", type="primary", use_container_width=True):
                _generate_download()
        else:
            st.button(
                f"📥 Generate & Download — resolve {total_flag - resolved} more section(s) first",
                disabled=True,
                use_container_width=True,
            )

    with col_reset:
        if st.button("← Start Over", use_container_width=True):
            _reset()


def _generate_download() -> None:
    doc_format = st.session_state.get("doc_format", "docx")
    sections = st.session_state.sections

    if doc_format == "pdf":
        # PDF cannot be patched — skip file generation; review doc is on the download screen
        st.session_state.patched_bytes = b""
        st.session_state.output_filename = ""
    else:
        with st.spinner("Applying approved changes to your document..."):
            try:
                if doc_format == "pptx":
                    patched_bytes, output_filename = patch_pptx(
                        st.session_state.original_docx_bytes,
                        sections,
                        st.session_state.original_filename,
                    )
                else:
                    patched_bytes, output_filename = patch_document(
                        st.session_state.original_docx_bytes,
                        sections,
                        st.session_state.original_filename,
                    )
            except Exception as exc:
                st.error(
                    f"Could not generate the updated file: {_friendly_error(exc)}. "
                    "Try downloading the Review Document instead, or start over with the original file."
                )
                return
        st.session_state.patched_bytes   = patched_bytes
        st.session_state.output_filename = output_filename

    # Persist session to DB if we're in a project context
    doc_id = st.session_state.get("active_document_id")
    if doc_id:
        accepted = sum(1 for s in sections if s.review_state in (ReviewState.ACCEPTED, ReviewState.EDITED))
        rejected = sum(1 for s in sections if s.review_state == ReviewState.REJECTED)
        edited   = sum(1 for s in sections if s.review_state == ReviewState.EDITED)
        db.save_session(
            document_id=doc_id,
            sections_json=sections_to_json(sections),
            accepted_count=accepted,
            rejected_count=rejected,
            edited_count=edited,
        )
        db.update_document_status(doc_id, "complete")

    st.session_state.stage = "download"
    st.rerun()


# ── Download screen ────────────────────────────────────────────────────────────

def show_download_screen() -> None:
    doc_format = st.session_state.get("doc_format", "docx")
    sections = st.session_state.sections
    accepted = sum(1 for s in sections if s.review_state in (ReviewState.ACCEPTED, ReviewState.EDITED))
    rejected = sum(1 for s in sections if s.review_state == ReviewState.REJECTED)
    edited   = sum(1 for s in sections if s.review_state == ReviewState.EDITED)

    if doc_format == "pdf":
        st.title("Review Complete")
        st.info(
            "This document is a PDF — the app cannot write changes directly to PDF files. "
            "Download the review document below and apply the approved changes manually in your PDF editor."
        )
        st.divider()
        review_bytes, review_filename = generate_review_document(
            sections, st.session_state.original_filename
        )
        st.download_button(
            label="🖨️ Download Review Document (apply changes manually)",
            data=review_bytes,
            file_name=review_filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            use_container_width=True,
        )
        st.caption(
            f"Review summary: {accepted} section(s) approved · "
            f"{rejected} rejected · {edited} manually edited."
        )
    else:
        st.title("Your Document is Ready")
        st.success(
            f"**{st.session_state.output_filename}** is ready to download. "
            f"{accepted} section(s) updated · {rejected} rejected · {edited} manually edited."
        )
        st.divider()
        mime = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            if doc_format == "pptx"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        st.download_button(
            label=f"⬇️ Download {st.session_state.output_filename}",
            data=st.session_state.patched_bytes,
            file_name=st.session_state.output_filename,
            mime=mime,
            type="primary",
            use_container_width=True,
        )
        st.divider()
        app_name = "PowerPoint" if doc_format == "pptx" else "Word"
        st.caption(
            f"**Next step:** Open the file in {app_name} to verify the changes look correct, "
            "then send it through your normal management approval process."
        )

    col_back, col_another = st.columns([1, 2])
    with col_back:
        if st.session_state.get("active_document_id"):
            if st.button("← Back to Project", use_container_width=True):
                _reset_to_project()
        else:
            if st.button("← Process Another Document", use_container_width=True):
                _reset()
    with col_another:
        if st.session_state.get("active_document_id"):
            if st.button("Process Another Document", use_container_width=True):
                _reset()


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _reset() -> None:
    keys = [
        "stage", "sections", "reference_text", "original_docx_bytes",
        "original_filename", "context_note", "processing_complete",
        "patched_bytes", "output_filename", "doc_format",
        "active_project_id", "active_document_id",
        "history_document_id", "history_session_id",
    ]
    for key in keys:
        st.session_state.pop(key, None)
    to_remove = [k for k in st.session_state if k.startswith(("prop_", "orig_", "accept_", "reject_", "undo_"))]
    for k in to_remove:
        del st.session_state[k]
    st.rerun()


def _reset_to_project() -> None:
    """Clear processing state and return to the active project's detail page."""
    project_id = st.session_state.get("active_project_id")
    keys = [
        "stage", "sections", "reference_text", "original_docx_bytes",
        "original_filename", "context_note", "processing_complete",
        "patched_bytes", "output_filename", "doc_format", "active_document_id",
    ]
    for key in keys:
        st.session_state.pop(key, None)
    to_remove = [k for k in st.session_state if k.startswith(("prop_", "orig_", "accept_", "reject_", "undo_"))]
    for k in to_remove:
        del st.session_state[k]
    if project_id:
        st.session_state.active_project_id = project_id
        st.session_state.stage = "project_detail"
    else:
        st.session_state.stage = "dashboard"
    st.rerun()


def _reprocess() -> None:
    """Reset all sections to unprocessed state and return to processing screen."""
    for s in st.session_state.get("sections", []):
        s.change_type = ChangeType.NO_CHANGE
        s.proposed_text = None
        s.classify_reason = None
        s.review_state = ReviewState.PENDING
        s.final_text = None
        s.processing_failed = False
    to_remove = [k for k in st.session_state if k.startswith(("prop_", "orig_", "accept_", "reject_", "undo_"))]
    for k in to_remove:
        del st.session_state[k]
    st.session_state.processing_complete = False
    st.session_state.stage = "processing"
    st.rerun()


# ── Phase 4: Dashboard ────────────────────────────────────────────────────────

def show_dashboard() -> None:
    st.title("TD Collateral Modernizer")
    st.caption("Manage your document modernization projects, or run a one-off quick process.")

    col_new, col_quick, _ = st.columns([1, 1, 2])
    with col_new:
        if st.button("+ New Project", type="primary", use_container_width=True):
            st.session_state.stage = "project_new"
            st.rerun()
    with col_quick:
        if st.button("⚡ Quick Process", use_container_width=True):
            st.session_state.active_project_id = None
            st.session_state.active_document_id = None
            st.session_state.stage = "upload"
            st.rerun()

    st.divider()

    projects = db.get_projects()
    if not projects:
        st.info(
            "No projects yet. Create a project to group documents with shared reference material, "
            "or use **Quick Process** for a one-off run."
        )
        return

    st.subheader(f"Projects ({len(projects)})")
    for p in projects:
        with st.container(border=True):
            col_info, col_open, col_del = st.columns([4, 1, 1])
            with col_info:
                st.markdown(f"**{p.name}**")
                if p.description:
                    st.caption(p.description)
                st.caption(
                    f"📄 {p.document_count} document(s) · "
                    f"✅ {p.completed_count} completed · "
                    f"Created {p.created_at[:10]}"
                )
            with col_open:
                if st.button("Open →", key=f"open_proj_{p.id}", use_container_width=True):
                    st.session_state.active_project_id = p.id
                    st.session_state.stage = "project_detail"
                    st.rerun()
            with col_del:
                if st.button("🗑", key=f"del_proj_{p.id}", use_container_width=True,
                             help="Delete this project and all its documents"):
                    db.delete_project(p.id)
                    st.rerun()


# ── Phase 4: New Project ──────────────────────────────────────────────────────

def show_new_project_screen() -> None:
    if st.button("← Back to Dashboard"):
        st.session_state.stage = "dashboard"
        st.rerun()

    st.title("New Project")
    st.caption("A project groups related documents with shared reference material.")
    st.divider()

    with st.form("new_project_form"):
        name = st.text_input("Project name *", placeholder="e.g. Acme Product Line 2026")
        description = st.text_area(
            "Description (optional)",
            placeholder="Briefly describe what documents this project covers.",
            height=80,
        )
        st.subheader("Reference Material")
        st.caption("Upload reference files now, or add them later from the project page.")
        ref_uploads = st.file_uploader(
            "Upload reference files",
            type=["docx", "pdf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Create Project", type="primary", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("Project name is required.")
            return
        project_id = db.create_project(name.strip(), description.strip())
        for rf in (ref_uploads or []):
            db.add_reference_file(project_id, rf.name, rf.read())
        st.session_state.active_project_id = project_id
        st.session_state.stage = "project_detail"
        st.rerun()


# ── Phase 4: Project Detail ───────────────────────────────────────────────────

def show_project_detail() -> None:
    project_id = st.session_state.active_project_id
    project = db.get_project(project_id) if project_id else None
    if not project:
        st.error("Project not found.")
        if st.button("← Back to Dashboard"):
            st.session_state.stage = "dashboard"
            st.rerun()
        return

    if st.button("← Back to Dashboard"):
        st.session_state.stage = "dashboard"
        st.rerun()

    st.title(project.name)
    if project.description:
        st.caption(project.description)

    # ── Reference material ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Reference Material")

    ref_files = db.get_reference_files(project_id)
    if ref_files:
        for rf in ref_files:
            col_name, col_del = st.columns([5, 1])
            col_name.caption(f"📎 {rf.filename}  —  added {rf.created_at[:10]}")
            if col_del.button("🗑", key=f"del_ref_{rf.id}", help="Remove this reference file"):
                db.delete_reference_file(rf.id)
                st.rerun()
    else:
        st.caption("No reference files yet — add some below before processing documents.")

    with st.expander("➕ Add Reference Files"):
        with st.form("add_refs_form", clear_on_submit=True):
            new_refs = st.file_uploader(
                "Upload .docx or .pdf reference files",
                type=["docx", "pdf"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            if st.form_submit_button("Add"):
                for f in (new_refs or []):
                    db.add_reference_file(project_id, f.name, f.read())
                st.rerun()

    # ── Document queue ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Documents")

    docs = db.get_documents(project_id)
    if not docs:
        st.info("No documents queued yet. Add documents below to get started.")
    else:
        for doc in docs:
            _render_document_card(doc, ref_files)

    with st.expander("➕ Add Documents to Queue"):
        with st.form("add_docs_form", clear_on_submit=True):
            new_docs = st.file_uploader(
                "Upload .docx, .pptx, or .pdf files to add to the queue",
                type=["docx", "pptx", "pdf"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            if st.form_submit_button("Add to Queue"):
                for f in (new_docs or []):
                    db.add_document(project_id, f.name, f.read())
                st.rerun()


def _render_document_card(doc: db.DocumentRow, ref_files: list[db.RefFileRow]) -> None:
    status_icon = {"queued": "⏳", "processing": "⚙️", "complete": "✅"}.get(doc.status, "❓")
    label = f"{status_icon} **{doc.original_filename}** — {doc.status.title()}"
    if doc.session_count:
        label += f"  ·  {doc.session_count} session(s)"

    with st.expander(label, expanded=False):
        col_proc, col_hist, col_del = st.columns(3)

        has_refs = bool(ref_files)
        proc_help = None if has_refs else "Add reference files to this project before processing."

        with col_proc:
            if st.button(
                "⚡ Process Now",
                key=f"proc_{doc.id}",
                type="primary",
                use_container_width=True,
                disabled=not has_refs,
                help=proc_help,
            ):
                _launch_from_project(doc)

        if doc.session_count > 0:
            with col_hist:
                if st.button("🕐 View History", key=f"hist_{doc.id}", use_container_width=True):
                    st.session_state.history_document_id = doc.id
                    st.session_state.history_session_id = None
                    st.session_state.stage = "session_history"
                    st.rerun()

        with col_del:
            if st.button("🗑 Remove", key=f"del_doc_{doc.id}", use_container_width=True):
                db.delete_document(doc.id)
                st.rerun()

        st.caption(f"Added: {doc.created_at[:10]}")


# ── Phase 4: Launch processing from a project document ────────────────────────

def _launch_from_project(doc: db.DocumentRow) -> None:
    doc_path = Path(doc.stored_path)
    if not doc_path.exists():
        st.error(f"Document file not found on disk: {doc.original_filename}")
        return

    ref_files = db.get_reference_files(doc.project_id)
    ref_texts: list[str] = []
    errors: list[str] = []
    for rf in ref_files:
        rf_path = Path(rf.stored_path)
        if not rf_path.exists():
            errors.append(f"Reference file missing: {rf.filename}")
            continue
        text, err = extract_reference_text(rf_path)
        if err:
            errors.append(f"{rf.filename}: {err}")
        elif text:
            ref_texts.append(f"--- {rf.filename} ---\n{text}")

    if errors:
        for e in errors:
            st.error(e)
        return
    if not ref_texts:
        st.error("Could not extract text from any reference files.")
        return

    suffix = Path(doc.original_filename).suffix.lower()
    sections, extract_error = _extract_primary_sections(doc_path, suffix)
    if extract_error:
        st.error(extract_error)
        return
    if not sections:
        st.error(f"{doc.original_filename} appears to be empty or unreadable.")
        return

    st.session_state.original_docx_bytes = doc_path.read_bytes()
    st.session_state.original_filename = doc.original_filename
    st.session_state.reference_text = "\n\n".join(ref_texts)
    st.session_state.context_note = ""
    st.session_state.sections = sections
    st.session_state.processing_complete = False
    st.session_state.doc_format = suffix.lstrip(".")
    st.session_state.active_document_id = doc.id

    db.update_document_status(doc.id, "processing")
    st.session_state.stage = "processing"
    st.rerun()


# ── Phase 4: Session History ──────────────────────────────────────────────────

def show_session_history() -> None:
    doc_id = st.session_state.get("history_document_id")
    if not doc_id:
        st.session_state.stage = "dashboard"
        st.rerun()
        return

    doc = db.get_document(doc_id)
    if not doc:
        st.error("Document not found.")
        return

    if st.button("← Back to Project"):
        st.session_state.active_project_id = doc.project_id
        st.session_state.stage = "project_detail"
        st.rerun()

    st.title(f"Session History")
    st.caption(f"Document: **{doc.original_filename}**")
    st.divider()

    sessions = db.get_sessions(doc_id)
    if not sessions:
        st.info("No sessions recorded for this document yet.")
        return

    session_id = st.session_state.get("history_session_id")

    if session_id is None:
        for s in sessions:
            with st.container(border=True):
                col_info, col_view = st.columns([4, 1])
                with col_info:
                    st.markdown(f"**{s.created_at}**")
                    st.caption(
                        f"✅ {s.accepted_count} accepted · "
                        f"✏️ {s.edited_count} edited · "
                        f"❌ {s.rejected_count} rejected"
                    )
                with col_view:
                    if st.button("View →", key=f"view_sess_{s.id}", use_container_width=True):
                        st.session_state.history_session_id = s.id
                        st.rerun()
    else:
        session = db.get_session(session_id)
        if not session:
            st.error("Session not found.")
            return

        if st.button("← Back to Session List"):
            st.session_state.history_session_id = None
            st.rerun()

        st.subheader(f"Session — {session.created_at}")
        st.caption(
            f"✅ {session.accepted_count} accepted · "
            f"✏️ {session.edited_count} edited · "
            f"❌ {session.rejected_count} rejected"
        )

        sections = sections_from_json(session.sections_json)

        # ── Downloads ─────────────────────────────────────────────────────────
        col_review, col_updated = st.columns(2)

        with col_review:
            review_bytes, review_filename = generate_review_document(sections, doc.original_filename)
            st.download_button(
                label="🖨️ Export Review Document",
                data=review_bytes,
                file_name=review_filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                help="Download the side-by-side comparison document for partner sign-off.",
            )

        with col_updated:
            doc_path = Path(doc.stored_path)
            fname_lower = doc.original_filename.lower()
            if fname_lower.endswith(".pdf"):
                st.caption("PDF document — apply changes manually using the review document.")
            elif not doc_path.exists():
                st.caption("Original file no longer on disk — updated document cannot be regenerated.")
            elif fname_lower.endswith(".pptx"):
                patched_bytes, patched_filename = patch_pptx(
                    doc_path.read_bytes(), sections, doc.original_filename
                )
                st.download_button(
                    label="⬇️ Download Updated Presentation",
                    data=patched_bytes,
                    file_name=patched_filename,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True,
                    help="Re-generates the patched .pptx with all approved changes applied.",
                )
            else:
                patched_bytes, patched_filename = patch_document(
                    doc_path.read_bytes(), sections, doc.original_filename
                )
                st.download_button(
                    label="⬇️ Download Updated Document",
                    data=patched_bytes,
                    file_name=patched_filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    help="Re-generates the patched .docx with all approved changes applied.",
                )

        st.divider()

        for s in sections:
            _render_section_readonly(s)


def _render_section_readonly(section: Section) -> None:
    badge = _BADGE.get(section.change_type, "")
    state_label = {
        ReviewState.ACCEPTED: "✅ Accepted",
        ReviewState.EDITED:   "✅ Accepted (edited)",
        ReviewState.REJECTED: "❌ Rejected",
        ReviewState.PENDING:  "⏳ Pending",
    }.get(section.review_state, "")

    with st.expander(f"**{section.heading}** — {badge}  ·  {state_label}", expanded=False):
        col_orig, col_final = st.columns(2)
        with col_orig:
            st.markdown("**Original**")
            st.text_area(
                "ro_orig",
                value=section.original_text,
                height=180,
                disabled=True,
                label_visibility="collapsed",
                key=f"ro_orig_{section.index}",
            )
        with col_final:
            st.markdown("**Final**")
            st.text_area(
                "ro_final",
                value=section.effective_text(),
                height=180,
                disabled=True,
                label_visibility="collapsed",
                key=f"ro_final_{section.index}",
            )


# ── Main router ────────────────────────────────────────────────────────────────
show_sidebar()
stage = st.session_state.stage

if stage == "dashboard":
    show_dashboard()
elif stage == "project_new":
    show_new_project_screen()
elif stage == "project_detail":
    show_project_detail()
elif stage == "session_history":
    show_session_history()
elif stage == "upload":
    show_upload_screen()
elif stage == "processing":
    show_processing_screen()
elif stage == "review":
    show_review_screen()
elif stage == "download":
    show_download_screen()
else:
    st.error(f"Unknown stage: {stage!r}")
