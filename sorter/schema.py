"""Schema, JSON parsing and validation for model output."""
import json
import re
from datetime import datetime

DOC_TYPES = ["receipt", "invoice", "other"]


def build_schema(categories):
    return {
        "type": "object",
        "properties": {
            "vendor": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "total": {"type": "number"},
            "tax": {"type": "number"},
            "currency": {"type": "string", "description": "ISO 4217 code"},
            "category": {"type": "string", "enum": categories},
            "document_type": {"type": "string", "enum": DOC_TYPES},
            "confidence": {"type": "number", "description": "0 to 1"},
            "date_text": {"type": "string", "description": "the date exactly as printed"},
            "total_text": {"type": "string", "description": "the total exactly as printed"},
        },
        "required": ["vendor", "date", "total", "category", "date_text", "total_text"],
    }


def parse_json(text):
    """Pull the first JSON object out of a model reply (tolerates fences/prose)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])


def money(value):
    """'₹1,234.50' / '1.234,50' / 12 -> float, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    s = re.sub(r"[^\d.,\-]", "", str(value))
    if not s:
        return None
    if "," in s and "." in s:
        # whichever separator comes last is the decimal mark
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + "." + tail if len(tail) <= 2 else s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y",
                 "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y/%m/%d"]


def iso_date(value):
    if not value:
        return None
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize(raw, categories, vendor_rules=None):
    """Validate and clean one model result. Returns (record, issues)."""
    issues = []
    vendor = str(raw.get("vendor") or "").strip()
    if not vendor:
        issues.append("missing vendor")
    date = iso_date(raw.get("date"))
    if not date:
        issues.append("missing/unreadable date")
    total = money(raw.get("total"))
    if total is None:
        issues.append("missing total")
    tax = money(raw.get("tax"))
    if tax is not None and total is not None and tax > total:
        issues.append("tax exceeds total")

    # evidence check: the model must quote the date/total as printed; flag doubt or mismatch
    for label, shown, parsed, parse in (("date", raw.get("date_text"), date, iso_date),
                                        ("total", raw.get("total_text"), total, money)):
        shown = str(shown or "").strip()
        if not shown:
            continue
        if "?" in shown or re.search(r"illegible|unclear|unreadable|blur", shown, re.I):
            issues.append(f"{label} text unclear ('{shown}')")
        else:
            seen = parse(shown)
            if seen is None:
                issues.append(f"{label} text not parseable ('{shown}')")
            elif parsed is not None and seen != parsed:
                issues.append(f"{label} text disagrees ('{shown}' vs {parsed})")

    category = raw.get("category")
    if category not in categories:
        category = "Other" if "Other" in categories else categories[-1]
        issues.append("unknown category")
    # user-defined vendor rules always win over the model
    for key, cat in (vendor_rules or {}).items():
        if key.lower() in vendor.lower() and cat in categories:
            category = cat
            break

    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    if confidence < 0.6:
        issues.append("low confidence")

    doc_type = raw.get("document_type")
    return {
        "vendor": vendor,
        "date": date or "",
        "total": total if total is not None else "",
        "tax": tax if tax is not None else "",
        "currency": (str(raw.get("currency") or "").upper()[:3]),
        "category": category,
        "document_type": doc_type if doc_type in DOC_TYPES else "other",
        "confidence": round(confidence, 2),
    }, issues
