"""
utils/llm_measures.py
LLM Measure Suggestion Engine
"""

import json
import re

# REMOVED: from utils.description_engine.config import ...

# ── Valid measure types (must match what the Table YAML builder accepts) ──────
MEASURE_TYPES = ["number", "count", "count_distinct", "sum", "avg", "min", "max", "string"]

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior analytics engineer specializing in semantic data modeling for DataOS Lens.

Your task:
Given a table name, its columns (name + type), and an optional table description,
suggest 3 to 5 meaningful measures for a semantic Lens model.

Rules:
- Infer business meaning from column names and types.
- Suggest measures that are genuinely useful for analytics (counts, sums, averages, etc.).
- SQL expressions must use the Lens SQL format: {column_name} (curly braces, no table prefix).
- For COUNT DISTINCT use: COUNT(DISTINCT {column_name})
- For SUM use: SUM({column_name})
- For AVG use: AVG({column_name})
- For plain COUNT use: COUNT({column_name})
- For MIN/MAX use: MIN({column_name}) / MAX({column_name})
- Do not fabricate column names. Only reference columns that exist in the provided list.
- Do not suggest a measure if there are no numeric, id, or date columns to aggregate.
- name must be snake_case, short, and descriptive (e.g. total_revenue, unique_customers).
- description must be 1 sentence, business-facing (e.g. "Total revenue across all orders.").
- type must be exactly one of: number, count, count_distinct, sum, avg, min, max, string.

Return ONLY a valid JSON array. No markdown, no explanation, no code fences.

Example output:
[
  {
    "name": "total_revenue",
    "sql": "SUM({revenue})",
    "type": "sum",
    "description": "Total revenue generated across all transactions."
  },
  {
    "name": "unique_customers",
    "sql": "COUNT(DISTINCT {customer_id})",
    "type": "count_distinct",
    "description": "Number of distinct customers who placed an order."
  }
]
"""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(table_name: str, dimensions: list[dict], table_desc: str = "") -> str:
    col_lines = "\n".join(
        f"  - {d.get('name') or d.get('column', '')} (type: {d.get('type', 'string')})"
        for d in dimensions
        if (d.get("name") or d.get("column", "")).strip()
    )

    existing_measures_note = ""  # could be extended later

    return f"""\
TABLE NAME: {table_name}

TABLE DESCRIPTION: {table_desc.strip() or "Not provided"}

COLUMNS:
{col_lines or "  (no columns defined yet)"}

{existing_measures_note}
Suggest 3–5 meaningful measures for this table. Return only a JSON array.
"""


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE PARSER
# ─────────────────────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> list[dict]:
    text = raw.strip()
    # Strip markdown fences if model adds them despite instructions
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Extract first JSON array found
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        text = match.group(0)

    data = json.loads(text)

    cleaned = []
    for item in data:
        name = str(item.get("name", "")).strip()
        sql  = str(item.get("sql",  "")).strip()
        typ  = str(item.get("type", "number")).strip().lower()
        desc = str(item.get("description", "")).strip()

        if not name or not sql:
            continue

        # Normalise type to allowed values
        if typ not in MEASURE_TYPES:
            typ = "number"

        cleaned.append({
            "name":        name,
            "sql":         sql,
            "type":        typ,
            "description": desc,
        })

    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# GROQ
# ─────────────────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, model_config: dict) -> list[dict]:
    from groq import Groq

    api_key = model_config.get("api_key")
    model_name = model_config.get("model", "llama-3.1-8b-instant")
    
    if not api_key:
        raise ValueError("Groq API Key is missing.")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1500,
    )
    return _parse_response(response.choices[0].message.content)


# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA
# ─────────────────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model_config: dict) -> list[dict]:
    import urllib.request

    base_url = model_config.get("base_url", "http://localhost:11434")
    model_name = model_config.get("model", "llama3")

    payload = json.dumps({
        "model":  model_name,
        "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())

    return _parse_response(data.get("response", ""))


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def suggest_measures(
    table_name:  str,
    dimensions:  list[dict],
    table_desc:  str = "",
    model_config: dict = None, # ADDED
) -> list[dict]:
    """
    Call the configured LLM to suggest measures for a table.
    """
    if not model_config:
        raise ValueError("LLM Config is missing. Please configure in the sidebar.")

    prompt = _build_prompt(table_name, dimensions, table_desc)

    try:
        if model_config.get("provider") == "groq":
            return _call_groq(prompt, model_config)
        else:
            return _call_ollama(prompt, model_config)
    except Exception as e:
        raise RuntimeError(f"Measure suggestion failed: {e}") from e