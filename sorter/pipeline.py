"""Folder in -> renamed files, receipts.csv, summary.md out."""
import csv
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from .images import SUPPORTED, load_images
from .schema import build_schema, normalize, parse_json

FIELDS = ["file", "original_name", "date", "vendor", "total", "tax", "currency",
          "category", "document_type", "confidence", "needs_review", "notes"]


def build_prompt(categories, examples):
    shots = "\n".join(json.dumps(e["output"]) for e in examples if "output" in e)
    return (
        "You are a bookkeeping assistant. Read this receipt or invoice and return ONE JSON object.\n"
        "Fields: vendor (merchant name, not the customer), date (YYYY-MM-DD, the document date), "
        "total (final amount paid, number only), tax (tax portion, 0 if none), currency (ISO code), "
        f"category (exactly one of: {', '.join(categories)}), "
        "document_type (receipt, invoice or other), confidence (0 to 1, your certainty), "
        "date_text and total_text (copy the date and total EXACTLY as printed; write ? for any character you cannot read).\n"
        "Never invent values. If something is unreadable, use an empty string and lower confidence.\n"
        + (f"Examples of good output:\n{shots}\n" if shots else "")
    )


def _slug(text, limit=30):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:limit] or "unknown"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique(dest_dir, name):
    p = Path(name)
    candidate, n = dest_dir / name, 2
    while candidate.exists():
        candidate = dest_dir / f"{p.stem}_{n}{p.suffix}"
        n += 1
    return candidate


def _read(images, client, categories, vendor_rules, examples, retries):
    prompt = build_prompt(categories, examples)
    schema = build_schema(categories)
    last_err = None
    for _ in range(retries + 1):
        try:
            raw = parse_json(client.extract(images, prompt, schema))
            return normalize(raw, categories, vendor_rules)
        except (ValueError, KeyError) as e:  # bad JSON -> retry
            last_err = e
    raise ValueError(f"model returned unusable output: {last_err}")


def extract_one(path, client, categories, vendor_rules, examples, retries=2, verify=False):
    rec, issues = _read(load_images(path), client, categories, vendor_rules, examples, retries)
    if verify:
        # second read at a different resolution; a model that is guessing rarely guesses the same twice
        try:
            rec2, _ = _read(load_images(path, max_side=1000), client, categories, vendor_rules, examples, retries)
            diffs = [f for f in ("date", "total") if rec[f] != rec2[f]]
            if diffs:
                issues.append("verification pass disagreed on " + " and ".join(diffs))
        except ValueError:
            issues.append("verification pass failed")
    return rec, issues


def process_folder(inp, out, client, config, examples, dry_run=False, log=print, verify=False):
    inp, out = Path(inp), Path(out)
    categories, rules = config["categories"], config.get("vendor_rules", {})
    files = sorted(p for p in inp.rglob("*")
                   if p.suffix.lower() in SUPPORTED and out.resolve() not in p.resolve().parents)
    sorted_dir, review_dir = out / "sorted", out / "needs_review"
    if not dry_run:
        sorted_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)

    rows, seen_hash, seen_key = [], {}, {}
    for i, path in enumerate(files, 1):
        log(f"[{i}/{len(files)}] {path.name}")
        digest = _sha(path)
        if digest in seen_hash:
            rows.append(_row(path, "", {}, ["exact duplicate of " + seen_hash[digest]], True))
            log("   duplicate file, skipped")
            continue
        seen_hash[digest] = path.name
        try:
            rec, issues = extract_one(path, client, categories, rules, examples, verify=verify)
        except Exception as e:
            rows.append(_row(path, "", {}, [str(e)], True))
            log(f"   FAILED: {e}")
            if not dry_run:
                shutil.copy2(path, _unique(review_dir, path.name))
            continue

        key = (rec["vendor"].lower(), rec["date"], rec["total"])
        if rec["vendor"] and rec["date"] and key in seen_key:
            issues.append("possible duplicate of " + seen_key[key])
        seen_key[key] = path.name

        needs_review = bool(issues)
        new_name = f"{rec['date'] or 'undated'}_{_slug(rec['vendor'])}_{rec['total'] if rec['total'] != '' else 'NA'}{path.suffix.lower()}"
        dest = _unique(review_dir if needs_review else sorted_dir, new_name)
        if not dry_run:
            shutil.copy2(path, dest)  # originals are never moved or modified
        rows.append(_row(path, dest.name, rec, issues, needs_review))
        log(f"   -> {dest.name}" + (f"  (review: {'; '.join(issues)})" if issues else ""))

    if not dry_run:
        with open(out / "receipts.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(rows)
        (out / "summary.md").write_text(build_summary(rows), encoding="utf-8")
    return rows


def _row(path, new_name, rec, issues, needs_review):
    row = {k: rec.get(k, "") for k in FIELDS}
    row.update(file=new_name, original_name=path.name,
               needs_review="yes" if needs_review else "", notes="; ".join(issues))
    return row


def build_summary(rows):
    ok = [r for r in rows if r["total"] != ""]
    by_cat, by_cur = defaultdict(float), defaultdict(float)
    for r in ok:
        by_cat[(r["currency"] or "?", r["category"])] += r["total"]
        by_cur[r["currency"] or "?"] += r["total"]
    lines = ["# Expense summary", "",
             f"Documents: {len(rows)}  |  Extracted: {len(ok)}  |  "
             f"Needs review: {sum(1 for r in rows if r['needs_review'])}", ""]
    for cur in sorted(by_cur):
        lines += [f"## {cur}  (total {by_cur[cur]:,.2f})", "", "| Category | Amount |", "|---|---:|"]
        for (c, cat), amt in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            if c == cur:
                lines.append(f"| {cat} | {amt:,.2f} |")
        lines.append("")
    flagged = [r for r in rows if r["needs_review"]]
    if flagged:
        lines += ["## Needs your review", ""]
        lines += [f"- `{r['original_name']}`: {r['notes']}" for r in flagged]
    return "\n".join(lines) + "\n"
