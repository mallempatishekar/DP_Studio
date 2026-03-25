"""
SADP Quality Checks
════════════════════
Standalone quality checks page for the Source-Aligned Data Product flow.
Supports multi-table selection for Snowflake, batch processing, and ZIP download.
"""

import streamlit as st
import json
import sys, os
import pandas as pd
import copy
import zipfile
from io import BytesIO

@st.cache_data
def read_excel_cached(file):
    return pd.read_excel(file)

from utils.qc_learning.qc_diff_engine import detect_new_rules
from utils.qc_learning.save_learning import save_reference_rules

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.ui_utils import load_global_css, render_sidebar, section_header, app_footer
from utils.sf_utils import (
    connect, fetch_databases, fetch_schemas,
    fetch_tables, fetch_full_context, fetch_schema_overview,
)
from utils.default_checks import generate_default_checks
from utils.llm_checks import call_llm
from utils.qc_yaml_generator import generate_qc_yaml
from utils.qc_config import PROVIDER, GROQ_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL

st.set_page_config(page_title="SADP — Quality Checks", page_icon="✅", layout="wide")
load_global_css()
render_sidebar()

CATEGORIES = [
    ("Schema",       "🔷", "#1e3a5f", "#93c5fd"),
    ("Completeness", "🟢", "#14532d", "#86efac"),
    ("Uniqueness",   "🟣", "#3b0764", "#d8b4fe"),
    ("Freshness",    "🟡", "#78350f", "#fcd34d"),
    ("Validity",     "🩷", "#4a1d4a", "#f9a8d4"),
    ("Accuracy",     "🩵", "#134e4a", "#6ee7b7"),
]
CAT_NAMES = [c[0] for c in CATEGORIES]

_QC_DEFAULTS = {
    # Snowflake Connection State
    "sadp_qc_sf_conn": None, "sadp_qc_sf_databases": [], "sadp_qc_sf_last_db": "",
    "sadp_qc_sf_schemas": [], "sadp_qc_sf_last_schema": "", "sadp_qc_sf_tables": [],
    
    # Multi-table processing state
    "sadp_qc_selected_tables": [],
    "sadp_qc_processed_tables": set(),
    "sadp_qc_all_yaml": {},
    "sadp_qc_current_table": None,
    
    # Current table context
    "sadp_qc_ctx": None, "sadp_qc_default_checks": [], "sadp_qc_llm_suggestions": [],
    "sadp_qc_accepted_defaults": {}, "sadp_qc_accepted_llm": {},
    "sadp_qc_show_manual_form": False,
    "sadp_qc_llm_done": False, "sadp_qc_llm_error": None,
    
    # Workflow metadata
    "sadp_qc_wf_name": "", "sadp_qc_wf_desc": "", "sadp_qc_wf_depot": "",
    "sadp_qc_wf_workspace": "public", "sadp_qc_wf_engine": "", "sadp_qc_wf_cluster": "",
    "sadp_qc_wf_tag_domain": "", "sadp_qc_wf_tag_usecase": "",
    "sadp_qc_wf_tag_tier": "Source Aligned",
    "sadp_qc_wf_tag_region": "", "sadp_qc_wf_tag_dataos": "", "sadp_qc_wf_tag_custom": "",
    "sadp_qc_last_yaml": None, "sadp_qc_last_yaml_name": "",
}

for k, v in _QC_DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

def _manual_key():
    table = st.session_state.get("sadp_qc_current_table", "")
    return f"sadp_qc_manual_{table}"

def _accepted_manual_key():
    table = st.session_state.get("sadp_qc_current_table", "")
    return f"sadp_qc_acc_manual_{table}"

def reset_table_state():
    for k in ["sadp_qc_ctx", "sadp_qc_default_checks", "sadp_qc_llm_suggestions",
              "sadp_qc_accepted_defaults", "sadp_qc_accepted_llm",
              "sadp_qc_llm_done", "sadp_qc_llm_error",
              "sadp_qc_last_yaml", "sadp_qc_last_yaml_name"]:
        st.session_state[k] = _QC_DEFAULTS.get(k, None) or (
            [] if "checks" in k or "suggestions" in k
            else {} if "accepted" in k
            else None
        )

def checks_by_category(checks):
    out = {cat: [] for cat in CAT_NAMES}
    for i, chk in enumerate(checks):
        cat = chk.get("category", "Schema")
        if cat in out:
            out[cat].append((i, chk))
    return out

def syntax_preview(chk):
    s = chk.get("syntax", "")
    body = chk.get("body") or {}
    if s == "schema":
        if "warn" in body:
            cols = body["warn"].get("when required column missing", [])
            snip = ", ".join(str(c) for c in cols[:4])
            more = f" ... +{len(cols)-4}" if len(cols) > 4 else ""
            return f"schema: warn when required column missing: [{snip}{more}]"
        if "fail" in body:
            n = len(body["fail"].get("when wrong column type", {}))
            return f"schema: fail when wrong column type: ({n} columns)"
    parts = [s]
    for k, v in body.items():
        parts.append(f"  {k}: {v}")
    return "\\n".join(parts)

# ── Header + Nav ──────────────────────────────────────────────────────────────
st.markdown("## ✅ Quality Checks")
st.markdown(
    '<p style="color:#6b7280;font-size:13px;margin-top:-8px;">'
    'Connect to Snowflake, select multiple tables, generate checks, and export as ZIP.'
    '</p>', unsafe_allow_html=True,
)
nav_l, _, nav_r = st.columns([1, 4, 1.5])
with nav_l:
    if st.button("← Back"):
        st.switch_page("pages/sadp_flow.py")
with nav_r:
    if st.button("🔄 Start Over"):
        for k in list(_QC_DEFAULTS.keys()):
            st.session_state[k] = _QC_DEFAULTS[k]
        st.rerun()

model_label = GROQ_DEFAULT_MODEL if PROVIDER == "groq" else OLLAMA_DEFAULT_MODEL
st.markdown(
    f'<div style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:8px;'
    f'padding:8px 14px;font-size:12px;color:#6b7280;margin:8px 0;">'
    f'⚙️ LLM Provider: <b style="color:#374151">{PROVIDER.upper()}</b> &nbsp;|&nbsp; '
    f'Model: <b style="color:#374151">{model_label}</b> &nbsp;|&nbsp; '
    f'Edit in <b style="color:#374151">utils/qc_config.py</b></div>',
    unsafe_allow_html=True,
)
st.divider()

# ── ① Database Connection ─────────────────────────────────────────────────────
section_header("🔗", "Database Connection")

# ── Snowflake Connection ──────────────────────────────────────────────────────
# Level 1: reuse existing sf_conn object
if st.session_state.sadp_qc_sf_conn is None and st.session_state.get("sf_conn"):
    try:
        st.session_state.sadp_qc_sf_conn      = st.session_state.sf_conn
        st.session_state.sadp_qc_sf_databases = fetch_databases(st.session_state.sadp_qc_sf_conn)
        st.success("✅ Reusing Snowflake connection from previous step.")
    except Exception:
        st.session_state.sadp_qc_sf_conn = None

# Level 2: auto-connect from Depot credentials (no form needed)
if st.session_state.sadp_qc_sf_conn is None:
    _d_acct = st.session_state.get("depot_account", "")
    _d_user = st.session_state.get("depot_username", "")
    _d_pw   = st.session_state.get("depot_password", "")
    _d_wh   = st.session_state.get("depot_warehouse", "")
    if _d_acct and _d_user and _d_pw:
        with st.spinner("Auto-connecting to Snowflake using Depot credentials..."):
            try:
                _auto_conn = connect(_d_acct.strip(), _d_user.strip(), _d_pw, warehouse=_d_wh.strip())
                st.session_state.sadp_qc_sf_conn      = _auto_conn
                st.session_state.sadp_qc_sf_databases = fetch_databases(_auto_conn)
                st.session_state["sf_conn"]           = _auto_conn
                st.success("✅ Auto-connected to Snowflake using Depot credentials.")
                st.rerun()
            except Exception as _e:
                st.warning(f"⚠️ Could not auto-connect using Depot credentials: {_e}. Please connect manually below.")

# Level 3: manual form — pre-fill from depot credentials where available
if st.session_state.sadp_qc_sf_conn is None:
    _pre_acct = st.session_state.get("depot_account", "")
    _pre_user = st.session_state.get("depot_username", "")
    _pre_wh   = st.session_state.get("depot_warehouse", "")
    with st.form("sadp_qc_sf_form"):
        c1, c2 = st.columns(2)
        with c1:
            sf_acct = st.text_input("Account Identifier *", value=_pre_acct,
                                    placeholder="abc12345.us-east-1.aws")
            sf_user = st.text_input("Username *", value=_pre_user,
                                    placeholder="john_doe")
        with c2:
            sf_pw   = st.text_input("Password *", type="password")
            sf_role = st.text_input("Role (optional)", placeholder="SYSADMIN")
            sf_wh   = st.text_input("Warehouse (optional)", value=_pre_wh,
                                    placeholder="COMPUTE_WH")
        if _pre_acct or _pre_user:
            st.markdown(
                '<p style="font-size:12px;color:#6b7280;margin-top:4px;">'
                '💡 Account, username and warehouse pre-filled from Depot step. Enter password to connect.</p>',
                unsafe_allow_html=True,
            )
        go = st.form_submit_button("Connect", use_container_width=True, type="primary")
    if go:
        if not sf_acct or not sf_user or not sf_pw:
            st.error("Account, username and password are required.")
        else:
            with st.spinner("Connecting..."):
                try:
                    _conn = connect(sf_acct.strip(), sf_user.strip(), sf_pw, sf_role.strip(), sf_wh.strip())
                    st.session_state.sadp_qc_sf_conn      = _conn
                    st.session_state.sadp_qc_sf_databases = fetch_databases(_conn)
                    st.session_state["sf_conn"]           = _conn
                    st.rerun()
                except Exception as e:
                    st.error(f"Connection failed: {e}")
    st.stop()

hdr_c, disc_c = st.columns([8, 1])
with hdr_c:
    st.success("✅ Connected to Snowflake")
with disc_c:
    if st.button("Disconnect"):
        for k in list(_QC_DEFAULTS.keys()):
            st.session_state[k] = _QC_DEFAULTS[k]
        st.rerun()

# ── Route DB utilities ────────────────────────────────────────────────────────
_conn           = st.session_state.sadp_qc_sf_conn
_db_list_key    = "sadp_qc_sf_databases"
_schema_list_key= "sadp_qc_sf_schemas"
_table_list_key = "sadp_qc_sf_tables"
_last_db_key    = "sadp_qc_sf_last_db"
_last_schema_key= "sadp_qc_sf_last_schema"
_fetch_schemas  = fetch_schemas
_fetch_tables   = fetch_tables
_fetch_full_ctx = fetch_full_context
_fetch_overview = fetch_schema_overview

# ── ② Multi-Table Selection ───────────────────────────────────────────────────
st.divider()
section_header("🗄️", "Select Tables")

# DB Selection
d1, d2 = st.columns(2)
with d1:
    db_opts = ["— select —"] + st.session_state[_db_list_key]
    db_idx  = db_opts.index(st.session_state[_last_db_key]) if st.session_state[_last_db_key] in db_opts else 0
    sel_db  = st.selectbox("Database", db_opts, index=db_idx)
    if sel_db != "— select —" and sel_db != st.session_state[_last_db_key]:
        st.session_state[_last_db_key]     = sel_db
        st.session_state[_schema_list_key] = _fetch_schemas(_conn, sel_db)
        st.session_state[_last_schema_key] = ""
        st.session_state[_table_list_key]  = []
        # Reset selection state
        st.session_state.sadp_qc_selected_tables = []
        st.session_state.sadp_qc_processed_tables = set()
        st.session_state.sadp_qc_all_yaml = {}
        st.rerun()

with d2:
    sc_opts = ["— select —"] + st.session_state[_schema_list_key]
    sc_idx  = sc_opts.index(st.session_state[_last_schema_key]) if st.session_state[_last_schema_key] in sc_opts else 0
    sel_sc  = st.selectbox("Schema", sc_opts, index=sc_idx, disabled=not st.session_state[_schema_list_key])
    if sel_sc != "— select —" and sel_sc != st.session_state[_last_schema_key]:
        st.session_state[_last_schema_key] = sel_sc
        st.session_state[_table_list_key]  = _fetch_tables(_conn, st.session_state[_last_db_key], sel_sc)
        # Reset selection state
        st.session_state.sadp_qc_selected_tables = []
        st.session_state.sadp_qc_processed_tables = set()
        st.session_state.sadp_qc_all_yaml = {}
        st.rerun()

# Multi-select for tables
available_tables = st.session_state[_table_list_key]
if not available_tables:
    st.stop()

selected_tables = st.multiselect(
    "Select Tables for QC Generation",
    available_tables,
    default=st.session_state.sadp_qc_selected_tables,
    help="Select one or more tables to generate QC checks."
)

# Update session state if selection changes
if selected_tables != st.session_state.sadp_qc_selected_tables:
    st.session_state.sadp_qc_selected_tables = selected_tables

# Progress Display
total_selected = len(selected_tables)
total_done = len([t for t in selected_tables if t in st.session_state.sadp_qc_processed_tables])

if total_selected > 0:
    st.progress(total_done / total_selected, text=f"Progress: {total_done}/{total_selected} tables processed")

# Determine current table to process
current_table = None
if st.session_state.sadp_qc_current_table:
    current_table = st.session_state.sadp_qc_current_table
elif selected_tables:
    for t in selected_tables:
        if t not in st.session_state.sadp_qc_processed_tables:
            current_table = t
            break

# Action Buttons
col_act1, col_act2, col_act3 = st.columns([2, 2, 2])
with col_act1:
    if current_table and current_table not in st.session_state.sadp_qc_processed_tables:
        if st.button(f"⚡ Load & Review: {current_table}", type="primary", use_container_width=True):
            st.session_state.sadp_qc_current_table = current_table
            reset_table_state()
            
            with st.spinner(f"Pulling schema & profiling for {current_table}..."):
                try:
                    _ctx = _fetch_full_ctx(
                        _conn,
                        st.session_state[_last_db_key],
                        st.session_state[_last_schema_key],
                        current_table,
                    )
                    _ctx["schema_overview"] = _fetch_overview(
                        _conn,
                        st.session_state[_last_db_key],
                        st.session_state[_last_schema_key],
                    )
                    st.session_state.sadp_qc_ctx = _ctx
                    
                    _defs = generate_default_checks(_ctx)
                    for _chk in _defs:
                        _chk["_original"] = {
                            "name": _chk.get("name"),
                            "syntax": _chk.get("syntax"),
                            "body": json.dumps(_chk.get("body"), sort_keys=True),
                        }
                    st.session_state.sadp_qc_default_checks    = _defs
                    st.session_state.sadp_qc_accepted_defaults = {i: True for i in range(len(_defs))}
                    st.session_state["generated_qc_checks"]    = copy.deepcopy(_defs)
                    
                    if _ctx["errors"]:
                        for err in _ctx["errors"]:
                            st.warning(f"⚠️ {err}")
                except Exception as e:
                    st.error(f"Failed to fetch table context: {e}")
            st.rerun()

with col_act2:
    remaining = [t for t in selected_tables if t not in st.session_state.sadp_qc_processed_tables]
    if remaining:
        if st.button(f"🚀 Bulk Generate Defaults ({len(remaining)} tables)", use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, t_name in enumerate(remaining):
                status_text.text(f"Processing {t_name}...")
                try:
                    t_ctx = _fetch_full_ctx(_conn, st.session_state[_last_db_key], st.session_state[_last_schema_key], t_name)
                    t_defs = generate_default_checks(t_ctx)
                    accepted_checks = t_defs
                    
                    wf_name = f"soda-{t_name.lower()}-qc"
                    depot = st.session_state.sadp_qc_wf_depot or "depot"
                    workspace = st.session_state.sadp_qc_wf_workspace or "public"
                    
                    tags = ["workflow", "soda-checks", "DPTier.Source Aligned"]
                    db = st.session_state[_last_db_key]
                    sch = st.session_state[_last_schema_key]
                    udl = f"dataos://{depot}:{db}.{sch}/{t_name}"
                    
                    yaml_out = generate_qc_yaml(
                        metadata={"workflow_name": wf_name, "description": f"QC for {t_name}", "tags": tags},
                        accepted_checks=accepted_checks, dataset_udl=udl, workspace=workspace
                    )
                    
                    st.session_state.sadp_qc_all_yaml[t_name] = yaml_out
                    st.session_state.sadp_qc_processed_tables.add(t_name)
                except Exception as e:
                    st.warning(f"Failed to process {t_name}: {e}")
                
                progress_bar.progress((i + 1) / len(remaining))
            
            status_text.text("Bulk generation complete!")
            # Set last_yaml to the final table so preview section renders
            if st.session_state.sadp_qc_all_yaml:
                _last_tbl = list(st.session_state.sadp_qc_all_yaml.keys())[-1]
                st.session_state.sadp_qc_last_yaml      = st.session_state.sadp_qc_all_yaml[_last_tbl]
                st.session_state.sadp_qc_last_yaml_name = f"soda-{_last_tbl.lower()}-qc.yml"
            st.rerun()

with col_act3:
    if st.session_state.sadp_qc_all_yaml:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for t_name, yaml_content in st.session_state.sadp_qc_all_yaml.items():
                if isinstance(yaml_content, (dict, list)):
                    import yaml
                    _content = yaml.dump(yaml_content, sort_keys=False)
                else:
                    _content = yaml_content

                fname = f"soda-{t_name.lower()}-qc.yml"
                zf.writestr(fname, _content)

        zip_buffer.seek(0)
        st.download_button(
            "📥 Download All QC (ZIP)",
            data=zip_buffer,
            file_name="sadp_qc_checks.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary"
        )

# ── Back to SADP Flow — shown when at least one table is done ─────────────────
if st.session_state.sadp_qc_all_yaml and st.session_state.get("sadp_qc_origin") == "sadp_full":
    _n_done = len(st.session_state.sadp_qc_all_yaml)
    st.markdown(" ")
    st.markdown(
        f'<div style="background:#f0fdf4;border:1px solid #86efac;border-left:3px solid #16a34a;'
        f'border-radius:8px;padding:10px 16px;font-size:13px;color:#15803d;margin-bottom:8px;">'
        f'✅ <b>{_n_done} table{"s" if _n_done != 1 else ""}</b> '
        f'{"have" if _n_done != 1 else "has"} been processed and saved.</div>',
        unsafe_allow_html=True,
    )
    if st.button("✅ Done — Back to SADP Flow", key="sadp_qc_back_to_flow",
                 type="primary", use_container_width=True):
        if "sadp_completed_steps" not in st.session_state:
            st.session_state.sadp_completed_steps = set()
        st.session_state.sadp_completed_steps.add(2)
        st.switch_page("pages/sadp_flow.py")

# ── ③ Checks Review (Single Table) ───────────────────────────────────────────
if st.session_state.sadp_qc_ctx and st.session_state.get("sadp_qc_current_table"):
    ctx = st.session_state.sadp_qc_ctx
    st.divider()
    
    curr_t = st.session_state.sadp_qc_current_table
    proc_count = len(st.session_state.sadp_qc_processed_tables)
    sel_count = len(st.session_state.sadp_qc_selected_tables)
    
    section_header("🔍", f"Reviewing: {curr_t} ({proc_count+1}/{sel_count})")

    ic, wc = st.columns([3, 3])
    with ic:
        st.caption(f"📊 {len(ctx['columns'])} columns · ~{ctx['row_count'] or '?'} rows sampled")
    if ctx["errors"]:
        with wc:
            with st.expander(f"⚠️ {len(ctx['errors'])} data-pull warning(s)"):
                for e in ctx["errors"]:
                    st.caption(f"• {e}")

    with st.expander("🧠 Upload Metadata for Advanced LLM Checks (optional)"):
        uploaded_meta = st.file_uploader("Upload Excel with table & column descriptions", type=["xlsx"], key="sadp_qc_meta_upload")
        semantic_metadata = None
        if uploaded_meta:
            try:
                df_meta = pd.read_excel(uploaded_meta)
                required = {"table_name", "table_description", "column_name", "column_description"}
                if not required.issubset(set(df_meta.columns)):
                    st.error("Excel format invalid — required columns missing.")
                else:
                    semantic_metadata = df_meta
                    st.success(f"✅ {len(df_meta)} metadata rows loaded.")
            except Exception as e:
                st.error(f"Failed to read metadata: {e}")

    st.markdown(" ")

    # ── LLM controls ──────────────────────────────────────────────────────────────
    llm_c1, llm_c2 = st.columns([4, 1])
    with llm_c1:
        llm_label = "✨ Generate LLM Suggestions" if not st.session_state.sadp_qc_llm_done else "🔄 Re-run LLM Suggestions"
        run_llm = st.button(llm_label, type="primary", use_container_width=True)
    with llm_c2:
        if st.button("Clear LLM", use_container_width=True):
            st.session_state.sadp_qc_llm_suggestions = []
            st.session_state.sadp_qc_accepted_llm    = {}
            st.session_state.sadp_qc_llm_done        = False
            st.session_state.sadp_qc_llm_error       = None
            st.rerun()

    if run_llm and not st.session_state.sadp_qc_llm_done:
        with st.spinner("Calling LLM..."):
            try:
                ctx_for_llm = ctx.copy()
                ctx_for_llm["columns"] = [c.copy() for c in ctx.get("columns", [])]
                if semantic_metadata is not None:
                    tbl_rows = semantic_metadata[semantic_metadata["table_name"] == ctx["table"]]
                    if not tbl_rows.empty:
                        ctx_for_llm["table_description"] = tbl_rows.iloc[0]["table_description"]
                        col_desc = dict(zip(tbl_rows["column_name"], tbl_rows["column_description"]))
                        for col in ctx_for_llm["columns"]:
                            col["description"] = col_desc.get(col["name"], "")
                try:
                    suggs = call_llm(ctx_for_llm, st.session_state.sadp_qc_default_checks)
                except RuntimeError as e:
                    st.session_state.sadp_qc_llm_error = str(e)
                    st.rerun()
                for chk in suggs:
                    chk["_original"] = {
                        "name": chk.get("name"),
                        "syntax": chk.get("syntax"),
                        "body": json.dumps(chk.get("body"), sort_keys=True),
                    }
                st.session_state.sadp_qc_llm_suggestions = suggs
                generated_all = st.session_state.sadp_qc_default_checks + suggs
                st.session_state["generated_qc_checks"] = copy.deepcopy(generated_all)
                st.session_state.sadp_qc_accepted_llm    = {i: False for i in range(len(suggs))}
                st.session_state.sadp_qc_llm_done        = True
                st.session_state.sadp_qc_llm_error       = None
            except Exception as e:
                st.session_state.sadp_qc_llm_error = str(e)
        st.rerun()

    if st.session_state.sadp_qc_llm_error:
        st.error(f"LLM error: {st.session_state.sadp_qc_llm_error}")
        st.caption("Check your API key in utils/qc_config.py")
    if st.session_state.sadp_qc_llm_done and st.session_state.sadp_qc_llm_suggestions:
        st.success(f"✅ {len(st.session_state.sadp_qc_llm_suggestions)} LLM suggestions ready — tick what you want to include.")

    # ── Category buckets ──────────────────────────────────────────────────────────
    def_by_cat    = checks_by_category(st.session_state.sadp_qc_default_checks)
    llm_by_cat    = checks_by_category(st.session_state.sadp_qc_llm_suggestions)
    manual_key    = _manual_key()
    acc_man_key   = _accepted_manual_key()
    manual_checks = st.session_state.get(manual_key, [])
    acc_manual    = st.session_state.get(acc_man_key, {})
    manual_by_cat = checks_by_category(manual_checks)

    for cat_name, icon, bg_color, text_color in CATEGORIES:
        def_items    = def_by_cat.get(cat_name, [])
        llm_items    = llm_by_cat.get(cat_name, [])
        manual_items = manual_by_cat.get(cat_name, [])
        if not def_items and not llm_items and not manual_items:
            continue
        total_checks   = len(def_items) + len(llm_items) + len(manual_items)
        accepted_count = (
            sum(1 for i, _ in def_items    if st.session_state.sadp_qc_accepted_defaults.get(i, True)) +
            sum(1 for i, _ in llm_items    if st.session_state.sadp_qc_accepted_llm.get(i, False)) +
            sum(1 for i, _ in manual_items if acc_manual.get(i, True))
        )
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;padding:10px 16px;'
            f'border-radius:8px 8px 0 0;margin-top:18px;background:{bg_color};">'
            f'{icon} <span style="color:{text_color};font-weight:700;font-size:15px;">{cat_name}</span>'
            f'<span style="color:{text_color};opacity:0.7;font-size:12px;margin-left:8px;">'
            f'{accepted_count}/{total_checks} selected</span></div>', unsafe_allow_html=True,
        )
        with st.container():
            if def_items:
                st.markdown('<span style="font-size:11px;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Default Checks</span>', unsafe_allow_html=True)
                for idx, chk in def_items:
                    col_chk, col_acc = st.columns([0.5, 9.5])
                    with col_acc:
                        with st.expander(f"[DEFAULT] {chk['col'] or 'table-level'} — {chk['name'][:80]}", expanded=False):
                            st.markdown('<span style="font-size:10px;font-weight:700;background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe;padding:1px 7px;border-radius:10px;">DEFAULT</span>', unsafe_allow_html=True)
                            st.code(syntax_preview(chk), language="yaml")
                            if chk.get("body"):
                                st.json(chk["body"])
                            new_syn  = st.text_area("Edit SodaCL condition", value=chk["syntax"], key=f"sadp_def_syn_{idx}", height=60)
                            st.session_state.sadp_qc_default_checks[idx]["syntax"] = new_syn
                            new_name = st.text_input("Check name", value=chk["name"], key=f"sadp_def_name_{idx}")
                            st.session_state.sadp_qc_default_checks[idx]["name"] = new_name
                            if chk.get("body") and chk["syntax"] != "schema":
                                body_str = st.text_area("body", value=json.dumps(chk["body"], indent=2), height=80, key=f"sadp_def_body_{idx}", label_visibility="collapsed")
                                try:
                                    st.session_state.sadp_qc_default_checks[idx]["body"] = json.loads(body_str)
                                except Exception:
                                    st.caption("⚠️ Invalid JSON — original body preserved")
                            orig = chk.get("_original", {})
                            if new_name != orig.get("name") or new_syn != orig.get("syntax"):
                                st.markdown("<span style='color:#facc15;font-weight:600;'>✏️ Modified</span>", unsafe_allow_html=True)
                    with col_chk:
                        acc = st.checkbox("✓", value=st.session_state.sadp_qc_accepted_defaults.get(idx, True), key=f"sadp_def_acc_{idx}", label_visibility="collapsed")
                        st.session_state.sadp_qc_accepted_defaults[idx] = acc

            if llm_items:
                st.markdown('<span style="font-size:11px;color:#7c3aed;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">LLM Suggested</span>', unsafe_allow_html=True)
                for idx, chk in llm_items:
                    col_chk, col_acc = st.columns([0.5, 9.5])
                    with col_acc:
                        with st.expander(f"[LLM] {chk.get('col') or 'table-level'} — {chk.get('name','')[:80]}", expanded=False):
                            st.markdown('<span style="font-size:10px;font-weight:700;background:#3b0764;color:#d8b4fe;padding:1px 7px;border-radius:10px;">LLM SUGGESTION</span>', unsafe_allow_html=True)
                            if chk.get("reason"):
                                st.markdown(f'<div style="font-size:11px;color:#6b7280;font-style:italic;margin-top:4px;">💡 {chk["reason"]}</div>', unsafe_allow_html=True)
                            new_name = st.text_input("Check name", value=chk.get("name",""), key=f"sadp_llm_name_{idx}")
                            st.session_state.sadp_qc_llm_suggestions[idx]["name"] = new_name
                            new_syn  = st.text_area("Edit SodaCL condition", value=chk.get("syntax",""), key=f"sadp_llm_syn_{idx}", height=70)
                            st.session_state.sadp_qc_llm_suggestions[idx]["syntax"] = new_syn
                            if chk.get("body"):
                                body_str = st.text_area("body", value=json.dumps(chk["body"], indent=2), height=80, key=f"sadp_llm_body_{idx}", label_visibility="collapsed")
                                try:
                                    st.session_state.sadp_qc_llm_suggestions[idx]["body"] = json.loads(body_str)
                                except Exception:
                                    st.caption("⚠️ Invalid JSON")
                    with col_chk:
                        acc = st.checkbox("✓", value=st.session_state.sadp_qc_accepted_llm.get(idx, False), key=f"sadp_llm_acc_{idx}", label_visibility="collapsed")
                        st.session_state.sadp_qc_accepted_llm[idx] = acc

            if manual_items:
                st.markdown('<span style="font-size:11px;color:#10b981;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Manual Checks</span>', unsafe_allow_html=True)
                for idx, chk in manual_items:
                    col_chk, col_acc = st.columns([0.5, 9.5])
                    with col_acc:
                        with st.expander(f"[MANUAL] {chk.get('col') or 'table-level'} — {chk['name'][:80]}", expanded=False):
                            st.markdown("<span style='color:#10b981;font-weight:700;'>🟢 MANUAL</span>", unsafe_allow_html=True)
                            new_name = st.text_input("Check name", value=chk["name"], key=f"sadp_man_name_{idx}")
                            manual_checks[idx]["name"] = new_name
                            new_syn  = st.text_area("Edit SodaCL condition", value=chk["syntax"], key=f"sadp_man_syn_{idx}", height=70)
                            manual_checks[idx]["syntax"] = new_syn
                    with col_chk:
                        acc = st.checkbox("✓", value=acc_manual.get(idx, True), key=f"sadp_man_acc_{idx}", label_visibility="collapsed")
                        acc_manual[idx] = acc
            st.markdown("---")

    # ── Summary ───────────────────────────────────────────────────────────────────
    acc_def_count = sum(1 for v in st.session_state.sadp_qc_accepted_defaults.values() if v)
    acc_llm_count = sum(1 for v in st.session_state.sadp_qc_accepted_llm.values() if v)
    acc_man_count = sum(1 for v in acc_manual.values() if v)
    total_acc     = acc_def_count + acc_llm_count + acc_man_count
    st.info(f"**{total_acc} checks** selected  ({acc_def_count} default · {acc_llm_count} LLM · {acc_man_count} manual)")

    if st.button("➕ Add Manual Check", use_container_width=True):
        st.session_state.sadp_qc_show_manual_form = True

    if st.session_state.sadp_qc_show_manual_form:
        table_cols = [c["name"] for c in ctx["columns"]]
        with st.form("sadp_manual_form"):
            c1, c2 = st.columns(2)
            with c1:
                m_name     = st.text_input("Check Name *")
                m_category = st.selectbox("Category", CAT_NAMES)
                m_column   = st.selectbox("Column (optional)", [""] + table_cols)
            with c2:
                m_syntax = st.text_input("SodaCL Syntax *", placeholder="e.g. missing_count(COL) = 0")
            m_body_str = st.text_area("Body JSON (optional)", value="", height=80)
            if st.form_submit_button("Add Check", type="primary"):
                if not m_name.strip() or not m_syntax.strip():
                    st.error("Name and syntax are required.")
                else:
                    try:
                        parsed_body = json.loads(m_body_str) if m_body_str.strip() else None
                    except Exception:
                        parsed_body = None
                    new_chk = {
                        "name": m_name.strip(), "syntax": m_syntax.strip(),
                        "body": parsed_body, "category": m_category,
                        "col": m_column.strip() or None,
                    }
                    if manual_key not in st.session_state:
                        st.session_state[manual_key] = []
                    idx = len(st.session_state[manual_key])
                    st.session_state[manual_key].append(new_chk)
                    if acc_man_key not in st.session_state:
                        st.session_state[acc_man_key] = {}
                    st.session_state[acc_man_key][idx] = True
                    st.session_state.sadp_qc_show_manual_form = False
                    st.rerun()

    # ── ④ Workflow Metadata + Save ────────────────────────────────────────────
    st.divider()
    section_header("⚙️", "Workflow Metadata & Save")

    with st.form("sadp_meta_form"):
        m1, m2 = st.columns(2)
        with m1:
            def_name = f"soda-{st.session_state.sadp_qc_current_table.lower()}-qc"
            wf_name = st.text_input("Workflow Name *", value=st.session_state.sadp_qc_wf_name or def_name)
            wf_desc = st.text_area("Description", value=st.session_state.sadp_qc_wf_desc or f"Quality checks for {st.session_state.sadp_qc_current_table}", height=80)
        with m2:
            wf_depot     = st.text_input("Depot Name *", value=st.session_state.sadp_qc_wf_depot, placeholder="e.g. sfdataproductsnaaprod")
            wf_workspace = st.text_input("Workspace *", value=st.session_state.sadp_qc_wf_workspace or "public")
        
        co1, co2 = st.columns(2)
        with co1:
            wf_engine  = st.text_input("Engine (optional)", value=st.session_state.sadp_qc_wf_engine)
        with co2:
            wf_cluster = st.text_input("Cluster (optional)", value=st.session_state.sadp_qc_wf_cluster)
        
        st.markdown("**Tags**")
        t1, t2, t3 = st.columns(3)
        with t1:
            tag_domain  = st.text_input("DPDomain", value=st.session_state.sadp_qc_wf_tag_domain)
            tag_usecase = st.text_input("DPUsecase", value=st.session_state.sadp_qc_wf_tag_usecase)
        with t2:
            tag_tier   = st.selectbox("DPTier", ["Source Aligned", "Consumer Aligned", "Derived"], index=0)
            tag_region = st.text_input("DPRegion", value=st.session_state.sadp_qc_wf_tag_region)
        with t3:
            tag_dataos = st.text_input("Dataos tag", value=st.session_state.sadp_qc_wf_tag_dataos)
            tag_custom = st.text_input("Custom project tag", value=st.session_state.sadp_qc_wf_tag_custom)
        
        gen_btn = st.form_submit_button("💾 Save & Generate QC for this Table", use_container_width=True, type="primary")
        
        if gen_btn:
            if not wf_name.strip() or not wf_depot.strip() or not wf_workspace.strip():
                st.error("Workflow name, Depot, and Workspace are required.")
            else:
                # Persist global tags
                st.session_state.sadp_qc_wf_depot = wf_depot.strip()
                st.session_state.sadp_qc_wf_workspace = wf_workspace.strip()
                st.session_state.sadp_qc_wf_tag_domain = tag_domain.strip()
                st.session_state.sadp_qc_wf_tag_usecase = tag_usecase.strip()
                st.session_state.sadp_qc_wf_tag_tier = tag_tier
                st.session_state.sadp_qc_wf_tag_region = tag_region.strip()
                st.session_state.sadp_qc_wf_tag_dataos = tag_dataos.strip()
                st.session_state.sadp_qc_wf_tag_custom = tag_custom.strip()
                
                # Collect accepted checks
                accepted = []
                for i, chk in enumerate(st.session_state.sadp_qc_default_checks):
                    if st.session_state.sadp_qc_accepted_defaults.get(i, True):
                        accepted.append(chk)
                for i, chk in enumerate(st.session_state.sadp_qc_llm_suggestions):
                    if st.session_state.sadp_qc_accepted_llm.get(i, False):
                        accepted.append(chk)
                for i, chk in enumerate(manual_checks):
                    if acc_manual.get(i, True):
                        accepted.append(chk)
                
                tags = ["workflow", "soda-checks"]
                if tag_domain: tags.append(f"DPDomain.{tag_domain}")
                if tag_usecase: tags.append(f"DPUsecase.{tag_usecase}")
                if tag_tier: tags.append(f"DPTier.{tag_tier}")
                
                db  = st.session_state[_last_db_key]
                sch = st.session_state[_last_schema_key]
                udl = f"dataos://{wf_depot.strip()}:{db}.{sch}/{st.session_state.sadp_qc_current_table}"
                
                try:
                    yaml_out = generate_qc_yaml(
                        metadata={"workflow_name": wf_name.strip(), "description": wf_desc.strip(), "tags": tags},
                        accepted_checks=accepted, dataset_udl=udl, workspace=wf_workspace.strip(),
                        engine=wf_engine.strip() or None, cluster=wf_cluster.strip() or None,
                    )
                    
                    # Save to all_yaml dict
                    st.session_state.sadp_qc_all_yaml[st.session_state.sadp_qc_current_table] = yaml_out
                    st.session_state.sadp_qc_processed_tables.add(st.session_state.sadp_qc_current_table)
                    
                    # Save for immediate viewing
                    st.session_state.sadp_qc_last_yaml = yaml_out
                    st.session_state.sadp_qc_last_yaml_name = f"{wf_name.strip()}.yaml"
                    
                    st.success(f"✅ QC generated for {st.session_state.sadp_qc_current_table}")
                    # REMOVED st.rerun() to allow code to render immediately below
                    
                except Exception as e:
                    st.error(f"YAML generation failed: {e}")

# ── ⑤ YAML Output Display ─────────────────────────────────────────────────────
if st.session_state.sadp_qc_last_yaml:
    st.divider()
    section_header("📄", "Generated QC YAML")

    # If multiple tables generated via bulk, show all in tabs
    all_yaml = st.session_state.sadp_qc_all_yaml
    if len(all_yaml) > 1:
        st.markdown(
            f'<p style="font-size:13px;color:#6b7280;margin-bottom:8px;">'
            f'Showing all {len(all_yaml)} generated files — click a tab to preview.</p>',
            unsafe_allow_html=True,
        )
        _tab_names = list(all_yaml.keys())
        _tabs = st.tabs(_tab_names)
        for _ti, (_tname, _tyaml) in enumerate(all_yaml.items()):
            with _tabs[_ti]:
                _fname = f"soda-{_tname.lower()}-qc.yml"
                st.download_button(
                    f"⬇️ Download {_fname}",
                    data=_tyaml,
                    file_name=_fname,
                    mime="text/yaml",
                    use_container_width=True,
                    type="primary",
                    key=f"dl_bulk_{_tname}",
                )
                st.code(_tyaml, language="yaml")
    else:
        # Single table — original layout
        dl_col, next_col = st.columns([2, 2])
        with dl_col:
            st.download_button("⬇️ Download YAML", data=st.session_state.sadp_qc_last_yaml,
                file_name=st.session_state.sadp_qc_last_yaml_name or "sadp-qc.yaml",
                mime="text/yaml", use_container_width=True, type="primary")
        with next_col:
            if st.button("➡️ Next Table", use_container_width=True, type="secondary"):
                reset_table_state()
                st.session_state.sadp_qc_current_table = None
                st.rerun()
        st.code(st.session_state.sadp_qc_last_yaml, language="yaml")

app_footer()