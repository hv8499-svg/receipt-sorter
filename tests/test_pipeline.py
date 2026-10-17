import csv
import json
from pathlib import Path

from sorter.pipeline import process_folder
from sorter.schema import iso_date, money, parse_json

CONFIG = json.loads((Path(__file__).parent.parent / "categories.json").read_text())


class FakeModel:
    """Returns canned replies in order, so tests need no GPU or network."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def extract(self, images, prompt, schema=None):
        self.calls += 1
        return self.replies.pop(0)


def good(**kw):
    d = {"vendor": "Figma", "date": "2026-03-04", "total": 15, "tax": 0, "currency": "usd",
         "category": "Other", "document_type": "invoice", "confidence": 0.9}
    d.update(kw)
    return json.dumps(d)


def test_money_formats():
    assert money("₹1,234.50") == 1234.50
    assert money("1.234,50") == 1234.50
    assert money("12,5") == 12.5
    assert money("1,234") == 1234.0
    assert money("abc") is None


def test_dates_and_json():
    assert iso_date("04/03/2026") == "2026-03-04"
    assert iso_date("Mar 4, 2026") == "2026-03-04"
    assert parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}


def test_end_to_end(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "a.png").write_bytes(b"one")
    (inp / "b.png").write_bytes(b"two")
    (inp / "c.png").write_bytes(b"three")
    (inp / "d.png").write_bytes(b"one")      # exact dup of a.png
    (inp / "e.png").write_bytes(b"five")
    model = FakeModel([
        good(),                                        # a: vendor rule fixes category
        good(),                                        # b: same vendor/date/total -> possible dup
        "not json at all", "still no", "nope",         # c: 3 failures -> review
        good(vendor="Corner Cafe", total="₹250.00", category="Meals & Entertainment", confidence=0.3),  # e: low conf
    ])
    rows = process_folder(inp, out, model, CONFIG, [], log=lambda *_: None)
    by = {r["original_name"]: r for r in rows}

    assert by["a.png"]["category"] == "Software & Subscriptions"
    assert by["a.png"]["currency"] == "USD" and not by["a.png"]["needs_review"]
    assert "possible duplicate" in by["b.png"]["notes"]
    assert "unusable" in by["c.png"]["notes"]
    assert "exact duplicate" in by["d.png"]["notes"]
    assert "low confidence" in by["e.png"]["notes"]
    assert model.calls == 6  # a, b, c x3 (retries), e; the duplicate never hits the model

    assert (out / "sorted" / "2026-03-04_Figma_15.0.png").exists()
    assert (inp / "a.png").exists()  # originals untouched
    assert len(list(csv.DictReader(open(out / "receipts.csv")))) == 5
    summary = (out / "summary.md").read_text()
    assert "Software & Subscriptions" in summary and "Needs your review" in summary


def test_dry_run_writes_nothing(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "a.png").write_bytes(b"x")
    process_folder(inp, out, FakeModel([good()]), CONFIG, [], dry_run=True, log=lambda *_: None)
    assert not out.exists()


def test_evidence_flags_unclear_and_mismatch(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "a.png").write_bytes(b"a")
    (inp / "b.png").write_bytes(b"b")
    (inp / "c.png").write_bytes(b"c")
    model = FakeModel([
        good(date_text="1?/09/2026", total_text="Rs 3?5.00"),   # the blurry-receipt case
        good(vendor="X", total_text="Rs 99.00"),                  # claims 15, text says 99
        good(vendor="Y", date_text="March 4, 2026", total_text="$15.00"),  # consistent: no flag
    ])
    rows = {r["original_name"]: r for r in process_folder(inp, out, model, CONFIG, [], log=lambda *_: None)}
    assert "date text unclear" in rows["a.png"]["notes"] and "total text unclear" in rows["a.png"]["notes"]
    assert rows["a.png"]["needs_review"] == "yes"
    assert "total text disagrees" in rows["b.png"]["notes"]
    assert rows["c.png"]["needs_review"] == ""


def test_verify_pass_flags_disagreement(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "a.png").write_bytes(b"a")
    (inp / "b.png").write_bytes(b"b")
    model = FakeModel([
        good(vendor="A", date="2026-09-17", total=375), good(vendor="A", date="2026-09-11", total=315),  # a: reads differ
        good(vendor="B"), good(vendor="B"),                                                              # b: reads agree
    ])
    rows = {r["original_name"]: r for r in
            process_folder(inp, out, model, CONFIG, [], log=lambda *_: None, verify=True)}
    assert "verification pass disagreed on date and total" in rows["a.png"]["notes"]
    assert rows["b.png"]["needs_review"] == ""
    assert model.calls == 4
