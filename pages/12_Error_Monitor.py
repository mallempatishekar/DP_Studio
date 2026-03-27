"""
Error Monitoring Dashboard
Monitor all errors logged in the application with filtering and analytics.
"""

import streamlit as st
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils.ui_utils import load_global_css, render_sidebar, app_footer
from utils.error_logger import get_error_summary, JSON_ERROR_LOG, ERROR_LOG_FILE
import json
from datetime import datetime
from pathlib import Path

st.set_page_config(page_title="Error Monitor", layout="wide")
load_global_css()
render_sidebar()

st.markdown("## 🔍 Error Monitoring")
st.markdown(
    '<p style="color:#6b7280; font-size:13px; margin-top:-8px; margin-bottom:16px;">'
    'Monitor, analyze, and troubleshoot all application errors in one place.'
    '</p>',
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# ERROR SUMMARY CARDS
# ─────────────────────────────────────────────────────────────────────────────

try:
    summary = get_error_summary()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Total Errors Logged",
            summary["total_errors"],
            help="All errors recorded since application started"
        )
    
    with col2:
        unique_categories = len(summary["error_counts"])
        st.metric(
            "Error Categories",
            unique_categories,
            help="Number of distinct error types"
        )
    
    with col3:
        if summary["total_errors"] > 0:
            top_error = max(summary["error_counts"].items(), key=lambda x: x[1])
            st.metric(
                "Most Common Error",
                top_error[0],
                value=top_error[1],
                help="Most frequently occurring error type"
            )
        else:
            st.metric("Most Common Error", "None", help="No errors yet")
    
    st.divider()
    
except Exception as e:
    st.error(f"Failed to load error summary: {e}")
    summary = {"total_errors": 0, "error_counts": {}, "error_examples": {}}

# ─────────────────────────────────────────────────────────────────────────────
# ERROR DISTRIBUTION
# ─────────────────────────────────────────────────────────────────────────────

if summary["error_counts"]:
    st.markdown("### Error Distribution")
    
    col_chart, col_table = st.columns([2, 1])
    
    with col_chart:
        # Try using plotly, fallback to simple chart
        try:
            import plotly.express as px  # type: ignore
            
            error_df = {
                "Error Type": list(summary["error_counts"].keys()),
                "Count": list(summary["error_counts"].values()),
            }
            
            fig = px.bar(
                error_df,
                x="Error Type",
                y="Count",
                title="Errors by Category",
                color="Count",
                color_continuous_scale="Reds"
            )
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            # Fallback to simple streamlit bar chart
            st.bar_chart(
                {
                    "Error Type": list(summary["error_counts"].keys()),
                    "Count": list(summary["error_counts"].values()),
                }
            )
    
    with col_table:
        st.markdown("**Error Count Details**")
        for error_type, count in sorted(summary["error_counts"].items(), key=lambda x: x[1], reverse=True):
            st.write(f"• {error_type}: **{count}**")

# ─────────────────────────────────────────────────────────────────────────────
# ERROR LOG VIEWER
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("### 📋 Recent Error Logs")

try:
    if JSON_ERROR_LOG.exists():
        with open(JSON_ERROR_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        if lines:
            # Parse and reverse to show newest first
            errors = []
            for line in lines:
                try:
                    errors.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            
            errors.reverse()
            
            # Filters
            col_filter1, col_filter2 = st.columns(2)
            
            with col_filter1:
                selected_categories = st.multiselect(
                    "Filter by Error Category",
                    sorted(summary["error_counts"].keys()),
                    help="Show only errors of selected types"
                )
            
            with col_filter2:
                limit = st.select_slider(
                    "Show last N errors",
                    options=[10, 25, 50, 100, 250],
                    value=25
                )
            
            # Filter errors
            if selected_categories:
                filtered_errors = [e for e in errors if e.get("category") in selected_categories]
            else:
                filtered_errors = errors
            
            filtered_errors = filtered_errors[:limit]
            
            if filtered_errors:
                st.write(f"Showing {len(filtered_errors)} of {len(errors)} total errors")
                
                for i, error in enumerate(filtered_errors, 1):
                    with st.expander(
                        f"**[{error.get('category', 'unknown')}]** {error.get('message', 'No message')[:60]}..."
                    ):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write(f"**Category:** {error.get('category')}")
                            st.write(f"**Time:** {error.get('timestamp', 'N/A')}")
                            st.write(f"**User:** {error.get('user_id', 'unknown')[:8]}...")
                            if error.get('current_screen'):
                                st.write(f"**Screen:** {error.get('current_screen')}")
                        
                        with col2:
                            if error.get('workflow_step'):
                                st.write(f"**Workflow Step:** {error.get('workflow_step')}")
                            if error.get('llm_provider'):
                                st.write(f"**LLM Provider:** {error.get('llm_provider')}")
                            if error.get('llm_model'):
                                st.write(f"**LLM Model:** {error.get('llm_model')}")
                        
                        st.divider()
                        st.write(f"**Message:** {error.get('message')}")
                        
                        if error.get("exception"):
                            with st.expander("Exception Details"):
                                exc = error["exception"]
                                st.code(f"{exc.get('type')}: {exc.get('message')}", language="python")
                                if exc.get("traceback"):
                                    st.text(exc["traceback"])
            else:
                st.info("No errors found matching the selected filters.")
        else:
            st.info("No error logs found yet. Your application is running smoothly!")
    else:
        st.info("Error log file not created yet.")

except Exception as e:
    st.error(f"Failed to read error logs: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# TOOLS & ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
st.markdown("### 🛠️ Tools")

col_action1, col_action2, col_action3 = st.columns(3)

with col_action1:
    if st.button("📥 Download Error Logs", use_container_width=True):
        if ERROR_LOG_FILE.exists():
            with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
                error_content = f.read()
            st.download_button(
                label="Download as .log",
                data=error_content,
                file_name=f"error_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                mime="text/plain"
            )
        else:
            st.warning("No error logs to download")

with col_action2:
    if st.button("🧹 Clear All Error Logs", use_container_width=True):
        try:
            if JSON_ERROR_LOG.exists():
                JSON_ERROR_LOG.unlink()
            if ERROR_LOG_FILE.exists():
                ERROR_LOG_FILE.unlink()
            st.success("Error logs cleared!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to clear logs: {e}")

with col_action3:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

app_footer()
