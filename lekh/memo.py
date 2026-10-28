"""Memo drafting, where the model writes prose and never writes a number.

The architecture is the point:

    the model plans nothing, decides nothing and computes nothing.
    It re-writes a finding that deterministic code already proved.

So the memo drafter has exactly one job, and one guard: `numeric_fidelity()`
extracts every number from the generated text and refuses the draft if any of
them is not already present in the finding's derivation or evidence. A model
that invents a figure gets caught by arithmetic, not by a second model.

Runs with zero API cost by default (`template`), and can be pointed at a free
local or free-tier provider (`ollama`, `groq`) without changing anything else.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass

from .engine import CaseRecord
from .rules import Finding

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUM_RE.findall(text or ""):
        cleaned = raw.replace(",", "").rstrip(".")
        try:
            val = float(cleaned)
        except ValueError:
            continue
        out.add(f"{val:.2f}")
    return out


def allowed_numbers(finding: Finding) -> set[str]:
    """Every number the finding can legitimately talk about."""
    blob = (json.dumps(finding.derivation, default=str) + " " + finding.claim + " "
            + finding.detail + " " + str(finding.clause) + " " + str(finding.clause_page))
    for ev in finding.evidence:
        blob += " " + str(ev.get("quote", "")) + " p." + str(ev.get("page", ""))
    return _numbers(blob)


def numeric_fidelity(text: str, finding: Finding) -> dict:
    used = _numbers(text)
    allowed = allowed_numbers(finding)
    invented = sorted(used - allowed)
    return {"ok": not invented, "invented": invented,
            "numbers_used": len(used), "numbers_allowed": len(allowed)}


# ---------------------------------------------------------------------------- template
def draft_finding_template(finding: Finding, borrower: str | None) -> str:
    who = borrower or "the borrower"
    head = {
        "finding": "FINDING — requires a decision",
        "explained": "EXPLAINED — breach covered, needs acknowledgement",
        "needs_human": "ABSTAINED — cannot be determined from the file",
    }[finding.status]
    lines = [f"**{head}** · {finding.family} · severity {finding.severity}",
             "",
             finding.claim + ".",
             ""]
    if finding.detail:
        lines += [finding.detail, ""]
    deriv = finding.derivation or {}
    if deriv:
        pairs = [f"{k.replace('_', ' ')}: {v}" for k, v in deriv.items()
                 if isinstance(v, (int, float, str)) and not isinstance(v, bool)]
        if pairs:
            lines += ["Derivation — " + "; ".join(pairs) + ".", ""]
    if finding.evidence:
        lines.append("Evidence:")
        for ev in finding.evidence[:6]:
            lines.append(f"- {ev.get('doc')} p.{ev.get('page')}: “{ev.get('quote')}”")
        lines.append("")
    for note in finding.notes:
        lines.append(f"Note: {note}")
    if finding.notes:
        lines.append("")
    lines.append(f"Clause {finding.clause} (policy p.{finding.clause_page}). "
                 f"Nothing in this memo has effect until a named reviewer signs it.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- llm
PROMPTS = {
    "ollama": ("http://localhost:11434/api/generate", "llama3.2:3b"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant"),
}

INSTRUCTION = (
    "You are drafting a paragraph for a credit review memorandum. You may only restate "
    "facts given to you. You must not introduce any number that is not in the input. "
    "Write two sentences, plain and specific, no adjectives, no recommendations."
)


def draft_finding_llm(finding: Finding, provider: str, timeout: int = 30) -> tuple[str, dict]:
    """Ask a model to re-word the finding. Falls back to the template on any doubt."""
    url, model = PROMPTS[provider]
    payload_facts = {
        "claim": finding.claim, "detail": finding.detail,
        "derivation": finding.derivation, "clause": finding.clause,
    }
    prompt = f"{INSTRUCTION}\n\nFACTS:\n{json.dumps(payload_facts, indent=1, default=str)}\n\nMEMO PARAGRAPH:"

    try:
        if provider == "ollama":
            body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(url, data=body,
                                        headers={"Content-Type": "application/json"})
        else:
            key = os.environ.get("GROQ_API_KEY")
            if not key:
                raise RuntimeError("GROQ_API_KEY not set")
            body = json.dumps({"model": model, "temperature": 0,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        text = data.get("response") if provider == "ollama" else \
            data["choices"][0]["message"]["content"]
        text = (text or "").strip()
        guard = numeric_fidelity(text, finding)
        if not guard["ok"]:
            return draft_finding_template(finding, None), {
                "provider": provider, "used": "template",
                "reason": f"numeric fidelity failed: {guard['invented']}"}
        return text, {"provider": provider, "used": provider, "fidelity": guard}
    except Exception as exc:
        return draft_finding_template(finding, None), {
            "provider": provider, "used": "template", "reason": str(exc)[:160]}


# ---------------------------------------------------------------------------- case memo
@dataclass
class MemoDraft:
    loan_id: str
    markdown: str
    provider: str
    guards: list[dict]
    template_markdown: str

    def to_dict(self) -> dict:
        return {"loan_id": self.loan_id, "markdown": self.markdown,
                "provider": self.provider, "guards": self.guards,
                "template_markdown": self.template_markdown}


def draft_case_memo(record: CaseRecord, provider: str = "template") -> MemoDraft:
    f = record.facts
    order = {"finding": 0, "needs_human": 1, "explained": 2}
    findings = sorted(record.findings, key=lambda x: (order.get(x.status, 3), -len(x.claim)))
    header = [
        f"# Review memorandum — {record.loan_id}",
        "",
        f"**Borrower:** {f.get('borrower')}  |  **Branch:** {f.get('branch')}  |  "
        f"**Sanction date:** {f.get('sanction_date')}  |  "
        f"**Amount:** Rs. {f.get('sanction_amount') or 0:,.0f}  ",
        f"**Policy:** {record.policy_version} (`{record.policy_fingerprint}`)  |  "
        f"**Run:** {record.run_id}  |  **Digest:** `{record.digest}`",
        "",
        f"Files reviewed: {len(record.documents)} documents, "
        f"{sum(d.get('pages', 0) for d in record.documents)} pages. "
        f"Coverage: 100% of documents on file, not a sample.",
        "",
        f"**Result:** {len(record.flagged)} finding(s), {len(record.explained)} explained breach(es), "
        f"{len(record.needs_human)} item(s) abstained for a human.",
        "",
        "---", "",
    ]
    blocks, guards, template_blocks = [], [], []
    for fd in findings:
        tpl = draft_finding_template(fd, f.get("borrower"))
        template_blocks.append(tpl)
        if provider == "template":
            blocks.append(tpl)
            continue
        text, meta = draft_finding_llm(fd, provider)
        guards.append({"finding": fd.family, **meta})
        blocks.append(f"**{fd.family}** · {fd.status} · severity {fd.severity}\n\n{text}\n\n"
                      f"Evidence: " + "; ".join(
                          f"{e.get('doc')} p.{e.get('page')}" for e in fd.evidence[:4]) + "\n")

    residue = [
        "", "---", "",
        "## What was not checked",
        "",
        "Stated plainly, because a review memo that implies more coverage than it had is a lie:",
        "",
        "- Text-bearing PDFs only. No OCR, so a scanned-only file is not reviewed.",
        "- The rules in this policy and no others. A breach the policy does not name is not found.",
        "- Numbers are verified against documents, not against the core system of record.",
        "- Co-applicant income is excluded unless separately evidenced; personal discussion,",
        "  field visits, and legal title opinion are outside this review.",
        "",
        f"_Drafted by lekh. No output in this memo counts until a named reviewer signs it. "
        f"Ledger digest `{record.digest}`._",
    ]
    markdown = "\n".join(header) + "\n".join(blocks) + "\n".join(residue)
    return MemoDraft(loan_id=record.loan_id, markdown=markdown, provider=provider,
                     guards=guards,
                     template_markdown="\n".join(header) + "\n\n---\n\n".join(template_blocks)
                     + "\n" + "\n".join(residue))
