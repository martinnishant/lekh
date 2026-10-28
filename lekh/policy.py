"""The credit policy, as code, with a page reference on every rule.

Two ideas matter here and both are borrowed from how Winsen One describes its
process maps: a rule is only real if it cites the clause it came from, and the
citation has to be *checkable*. So the policy file carries `clause` and
`page`, and `verify_citations()` re-reads the policy PDF and confirms that the
clause text actually appears on the page we claim. A rule whose citation has
drifted fails loudly instead of quietly reviewing files against a rule nobody
approved.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # PyYAML is optional; JSON policies always work.
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    clause: str
    page: int
    severity: str            # high | medium | low
    check: str               # name of the checker function in lekh.rules
    quote: str               # the clause text as it appears in the policy PDF
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stable id for this exact rule text, used in the audit ledger."""
        blob = f"{self.id}|{self.clause}|{self.page}|{self.quote}|{sorted(self.params.items())}"
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass
class Policy:
    name: str
    version: str
    rules: list[Rule]

    @property
    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for r in sorted(self.rules, key=lambda r: r.id):
            h.update(r.fingerprint.encode())
        return h.hexdigest()[:16]

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)


def load_policy(path: str | Path) -> Policy:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("PyYAML not installed; use the JSON policy or pip install pyyaml")
        data = yaml.safe_load(raw)
    else:
        import json
        data = json.loads(raw)
    rules = [Rule(**r) for r in data["rules"]]
    return Policy(name=data["name"], version=data["version"], rules=rules)


def verify_citations(policy: Policy, policy_pages: list[str]) -> list[dict]:
    """Re-check every rule against the policy PDF it cites.

    Returns a list of problems. Empty list means the policy is trustworthy.
    """
    problems: list[dict] = []
    for r in policy.rules:
        if not (1 <= r.page <= len(policy_pages)):
            problems.append({"rule": r.id, "issue": "page out of range", "page": r.page})
            continue
        page_text = " ".join(policy_pages[r.page - 1].split()).lower()
        needle = " ".join(r.quote.split()).lower()
        if needle not in page_text:
            problems.append({"rule": r.id, "issue": "clause quote not found on cited page",
                             "page": r.page, "quote": r.quote})
    return problems
