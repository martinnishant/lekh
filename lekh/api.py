"""FastAPI surface: the console, the case API, the decision gate, the ledger.

The decision endpoint is the whole point of the product. It requires a named
reviewer, it refuses to decide a finding twice, and it writes to the hash chain
before it answers. There is no code path where a finding becomes effective
without a person's name on it.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "state" / "ledger.jsonl"
CONSOLE_DATA = ROOT / "reports" / "console-data.json"

app = FastAPI(title="lekh", version="0.1.0",
              description="A document-evidence review kernel: cited findings, human signatures, "
                          "a hash-chained record.")


class Decision(BaseModel):
    loan_id: str
    finding_id: str
    action: str            # approve | edit | reject | explain
    reviewer: str
    note: str = ""


def _records() -> list[dict]:
    if not CONSOLE_DATA.exists():
        return []
    return json.loads(CONSOLE_DATA.read_text(encoding="utf-8")).get("records", [])


@app.get("/", response_class=HTMLResponse)
def console() -> str:
    data = CONSOLE_DATA.read_text(encoding="utf-8") if CONSOLE_DATA.exists() else "null"
    template = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    return template.replace("/*__DATA__*/null", data)


@app.get("/api/cases")
def cases(status: str | None = None) -> JSONResponse:
    rows = _records()
    if status:
        rows = [r for r in rows if any(f["status"] == status for f in r["findings"])]
    return JSONResponse([{"loan_id": r["loan_id"], "summary": r["summary"],
                          "digest": r["digest"], "facts": r["facts"]} for r in rows])


@app.get("/api/case/{loan_id}")
def case(loan_id: str) -> JSONResponse:
    for r in _records():
        if r["loan_id"] == loan_id:
            return JSONResponse(r)
    raise HTTPException(404, f"no such file: {loan_id}")


@app.get("/api/eval")
def evaluation() -> JSONResponse:
    path = ROOT / "reports" / "eval-report.json"
    if not path.exists():
        raise HTTPException(404, "run `python -m lekh.cli eval` first")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.post("/api/decision")
def decide(d: Decision) -> JSONResponse:
    if d.action not in ("approve", "edit", "reject", "explain"):
        raise HTTPException(400, "action must be approve, edit, reject or explain")
    if len(d.reviewer.strip()) < 3:
        raise HTTPException(400, "a named reviewer is required; this gate does not accept anonymous")
    rec = next((r for r in _records() if r["loan_id"] == d.loan_id), None)
    if rec is None:
        raise HTTPException(404, f"no such file: {d.loan_id}")
    finding = next((f for f in rec["findings"] if f["id"] == d.finding_id), None)
    if finding is None:
        raise HTTPException(404, "no such finding on this file")

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(LEDGER_PATH)
    already = {x["finding_id"] for x in ledger.decisions()}
    if d.finding_id in already:
        raise HTTPException(409, "this finding already carries a decision; the ledger is append-only")

    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ev = ledger.append("decision", {
        "loan_id": d.loan_id, "finding_id": d.finding_id, "action": d.action,
        "reviewer": d.reviewer.strip(), "note": d.note,
        "finding_family": finding["family"], "finding_status": finding["status"],
        "clause": finding["clause"], "evidence": finding["evidence"],
    }, ts)
    return JSONResponse({"ok": True, "event": ev.to_dict(), "chain": ledger.verify() == []})


@app.get("/api/ledger")
def ledger_state() -> JSONResponse:
    ledger = Ledger(LEDGER_PATH)
    return JSONResponse({"events": len(ledger.events), "tail": ledger.tail_hash(),
                         "verified": ledger.verify() == [],
                         "decisions": ledger.decisions()[-50:]})


@app.get("/api/ledger/replay")
def replay() -> JSONResponse:
    """Rebuild the book from the ledger alone; the ledger is the source of truth."""
    ledger = Ledger(LEDGER_PATH)
    state = ledger.replay()
    return JSONResponse({"verified": ledger.verify() == [],
                         "events": len(ledger.events),
                         "cases": len(state),
                         "replay_skipped": getattr(ledger, "replay_skipped", []),
                         "state": state})
