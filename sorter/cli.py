import argparse
import json
from pathlib import Path

from .model import OllamaClient
from .pipeline import process_folder

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="receipt-sorter",
                                 description="Sort receipts and invoices with a local vision model. Nothing leaves your machine.")
    ap.add_argument("input", help="folder of PDFs / photos")
    ap.add_argument("-o", "--output", default="sorted_output")
    ap.add_argument("--model", default="qwen2.5vl:7b", help="any Ollama vision model, e.g. gemma3:4b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--config", default=str(ROOT / "categories.json"))
    ap.add_argument("--examples", default=str(ROOT / "examples.json"))
    ap.add_argument("--dry-run", action="store_true", help="extract and print, write nothing")
    ap.add_argument("--verify", action="store_true", help="read each document twice and flag disagreements (slower, safer)")
    a = ap.parse_args(argv)

    config = json.loads(Path(a.config).read_text())
    examples = json.loads(Path(a.examples).read_text()) if Path(a.examples).exists() else []
    client = OllamaClient(a.model, a.host)
    client.check()
    rows = process_folder(a.input, a.output, client, config, examples, dry_run=a.dry_run, verify=a.verify)
    flagged = sum(1 for r in rows if r["needs_review"])
    print(f"\nDone: {len(rows)} documents, {flagged} need review. Output: {a.output}/")


if __name__ == "__main__":
    main()
