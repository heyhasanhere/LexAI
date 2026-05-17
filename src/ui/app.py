import os
import streamlit as st
import requests

API = os.getenv("LEXAI_API_URL", "http://localhost:8000")
FREQ_THRESHOLD = 3  # patterns below this are stored but not injected into prompts

st.set_page_config(page_title="LexAI", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
section[data-testid="stSidebar"] { width: 264px !important; }

.field-label { font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; }
.stage-label {
    font-size: 11px; font-weight: 700; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px;
}
.evidence-chunk {
    background: #eff6ff;
    border-left: 3px solid #3b82f6;
    padding: 10px 14px;
    margin: 6px 0;
    border-radius: 0 6px 6px 0;
    font-size: 13px;
    line-height: 1.5;
    color: #1e3a5f;
}
.evidence-meta { font-size: 11px; color: #6b7280; margin-bottom: 6px; }
.pattern-active { color: #16a34a; font-size: 11px; font-weight: 600; }
.pattern-learning { color: #d97706; font-size: 11px; }
</style>
""", unsafe_allow_html=True)

# ── Session state ───────────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "process"
if "selected_doc_id" not in st.session_state:
    st.session_state.selected_doc_id = None
if "canvas_doc" not in st.session_state:
    st.session_state.canvas_doc = None
if "selected_draft_id" not in st.session_state:
    st.session_state.selected_draft_id = None
if "canvas_draft" not in st.session_state:
    st.session_state.canvas_draft = None
if "canvas_text" not in st.session_state:
    st.session_state.canvas_text = ""
if "canvas_editing" not in st.session_state:
    st.session_state.canvas_editing = False
if "upload_keys" not in st.session_state:
    st.session_state.upload_keys = set()
if "confirm_reset" not in st.session_state:
    st.session_state.confirm_reset = False
if "submit_result" not in st.session_state:
    st.session_state.submit_result = None
if "evidence" not in st.session_state:
    st.session_state.evidence = None
if "settings_api_key" not in st.session_state:
    st.session_state.settings_api_key = ""


# ── API helpers ────────────────────────────────────────────────────────────────

def _get(path: str, **params):
    try:
        r = requests.get(f"{API}{path}", params=params or None, timeout=15)
        return r.json() if r.ok else None
    except Exception:
        return None


def _post(path: str, json=None, files=None, data=None, timeout=300):
    try:
        return requests.post(f"{API}{path}", json=json, files=files, data=data, timeout=timeout)
    except Exception:
        return None


def _delete(path: str) -> bool:
    try:
        r = requests.delete(f"{API}{path}", timeout=10)
        return r.status_code in (200, 204)
    except Exception:
        return False


def _patch(path: str, json: dict, timeout: int = 10):
    try:
        return requests.patch(f"{API}{path}", json=json, timeout=timeout)
    except Exception:
        return None


def _badge(status: str) -> str:
    colors = {
        "ready": "#22c55e", "failed": "#ef4444", "processing": "#f59e0b",
        "generated": "#60a5fa", "submitted": "#a78bfa", "pending": "#6b7280",
    }
    c = colors.get(status, "#6b7280")
    return f'<span style="color:{c};font-size:11px;font-weight:600">● {status}</span>'


def _load_draft(draft_id: str) -> None:
    d = _get(f"/drafts/{draft_id}")
    if not d:
        return
    st.session_state.selected_draft_id = draft_id
    st.session_state.canvas_draft = d
    st.session_state.canvas_text = d["draft_text"]
    st.session_state.canvas_editing = False
    st.session_state.submit_result = None
    st.session_state.evidence = None
    doc_id = d["document_ids"][0] if d["document_ids"] else None
    st.session_state.canvas_doc = _get(f"/documents/{doc_id}") if doc_id else None


def _load_doc(doc_id: str) -> None:
    doc = _get(f"/documents/{doc_id}")
    if not doc:
        return
    st.session_state.selected_doc_id = doc_id
    st.session_state.canvas_doc = doc


# ── Sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div style="font-size:20px;font-weight:700;padding:4px 0 8px 0">'
        '<span style="color:#d97706">Lex</span>'
        '<span>AI</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    try:
        h = requests.get(f"{API}/health", timeout=2).json()
        ok = h.get("status") == "ok" and h.get("database") == "connected"
        color, label = ("#22c55e", "Connected") if ok else ("#ef4444", "Degraded")
        issues = []
        if h.get("database") != "connected": issues.append("DB")
        if h.get("vector_store") != "connected": issues.append("Vector store")
        if not h.get("ocr_available"): issues.append("OCR")
        suffix = f" — {', '.join(issues)} down" if issues else ""
        st.markdown(f'<span style="color:{color};font-size:12px">● {label}{suffix}</span>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<span style="color:#ef4444;font-size:12px">● API unreachable</span>', unsafe_allow_html=True)

    st.divider()

    page_map = {"Process": "process", "Review & Learn": "review", "Patterns": "patterns", "Settings": "settings"}
    idx_map = {"process": 0, "review": 1, "patterns": 2, "settings": 3}
    nav = st.radio(
        "Navigation",
        list(page_map.keys()),
        index=idx_map.get(st.session_state.page, 0),
        label_visibility="collapsed",
    )
    st.session_state.page = page_map[nav]

    st.divider()

    if st.session_state.page == "review":
        st.caption("DRAFTS")
        drafts_data = _get("/drafts", limit=30)
        if drafts_data:
            for draft in drafts_data["drafts"]:
                did = draft["draft_id"]
                doc_ids = draft["document_ids"]
                label = (doc_ids[0][:16] + "…") if doc_ids else did[:16]
                is_active = did == st.session_state.selected_draft_id
                c1, c2 = st.columns([3, 1])
                if c1.button(label, key=f"sb_d_{did}", use_container_width=True,
                             type="primary" if is_active else "secondary"):
                    _load_draft(did)
                    st.rerun()
                c2.markdown(f'<div style="padding-top:6px">{_badge(draft["status"])}</div>',
                            unsafe_allow_html=True)
        else:
            st.caption("No drafts yet.")
    else:
        st.caption("DOCUMENTS")
        docs_data = _get("/documents", limit=50)
        if docs_data:
            visible = [d for d in docs_data["documents"] if d["status"] != "failed"]
            if visible:
                for doc in visible:
                    did = doc["document_id"]
                    name = doc["filename"]
                    short = (name[:18] + "…") if len(name) > 18 else name
                    is_active = did == st.session_state.selected_doc_id
                    c1, c2, c3 = st.columns([3, 1, 0.6])
                    if c1.button(short, key=f"sb_doc_{did}", use_container_width=True,
                                 type="primary" if is_active else "secondary"):
                        _load_doc(did)
                        st.rerun()
                    c2.markdown(f'<div style="padding-top:6px">{_badge(doc["status"])}</div>',
                                unsafe_allow_html=True)
                    if c3.button("×", key=f"del_doc_{did}", use_container_width=True):
                        if _delete(f"/documents/{did}"):
                            if st.session_state.selected_doc_id == did:
                                st.session_state.selected_doc_id = None
                                st.session_state.canvas_doc = None
                            st.rerun()
            else:
                st.caption("No documents yet.")
        else:
            st.caption("No documents yet.")

    # ── Reset ─────────────────────────────────────────────────────────────────
    st.divider()
    if st.session_state.confirm_reset:
        st.warning("This deletes all documents, drafts, patterns, and files.")
        rc1, rc2 = st.columns(2)
        if rc1.button("Confirm reset", type="primary", use_container_width=True):
            r = _post("/admin/reset", json={}, timeout=30)
            if r and r.ok:
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            else:
                st.error("Reset failed.")
        if rc2.button("Cancel", use_container_width=True):
            st.session_state.confirm_reset = False
            st.rerun()
    else:
        if st.button("Reset everything", use_container_width=True):
            st.session_state.confirm_reset = True
            st.rerun()


# ── Extracted fields renderer ───────────────────────────────────────────────────

def _pr(page) -> str:
    """Format a page number as an inline [p.N] reference span."""
    return f' <span style="color:#6b7280;font-size:11px">[p.{page}]</span>' if page else ""


def _render_extracted_fields(fields: dict) -> None:
    """Render all extracted sections from a document's fields_json dict."""

    # ABOUT THIS DOCUMENT
    notes = fields.get("extraction_notes")
    if notes:
        st.markdown("**About This Document:**")
        st.markdown(
            f'<div style="font-size:13px;color:#374151;padding:4px 0 12px 0">{notes}</div>',
            unsafe_allow_html=True,
        )

    # PARTIES
    parties = fields.get("parties") or []
    if parties:
        st.markdown("*PARTIES*")
        for p in parties:
            conf = p.get("confidence", "")
            conf_color = {"high": "#22c55e", "medium": "#f59e0b"}.get(conf, "#ef4444")
            ident = f" ({p['identifier']})" if p.get("identifier") else ""
            st.markdown(
                f'<div style="font-size:13px;padding:3px 0">'
                f'<b>{p.get("role", "?")}:</b> {p.get("name", "?")}{ident}'
                f'{_pr(p.get("page"))}'
                + (f' <span style="color:{conf_color};font-size:11px">({conf})</span>' if conf else "")
                + "</div>",
                unsafe_allow_html=True,
            )

    # KEY DATES
    key_dates = fields.get("key_dates") or []
    if key_dates:
        st.markdown("*KEY DATES*")
        for d in key_dates:
            c1, c2 = st.columns([2, 4])
            c1.markdown(f'<span class="field-label">{d.get("label", "")}</span>', unsafe_allow_html=True)
            alert = f" ⚠ {d['alert']}" if d.get("alert") else ""
            c2.markdown(
                f'{d.get("date", "")}{_pr(d.get("page"))}{alert}',
                unsafe_allow_html=True,
            )

    # KEY CLAUSES
    key_clauses = fields.get("key_clauses") or []
    if key_clauses:
        st.markdown("*KEY CLAUSES*")
        for kc in key_clauses:
            c1, c2 = st.columns([2, 4])
            c1.markdown(f'<span class="field-label">{kc.get("name", "")}</span>', unsafe_allow_html=True)
            c2.markdown(f'{kc.get("value", "")}{_pr(kc.get("page"))}', unsafe_allow_html=True)

    # FLAGS & RISKS
    flags_and_risks = fields.get("flags_and_risks") or []
    if flags_and_risks:
        st.markdown("*FLAGS & RISKS*")
        for fr in flags_and_risks:
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'⚠ {fr.get("description", "")}{_pr(fr.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # MATTER TIMELINE
    timeline = fields.get("matter_timeline") or []
    if timeline:
        st.markdown("*MATTER TIMELINE*")
        for t in timeline:
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<span style="color:#6b7280">{t.get("date", "")}</span>'
                f' — {t.get("event", "")}{_pr(t.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # OBLIGATION TRACKER
    obligations = fields.get("obligation_tracker") or []
    if obligations:
        st.markdown("*OBLIGATION TRACKER*")
        for ob in obligations:
            due = f" — Due: {ob['due']}" if ob.get("due") else ""
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<b>{ob.get("party", "")}</b> — {ob.get("obligation", "")}{due}{_pr(ob.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # RISK SUMMARY REPORT
    risk_summary = fields.get("risk_summary")
    if risk_summary:
        st.markdown("*RISK SUMMARY REPORT*")
        level = risk_summary.get("level", "")
        level_color = {"High": "#ef4444", "Medium": "#f59e0b", "Low": "#22c55e"}.get(level, "#6b7280")
        st.markdown(
            f'<div style="font-size:13px;padding:2px 0">'
            f'<b>Overall:</b> {risk_summary.get("overall", "")}'
            f' — <span style="color:{level_color};font-weight:600">{level}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        for item in risk_summary.get("items") or []:
            sev = item.get("severity", "")
            sev_color = {"High": "#ef4444", "Medium": "#f59e0b", "Low": "#22c55e"}.get(sev, "#6b7280")
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0;margin-left:12px">'
                f'<span style="color:{sev_color};font-size:11px;font-weight:600">{sev}</span>'
                f' ⚠ {item.get("description", "")}{_pr(item.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # CLAUSE LIBRARY
    clause_lib = fields.get("clause_library") or []
    if clause_lib:
        st.markdown("*CLAUSE LIBRARY*")
        for cl in clause_lib:
            c1, c2 = st.columns([2, 4])
            c1.markdown(f'<span class="field-label">{cl.get("clause_type", "")}</span>', unsafe_allow_html=True)
            c2.markdown(f'{cl.get("text", "")}{_pr(cl.get("page"))}', unsafe_allow_html=True)

    # PARTY PROFILE
    party_profiles = fields.get("party_profile") or []
    if party_profiles:
        st.markdown("*PARTY PROFILE*")
        for pp in party_profiles:
            idents = f" ({pp['identifiers']})" if pp.get("identifiers") else ""
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<b>{pp.get("entity", "")}</b> — {pp.get("role", "")}{idents}{_pr(pp.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # DUE DILIGENCE CHECKLIST
    checklist = fields.get("due_diligence_checklist") or []
    if checklist:
        st.markdown("*DUE DILIGENCE CHECKLIST*")
        for ch in checklist:
            tick = "✓" if ch.get("found") else "✗"
            color = "#22c55e" if ch.get("found") else "#ef4444"
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<span style="color:{color}">{tick}</span> {ch.get("item", "")}{_pr(ch.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ANOMALY / DEVIATION REPORT
    anomalies = fields.get("anomaly_report") or []
    if anomalies:
        st.markdown("*ANOMALY / DEVIATION REPORT*")
        for an in anomalies:
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<b>{an.get("clause", "")}</b> — {an.get("deviation", "")}{_pr(an.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # DEPOSITION / TRANSCRIPT SUMMARY
    transcripts = fields.get("transcript_summary") or []
    if transcripts:
        st.markdown("*DEPOSITION / TRANSCRIPT SUMMARY*")
        for tr in transcripts:
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<b>{tr.get("speaker", "")}</b>: {tr.get("statement", "")}{_pr(tr.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # CASE LAW CITATION MAP
    case_laws = fields.get("case_law_citations") or []
    if case_laws:
        st.markdown("*CASE LAW CITATION MAP*")
        for cl in case_laws:
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<b>{cl.get("case", "")}</b> — {cl.get("context", "")}{_pr(cl.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # DOCUMENT GAP REPORT
    gaps = fields.get("document_gap_report") or []
    if gaps:
        st.markdown("*DOCUMENT GAP REPORT*")
        for g in gaps:
            status = g.get("status", "")
            s_color = {"Present": "#22c55e", "Missing": "#ef4444", "Illegible": "#f59e0b"}.get(status, "#6b7280")
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'{g.get("expected", "")} — <span style="color:{s_color}">{status}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # AUDIT TRAIL
    audit_trail = fields.get("audit_trail") or []
    if audit_trail:
        st.markdown("*AUDIT TRAIL*")
        for at in audit_trail:
            ts = f" — {at['timestamp']}" if at.get("timestamp") else ""
            st.markdown(
                f'<div style="font-size:13px;padding:2px 0">'
                f'<b>{at.get("actor", "")}</b> — {at.get("action", "")}{ts}{_pr(at.get("page"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # SOURCE GROUNDING
    source_grounding = fields.get("source_grounding") or []
    if source_grounding:
        st.markdown("*SOURCE GROUNDING*")
        for sg in source_grounding:
            c1, c2 = st.columns([2, 4])
            c1.markdown(f'<span class="field-label">{sg.get("field", "")}</span>', unsafe_allow_html=True)
            c2.markdown(f'{sg.get("value", "")}{_pr(sg.get("page"))}', unsafe_allow_html=True)

    pass  # extraction_notes rendered at the top of this function, not here


# ── Page: Process ───────────────────────────────────────────────────────────────
def render_process():
    st.markdown('<div class="stage-label">Stage 1</div>', unsafe_allow_html=True)
    st.markdown("## Document Processing")
    st.caption("Upload any document — PDFs or scanned images. The system runs OCR, extracts text, and pulls out structured fields automatically.")

    upload_col, detail_col = st.columns([2, 3], gap="large")

    with upload_col:
        st.markdown("#### Upload")
        uploaded = st.file_uploader(
            "Drop a file",
            type=["pdf", "png", "jpg", "jpeg", "tiff", "txt"],
            label_visibility="collapsed",
        )
        if uploaded:
            key = f"{uploaded.name}_{uploaded.size}"
            if key not in st.session_state.upload_keys:
                st.session_state.upload_keys.add(key)
                with st.spinner(f"Ingesting {uploaded.name}…"):
                    resp = _post(
                        "/documents",
                        files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                        timeout=300,
                    )
                if resp and resp.ok:
                    doc_id = resp.json()["document_id"]
                    _load_doc(doc_id)
                    st.success(f"Uploaded — processing in background. Refresh to see results.")
                    st.rerun()
                else:
                    detail = resp.json().get("detail", resp.text) if resp else "Request failed"
                    st.error(f"Ingestion failed: {detail}")

    with detail_col:
        doc = st.session_state.canvas_doc
        if not doc:
            st.markdown(
                '<div style="color:#555;font-size:14px;padding:48px 0">'
                'Select a document from the sidebar or upload one to see its processing results.'
                '</div>',
                unsafe_allow_html=True,
            )
            return

        flags = doc.get("flags") or []
        fields = doc.get("fields") or {}

        st.markdown(f"#### {doc['filename']}")
        st.markdown(f'Status: {_badge(doc["status"])}', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("Pages", doc.get("page_count") or "—")
        m2.metric("File type", doc.get("file_type", "—").upper())
        m3.metric("Document type", fields.get("document_type") or "—")

        if flags:
            st.warning("**Processing flags:** " + " · ".join(flags))

        if doc["status"] == "failed":
            st.error(f"Ingestion error: {doc.get('error_detail', 'Unknown error')}")
            return

        if doc["status"] == "processing":
            st.info("Still processing — refresh in a moment.")
            return

        if not fields:
            st.info("No fields extracted.")
            return

        st.divider()
        st.markdown("**Extracted Structured Fields**")
        _render_extracted_fields(fields)
        st.divider()

        gen_col, del_col = st.columns([3, 1])
        if gen_col.button("Generate Draft", type="primary", use_container_width=True):
            with st.spinner("Retrieving evidence and generating grounded draft…"):
                r = _post("/drafts", json={
                    "document_ids": [doc["document_id"]],
                    "draft_type": "case_fact_summary",
                })
            if r and r.ok:
                d = r.json()
                st.session_state.selected_draft_id = d["draft_id"]
                st.session_state.canvas_draft = d
                st.session_state.canvas_text = d["draft_text"]
                st.session_state.canvas_editing = False
                st.session_state.submit_result = None
                st.session_state.evidence = None
                st.session_state.page = "review"
                st.rerun()
            else:
                detail = r.json().get("detail", r.text) if r else "Request failed"
                st.error(f"Generation failed: {detail}")

        if del_col.button("Delete", use_container_width=True):
            if _delete(f"/documents/{doc['document_id']}"):
                st.session_state.selected_doc_id = None
                st.session_state.canvas_doc = None
                st.rerun()
            else:
                st.error("Delete failed.")


# ── Page: Review & Learn ────────────────────────────────────────────────────────
def render_review():
    st.markdown('<div class="stage-label">Stages 2 · 3 · 4</div>', unsafe_allow_html=True)
    st.markdown("## Retrieve, Generate, and Learn")
    st.caption("Review the grounded draft, inspect the evidence passages that support it, edit, and submit to teach the system.")

    if not st.session_state.canvas_draft:
        st.info("Select a draft from the sidebar, or go to **Process** and click **Generate Draft**.")
        return

    draft = st.session_state.canvas_draft
    status = draft.get("status", "generated")
    ug = draft.get("ungrounded_sentences") or []
    patterns_used = draft.get("patterns_used") or []

    # Header row
    h1, h2, h3, h4 = st.columns([3, 2, 2, 2])
    h1.markdown(f'Draft `{draft["draft_id"][:12]}…` {_badge(status)}', unsafe_allow_html=True)
    h2.caption(f'Created {draft.get("created_at", "")[:10]}')
    if ug:
        h3.warning(f"{len(ug)} ungrounded")
    if patterns_used:
        h4.success(f"{len(patterns_used)} pattern(s) applied")

    draft_col, side_col = st.columns([3, 2], gap="large")

    # ── Draft ───────────────────────────────────────────────────────────────────
    with draft_col:
        st.markdown('<div class="stage-label">Stage 3 — Draft</div>', unsafe_allow_html=True)

        if status == "submitted":
            st.info("This draft has been submitted and is locked. Select another or generate a new one.")

        if status != "submitted":
            edit_btn, preview_btn, _ = st.columns([1, 1, 4])
            if not st.session_state.canvas_editing:
                if edit_btn.button("Edit", use_container_width=True):
                    st.session_state.canvas_editing = True
                    st.rerun()
            else:
                if preview_btn.button("Preview", use_container_width=True):
                    st.session_state.canvas_editing = False
                    st.rerun()

        if not st.session_state.canvas_editing:
            with st.container(height=480, border=True):
                st.markdown(st.session_state.canvas_text)
        else:
            st.markdown('<div class="stage-label">Stage 4 — Edit to teach the system</div>', unsafe_allow_html=True)
            edited = st.text_area(
                "Edit draft:",
                value=st.session_state.canvas_text,
                height=440,
                key=f"editor_{draft['draft_id']}",
                label_visibility="collapsed",
            )
            st.session_state.canvas_text = edited

            save_c, reset_c, _ = st.columns([2, 2, 5])
            if save_c.button("Save & Learn", type="primary", use_container_width=True):
                with st.spinner("Submitting edits and extracting reusable patterns…"):
                    r = _post(
                        f"/drafts/{draft['draft_id']}/submit",
                        json={"submitted_text": edited},
                        timeout=120,
                    )
                if r and r.ok:
                    result = r.json()
                    st.session_state.submit_result = result
                    st.session_state.canvas_draft["status"] = "submitted"
                    st.session_state.canvas_editing = False
                    st.rerun()
                else:
                    detail = r.json().get("detail", r.text) if r else "Request failed"
                    st.error(f"Submit failed: {detail}")

            if reset_c.button("Reset", use_container_width=True):
                st.session_state.canvas_text = draft["draft_text"]
                st.session_state.canvas_editing = False
                st.rerun()

        # Submit result
        if st.session_state.submit_result:
            res = st.session_state.submit_result
            n = res.get("patterns_extracted", 0)
            if n > 0:
                st.success(
                    f"**{n} pattern(s) extracted** and added to the learning store.  \n"
                    f"Patterns seen {FREQ_THRESHOLD}+ times are automatically injected into future drafts. "
                    f"Check the **Patterns** page to review them."
                )
            else:
                st.info(
                    "No generalizable patterns extracted from this edit.  \n"
                    "The system only stores structural and formatting preferences that apply across documents — "
                    "not corrections specific to this document's content."
                )

        # Ungrounded sentences
        if ug:
            with st.expander(f"{len(ug)} sentence(s) without citations"):
                st.caption("These lines appear in the draft without a [doc_id, chunk_id] citation.")
                for s in ug:
                    st.markdown(f"- {s}")

    # ── Side panel ──────────────────────────────────────────────────────────────
    with side_col:

        # Stage 2: Evidence
        st.markdown('<div class="stage-label">Stage 2 — Retrieved Evidence</div>', unsafe_allow_html=True)
        st.caption("Passages retrieved from the source documents that grounded this draft.")

        if st.session_state.evidence is None:
            with st.spinner("Fetching evidence…"):
                ev = _get(f"/drafts/{draft['draft_id']}/evidence")
                st.session_state.evidence = ev or []

        evidence = st.session_state.evidence
        if not evidence:
            st.caption("No evidence chunks returned above the similarity threshold.")
        else:
            for chunk in evidence:
                score_pct = int(chunk.get("score", 0) * 100)
                conf = chunk.get("ocr_confidence", 1.0)
                low_conf = " · low OCR confidence" if conf < 0.40 else ""
                text = chunk["text"]
                truncated = (text[:380] + "…") if len(text) > 380 else text
                st.markdown(
                    f'<div class="evidence-chunk">'
                    f'<div class="evidence-meta">'
                    f'{chunk["chunk_id"]} &nbsp;·&nbsp; page {chunk["page_number"]} '
                    f'&nbsp;·&nbsp; {score_pct}% match{low_conf}'
                    f'</div>'
                    f'{truncated}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # Patterns applied
        if patterns_used:
            st.markdown('<div class="stage-label">Patterns Applied to This Draft</div>', unsafe_allow_html=True)
            all_p = _get("/patterns", min_frequency=1)
            if all_p:
                used_set = set(patterns_used)
                shown = [p for p in all_p.get("patterns", []) if p["pattern_id"] in used_set]
                if shown:
                    for p in shown:
                        st.markdown(
                            f'**[{p["section"]} / {p["edit_type"]}]**  \n'
                            f'*{p.get("trigger", "")}*  \n'
                            f'Applied {p["frequency"]}× across documents.'
                        )
                else:
                    st.caption("Pattern details unavailable.")
        else:
            st.caption(
                "No learned patterns were applied to this draft.  \n"
                "Submit edited drafts to start building the pattern library."
            )


# ── Page: Patterns ──────────────────────────────────────────────────────────────
def render_patterns():
    st.markdown('<div class="stage-label">Stage 4</div>', unsafe_allow_html=True)
    st.markdown("## Learned Patterns")
    st.caption(
        f"Extracted from operator edits. Patterns with **{FREQ_THRESHOLD}+ occurrences** are "
        f"automatically injected into future draft prompts as few-shot examples."
    )

    all_data = _get("/patterns", min_frequency=1)
    if not all_data or all_data["total"] == 0:
        st.info(
            "No patterns learned yet.  \n\n"
            "How to teach the system:  \n"
            "1. Go to **Process**, upload a document, and click **Generate Draft**  \n"
            "2. In **Review & Learn**, edit the draft and click **Save & Learn**  \n"
            "3. Patterns from your edits appear here and improve future drafts"
        )
        return

    patterns = all_data["patterns"]
    active = [p for p in patterns if p["frequency"] >= FREQ_THRESHOLD]
    learning = [p for p in patterns if p["frequency"] < FREQ_THRESHOLD]

    m1, m2, m3 = st.columns(3)
    m1.metric("Total patterns", len(patterns))
    m2.metric(f"Active (freq >= {FREQ_THRESHOLD})", len(active),
              help="Injected into generation prompts automatically")
    m3.metric("Learning (below threshold)", len(learning),
              help=f"Stored, but need {FREQ_THRESHOLD} occurrences before being used")

    st.divider()

    # Filters
    f1, f2, f3 = st.columns(3)
    all_types = sorted({p.get("document_type") or "any" for p in patterns})
    all_sections = sorted({p.get("section", "unknown") for p in patterns})
    all_edits = sorted({p.get("edit_type", "?") for p in patterns})

    sel_type = f1.selectbox("Document type", ["all"] + all_types)
    sel_section = f2.selectbox("Section", ["all"] + all_sections)
    sel_edit = f3.selectbox("Edit type", ["all"] + all_edits)

    filtered = [
        p for p in patterns
        if (sel_type == "all" or (p.get("document_type") or "any") == sel_type)
        and (sel_section == "all" or p.get("section") == sel_section)
        and (sel_edit == "all" or p.get("edit_type") == sel_edit)
    ]

    st.markdown(f"**{len(filtered)} pattern(s) shown**")

    for p in filtered:
        is_active = p["frequency"] >= FREQ_THRESHOLD
        status_html = (
            f'<span class="pattern-active">● Active — injected into prompts</span>'
            if is_active else
            f'<span class="pattern-learning">● Learning — {p["frequency"]}/{FREQ_THRESHOLD} occurrences</span>'
        )
        trigger_short = (p.get("trigger", "") or "")[:90]
        label = f'[{p.get("section","?")} / {p.get("edit_type","?")}]  {trigger_short}'

        with st.expander(label, expanded=False):
            info_col, del_col = st.columns([6, 1])

            with info_col:
                st.markdown(f"**Status:** {status_html}", unsafe_allow_html=True)
                if p.get("document_type"):
                    st.markdown(f"**Document type:** `{p['document_type']}`")
                st.markdown(f"**Trigger:** {p.get('trigger', '')}")
                st.markdown(
                    f"**Occurrences:** {p['frequency']}  "
                    f"· First seen: {str(p.get('first_seen', ''))[:10]}  "
                    f"· Last seen: {str(p.get('last_seen', ''))[:10]}"
                )
                with st.expander("Before / After"):
                    bc, ac = st.columns(2)
                    bc.markdown("**Original (before edit)**")
                    bc.code(str(p.get("original_text", ""))[:600], language=None)
                    ac.markdown("**Corrected (operator edit)**")
                    ac.code(str(p.get("corrected_text", ""))[:600], language=None)

            with del_col:
                if st.button("Delete", key=f"del_{p['pattern_id']}", type="secondary"):
                    if _delete(f"/patterns/{p['pattern_id']}"):
                        st.success("Deleted")
                        st.rerun()
                    else:
                        st.error("Failed")


# ── Page: Settings ──────────────────────────────────────────────────────────────
_PROVIDER_DEFAULTS = {
    "vllm":       ("http://localhost:8080/v1", "Qwen/Qwen3-4B-AWQ"),
    "groq":       ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.1-8b-instruct:free"),
    "gemini":     ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash-lite"),
    "mistral":    ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "together":   ("https://api.together.xyz/v1", "meta-llama/Llama-3.2-3B-Instruct-Turbo"),
    "openai":     ("https://api.openai.com/v1", "gpt-4o-mini"),
}

def render_settings():
    st.markdown("## LLM Settings")
    st.caption("Changes take effect immediately for all new requests. Restart resets to defaults from settings.yaml.")

    current = _get("/config/llm")
    if not current:
        st.error("Could not reach the API.")
        return

    st.markdown(
        f'**Active:** `{current["provider"]}` · `{current["model"]}` · '
        f'`{current["base_url"]}` · '
        f'API key: {"set" if current["api_key_set"] else "not set"} · '
        f'max_tokens: `{current["max_tokens"]}`'
    )
    st.divider()

    providers = list(_PROVIDER_DEFAULTS.keys())
    cur_provider = current.get("provider", "vllm")
    provider_idx = providers.index(cur_provider) if cur_provider in providers else 0

    provider = st.selectbox(
        "Provider",
        providers,
        index=provider_idx,
        help="Selecting a provider auto-fills the base URL and a default model.",
    )

    default_url, default_model = _PROVIDER_DEFAULTS[provider]
    # If switching provider, suggest its defaults; otherwise keep current values
    suggest_url = default_url if provider != cur_provider else current["base_url"]
    suggest_model = default_model if provider != cur_provider else current["model"]

    col1, col2 = st.columns(2)
    model = col1.text_input("Model", value=suggest_model)
    base_url = col2.text_input(
        "Base URL",
        value=suggest_url,
        disabled=(provider != "vllm"),
        help="Only editable for vLLM. Other providers use fixed endpoints.",
    )

    api_key = st.text_input(
        "API key",
        value=st.session_state.settings_api_key,
        type="password",
        placeholder="Leave blank to keep existing key" if current["api_key_set"] else "Enter API key",
    )
    st.session_state.settings_api_key = api_key

    max_tokens = st.slider("Max tokens", min_value=256, max_value=8192, value=current["max_tokens"], step=256)

    if st.button("Apply", type="primary"):
        payload: dict = {"provider": provider, "model": model, "max_tokens": max_tokens}
        if provider == "vllm":
            payload["base_url"] = base_url
        if api_key:
            payload["api_key"] = api_key

        r = _patch("/config/llm", payload)
        if r and r.ok:
            st.session_state.settings_api_key = ""
            st.success(
                f"Updated: `{r.json()['provider']}` / `{r.json()['model']}` — "
                f"max_tokens={r.json()['max_tokens']}"
            )
            st.rerun()
        else:
            detail = r.json().get("detail", r.text) if r else "Request failed"
            st.error(f"Failed: {detail}")


# ── Router ──────────────────────────────────────────────────────────────────────
if st.session_state.page == "process":
    render_process()
elif st.session_state.page == "review":
    render_review()
elif st.session_state.page == "patterns":
    render_patterns()
elif st.session_state.page == "settings":
    render_settings()
