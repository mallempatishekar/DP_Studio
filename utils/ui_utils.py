"""
ui_utils.py — Shared UI helpers for all pages.
Loads the global CSS design system and provides reusable HTML components.
"""

import os
import json
import uuid
import logging
import streamlit as st
from pathlib import Path

# ── Logging setup ────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

logger = logging.getLogger("dp_generator")
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_user_id() -> str:
    if "dp_user_id" not in st.session_state:
        st.session_state.dp_user_id = str(uuid.uuid4())
    return st.session_state.dp_user_id


def log_event(level: str, message: str, **context):
    user_id = get_user_id()
    extra = {"user_id": user_id, **context}
    text = f"{message} | {json.dumps(extra, default=str)}"
    if level.lower() == "info":
        logger.info(text)
    elif level.lower() == "warning":
        logger.warning(text)
    elif level.lower() == "error":
        logger.error(text)
    else:
        logger.debug(text)


def _clear_nav_state():
    for _k in ["sm_mode", "sm_origin", "semantic_section",
                "dp_origin", "dp_step", "dp_entry_step",
                "depot_origin", "depot_specific_file", "flare_origin",
                "cadp_qc_origin", "sadp_qc_origin"]:
        st.session_state.pop(_k, None)

# --- Callback for Reset Button (Must be defined before usage) ---
def _reset_model_callback():
    """Callback to reset model to default."""
    st.session_state.groq_model_name = "llama-3.3-70b-versatile"
    # Note: No st.rerun() needed here, Streamlit reruns automatically after callback

# --- Callback for API Key Sync (Must be defined before usage) ---
def _on_api_key_change():
    """Syncs the separate widget key back to our storage key."""
    st.session_state.groq_api_key = st.session_state._api_key_widget

def render_sidebar():
    # Initialize all LLM config keys at the start to ensure persistence
    if "llm_provider" not in st.session_state:
        st.session_state.llm_provider = "groq"
    if "groq_api_key" not in st.session_state:
        st.session_state.groq_api_key = ""
    if "groq_model_name" not in st.session_state:
        st.session_state.groq_model_name = "llama-3.3-70b-versatile"
    if "ollama_base_url" not in st.session_state:
        st.session_state.ollama_base_url = "http://localhost:11434"
    if "ollama_model_name" not in st.session_state:
        st.session_state.ollama_model_name = "llama3"
    
    with st.sidebar:
        # --- Title ---
        st.markdown(
            '<div style="padding:16px 8px 8px 8px;">'
            '<p style="font-size:16px;font-weight:700;color:#f3f4f6;margin:0;letter-spacing:-0.01em;">'
            '⚙️ DP YAML Generator</p>'
            '<p style="font-size:11px;color:#6b7280;margin:4px 0 0 0;">YAML & SQL file builder</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="border-top:1px solid #1f2937;margin:8px 0 12px 0;"></div>',
            unsafe_allow_html=True,
        )
        
        # --- Navigation ---
        if st.button("🏠  Home", key="sb_home", use_container_width=True):
            _clear_nav_state()
            st.switch_page("app.py")
        if st.button("🕓  History", key="sb_history", use_container_width=True):
            st.switch_page("pages/10_History.py")

        # --- LLM Configuration Section ---
        st.markdown('<div style="border-top:1px solid #1f2937;margin:16px 0 12px 0;"></div>', unsafe_allow_html=True)
        with st.expander("🤖 LLM Configuration", expanded=False):
            
            # 1. Provider Selection
            provider = st.selectbox(  
                "Provider", 
                ["groq", "ollama"], 
                key="llm_provider",
                help="Select 'groq' for cloud or 'ollama' for local models."
            )

            if provider == "groq":
                # Toggle state for show/hide
                if "show_api_key" not in st.session_state:
                    st.session_state.show_api_key = False

                # CSS — mask input & proper alignment
                security = "none" if st.session_state.show_api_key else "disc"
                st.markdown(f"""
                <style>
                    /* Mask input */
                    div[data-testid="stTextInput"] input[aria-label="Groq API Key"] {{
                        -webkit-text-security: {security};
                    }}

                    /* Proper button styling */
                    #toggle_api_key_btn {{
                        min-height: 42px !important;
                        width: 100% !important;
                        display: flex !important;
                        align-items: center !important;
                        justify-content: center !important;
                        border-radius: 8px !important;
                        margin: 0 !important;
                        padding: 0px !important;
                    }}
                    #toggle_api_key_btn > button {{
                        min-height: 36px !important;
                        height: 36px !important;
                        width: 100% !important;
                        padding: 0 8px !important;
                        margin: 0 !important;
                        line-height: 1 !important;
                        font-size: 16px !important;
                    }}
                </style>
                """, unsafe_allow_html=True)

                # Re-seed widget if Streamlit cleared it during page switch
                if "_api_key_widget" not in st.session_state:
                    st.session_state._api_key_widget = st.session_state.get("groq_api_key", "")

                # Input + Eye button side by side
                key_col, btn_col = st.columns([0.88, 0.12], gap="small")
                with key_col:
                    st.text_input(
                        "Groq API Key",
                        key="_api_key_widget",
                        on_change=_on_api_key_change,
                        help="Enter your Groq API Key (gsk_...)"
                    )
                with btn_col:
                    st.markdown(
                        "<div style='display:flex; align-items:center; justify-content:center; height:100%; min-height:28px;'>",
                        unsafe_allow_html=True
                    )

                    eye = "🙈" if st.session_state.show_api_key else "👁️"
                    if st.button(eye, key="toggle_api_key_btn", help="Show / Hide API Key"):
                        st.session_state.show_api_key = not st.session_state.show_api_key
                        st.rerun()

                    st.markdown("</div>", unsafe_allow_html=True)

                
                # Model List - Optimized for YAML/SQL generation
                groq_models = [
                    "llama-3.3-70b-versatile",      # Best for complex code generation (70B)
                    "mixtral-8x7b-32768",           # Excellent for code tasks, good balance of quality & speed
                    "llama-3.1-70b-versatile",      # Alternative 70B model with good code generation
                    "llama-3.1-8b-instant",         # Quick operations (lower quality but fast)
                ]
                
                # --- SAFE DEFAULT LOGIC (BEFORE WIDGET) ---
                # If key invalid (ghost value), update it NOW
                if st.session_state.groq_model_name not in groq_models:
                    st.session_state.groq_model_name = groq_models[0]
                
                # Create Widget
                st.selectbox( 
                    "Model",
                    groq_models,
                    key="groq_model_name"
                )
                
                # Reset Button using Callback (Prevents Exception)
                st.button("🔄 Reset to Default Model", on_click=_reset_model_callback, key="reset_model_btn")

            else:
                # Ollama Logic
                st.text_input(
                    "Base URL", 
                    key="ollama_base_url"
                )
                st.text_input(
                    "Model Name", 
                    key="ollama_model_name"
                )
            st.caption("Settings apply globally for this session.")

def get_llm_config() -> dict:
    provider = st.session_state.get("llm_provider", "groq")

    # Persist by default across pages; fallback to environment if not set in UI.
    groq_api_key = st.session_state.get("groq_api_key", "") or os.getenv("GROQ_API_KEY", "")
    ollama_base_url = st.session_state.get("ollama_base_url", "http://localhost:11434")
    groq_model_name = st.session_state.get("groq_model_name", "llama-3.1-8b-instant")
    ollama_model_name = st.session_state.get("ollama_model_name", "llama3")

    if provider == "groq":
        return {
            "provider": "groq",
            "api_key": groq_api_key,
            "model": groq_model_name,
        }
    else:
        return {
            "provider": "ollama",
            "base_url": ollama_base_url,
            "model": ollama_model_name,
        }

def load_global_css():
    css_path = os.path.join(os.path.dirname(__file__), "..", "assets", "style.css")
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass
    st.markdown("""
        <style>
            [data-testid="stSidebarNav"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)


def section_header(icon: str, title: str):
    st.markdown(
        f'<div class="section-header"><span>{icon}</span><h4>{title}</h4></div>',
        unsafe_allow_html=True,
    )

def group_label(title: str, dot_class: str = "dot-blue"):
    st.markdown(
        f'<div class="group-label"><span class="dot {dot_class}"></span>{title}</div>',
        unsafe_allow_html=True,
    )

def yaml_tab(filename: str):
    st.markdown(
        f'<div class="yaml-tab"><span class="yaml-dot"></span>{filename}</div>',
        unsafe_allow_html=True,
    )

def app_footer():
    st.markdown(
        '<div class="app-footer">⚙️ &nbsp; Internal Automation Tool — YAML & SQL Generation</div>',
        unsafe_allow_html=True,
    )

DOCS_URLS = {
    "lens":        ("Lens Docs",        "https://dataos.info/resources/lens/"),
    "segments":    ("Segments Docs",    "https://dataos.info/resources/lens/segments/"),
    "user_groups": ("User Groups Docs", "https://dataos.info/resources/lens/user_groups_and_data_policies/"),
    "views":       ("Views Docs",       "https://dataos.info/resources/lens/views/"),
    "bundle":      ("Bundle Docs",      "https://dataos.info/resources/bundle/"),
    "spec":        ("DP Spec Docs",     "https://dataos.info/learn/dp_foundations1_learn_track/create_dp_spec/"),
    "scanner":     ("Scanner Docs",     "https://dataos.info/resources/stacks/scanner/"),
    "depot":       ("Depot Docs",       "https://dataos.info/resources/depot/"),
    "flare":       ("Flare Docs",       "https://dataos.info/resources/stacks/flare/"),
    "dp_learn":    ("DP Learn Track",   "https://dataos.info/learn/dp_developer_learn_track/"),
}

def floating_docs(*keys: str):
    css = """
<style>
.floating-docs {
    position: fixed; bottom: 28px; right: 28px; z-index: 9999;
    display: flex; flex-direction: column; align-items: flex-end; gap: 8px;
}
.floating-docs a {
    display: flex; align-items: center; gap: 8px;
    background: #1e2638; border: 1px solid #3b82f6;
    color: #93c5fd !important; text-decoration: none !important;
    padding: 10px 16px; border-radius: 999px;
    font-size: 13px; font-weight: 600; font-family: 'DM Sans', sans-serif;
    box-shadow: 0 4px 16px rgba(59,130,246,0.25); transition: all 0.2s ease;
    white-space: nowrap;
}
.floating-docs a:hover {
    background: #253047; border-color: #60a5fa; color: #bfdbfe !important;
    box-shadow: 0 6px 20px rgba(59,130,246,0.4); transform: translateY(-2px);
}
</style>"""
    links_html = "\n".join(
        f'    <a href="{DOCS_URLS[k][1]}" target="_blank">📖 {DOCS_URLS[k][0]}</a>'
        for k in keys if k in DOCS_URLS
    )
    st.markdown(
        f'{css}\n<div class="floating-docs">\n{links_html}\n</div>',
        unsafe_allow_html=True,
    )

def inline_docs_banner(*keys: str):
    links = " &nbsp;·&nbsp; ".join(
        f'<a href="{DOCS_URLS[k][1]}" target="_blank" '
        f'style="color:#60a5fa;font-size:12px;text-decoration:none;">📖 {DOCS_URLS[k][0]}</a>'
        for k in keys if k in DOCS_URLS
    )
    st.markdown(
        f'<div style="margin-bottom:12px; padding:8px 12px; background:#111827; '
        f'border:1px solid #1f2937; border-radius:8px;">{links}</div>',
        unsafe_allow_html=True,
    )