"""
error_logger.py — Centralized error logging for the DP Generator application.
Captures and logs all types of errors with context, timestamps, and user information.
"""

import logging
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Main error log
ERROR_LOG_FILE = LOG_DIR / "errors.log"
# Rotating error logs by date (daily)
DAILY_ERROR_LOG = LOG_DIR / f"errors_{datetime.now().strftime('%Y%m%d')}.log"

# Structured JSON log for analysis
JSON_ERROR_LOG = LOG_DIR / "errors_structured.jsonl"

# Setup error logger
error_logger = logging.getLogger("dp_generator_errors")
if not error_logger.handlers:
    # File handler for errors
    handler = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    error_logger.addHandler(handler)
    error_logger.setLevel(logging.ERROR)


# ─────────────────────────────────────────────────────────────────────────────
# ERROR CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────

class ErrorCategory:
    """Standard error categories for classification."""
    
    # API Errors
    GROQ_API_ERROR = "groq_api_error"
    GROQ_AUTHENTICATION_ERROR = "groq_authentication_error"
    GROQ_RATE_LIMIT_ERROR = "groq_rate_limit_error"
    GROQ_MODEL_NOT_FOUND = "groq_model_not_found"
    
    OLLAMA_CONNECTION_ERROR = "ollama_connection_error"
    OLLAMA_MODEL_ERROR = "ollama_model_error"
    
    # Database Errors
    SNOWFLAKE_CONNECTION_ERROR = "snowflake_connection_error"
    SNOWFLAKE_AUTHENTICATION_ERROR = "snowflake_authentication_error"
    SNOWFLAKE_QUERY_ERROR = "snowflake_query_error"
    DATABASE_FETCH_ERROR = "database_fetch_error"
    
    # File/Format Errors
    YAML_VALIDATION_ERROR = "yaml_validation_error"
    YAML_PARSE_ERROR = "yaml_parse_error"
    SQL_PARSE_ERROR = "sql_parse_error"
    SQL_VALIDATION_ERROR = "sql_validation_error"
    JSON_PARSE_ERROR = "json_parse_error"
    FILE_UPLOAD_ERROR = "file_upload_error"
    FILE_DOWNLOAD_ERROR = "file_download_error"
    FILE_NOT_FOUND_ERROR = "file_not_found_error"
    
    # Data Validation Errors
    DATA_VALIDATION_ERROR = "data_validation_error"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_FIELD_TYPE = "invalid_field_type"
    INVALID_FIELD_VALUE = "invalid_field_value"
    
    # Session/State Errors
    SESSION_STATE_ERROR = "session_state_error"
    NAVIGATION_ERROR = "navigation_error"
    
    # LLM Quality Errors
    LLM_OUTPUT_PARSING_ERROR = "llm_output_parsing_error"
    LLM_VALIDATION_ERROR = "llm_validation_error"
    LLM_TIMEOUT_ERROR = "llm_timeout_error"
    
    # Quality Check Errors
    QUALITY_CHECK_ERROR = "quality_check_error"
    QUALITY_CHECK_FAILED = "quality_check_failed"
    
    # Workflow Errors
    WORKFLOW_STEP_ERROR = "workflow_step_error"
    WORKFLOW_STATE_ERROR = "workflow_state_error"
    
    # Unknown/Generic Errors
    UNKNOWN_ERROR = "unknown_error"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ERROR LOGGING FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def get_user_id() -> str:
    """Get or create user ID from session state."""
    if "dp_user_id" not in st.session_state:
        import uuid
        st.session_state.dp_user_id = str(uuid.uuid4())
    return st.session_state.dp_user_id


def get_session_context() -> Dict[str, Any]:
    """Extract relevant session context for error logging."""
    context = {
        "user_id": get_user_id(),
        "timestamp": datetime.now().isoformat(),
    }
    
    # Add current page if available
    if "home_screen" in st.session_state:
        context["current_screen"] = st.session_state.home_screen
    
    # Add workflow step if available
    if "dp_step" in st.session_state:
        context["workflow_step"] = st.session_state.dp_step
    
    if "sm_mode" in st.session_state:
        context["mode"] = st.session_state.sm_mode
    
    # Add LLM config
    context["llm_provider"] = st.session_state.get("llm_provider", "unknown")
    context["llm_model"] = st.session_state.get("groq_model_name") or st.session_state.get("ollama_model_name", "unknown")
    
    return context


def log_error(
    error_category: str,
    error_message: str,
    exception: Optional[Exception] = None,
    context: Optional[Dict[str, Any]] = None,
    show_user_message: bool = True
) -> None:
    """
    Log an error with full context.
    
    Args:
        error_category: One of ErrorCategory constants
        error_message: Human-readable error message
        exception: The Python exception object (if applicable)
        context: Additional context dictionary
        show_user_message: Whether to show error message in Streamlit UI
    """
    
    # Build complete context
    session_context = get_session_context()
    if context:
        session_context.update(context)
    
    # Extract exception details
    exception_details = None
    if exception:
        exception_details = {
            "type": type(exception).__name__,
            "message": str(exception),
            "traceback": traceback.format_exc(),
        }
        session_context["exception"] = exception_details
    
    # Log to file
    log_entry = {
        "category": error_category,
        "message": error_message,
        **session_context
    }
    
    # Write to structured JSON log
    try:
        with open(JSON_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, default=str) + "\n")
    except Exception as write_error:
        error_logger.error(f"Failed to write to JSON error log: {write_error}")
    
    # Log to traditional error log
    error_logger.error(
        f"[{error_category}] {error_message} | Context: {json.dumps(session_context, default=str)}"
    )
    
    # Show user-facing message (optional)
    if show_user_message:
        display_error_message(error_message, error_category)


def display_error_message(message: str, category: str) -> None:
    """Display error message in Streamlit UI."""
    error_map = {
        ErrorCategory.GROQ_AUTHENTICATION_ERROR: "🔑 API Key Error: Please check your Groq API key in the LLM Configuration.",
        ErrorCategory.GROQ_RATE_LIMIT_ERROR: "⏱️ Rate Limit: Too many requests. Please wait a moment and try again.",
        ErrorCategory.SNOWFLAKE_CONNECTION_ERROR: "🔌 Database Connection: Unable to connect to Snowflake. Check your credentials.",
        ErrorCategory.SNOWFLAKE_AUTHENTICATION_ERROR: "🔐 Authentication Failed: Invalid Snowflake credentials.",
        ErrorCategory.YAML_VALIDATION_ERROR: "⚠️ YAML Format Error: Generated YAML is invalid.",
        ErrorCategory.SQL_PARSE_ERROR: "⚠️ SQL Syntax Error: Generated SQL has syntax issues.",
        ErrorCategory.FILE_UPLOAD_ERROR: "📤 Upload Error: Failed to upload file.",
        ErrorCategory.FILE_NOT_FOUND_ERROR: "📁 File Not Found: The requested file doesn't exist.",
        ErrorCategory.MISSING_REQUIRED_FIELD: "📋 Missing Information: Please fill in all required fields.",
        ErrorCategory.LLM_OUTPUT_PARSING_ERROR: "🤖 LLM Response Error: Failed to parse model response.",
    }
    
    display_msg = error_map.get(category, f"❌ Error: {message}")
    st.error(display_msg)


# ─────────────────────────────────────────────────────────────────────────────
# SPECIFIC ERROR LOGGING FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def log_groq_error(error_message: str, exception: Optional[Exception] = None) -> None:
    """Log Groq API errors."""
    if exception:
        exc_str = str(exception).lower()
        if "authentication" in exc_str or "unauthorized" in exc_str or "api_key" in exc_str:
            category = ErrorCategory.GROQ_AUTHENTICATION_ERROR
        elif "rate_limit" in exc_str or "429" in exc_str:
            category = ErrorCategory.GROQ_RATE_LIMIT_ERROR
        elif "model" in exc_str or "not found" in exc_str:
            category = ErrorCategory.GROQ_MODEL_NOT_FOUND
        else:
            category = ErrorCategory.GROQ_API_ERROR
    else:
        category = ErrorCategory.GROQ_API_ERROR
    
    log_error(category, error_message, exception)


def log_ollama_error(error_message: str, exception: Optional[Exception] = None) -> None:
    """Log Ollama connection/model errors."""
    if exception and "connection" in str(exception).lower():
        category = ErrorCategory.OLLAMA_CONNECTION_ERROR
    else:
        category = ErrorCategory.OLLAMA_MODEL_ERROR
    
    log_error(category, error_message, exception)


def log_snowflake_error(error_message: str, exception: Optional[Exception] = None) -> None:
    """Log Snowflake connection/query errors."""
    if exception:
        exc_str = str(exception).lower()
        if "authentication" in exc_str or "credential" in exc_str:
            category = ErrorCategory.SNOWFLAKE_AUTHENTICATION_ERROR
        elif "connection" in exc_str or "connect" in exc_str:
            category = ErrorCategory.SNOWFLAKE_CONNECTION_ERROR
        else:
            category = ErrorCategory.SNOWFLAKE_QUERY_ERROR
    else:
        category = ErrorCategory.SNOWFLAKE_CONNECTION_ERROR
    
    log_error(category, error_message, exception)


def log_yaml_error(error_message: str, exception: Optional[Exception] = None) -> None:
    """Log YAML parsing/validation errors."""
    if exception and "parse" in str(exception).lower():
        category = ErrorCategory.YAML_PARSE_ERROR
    else:
        category = ErrorCategory.YAML_VALIDATION_ERROR
    
    log_error(category, error_message, exception)


def log_sql_error(error_message: str, exception: Optional[Exception] = None) -> None:
    """Log SQL parsing/validation errors."""
    if exception and "parse" in str(exception).lower():
        category = ErrorCategory.SQL_PARSE_ERROR
    else:
        category = ErrorCategory.SQL_VALIDATION_ERROR
    
    log_error(category, error_message, exception)


def log_llm_output_error(error_message: str, exception: Optional[Exception] = None) -> None:
    """Log LLM output parsing errors."""
    log_error(ErrorCategory.LLM_OUTPUT_PARSING_ERROR, error_message, exception)


def log_data_validation_error(error_message: str, field_name: str = "", expected_type: str = "") -> None:
    """Log data validation errors."""
    context = {}
    if field_name:
        context["field_name"] = field_name
    if expected_type:
        context["expected_type"] = expected_type
    
    log_error(ErrorCategory.DATA_VALIDATION_ERROR, error_message, context=context)


def log_file_error(error_message: str, exception: Optional[Exception] = None, file_path: str = "") -> None:
    """Log file operation errors."""
    context = {}
    if file_path:
        context["file_path"] = file_path
    
    if exception:
        exc_str = str(exception).lower()
        if "not found" in exc_str or "no such file" in exc_str:
            category = ErrorCategory.FILE_NOT_FOUND_ERROR
        elif "upload" in error_message.lower():
            category = ErrorCategory.FILE_UPLOAD_ERROR
        elif "download" in error_message.lower():
            category = ErrorCategory.FILE_DOWNLOAD_ERROR
        else:
            category = ErrorCategory.FILE_NOT_FOUND_ERROR
    else:
        category = ErrorCategory.FILE_NOT_FOUND_ERROR
    
    log_error(category, error_message, exception, context)


def log_workflow_error(error_message: str, step: str = "", exception: Optional[Exception] = None) -> None:
    """Log workflow step errors."""
    context = {}
    if step:
        context["workflow_step"] = step
    
    log_error(ErrorCategory.WORKFLOW_STEP_ERROR, error_message, exception, context)


def log_quality_check_failure(check_name: str, failure_reason: str, severity: str = "warning") -> None:
    """Log quality check failures."""
    context = {
        "check_name": check_name,
        "severity": severity,
    }
    log_error(
        ErrorCategory.QUALITY_CHECK_FAILED,
        f"Quality check '{check_name}' failed: {failure_reason}",
        context=context,
        show_user_message=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# ERROR REPORTING & ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

def get_error_summary() -> Dict[str, Any]:
    """
    Parse error logs and return summary statistics.
    Useful for dashboards and debugging.
    """
    error_counts = {}
    error_examples = {}
    
    try:
        with open(JSON_ERROR_LOG, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    category = entry.get("category", "unknown")
                    error_counts[category] = error_counts.get(category, 0) + 1
                    
                    # Keep one example of each error type
                    if category not in error_examples:
                        error_examples[category] = {
                            "message": entry.get("message", ""),
                            "timestamp": entry.get("timestamp", ""),
                        }
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    
    return {
        "total_errors": sum(error_counts.values()),
        "error_counts": error_counts,
        "error_examples": error_examples,
    }


def clear_old_error_logs(days: int = 30) -> None:
    """Clear error logs older than specified days."""
    from datetime import timedelta
    import os
    
    cutoff_date = datetime.now() - timedelta(days=days)
    
    for log_file in LOG_DIR.glob("errors_*.log"):
        try:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
            if file_mtime < cutoff_date:
                log_file.unlink()
        except Exception as e:
            error_logger.warning(f"Failed to delete old log file {log_file}: {e}")
