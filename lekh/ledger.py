"""An append-only, hash-chained ledger of every proposal and every decision.

The rule the whole system is built on: a finding is a *draft* until a named
person acts on it, and the record of that act must survive the person. So the
ledger is a hash chain — each event commits to the one before it, so removing
or editing a past event is detectable, not just discouraged.

`replay()` rebuilds the state of the book from the ledger alone. If replay and
the live store disagree, the ledger wins.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev: str, seq: int, ts: str, kind: str, payload: Any) -> str:
    h = hashlib.sha256()
    h.update(prev.encode())
    h.update(f"{seq}|{ts}|{kind}|".encode())
    h.update(_canonical(payload).encode())
    return h.hexdigest()


@dataclass
class Event:
    seq: int
    ts: str
    kind: str                 # case_opened | finding_proposed | decision | memo_issued
    payload: dict
    prev: str
    hash: str = ""

    def to_dict(self) -> dict:
        return {"seq": self.seq, "ts": self.ts, "kind": self.kind,
                "payload": self.payload, "prev": self.prev, "hash": self.hash}


class Ledger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[Event] = []
        if self.path and self.path.exists():
            self._load()

    # -- write ---------------------------------------------------------------
    def append(self, kind: str, payload: dict, ts: str) -> Event:
        prev = self.events[-1].hash if self.events else "GENESIS"
        seq = len(self.events) + 1
        ev = Event(seq=seq, ts=ts, kind=kind, payload=payload, prev=prev)
        ev.hash = _hash(prev, seq, ts, kind, payload)
        self.events.append(ev)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(_canonical(ev.to_dict()) + "\n")
        return ev

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            self.events.append(Event(**raw))

    # -- read ----------------------------------------------------------------
    def verify(self) -> list[dict]:
        """Recompute the chain. Returns the list of breaks (empty means intact)."""
        problems: list[dict] = []
        prev = "GENESIS"
        for i, ev in enumerate(self.events, start=1):
            if ev.seq != i:
                problems.append({"seq": ev.seq, "issue": f"expected seq {i}"})
            if ev.prev != prev:
                problems.append({"seq": ev.seq, "issue": "prev hash does not link"})
            expect = _hash(ev.prev, ev.seq, ev.ts, ev.kind, ev.payload)
            if expect != ev.hash:
                problems.append({"seq": ev.seq, "issue": "payload does not match hash"})
            prev = ev.hash
        return problems

    def tail_hash(self) -> str:
        return self.events[-1].hash if self.events else "GENESIS"

    def decisions(self) -> list[dict]:
        return [e.payload for e in self.events if e.kind == "decision"]

    def replay(self) -> dict:
        """Rebuild the state of the book from events alone.

        An event shape this version does not understand is skipped and counted,
        never silently mapped onto the wrong field — a replay that guesses is
        worse than a replay that reports a gap.
        """
        cases: dict[str, dict] = {}
        self.replay_skipped: list[dict] = []
        for ev in self.events:
            if ev.kind == "case_opened":
                lid = ev.payload["loan_id"]
                cases.setdefault(lid, {"loan_id": lid, "findings": {}, "decisions": []})
            elif ev.kind == "finding_proposed":
                lid = ev.payload.get("loan_id")
                fid = ev.payload.get("finding_id") or ev.payload.get("id")
                if not lid or not fid:
                    self.replay_skipped.append({"seq": ev.seq, "reason": "no loan_id/finding_id"})
                    continue
                c = cases.setdefault(lid, {"loan_id": lid, "findings": {}, "decisions": []})
                c["findings"][fid] = {
                    "family": ev.payload["family"],
                    "status": ev.payload["status"],
                    "severity": ev.payload["severity"],
                    "claim": ev.payload["claim"],
                    "decision": None,
                }
            elif ev.kind == "decision":
                lid = ev.payload.get("loan_id")
                if not lid:
                    self.replay_skipped.append({"seq": ev.seq, "reason": "decision without loan_id"})
                    continue
                c = cases.setdefault(lid, {"loan_id": lid, "findings": {}, "decisions": []})
                c["decisions"].append(ev.payload)
                f = c["findings"].get(ev.payload.get("finding_id"))
                if f is not None:
                    f["decision"] = ev.payload["action"]
        return cases

    def export(self, path: str | Path) -> Path:
        """The audit pack: events plus the chain's final hash."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "events": [e.to_dict() for e in self.events],
            "tail": self.tail_hash(),
            "verified": self.verify() == [],
        }, indent=2), encoding="utf-8")
        return p


def counts_by_decision(ledger: Ledger) -> dict:
    out = {"approve": 0, "edit": 0, "reject": 0, "explain": 0}
    for d in ledger.decisions():
        out[d["action"]] = out.get(d["action"], 0) + 1
    return out
