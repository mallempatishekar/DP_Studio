"""
utils/llm_checks.py
Advanced LLM QC Suggestion Engine
"""

import json
import re
import pathlib
import urllib.request

# ─────────────────────────────────────────────────────────────────────────────
# Reference Library Loading
# ─────────────────────────────────────────────────────────────────────────────
REFERENCE_PATH = pathlib.Path("utils/qc_reference_library.yaml")
LEARNED_PATH = pathlib.Path("utils/qc_learning/reference_qc_rules.json")

library_text = ""

# Curated examples
if REFERENCE_PATH.exists():
    try:
        with open(REFERENCE_PATH, "r") as f:
            library_text += f.read()
    except Exception:
        pass

# Learned rules
if LEARNED_PATH.exists():
    try:
        with open(LEARNED_PATH, "r") as f:
            learned = json.load(f)
        
        if learned:
            library_text += "\n\nLEARNED QC RULES FROM USER FEEDBACK:\n"
            seen = set()
            for r in learned[:15]:
                syntax = r.get("syntax")
                if syntax in seen:
                    continue
                seen.add(syntax)
                library_text += f"""
Rule Example:
------------
Category: {r.get('category')}
Column: {r.get('column')}
Syntax: {syntax}
Reason: {r.get('reason')}
"""
    except Exception:
        pass

QC_REFERENCE_LIBRARY = library_text

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a Principal Data Quality Architect specializing in enterprise data governance using SodaCL for DataOS.

Your goal is to propose high-confidence, production-ready quality checks.
1.  **Strict JSON Output**: Return ONLY a valid JSON list of objects. No markdown, no explanations.
2.  **Schema**: Each object must have: "name", "syntax" (valid SodaCL), "body" (JSON object or null), "category", "col" (column name or null), "reason".
3.  **No Hallucinations**: Do not invent column names. Use only columns provided in the context.
4.  **Valid Values**: If generating 'valid values' checks, ensure the values are real samples from the context (enums). Never use placeholders like 'value1', 'sample', 'unknown'.
5.  **SodaCL Syntax**:
    - Use `invalid_count(col) = 0` for regex/format checks.
    - Use `missing_count(col) = 0` for null checks.
    - Use `duplicate_count(col) = 0` for uniqueness.
    - Use `freshness(col) < Xd` for timestamp checks.
    - Avoid `concat` or complex `custom_sql` unless necessary.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def _build_column_context(columns: list[dict]) -> str:
    lines = []
    for col in columns:
        parts = [
            f"Column: {col['name']}",
            f"  Snowflake type : {col.get('sf_type', 'UNKNOWN')}",
            f"  Nullable       : {col.get('nullable', True)}",
            f"  PK             : {col.get('is_pk', False)}  | FK: {col.get('is_fk', False)}",
        ]
        if col.get("description"):
            parts.append(f"  Description    : {col['description']}")
        if col.get("min_val") is not None:
            parts.append(f"  Min/Max/Avg    : {col['min_val']} / {col['max_val']} / {col.get('avg_val')}")
        if col.get("null_pct") is not None:
            parts.append(f"  Null %         : {col['null_pct']}% | Distinct: {col.get('distinct_count')}")
        if col.get("avg_length") is not None:
            parts.append(f"  Avg Length     : {col['avg_length']}")
        if col.get("sample_values"):
            parts.append(f"  Samples        : {col['sample_values']}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)

def _build_default_summary(default_checks: list[dict]) -> str:
    lines = []
    for chk in default_checks:
        col_part = chk.get("col") if chk.get("col") else "table-level"
        line = f"[{chk.get('category')}] {col_part} → {chk.get('syntax')}"
        if chk.get("body") and "valid values" in chk["body"]:
            line += " [SKIP — valid values check already exists for this column]"
        lines.append(line)
    return "\n".join(lines)

def _build_schema_context(schema_overview: dict) -> str:
    if not schema_overview:
        return "No schema overview provided."
    lines = []
    for table, cols in schema_overview.items():
        col_names = ", ".join(c["name"] for c in cols[:10])
        if len(cols) > 10:
            col_names += " ..."
        lines.append(f"{table}: {col_names}")
    return "\n".join(lines)

def _build_enum_hint(columns: list[dict]) -> str:
    lines = ["ENUM COLUMNS — use ONLY these exact values in any valid values check:"]
    found = False
    for col in columns:
        samples = col.get("sample_values")
        if samples and col.get("is_likely_enum"):
            clean = [str(v) for v in samples if v is not None]
            if clean:
                lines.append(f"  {col['name']}: {clean}")
                found = True
    if not found:
        lines.append("  (none detected — do not generate valid values checks)")
    return "\n".join(lines)

def build_prompt(ctx: dict, default_checks: list[dict]) -> str:
    MAX_LIBRARY_CHARS = 3000
    library_snippet = QC_REFERENCE_LIBRARY[:MAX_LIBRARY_CHARS]
    if len(QC_REFERENCE_LIBRARY) > MAX_LIBRARY_CHARS:
        library_snippet += "\n... (truncated for token budget)"
    
    return f"""
REFERENCE QUALITY CHECK PATTERNS (REAL PRODUCTION EXAMPLES):
{library_snippet}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE NAME: {ctx.get('table')}
TABLE DESCRIPTION: {ctx.get('table_description', 'Not provided')}
USE CASE: {ctx.get('use_case', 'Not provided')}
ROW COUNT: {ctx.get('row_count')}
COLUMNS:
{_build_column_context(ctx['columns'])}
FULL SCHEMA OVERVIEW:
{_build_schema_context(ctx.get('schema_overview', {}))}
ALREADY GENERATED CHECKS:
{_build_default_summary(default_checks)}
ENUM COLUMNS WITH REAL VALUES (use ONLY these — never invent):
{_build_enum_hint(ctx['columns'])}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTELLIGENT REASONING INSTRUCTIONS
Infer business logic from semantic metadata.
If related columns exist: → Generate relationship validation.
If hierarchy fields exist: → Validate logical structure.
If temporal fields exist: → Validate chronological integrity.
If numeric metrics exist: → Validate reasonability, non-negativity, and relationships.
If identifier columns appear to reference other tables in the schema: → Suggest referential integrity checks using "failed rows" syntax.
Never use custom_sql or concat functions.
Only generate checks for the selected table. Do NOT generate checks for other tables.
Generate additional advanced checks now.
"""

def strengthen_check(s: dict) -> dict | None:
    syntax = s.get("syntax", "")
    col = s.get("col")
    if not col or not syntax:
        return s
    
    min_len = 3
    col_lower = col.lower()
    if "email" in col_lower: min_len = 5
    elif "name" in col_lower: min_len = 3
    elif "code" in col_lower: min_len = 2

    if syntax.startswith("avg_length"):
        return {
            "col": col, 
            "category": "Validity", 
            "name": f"{col} should have meaningful values", 
            "syntax": f"invalid_count({col}) = 0", 
            "body": {"valid regex": f"^[A-Za-z0-9 ]{{{min_len},}}$"}, 
            "severity": "warn", 
            "source": "auto_fix", 
            "reason": "Enforcing regex-based minimum length for meaningful values"
        }
    
    body_check = s.get("body") or {}
    if body_check and any(k in body_check for k in ["valid min", "valid max", "valid min length", "valid max length", "valid regex", "valid values"]):
        if "invalid_count" in syntax and "= 0" not in syntax:
            s["syntax"] = f"invalid_count({col}) = 0"
            syntax = s["syntax"]

    if "valid regex" in str(s.get("body", {})):
        body = s.get("body", {})
        regex = body.get("valid regex")
        if regex:
            if not regex.startswith("^"): regex = "^" + regex
            if not regex.endswith("$"): regex = regex + "$"
            body["valid regex"] = regex
        s["body"] = body
        return s

    if "valid values" in (s.get("body") or {}):
        vals = s["body"].get("valid values")
        if not vals:
            return {
                "col": col, 
                "category": "Completeness", 
                "name": f"{col} should not be null", 
                "syntax": f"missing_count({col}) = 0", 
                "body": None, 
                "severity": "fail", 
                "source": "auto_fix", 
                "reason": "Removed invalid empty value check; enforcing non-null instead"
            }
    return s

_FAKE_VALUES = {"known_value", "unknown", "n/a", "na", "any_value", "placeholder", "example_value", "value1", "value2", "your_value", "sample_value", "none", "null", "tbd"}

def fix_escapes(json_text: str) -> str:
    result = []
    i = 0
    while i < len(json_text):
        if json_text[i] == '\\' and i + 1 < len(json_text):
            next_char = json_text[i + 1]
            if next_char in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't', 'u'):
                result.append(json_text[i])
                result.append(next_char)
                i += 2
            else:
                result.append('\\\\')
                i += 1
        else:
            result.append(json_text[i])
            i += 1
    return ''.join(result)

def _parse_response(raw: str) -> list[dict]:
    if not raw or not raw.strip():
        print("⚠️ Empty LLM response")
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    
    # Extract JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start: 
        text = text[start:end + 1]
    
    text = fix_escapes(text)
    try:
        data = json.loads(text)
    except Exception as e:
        print("⚠️ JSON parse failed:", e)
        return []
    
    if isinstance(data, dict):
        for key in ("checks", "rules", "suggestions", "results", "items"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break
            else:
                return []
    if not isinstance(data, list):
        return []
        
    for item in data:
        syntax = item.get("syntax", "")
        if "regex_match" in syntax:
            col = item.get("col")
            pattern = re.findall(r"'(.*?)'", syntax)
            if col and pattern:
                regex = pattern[0]
                if not regex.startswith("^"): regex = "^" + regex
                if not regex.endswith("$"): regex += "$"
                item["syntax"] = f"invalid_count({col}) = 0"
                item["body"] = {"valid regex": regex}
        if any(x in syntax for x in ["concat(", "length(", "custom_sql"]): 
            continue
        item["source"] = "llm"
        if "body" not in item: item["body"] = None
    return data

# ─────────────────────────────────────────────────────────────────────────────
# API Call Functions
# ─────────────────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, model_name: str, api_key: str) -> list[dict]:
    from groq import Groq
    
    if not api_key:
        raise ValueError("Groq API Key is missing.")

    client = Groq(api_key=api_key)
    
    fallback = "llama-3.1-8b-instant"
    models_to_try = [model_name]
    if model_name != fallback:
        models_to_try.append(fallback)

    last_err = None
    for model in models_to_try:
        try:
            print(f"🤖 Trying model: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            return _parse_response(response.choices[0].message.content)
        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                print(f"⚠️ {model} rate limited, trying next...")
                last_err = err_str
                continue
            raise
    raise RuntimeError(f"⏳ All Groq models rate limited. Details: {last_err[:300] if last_err else 'Unknown error'}")

def _call_ollama(prompt: str, model_name: str, base_url: str) -> list[dict]:
    payload = json.dumps({
        "model": model_name,
        "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
        "stream": False,
        "options": {"temperature": 0.1},
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
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(ctx: dict, default_checks: list[dict], provider: str = "groq", model_name: str = None, api_key: str = None, base_url: str = "http://localhost:11434") -> list[dict]:
    """
    Generates QC suggestions using an LLM.
    
    Args:
        ctx (dict): The table context.
        default_checks (list): Existing default checks.
        provider (str): "groq" or "ollama".
        model_name (str): Model ID.
        api_key (str): API key for Groq.
        base_url (str): URL for Ollama.
    """
    prompt = build_prompt(ctx, default_checks)

    # Get LLM suggestions
    try:
        if provider == "groq":
            if not model_name: model_name = "llama-3.1-8b-instant"
            suggestions = _call_groq(prompt, model_name, api_key)
        else:
            if not model_name: model_name = "llama3"
            suggestions = _call_ollama(prompt, model_name, base_url)
    except RuntimeError:
        raise  # pass rate limit errors up to the UI
    except Exception as e:
        print(f"⚠️ LLM call failed: {e}")
        suggestions = []

    if suggestions is None:
        suggestions = []

    print(f"🔍 LLM raw suggestions count: {len(suggestions)}")
    
    # ── Rule-based Injection (Email/Phone/Pincode) ────────────────────────────────
    for col in ctx["columns"]:
        col_name = col["name"]
        name_lower = col_name.lower()
        
        # Email validation
        if "email" in name_lower:
            already_exists = any(f"invalid_count({col_name.lower()})" in s.get("syntax","").lower() for s in suggestions)
            if not already_exists:
                suggestions.append({
                    "col": col_name, 
                    "category": "Validity", 
                    "name": f"{col_name} should follow valid email format", 
                    "syntax": f"invalid_count({col_name}) = 0", 
                    "body": {"valid regex": "^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$"}, 
                    "severity": "fail", 
                    "source": "rule", 
                    "reason": "Email columns should follow standard email format"
                })
        
        # Phone validation
        if "phone" in name_lower or "mobile" in name_lower:
            already_exists = any(col_name.lower() in s.get("syntax","").lower() and "invalid_count" in s.get("syntax","").lower() for s in suggestions)
            if not already_exists:
                suggestions.append({
                    "col": col_name, 
                    "category": "Validity", 
                    "name": f"{col_name} should contain valid phone numbers", 
                    "syntax": f"invalid_count({col_name}) = 0", 
                    "body": {"valid regex": "^\\+?[0-9]{10,15}$"}, 
                    "severity": "fail", 
                    "source": "rule", 
                    "reason": "Phone numbers should follow a valid numeric pattern"
                })
        
        # Pincode validation
        if "pin" in name_lower or "zipcode" in name_lower or "postal" in name_lower:
            already_exists = any(col_name.lower() in s.get("syntax","").lower() and "invalid_count" in s.get("syntax","").lower() for s in suggestions)
            if not already_exists:
                suggestions.append({
                    "col": col_name, 
                    "category": "Validity", 
                    "name": f"{col_name} should contain valid postal codes", 
                    "syntax": f"invalid_count({col_name}) = 0", 
                    "body": {"valid regex": "^[1-9][0-9]{5}$"}, 
                    "severity": "fail", 
                    "source": "rule", 
                    "reason": "Postal codes should follow standard numeric format"
                })

    # ── Post-Processing & Cleaning ─────────────────────────────────────────────
    VALID_PREFIXES = ["missing_count", "duplicate_count", "invalid_count", "avg_length", "row_count", "freshness", "schema", "failed rows"]
    default_syntax = {d["syntax"] for d in default_checks if d.get("syntax")}

    cleaned = []
    seen_syntax = set()

    for s in suggestions:
        s = strengthen_check(s)
        if not s or not isinstance(s, dict): continue
        syntax = s.get("syntax", "")
        if not syntax: continue
        syntax_text = syntax.lower()
        
        # Normalise body keys
        body = s.get("body") or {}
        if "valid_values" in body:
            body["valid values"] = body.pop("valid_values")
            s["body"] = body
        if "valid_min" in body:
            body["valid min"] = body.pop("valid_min")
            s["body"] = body
        if "valid_max" in body:
            body["valid max"] = body.pop("valid_max")
            s["body"] = body
        body_text = str(body).lower()

        # Fix fake values
        if ("valid values" in syntax_text or "valid values" in body_text or "must be one of" in syntax_text):
            if any(x in syntax_text for x in _FAKE_VALUES): continue
        if "valid values" in body_text:
            vals = body.get("valid values")
            if not vals: continue
            if any(str(v).lower().strip() in _FAKE_VALUES for v in vals): continue

        # Remove unsupported syntax
        if any(x in syntax for x in ["concat(", "length(", "regex_match"]): continue
        if re.search(r'=\s*0\s+(and|or|\[)', syntax): continue
        
        # Fix missing_percent
        if re.search(r'missing_percent\([^)]+\)\s*[<>]=?\s*\d+%', syntax):
            syntax = re.sub(r'(\d+)%', r'\1', syntax)
            s["syntax"] = syntax
        
        # Fix freshness
        if re.search(r'freshness\([^)]+\)\s*[<>]\s*\d+y', syntax):
            syntax = re.sub(r'(\d+)y', lambda m: str(int(m.group(1)) * 365) + 'd', syntax)
            s["syntax"] = syntax
        if syntax.startswith("freshness"):
            match = re.search(r'(\d+)d', syntax)
            if match and int(match.group(1)) > 30:
                syntax = re.sub(r'\d+d', '1d', syntax)
                s["syntax"] = syntax
        
        if re.search(r'invalid_count\([^)]*(<|>|!=|=|<=|>=)[^)]*\)', syntax): continue
        
        if syntax in default_syntax: continue
        if syntax.lower() in {d.lower() for d in default_syntax}: continue
        
        col_lower = (s.get("col") or "").lower()
        
        # Block Validity check for cols already covered
        if col_lower and any((d.get("col") or "").lower() == col_lower and d.get("category") == "Validity" for d in default_checks): continue
        
        # Block uniqueness for non-PK
        if syntax.startswith("duplicate_count"):
            col_is_pk = any(c.get("is_pk") and (c.get("name") or "").lower() == col_lower for c in ctx["columns"])
            if not col_is_pk: continue
        
        # Block freshness duplicates
        if syntax.startswith("freshness"):
            if any(d.get("category") == "Freshness" and (d.get("col") or "").lower() == col_lower for d in default_checks): continue
        
        # Duplicate detection
        normalized = syntax.lower().replace(" ", "")
        if normalized in seen_syntax: continue
        seen_syntax.add(normalized)
        
        if any(syntax.startswith(p) for p in VALID_PREFIXES):
            s["confidence"] = "high" if s.get("source") in ["rule", "auto_fix"] else "medium"
            cleaned.append(s)

    return cleaned