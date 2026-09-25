# Agentic Finance Crew — How to Use (Company Guide)

*A plain, practical guide for using this system at Sugarland Petroleum. Read the
"What it does NOT do yet" section carefully — it answers the file-upload
question directly and honestly.*

---

## 1. What this system is

An **AI expense/reimbursement approval system**. You send it an expense request
and it returns a decision:

- **AUTO-APPROVED** — small, compliant, low-risk → approved automatically.
- **NEEDS HUMAN REVIEW** — over the limit, breaks a rule, high-risk, or a
  possible duplicate → put in a **review queue** for a Finance Manager to
  approve/reject.
- **REJECTED** — invalid request (e.g. amount ≤ 0).

Every decision is **saved to a database**, gets a **full audit trail** (who
asked, what the AI recommended, which rules fired, who approved it, when, and
which model/version decided), and is protected by **login + roles**.

> **Important safety design:** the AI only *explains and recommends*. A fixed,
> tested rule (`decide()`) makes the final call, and a **human** signs off on
> anything risky. The AI can **never** silently approve spend on its own.

---

## 2. ⚠️ Does it read PDF / images / Excel / CSV? (your question)

Here is the honest, exact picture — **CSV now works through the web console**:

| File type | Read today? | Notes |
|-----------|:-----------:|-------|
| **CSV** | ✅ **Yes** | Upload or paste a CSV in the console's **Bulk Upload** tab — it decides the whole sheet and lets you **export the results as CSV**. |
| **JSON / API data** | ✅ **Yes** | One request or a batch via the API. |
| **Excel (.xlsx)** | ⚠️ **Save as CSV** | Not read directly yet — in Excel do *Save As → CSV*, then use Bulk Upload. Native `.xlsx` can be added. |
| **PDF invoices/receipts** | ❌ **No** | Not yet — needs an OCR/extraction step. |
| **PNG / JPG receipts** | ❌ **No** | Not yet — needs OCR (read amount / vendor / date from the image). |

So today you can **upload a CSV** (Bulk Upload tab) or enter one expense on the
Submit form. Excel → save as CSV first. PDF/image receipts still need a reader
to be built.

**What I can still add (in order of usefulness):**
1. **Native Excel (.xlsx) upload** → skip the "save as CSV" step.
2. **PDF / image receipt reading (OCR)** → drop a receipt, it extracts amount /
   vendor / date and runs the check. (Bigger job; needs an OCR engine.)
3. **PDF report export** → currently results export as CSV; PDF can be added.

Tell me which and I'll build it.

---

## 3. What reports / outputs it provides **today**

Everything below is available right now (as data via the API, viewable in the
browser at `/docs`):

| Output | Endpoint | What you get |
|--------|----------|--------------|
| **Decision for one expense** | `POST /approve` | Decision + risk score (0–100) + plain-English reason + which rules fired + model/version. |
| **Decision for many at once** | `POST /approve/batch` | Same, for a whole list (duplicates flagged across the batch). |
| **Decision history** | `GET /decisions` | Every past decision, filterable by outcome or employee, paginated. |
| **Review queue** | `GET /review-queue` | The list of items waiting for a human Finance Manager to approve/reject. |
| **Full audit trail (one item)** | `GET /decisions/{id}/audit` | The step-by-step history: request → AI reasoning → policy check → decision → human review → final action. |
| **Global audit log** | `GET /audit` | Every audit event across all decisions (for the Auditor). |
| **Users** | `GET /auth/users` | List of user accounts and roles (Admin only). |
| **Live metrics** | `GET /metrics` | Operational stats for monitoring: decisions, latency, failures, cost (Prometheus format). |

> These are **live data feeds**, not yet formatted PDF/Excel report files. A
> downloadable CSV/PDF report is on the "can add next" list above.

**Proof it works (quality benchmark):** the system was tested on **1,000
synthetic expense cases** — result: **100% correct decisions and 0 unsafe
auto-approvals**. See `benchmark/RESULTS.md` in this folder. This check also
runs automatically on every code change, so a mistake that let it wrongly
auto-approve something would be caught before release.

---

## 4. Who can do what (roles)

Log in and the system knows your role. Four roles:

| Role | Can submit expenses | Can approve/reject | Can view history & audit | Can manage users |
|------|:--:|:--:|:--:|:--:|
| **Employee** | ✅ | — | — | — |
| **Finance Manager** | ✅ | ✅ | ✅ | — |
| **Auditor** | ✅ | — | ✅ (read only) | — |
| **Admin** | ✅ | ✅ | ✅ | ✅ |

The person who approves is recorded automatically from their login — it can't
be faked in the request.

---

## 5. How to run it (one-time setup)

You need **Python 3.11+** on the machine (or Docker).

**Option A — Python (simplest for a quick start):**
```bash
cd "Agentic Finance Crew"
pip install -e ".[dev]"
uvicorn app:app --port 8000
```
Then open **http://localhost:8000/** in a browser — this is the **web console**
(a professional point-and-click app; log in with `admin` / `admin` on first
run). The technical API explorer is at **/docs** if you ever need it.

### The web console (easiest way to use it)
Once running, everything is done in the browser at `/ui`:
- **Submit** an expense and see the decision instantly.
- **Bulk Upload (CSV)** — upload/paste a spreadsheet, decide the whole batch,
  export results.
- **Review Queue** — managers approve/reject with one click.
- **Decisions** — filter, open any row's full **audit trail**, export to CSV.
- **Overview** — charts and KPIs. Plus **dark mode** and a 🔊 **Listen** button.

**Option B — Docker (closest to production):**
```bash
docker compose up --build       # API on http://localhost:8000
```

**On first run** the system creates a starter admin account. Set the password
first (don't leave it as the default):
```bash
# Windows PowerShell example
$env:ADMIN_USERNAME="admin"; $env:ADMIN_PASSWORD="a-strong-password"
$env:JWT_SECRET="a-long-random-string-at-least-32-characters"
uvicorn app:app --port 8000
```

**For real company data** point it at a proper database (PostgreSQL) instead of
the built-in file database, then apply the schema once:
```bash
pip install -e ".[postgres]"
$env:DATABASE_URL="postgresql+psycopg://user:password@server:5432/finance_crew"
alembic upgrade head
```

---

## 6. How to use it day-to-day

1. **Log in** to get a token (in `/docs` click *Authorize*, or via a call):
   ```bash
   curl -X POST http://localhost:8000/auth/login -d "username=admin&password=YOUR_PASSWORD"
   ```
2. **Submit an expense:**
   ```bash
   curl http://localhost:8000/approve -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"id":"EXP-1001","employee":"A. Rivera","category":"software","amount":149,"has_receipt":true}'
   ```
   You get back the decision, risk score, reason, and a `record_id`.
3. **Finance Manager checks the queue** (`GET /review-queue`) and approves or
   rejects: `POST /decisions/{id}/approve` (add a note if you like).
4. **Auditor / records** can pull the full trail any time: `GET /decisions/{id}/audit`.

**Expense fields you send:** `id`, `employee`, `category` (travel / meals /
software / equipment / other), `amount`, `has_receipt` (true/false),
and optionally `description`, `currency`, `date`.

The spend rules (auto-approve limit, per-category limits, receipt-required
amount, human-review limit) are set in code and can be tuned to SLP's real
policy — tell me the numbers and I'll set them.

---

## 7. What it does NOT do yet (be aware)

- ✅ **Does** read **CSV** (Bulk Upload tab) and export results to CSV — *new*.
- ❌ Does **not** yet read native Excel `.xlsx` (save as CSV first), PDFs or image receipts (OCR) — see section 2.
- ❌ Does **not** yet send email/Slack notifications to approvers.
- ❌ Does **not** yet produce a **PDF** report file (CSV export works today).
- ❌ Is **not** yet connected to SLP's real expense data or accounting system.

These are all things I can add — none are blockers, they're just not built yet.

---

## 8. Where things live

- **This folder** = the full project (code, tests, Docker, docs).
- `README.md` = the technical README (architecture, full endpoint list).
- `CHANGELOG.md` = what was built and when.
- Source code: `src/finance_crew/`  ·  Tests: `tests/` (57 passing).
- Live public demo (safe, synthetic data, no login):
  https://agentic-finance-crew-deploy.vercel.app

---

## 9. Data & privacy

- All sample data is **fictional**. No real SLP financial data is included.
- Passwords are stored as secure salted hashes, never in plain text.
- Login secret and database credentials are read from the environment — never
  written into the code or committed.
- Keep `JWT_SECRET`, `ADMIN_PASSWORD` and any `DATABASE_URL` **off** shared
  drives and out of email.

---

*Prepared for Sugarland Petroleum. Questions or a feature (CSV/Excel upload,
receipt OCR, downloadable reports) — ask and it gets built.*
