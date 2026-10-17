# receipt-sorter

Drop a folder of receipts and invoices (PDFs and phone photos) in, get back renamed files,
an accountant-ready `receipts.csv`, and a category summary. A local open-weight vision model
does the reading, so **client invoices and bank details never leave your laptop**.

```
sorted_output/
  sorted/          2026-03-04_Figma_15.0.pdf ...   (confident results)
  needs_review/    anything unreadable, low-confidence or possibly duplicated
  receipts.csv     date, vendor, total, tax, currency, category, notes ...
  summary.md       totals per currency and category + a review list
```
Originals are copied, never moved or modified.

## Setup

```bash
# 1. Install Ollama (https://ollama.com) and pull an open vision model
ollama pull qwen2.5vl:7b        # ~6 GB; use gemma3:4b or qwen2.5vl:3b on smaller machines

# 2. Install deps
pip install -r requirements.txt

# 3. Run
python -m sorter ~/Documents/receipts -o ~/Documents/receipts_sorted
python -m sorter ./receipts --model gemma3:4b --dry-run   # preview, writes nothing
```

## Make it yours (the part a closed API can't give you)

- `categories.json`: your own tax categories, plus `vendor_rules` that always override the model.
- `examples.json`: paste corrected outputs here; they are used as few-shot guidance, so it learns your vendors.
- `--model`: swap in any Ollama vision model, or your own fine-tune, with one flag.

## How it stays reliable with a small model

1. Constrained JSON output (Ollama `format` schema) plus tolerant parsing, with up to 2 retries.
2. Validation: dates normalized, `1.234,50` / `₹1,234.50` parsed, tax > total flagged, unknown categories caught.
3. Nothing is silently trusted: low confidence, missing fields and possible duplicates go to `needs_review/`.
4. Exact duplicates (SHA-256) are skipped without spending any inference.

## Tests

`python -m pytest` runs the pipeline end to end against a fake model (no GPU, no network).

## Roadmap ideas

Per-client folders, multi-page invoices, QuickBooks/Xero CSV export, a drag-and-drop UI.
