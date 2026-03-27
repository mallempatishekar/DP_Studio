"""
Snowflake connection and metadata helpers.
Used by: pages/1_CADP.py (Semantic Model builders)
"""

import streamlit as st
from utils.error_logger import log_snowflake_error


def sf_map_type(sf_type: str) -> str:
    """Map a raw Snowflake column type to a YAML dimension type."""
    base = sf_type.split("(")[0].strip().upper()
    mapping = {
        "VARCHAR": "string", "TEXT": "string", "STRING": "string",
        "CHAR": "string", "NCHAR": "string", "NVARCHAR": "string",
        "NVARCHAR2": "string", "VARIANT": "string", "OBJECT": "string", "ARRAY": "string",
        "NUMBER": "number", "INT": "number", "INTEGER": "number",
        "BIGINT": "number", "SMALLINT": "number", "TINYINT": "number",
        "BYTEINT": "number", "FLOAT": "number", "FLOAT4": "number",
        "FLOAT8": "number", "DOUBLE": "number", "REAL": "number",
        "DECIMAL": "number", "NUMERIC": "number", "FIXED": "number",
        "BOOLEAN": "boolean",
        "DATE": "time",
        "TIMESTAMP": "time", "TIMESTAMP_NTZ": "time", "TIMESTAMP_LTZ": "time",
        "TIMESTAMP_TZ": "time", "DATETIME": "time", "TIME": "time",
    }
    return mapping.get(base, "string")


def sf_get_connection():
    """Return cached Snowflake connection from session state, or None."""
    return st.session_state.get("sf_conn", None)


def sf_connect(account, user, password, role, warehouse):
    """
    Connect to Snowflake with error handling.
    Returns connection object or None if connection fails.
    """
    import snowflake.connector
    try:
        kwargs = {"account": account, "user": user, "password": password}
        if role.strip():      kwargs["role"]      = role.strip()
        if warehouse.strip(): kwargs["warehouse"] = warehouse.strip()
        return snowflake.connector.connect(**kwargs)
    except Exception as e:
        log_snowflake_error(
            f"Failed to connect to Snowflake account '{account}'",
            exception=e
        )
        return None


def sf_fetch_databases(conn):
    """Fetch list of databases with error handling."""
    if not conn:
        log_snowflake_error("Connection object is None or invalid")
        return []
    
    try:
        cur = conn.cursor()
        cur.execute("SHOW DATABASES")
        rows = cur.fetchall()
        return [r[1] for r in rows]
    except Exception as e:
        log_snowflake_error("Failed to fetch databases", exception=e)
        return []


def sf_fetch_schemas(conn, database):
    """Fetch schemas for a database with error handling."""
    if not conn:
        log_snowflake_error("Connection object is None or invalid")
        return []
    
    try:
        cur = conn.cursor()
        cur.execute(f'SHOW SCHEMAS IN DATABASE "{database}"')
        rows = cur.fetchall()
        return [r[1] for r in rows if r[1] != "INFORMATION_SCHEMA"]
    except Exception as e:
        log_snowflake_error(f"Failed to fetch schemas from database '{database}'", exception=e)
        return []


def sf_fetch_tables(conn, database, schema):
    """Fetch tables for a schema with error handling."""
    if not conn:
        log_snowflake_error("Connection object is None or invalid")
        return []
    
    try:
        cur = conn.cursor()
        cur.execute(f'SHOW TABLES IN SCHEMA "{database}"."{schema}"')
        rows = cur.fetchall()
        return [r[1] for r in rows]
    except Exception as e:
        log_snowflake_error(f"Failed to fetch tables from '{database}.{schema}'", exception=e)
        return []


def sf_fetch_columns(conn, database, schema, table):
    """
    Return list of dicts: {original, snowflake_type, mapped_type}
    With error handling.
    """
    if not conn:
        log_snowflake_error("Connection object is None or invalid")
        return []
    
    try:
        cur = conn.cursor()
        cur.execute(f'DESCRIBE TABLE "{database}"."{schema}"."{table}"')
        rows = cur.fetchall()
        return [
            {"original": r[0], "snowflake_type": r[1], "mapped_type": sf_map_type(r[1])}
            for r in rows
        ]
    except Exception as e:
        log_snowflake_error(
            f"Failed to fetch columns from '{database}.{schema}.{table}'",
            exception=e
        )
        return []