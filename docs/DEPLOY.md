# Deploying `lekh` — from zip to a link you can send

Everything here uses free tiers only. Total cost: **₹0**.

There are three levels. Do level 1 and 2 — that is what a reviewer clicks. Level 3 is
optional and only if you want a live API.

| level | what you get | time | cost |
|---|---|---|---|
| 1 | repo on GitHub, CI green, console built in Actions | ~15 min | free |
| 2 | **live console URL** on GitHub Pages — the link you put in the application | +5 min | free |
| 3 | live API + decision endpoint on Render/Fly/HF Spaces | +20 min | free tier |

---

## 0. Unzip and check it runs locally first

**macOS / Linux**
```bash
unzip lekh.zip
cd lekh

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

python -m lekh.cli generate      # builds 72 loan files (≈10s, all local)
python -m lekh.cli check         # every rule's citation resolves to its page
python -m lekh.cli run           # reviews all files, writes the hash-chained ledger
python -m lekh.cli eval          # scores it, writes reports/eval-report.md
python -m lekh.cli html          # writes reports/console.html
pytest -q                        # 26 tests
```

**Windows (PowerShell)**
```powershell
Expand-Archive lekh.zip -DestinationPath .
cd lekh
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m lekh.cli generate; python -m lekh.cli check; python -m lekh.cli run; python -m lekh.cli eval; python -m lekh.cli html
pytest -q
```

Then open `reports/console.html` in a browser (double-click — it needs no server).
You should see the queue on the left and a cited finding on the right.

**Expected output at the end of `eval`:**
```
recall 100.0%  precision 100.0%  exact 100.0%  citations 100.0%
baseline recall 24.3%  baseline false positives 7
determinism: identical digests
```

If that matches, everything downstream will work.

---

## 1. Put it on GitHub

### 1a. Create the repo

On github.com → **New repository** → name it `lekh` → **Public** → do **not** add a
README, .gitignore or licence (they are already in the zip) → **Create**.

### 1b. Push (terminal, recommended)

```bash
cd lekh
git init
git add .
git commit -m "lekh: a document-evidence review kernel for credit files

Deterministic policy-as-code checks with page-level citations, an explained/
abstained/finding outcome model, a hash-chained approval ledger, and an eval
rig that scores the reviewer against 72 synthetic home-loan files."

git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/lekh.git
git push -u origin main
```

Replace `<YOUR-USERNAME>`. Your résumé says `github.com/martinnishant` — use that account.

**If git asks for a password:** GitHub no longer accepts account passwords. Create a
Personal Access Token (Settings → Developer settings → Personal access tokens → Fine-grained
→ repo scope) and paste the token as the password. Or install the GitHub CLI (`gh auth login`).

### 1c. Or push with the web UI (no terminal)

1. On the empty repo page click **uploading an existing file**.
2. Drag the **contents** of the `lekh` folder (not the folder itself) — the browser
   flattens directories correctly if you drag the folders in.
3. Commit message: `lekh: a document-evidence review kernel for credit files`.
4. Note: the web UI cannot upload empty directories and sometimes skips dotfiles, so
   check afterwards that `.github/` and `.gitignore` exist. If `.github/` is missing,
   add the two workflow files manually: **Add file → Create new file**, and type the full
   path including `.github/workflows/ci.yml` — the slashes create the folders.

### 1d. Make the repo look like a portfolio piece (5 minutes, do it)

- **About** (top right, gear icon): description
  `Policy-as-code review kernel for credit files: cited findings, a deviation gate, measured abstentions, a hash-chained approval ledger. 72 synthetic loan files, 0 false positives.`
  Website: your Pages URL from step 2. Topics:
  `ai-agents` `evals` `document-ai` `llm` `fintech` `audit-trail` `policy-as-code` `india`
- **Pin the repo** on your profile (Profile → Customize your pins).
- Watch the **Actions** tab: your `ci` workflow should go green on the first push. A green
  check plus a badge at the top of the README is exactly the "strong GitHub" signal the
  founding-engineer JD asks for.

Optional badge for the top of `README.md`:
```markdown
[![ci](https://github.com/<YOUR-USERNAME>/lekh/actions/workflows/ci.yml/badge.svg)](https://github.com/<YOUR-USERNAME>/lekh/actions/workflows/ci.yml)
```

---

## 2. Make it live (GitHub Pages) — the link you send them

The console is one self-contained HTML file, so Pages can host it with no backend.

1. Repo → **Settings** → **Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions** (not "Deploy from a
   branch"). The `pages.yml` workflow in this repo takes it from there.
3. Go to **Actions** → **live console** → **Run workflow** (or push any commit).
4. Wait ~90 seconds. The job prints a URL like
   `https://<YOUR-USERNAME>.github.io/lekh/`.
5. Open it. You should see the console with the metric strip, the queue of 72 files, and
   cited findings. **This is the URL you paste into the Winsen application.**

Notes:
- `reports/eval-report.json` is published next to it, so anyone can inspect the raw scores.
- The page rebuilds the corpus in CI every push, so the numbers on the live link always
  match the code. That property matters more than it sounds: a live demo that cannot go
  stale is a trust signal.
- If the URL 404s, the usual cause is step 2 still being set to *Deploy from a branch*.
- Custom domain is not needed.

**Test it in an incognito window** before you send it — if it works logged out, it works
for them.

---

## 3. Optional: a live API (only if you want the decision endpoint online)

Pages hosts a static file. The FastAPI app needs a real host. Free tiers:

### Render (easiest)
1. render.com → **New → Web Service** → connect your GitHub repo.
2. Settings: **Runtime** Python 3, **Build command**
   `pip install -r requirements.txt && python -m lekh.cli generate && python -m lekh.cli check && python -m lekh.cli run && python -m lekh.cli eval`
   **Start command** `uvicorn lekh.api:app --host 0.0.0.0 --port $PORT`.
3. Free instance, deploy. You get `https://lekh-xxxx.onrender.com/` serving the console and
   `/api/case/{loan_id}`, `/api/decision`, `/api/ledger`.

### Fly.io / Railway / Hugging Face Spaces
A `Dockerfile` and a `Procfile` are included; any of these will pick them up.

**Say this out loud in the interview if you deploy level 3:** free hosts have ephemeral
filesystems, so the hash-chained ledger resets when the container restarts. The ledger is
append-only *by design*, which means it wants durable storage (a mounted volume or Postgres)
before it means anything in production. Demonstrating the constraint honestly is better
than pretending the demo is a deployment.

---

## 4. What "live" should NOT be

Do not add an LLM call just to make the demo feel more AI. The project's argument is that
**code decides and the model only writes**, so a demo where the numbers come from a model
would argue against itself. If you want the LLM path visible, run it locally with Ollama and
mention it; leave the hosted demo deterministic.

---

## 5. Common failures and the fix

| symptom | cause | fix |
|---|---|---|
| `ModuleNotFoundError: lekh` | running from inside `lekh/` subfolder instead of the repo root | `cd lekh` (the folder with `README.md`), then rerun |
| `pdfplumber` install error | very old Python | use Python 3.10 – 3.13 |
| `check` fails with "clause quote not found" | the policy PDF was edited but the YAML quote wasn't | regenerate: `python -m lekh.cli generate` (it rewrites the policy PDF) |
| `eval` says no records / console is empty | `eval` not run before `html` | `python -m lekh.cli eval && python -m lekh.cli html` |
| Pages shows a 404 | Source still set to "Deploy from a branch" | Settings → Pages → Source: **GitHub Actions**, then rerun the workflow |
| Actions fails on `pytest` | you committed a broken rule or edited `data/corpus` by hand | run `pytest -q` locally; delete `data/corpus` and `cli generate` again |
| Git push rejected (`non-fast-forward`) | repo was initialised with a README on GitHub | `git pull --rebase origin main` then push |
| Console shows stale numbers | you edited code but didn't rebuild | `cli run && cli eval && cli html`, then commit `reports/` |

---

## 6. After it is live: the 3-minute demo, on camera

Script is in `docs/RESEARCH.md` §6. Record it with the **live Pages URL**, not a local file,
so there is nothing to doubt. Structure:

1. `0:00` the claim: coverage instead of sampling, and what has to be true for that claim to hold.
2. `0:30` `HL-20126` — a breach credited as *explained*, with the deviation register row as evidence.
3. `1:15` `HL-20273` — OCR read a digit as `O`; the row is withheld instead of averaged.
4. `2:00` `HL-20343` — a deviation that lapsed before sanction, with the reason stated.
5. `2:40` the eval: 37/37, zero false positives, 113/113 citations resolve, two runs identical — then the honest sentence: *"green on a corpus I generated, so it's a regression suite, not a field study."*
6. `3:00` stop.

---

## 7. Checklist before you hit Apply

- [ ] `pytest -q` passes locally (26 tests)
- [ ] `ci` workflow is green on GitHub
- [ ] `live console` workflow is green and the URL loads in an incognito window
- [ ] repo About: description + topics + Pages link
- [ ] repo pinned on your profile
- [ ] `README.md` numbers match the live `eval-report` (they are generated, so they should)
- [ ] the two application answers from `docs/APPLICATION.md` have the live URL pasted in
- [ ] 3-minute video recorded, unlisted, link works
- [ ] résumé updated with the project + the live link (one line, with the numbers)
