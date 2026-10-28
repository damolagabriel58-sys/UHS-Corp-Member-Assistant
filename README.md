<div align="center">

# UHS Director Assistant

### Secure, approval-controlled document processing for the Director's Office

**University Health Service (UHS) — University of Ibadan**

A private web application for receiving corps members' PDF submissions through Gmail, organizing them by state code and reporting period, supporting deliberate Director approval, signing approved forms, returning signed copies by email, and tracking annual clearance history.

**React + Vite** · **FastAPI** · **PostgreSQL / Supabase** · **Google OAuth & Gmail API** · **PyMuPDF** · **Vercel + Render**

[Features](#features) · [How it works](#how-it-works) · [Quick start](#local-development) · [Deployment](#deployment) · [Security](#security-and-privacy) · [Troubleshooting](#troubleshooting)

</div>

> [!IMPORTANT]
> **Private Director's Office application.** This solution operates independently of any institutional UHS information system. Only the configured Director's Google identity should be authorized to use it. Document approval, signature application, and emailing must always remain deliberate, Director-initiated actions.

> [!NOTE]
> This README documents the **28 October 2026 four-feature update** using the supplied `main.py`, `models.py`, `document_service.py`, and latest dashboard bundle. Some supporting modules (`gmail_service.py`, `gmail_token_store.py`, `storage_service.py`, `database.py`, `document_classifier.py`, deployment configuration and dependency manifests) were not included in that update package; verify their exact settings against the actual repository when deploying. This document does not claim a production security audit, guaranteed email delivery, or live end-to-end testing.

---

## Table of contents

1. [Overview](#overview)
2. [Features](#features)
3. [Users and responsibilities](#users-and-responsibilities)
4. [How it works](#how-it-works)
5. [Document naming and submission rules](#document-naming-and-submission-rules)
6. [Director dashboard guide](#director-dashboard-guide)
7. [Architecture and technology](#architecture-and-technology)
8. [Repository structure](#repository-structure)
9. [Database design](#database-design)
10. [API reference](#api-reference)
11. [Local development](#local-development)
12. [Google authentication and Gmail authorization](#google-authentication-and-gmail-authorization)
13. [Supabase setup and migration](#supabase-setup-and-migration)
14. [Deployment](#deployment)
15. [Security and privacy](#security-and-privacy)
16. [Document lifecycle and retention](#document-lifecycle-and-retention)
17. [Testing checklist](#testing-checklist)
18. [Troubleshooting](#troubleshooting)
19. [Operations and maintenance](#operations-and-maintenance)
20. [Known limitations and future improvements](#known-limitations-and-future-improvements)
21. [Project handover](#project-handover)
22. [License and attribution](#license-and-attribution)

---

## Overview

The **UHS Director Assistant** streamlines the routine processing of NYSC corps members' **monthly clearance** and **payment approval** documents.

Traditionally, the Director might have to open each email, download an attachment, inspect the form, insert a signature, save a copy, and email it back. This application centralizes the workflow without giving up Director control over the signature or the decision to approve.

**The central rule:** *receiving an email never authorizes signing or sending*. Gmail synchronization can import and classify PDFs, but a separate, authenticated action from the Director is required for approval.

### Project goals

- Reduce repetitive download–sign–reply administration.
- Keep submitted PDFs and the signature asset in private storage.
- Present pending submissions and signed records on one dashboard.
- Support both individual review and explicitly confirmed bulk approval.
- Track monthly clearance completion for each corps member across calendar years.
- Preserve useful history and audit records while allowing the Director to declutter the dashboard.

### Scope

The current implementation is a **single-authorized-Director workflow**, not a public student portal or a multi-user institutional records system. Corps members submit by email; they do **not** receive login credentials to the dashboard. The app is intended for the specific UHS document layouts supported by its classifier and signing service.

---

## Features

| Area | Capability | Important behavior |
| --- | --- | --- |
| Gmail intake | Periodic retrieval of PDF attachments | Only recognized filenames are imported; no automatic approval |
| Classification | Distinguishes clearance from payment approval | Uses the document filename and state code |
| Director login | Google sign-in restricted to one configured email | Uses a server-managed authenticated session |
| Document list | Pending queue with state code, month, **year**, sender, timestamp and status | Search/filter and manual refresh |
| Secure preview | Read an original PDF through an authenticated backend endpoint | No public PDF link is required |
| Individual action | **Review → Approve, Sign & Send** | Director authorizes signing and sending explicitly |
| Bulk action | **Approve, Sign & Send All** | Separate batch confirmation; executes sequentially in the open browser tab |
| Signature placement | Document-specific placement and small date | Clearance date below signature; payment date beside its Director-signature field |
| Signed archive | Signed and sent PDFs grouped/filterable by month and year | Records are kept in private storage |
| Dashboard removal | **Remove** a document from visible lists | Soft removal; audit, deduplication and signed records remain |
| Retention | Discard original after confirmed sending | Original is kept if delivery outcome is uncertain |
| Clearance history | Year-by-year January–December matrix per state code | A check means recorded, confirmed sent clearance—not simply received |
| Audit trail | Tracks approval, send requests, outcomes, cleanup and removal | Useful for investigation and accountability |

### Refresh intervals

The supplied background Gmail worker is configured to **poll approximately every 30 seconds** (`gmail_sync_worker.py`), while the React document dashboard automatically refreshes **every five minutes**. A manual **Refresh** action updates the dashboard sooner. These are different processes; server availability and third-party API delays affect actual timing.

---

## Users and responsibilities

| Participant | Responsibilities | Access |
| --- | --- | --- |
| Corps member | Prepare a correct PDF, name it correctly, send it to the designated Director's mailbox | Email only; **no** dashboard account |
| UHS Director | Sign in, inspect/approve submissions, confirm bulk operations, inspect archive and clearance history | Restricted dashboard through Google login |
| Technical administrator | Configure Google Cloud, deploy services, maintain database/storage, investigate failures and backups | Infrastructure only; should not approve documents on the Director's behalf |

A technical administrator's access to infrastructure is **not** a substitute for the Director's approval to sign or send a document.

---

## How it works

```mermaid
flowchart TD
    A[Corps member emails PDF attachment] --> B[Gmail API polling]
    B --> C{Recognized filename and sender?}
    C -- No --> D[Skip and record import outcome]
    C -- Yes --> E[Save original in private Storage]
    E --> F[Insert pending document in PostgreSQL]
    F --> G[Director signs in through Google]
    G --> H{Review individually or confirm bulk approval}
    H --> I[Authenticated approval request]
    I --> J[Check Gmail account and signing field]
    J --> K[Create signed PDF in private Storage]
    K --> L[Reserve send and email signed PDF]
    L --> M{Gmail returns a message ID?}
    M -- Yes --> N[Mark sent and record audit/history]
    N --> O[Attempt to discard original; retain signed PDF]
    M -- No / uncertain --> P[Preserve evidence; reconcile Sent Mail]
    O --> Q[Signed archive and annual clearance history]
    P --> Q
```

### Key separation of duties

1. **Import:** Downloads and classifies; must not sign, approve or send.
2. **Approval:** Requires a valid Director session and allowed browser origin.
3. **Signing:** Applies the stored authentic signature only to recognized Director-signature fields.
4. **Emailing:** Sends the signed PDF to the recorded original sender upon approval.
5. **Recording:** Stores status and audit events; updates clearance history only after Gmail acknowledges the outgoing message.
6. **Cleanup:** Discards the original only after successful send confirmation and safe signed-copy retention.

---

## Document naming and submission rules

Corps members must send an actual **PDF attachment** to the Director's designated mailbox. The current filename convention is:

| Document | Pattern | Example |
| --- | --- | --- |
| Monthly clearance | `Clearance-Month-StateCode.pdf` | `Clearance-November-OY-26B-3445.pdf` |
| Payment approval | `PaymentApproval-Month-StateCode.pdf` | `PaymentApproval-November-OY-26B-3445.pdf` |

**Submission requirements:**

- Replace `Month` with the correct reporting month and `StateCode` with the corps member's valid state code.
- Attach the PDF itself; a photo or Google Drive link is not processed as an attached PDF.
- Use the supported template/layout. A correctly named file does **not** guarantee that an incompatible PDF can be signed.
- Submit to the mailbox connected to the system through authorized Gmail access.
- Keep personal information in the email and PDF to the minimum necessary for the process.

### How is the year determined?

The current filename pattern does **not** include the year. The importer uses the email's `Date` header when it is parseable; otherwise, it falls back to the year of import. Historical database rows are backfilled using `documents.created_at` during migration. **A late or backdated email can therefore be assigned the wrong reporting year.** Administrators should review cross-year submissions, especially in December/January, and consider adding an explicitly validated year to a future filename format.

### Duplicate handling

The database enforces uniqueness for each Gmail message/attachment pair and, for a given corps member, document type, month and year. This reduces accidental duplicate imports. A document hidden using dashboard **Remove** remains in the database and will not be silently imported again just because it is no longer visible.

---

## Director dashboard guide

### Sign in

1. Open the configured UHS Director Assistant web address.
2. Select **Continue with Google**.
3. Choose the exact Google account authorized by `DIRECTOR_EMAIL`.
4. After verification, the private dashboard appears. Other Google accounts are rejected.

### Review one submission

1. Open **Dashboard** or **All pending documents**.
2. Find the record by state code, filename, month, year or sender.
3. Click **Review** to open the secure original-PDF preview.
4. Check the document contents and intended recipient.
5. Click **Approve, Sign & Send**, and explicitly confirm.
6. Check the result in the **Signed documents by month** archive.

The approval endpoint first checks that Gmail authorization is usable, then signs, stores, and attempts to send the document. If Gmail's outcome is uncertain, the UI/record indicates that the Director should inspect **Gmail Sent Mail** and the audit history before retrying.

### Approve several submissions

1. Confirm that the pending queue can be approved **without individual inspection**.
2. Click **Approve, Sign & Send All** and read the confirmation.
3. Keep the browser tab open while the batch runs.
4. Review its progress report and investigate failures before attempting any manual action.

> [!CAUTION]
> Bulk processing runs sequentially from the **browser**, using the existing per-document approval endpoint. It is **not** a durable background queue. Closing the tab, connectivity loss, or a hosting timeout can interrupt a batch. An uncertain send must **not** be blindly retried, to avoid emailing a duplicate document. The current UI caps pending fetches at 500 records and avoids treating a truncated list as a complete batch.

### Search and filter

The provided dashboard includes filters for document type, month (signed archive), year, and text search over state code, sender, or filename. A pending document's state is different from a signed document's delivery state.

### Remove a document from the dashboard

Select **Remove** beside the record and confirm. This marks `documents.deleted_at` and hides the record from ordinary dashboard lists.

**Remove does not permanently delete** the database row, audit history or retained signed PDF, and it does not clear previously confirmed clearance history. Documents in `sending` or `send_unknown` cannot be hidden until the mail outcome has been reconciled. The backend provides a Director-authenticated restore route, though the supplied UI does not yet contain a separate **Restore** button.

### Annual clearance history

Open **Annual clearance history**, select a year, and search by state code. Each row shows a corps member with a recorded completed clearance, and columns represent January through December.

- **✓** = a clearance was signed and Gmail returned a message ID for its email submission.
- **—** = no completed clearance is recorded for that month. It does **not** prove nonattendance, non-submission, or failure to clear.
- Payment approval records are **not** counted as monthly clearance.
- Hidden documents and discarded originals do not remove confirmed history.

---

## Architecture and technology

| Layer | Technology | Purpose |
| --- | --- | --- |
| Frontend | React, Vite, JavaScript/CSS | Director dashboard, preview, filters and approval actions |
| Frontend hosting | Vercel | Hosts the SPA and can proxy `/api/*` to the backend |
| API | Python, FastAPI | Authentication, document queries, approval, sending, and audit operations |
| API hosting | Render | Runs FastAPI and its Gmail synchronization task |
| Database | Supabase PostgreSQL, SQLAlchemy | Corps members, document metadata, sessions, OAuth credential references and audit history |
| Object storage | Private Supabase Storage buckets | Original PDFs, signed PDFs and protected signature asset |
| Identity | Google OpenID Connect via Authlib | Restricts dashboard access to the configured Director account |
| Mail | Gmail API / Google OAuth | Fetches attachments and emails signed PDFs |
| PDF processing | PyMuPDF (`fitz`) | Identifies signature fields and produces signed copies |
| Credential protection | Encrypted Gmail token storage in PostgreSQL | Preserves OAuth authorization across ephemeral backend restarts |

### Logical layout

```text
                  PRIVATE DIRECTOR WORKFLOW

   Corps members             Director (browser)
         |                         |
         v                         v
    Google Gmail            Vercel / React
         |                         |
         +------ Gmail API         | /api
                    |              v
                    +------> Render / FastAPI
                               |     |      \
                               |     |       +-- PDF signing service
                               |     |
                               v     v
                         PostgreSQL  Private Supabase Storage
                         (Supabase)  original-pdfs / signed-pdfs
                                        director-assets
```

### Storage principles

- `original_file_path` and `signed_file_path` contain **Supabase object keys**, not local filesystem paths or public download URLs.
- Only temporary working files may exist on the Render filesystem; it is not durable storage.
- PDFs should be served only through authenticated API endpoints with restrictive cache controls.
- The real signature image is read from the private `director-assets` bucket; it must never be exposed to public frontend code.

---

## Repository structure

This is the logical structure of the project, including the modules referenced by the supplied files. Some files may have different names or locations in the currently deployed repository.

```text
UHS-Corp-Member-Assistant/
├── backend/
│   ├── main.py                  # FastAPI application, OAuth, routes and lifespan
│   ├── models.py                # SQLAlchemy data models
│   ├── database.py              # PostgreSQL engine and session handling
│   ├── document_service.py      # Gmail PDF import and persistence
│   ├── document_classifier.py   # Recognized filename parsing
│   ├── gmail_service.py         # Gmail OAuth, retrieval and verification
│   ├── gmail_send_service.py    # Gmail signed-PDF sending
│   ├── gmail_sync_worker.py     # Periodic import loop
│   ├── gmail_token_store.py     # Encrypted Gmail token persistence
│   ├── signing_service.py       # Approval-controlled signing implementation
│   ├── storage_service.py       # Private Supabase Storage access
│   ├── cleanup_sent_originals.py # Optional retention maintenance
│   ├── requirements.txt         # Python dependencies (if present)
│   ├── .env                     # LOCAL ONLY: never commit
│   └── credentials.json         # LOCAL ONLY: Google OAuth client (when used)
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Dashboard, individual/bulk operations, history
│   │   ├── App.css              # Dashboard styling
│   │   └── ...                  # Vite entry point and other assets
│   ├── package.json
│   └── ...
├── supabase_migration.sql       # Four-feature database migration (where kept)
├── README.md
└── .gitignore
```

**Deployment note:** The four-feature update archive ships replacement `backend/main.py`, `backend/models.py`, `backend/document_service.py`, `backend/cleanup_sent_originals.py`, `frontend/src/App.jsx`, and `supabase_migration.sql`—not an entire standalone repository. Keep the already working supporting modules and deployment files.

---

## Database design

The backend uses SQLAlchemy models backed by PostgreSQL. The notable tables are:

| Table | Purpose | Important fields |
| --- | --- | --- |
| `corps_members` | One row per recognized corps member | `id`, `state_code`, `created_at` |
| `documents` | Submission identity, processing state and private PDF object keys | `corps_member_id`, `document_type`, `month`, `year`, `filename`, `sender_email`, `gmail_message_id`, `attachment_id`, `status`, `original_file_path`, `signed_file_path`, `deleted_at` |
| `document_audit_logs` | History of document actions | `document_id`, `action`, `actor`, `details`, `created_at` |
| `clearance_history` | Independent confirmation of completed clearance | `corps_member_id`, `month`, `year`, `cleared_at`, `document_id` |
| `auth_sessions` | Revocable authenticated Director browser sessions | `token_hash`, `email`, `expires_at`, `revoked_at` |
| `gmail_credentials` | Encrypted Gmail OAuth token data | `email`, `encrypted_token`, timestamps |

### Relationships and uniqueness

- `corps_members.state_code` is unique.
- `documents` has a uniqueness rule on `(gmail_message_id, attachment_id)` and another on `(corps_member_id, month, year, document_type)`.
- One `Document` can have multiple `DocumentAuditLog` rows.
- `clearance_history` has one record per `(corps_member_id, year, month)` and is independent of dashboard visibility.
- `clearance_history.document_id` is a reference value in the supplied model, not a cascading foreign key; history can survive when a PDF original is deleted.

### Document status meanings

| Status | Meaning | Recommended action |
| --- | --- | --- |
| `pending_review` | Imported but not approved | Review or explicitly include in approved batch |
| `signed` | Signed copy saved; email not yet confirmed | Check state; a Director-only send route exists for this state |
| `sending` | Send reserved/in progress | Do not initiate another send |
| `send_unknown` | Gmail result could not be confirmed | Reconcile **Gmail Sent Mail** before any retry |
| `sent` | Gmail API returned a message ID and the database recorded it | Signed copy retained, clearance history updated where applicable |

**Important distinction:** `sent` means **Gmail accepted the outgoing send request and returned an ID**; it is not proof the recipient received, opened, or read the email.

---

## API reference

All document and history endpoints below require an authenticated Director session. State-changing endpoints also check the browser `Origin` against configured allowed origins.

| Method | Endpoint | Function |
| --- | --- | --- |
| `GET` | `/` | Backend status message |
| `GET` | `/health` | Health check |
| `GET` | `/auth/login` | Begin Google sign-in |
| `GET` | `/auth/callback` | Handle Google OAuth callback |
| `GET` | `/auth/me` | Inspect authenticated session |
| `POST` | `/auth/logout` | Revoke current browser session |
| `GET` | `/documents/pending?limit=500` | Pending documents; maximum requested limit is 500 |
| `GET` | `/documents/signed?month=november` | Signed/sent archive; optional month filter |
| `GET` | `/documents/{id}` | Document metadata |
| `GET` | `/documents/{id}/pdf` | Authenticated original-PDF preview while retained |
| `GET` | `/documents/{id}/signed-pdf` | Authenticated signed-PDF preview |
| `POST` | `/documents/{id}/approve` | Explicit approval, signing and immediate email send |
| `POST` | `/documents/{id}/send` | Send an already-signed document after explicit Director action |
| `DELETE` | `/documents/{id}` | Soft-remove from dashboard |
| `POST` | `/documents/{id}/restore` | Restore hidden dashboard record (API-only in supplied UI) |
| `GET` | `/clearance-history/years` | Years with recorded clearances |
| `GET` | `/clearance-history?year=2026` | Annual state-code/month history matrix |

The FastAPI application may expose interactive OpenAPI documentation at `/docs`, depending on deployment configuration. **Do not treat API documentation as public access authorization**; endpoints still enforce authentication.

---

## Local development

### Prerequisites

- Windows 10/11, macOS or Linux development computer.
- A Python version compatible with your actual `requirements.txt` and dependencies (Python 3.10+ is a practical starting point; verify pinned versions).
- Node.js and npm compatible with the existing Vite project.
- A Supabase project with PostgreSQL and private Storage buckets.
- A Google Cloud project with the Gmail API enabled and an OAuth client.
- The Director's explicit authorization to connect the mailbox and use the signature asset.
- The application's supporting files (`database.py`, `gmail_service.py`, `gmail_token_store.py`, `storage_service.py`, etc.).

### 1. Clone the repository

```powershell
# From your development directory
 git clone https://github.com/damolagabriel58-sys/UHS-Corp-Member-Assistant.git
 cd UHS-Corp-Member-Assistant
```

For a private repository, authenticate with GitHub using an account that has access.

### 2. Set up the FastAPI backend (Windows PowerShell)

```powershell
cd backend
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If Python 3.10 isn't installed, use an installed and dependency-compatible interpreter (for example, `py -3.11`). Do not generate or replace `requirements.txt` with guessed dependencies; use the repository's actual requirements.

### 3. Configure backend environment

Create `backend/.env` locally. These are **placeholders**, not working credentials:

```dotenv
# Database / private Supabase access
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_PRIVATE_SERVICE_ROLE_KEY

# Authorized Director identity and Google OpenID Connect
DIRECTOR_EMAIL=director@example.com
GOOGLE_CLIENT_ID=YOUR_ACTIVE_OAUTH_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_ACTIVE_OAUTH_CLIENT_SECRET
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/callback
SESSION_SIGNING_KEY=REPLACE_WITH_A_CRYPTOGRAPHICALLY_RANDOM_SECRET_AT_LEAST_32_CHARS

# Frontend and browser security
FRONTEND_URL=http://127.0.0.1:5173
FRONTEND_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
COOKIE_SECURE=false
```

**Also configure** the Gmail token-encryption key and any storage-specific environment settings expected by your actual `gmail_token_store.py` and `storage_service.py`. Their exact variable names must be taken from those files; they are not present in the four-feature archive and therefore are not invented here.

Do not use your real Director's email, secrets, OAuth files, signature image, or sample corps members' PDFs in screenshots, documentation, commits or public issue reports.

Generate a strong random session key locally, for example:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 4. Apply database migration

Use the instructions under [Supabase setup and migration](#supabase-setup-and-migration) before running the updated API against an older schema.

### 5. Start the API

```powershell
# With backend virtual environment active, inside backend/
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Local health check: `http://127.0.0.1:8000/health`.

The supplied FastAPI lifespan starts the Gmail polling worker when the API starts. Without valid Gmail credentials it will log failures while the public health route may still work. Avoid running multiple independent sync workers against the same mailbox unintentionally.

### 6. Start the frontend (new PowerShell terminal)

```powershell
cd frontend
npm install
```

Create `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Then run:

```powershell
npm run dev
```

Open the local Vite URL, normally `http://localhost:5173`.

### 7. Validate local authentication

Your Google Cloud OAuth client's authorized redirect URI must match **exactly** the URL set in `GOOGLE_REDIRECT_URI`. `FRONTEND_ORIGINS` must include the browser origin. For local sign-in and cookie testing, avoid accidentally mixing `localhost` and `127.0.0.1` across the frontend/API OAuth configuration; choose a consistent setup.

---

## Google authentication and Gmail authorization

**There are two related but different Google OAuth flows.**

### Dashboard sign-in: Google OpenID Connect

`main.py` uses Authlib and the `openid email profile` scopes to confirm the user's Google identity. It validates the verified email claim and only permits the configured `DIRECTOR_EMAIL`. Successful login creates a database-backed, hashed, expiring session token and sets a protected browser cookie.

### Mailbox access: Gmail API authorization

`gmail_service.py` uses separate Gmail permissions for reading submitted attachments and sending signed PDFs, currently including:

```text
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.send
```

Gmail credentials are persisted in encrypted form via `gmail_token_store.py` and the `gmail_credentials` table, rather than relying on the temporary Render filesystem. Sign-in via `/auth/login` **does not itself guarantee** that mailbox synchronization has been reauthorized.

### First-time Gmail setup or Director handover

1. Ensure the Gmail API and appropriate OAuth client are configured in Google Cloud.
2. Configure the correct `DIRECTOR_EMAIL` in the backend environment.
3. Have the Director personally authorize the mailbox permissions through Google's consent screen using the provided local authorization flow.
4. Confirm the account returned by Gmail `users.getProfile` matches `DIRECTOR_EMAIL`.
5. Persist/migrate the token to the encrypted PostgreSQL credential store using the repository's established migration workflow (for example, `migrate_gmail_token.py` **if present**).
6. Test Gmail read and send separately, then perform a non-sensitive end-to-end PDF test.
7. Revoke existing web sessions and old mailbox authorizations when ownership changes.

Do **not** request the Director's Gmail password, email refresh tokens in plaintext, or store `credentials.json`/`token.json` in GitHub. On Render, Gmail authorization is intended to be noninteractive; it must be established securely before deployment.

### OAuth environment and verification considerations

If Google OAuth is in **Testing**, the Director may need to be an authorized test user, and some Gmail-related refresh tokens may have limited validity. Google Workspace administrators may also restrict access. Review the current Google Cloud OAuth consent/verification requirements for your account and scopes before depending on continuous production operation.

---

## Supabase setup and migration

### Private Storage buckets

Maintain three **private** Storage buckets:

| Bucket | Purpose | Retention |
| --- | --- | --- |
| `original-pdfs` | Original submitted documents while they await processing | Eligible objects removed **after confirmed send** |
| `signed-pdfs` | Signed output PDFs | Retained for authorized review and accountability |
| `director-assets` | Authentic Director signature image | Protected; should not be deleted by document cleanup |

The signing service looks for a signature asset named `director_signature.png`, `.jpg`, or `.jpeg` in the assets bucket. The exact object must match the supported code and actual form templates. All three buckets should remain private, with backend service-role access protected.

### Run the four-feature SQL migration

**Before deployment:**

1. Back up PostgreSQL and review storage backups/retention.
2. Temporarily pause Gmail import if possible, to avoid changing data during migration.
3. Open **Supabase → SQL Editor**.
4. Run the supplied `supabase_migration.sql` from the four-feature update package.
5. Verify the result, then deploy backend and frontend code.
6. Resume import and test a new sample PDF.

The SQL migration adds:

- `documents.year` and `documents.deleted_at`.
- A new uniqueness constraint containing the year.
- `clearance_history`, with one record per corps member/year/month.
- Backfill of older document years and already-`sent` clearances where qualifying records exist.

It **does not delete Storage buckets or signature assets**. Historical backfill uses database dates and may require data quality review.

> [!WARNING]
> `Base.metadata.create_all()` creates missing tables; it does **not** reliably alter existing tables or replace constraints. Apply reviewed schema migrations explicitly. Do **not** repeat blanket `DELETE FROM public.documents` or delete audit records in a production system merely to clear the dashboard—use the dashboard's **Remove** action, which preserves history and duplicate protection.

### Optional cleanup of older sent originals

After confirming all relevant signed PDFs are present, you may run the bundled maintenance script. It begins in **dry-run** mode:

```powershell
cd backend
python cleanup_sent_originals.py
```

To execute actual deletion after reviewing the output and backups:

```powershell
python cleanup_sent_originals.py --execute
```

It targets originals for records already marked `sent`, verifies the signed PDF before deletion, and does not delete buckets or the signature image. This is irreversible at the object level unless storage backups are available.

---

## Deployment

The intended setup is **Vercel for React**, **Render for FastAPI**, and **Supabase for PostgreSQL and private objects**.

### Render — backend

- Deploy `backend/` with the repository's actual Python dependencies and entry command (for example, `uvicorn main:app --host 0.0.0.0 --port $PORT`, adjusted to your Render service configuration).
- Set the documented environment variables in **Render → Environment**, never in committed `.env` files.
- Use `COOKIE_SECURE=true`, a strong `SESSION_SIGNING_KEY`, and HTTPS endpoints in production.
- Set `FRONTEND_URL` and `FRONTEND_ORIGINS` to the **exact** deployed frontend origin.
- Set `GOOGLE_REDIRECT_URI` to the exact callback URL used by the deployed OAuth flow.
- Ensure the Supabase service-role key and Gmail token-encryption secret are present and correct.
- Confirm only the intended process instance runs Gmail synchronization; the current worker is started with the FastAPI lifespan.

### Vercel — frontend

- Build the existing Vite frontend from `frontend/` using its configured `package.json` scripts.
- Set `VITE_API_BASE_URL=/api` **if** your deployed Vercel configuration proxies `/api` to Render.
- Keep or configure the matching Vercel rewrite for `/api/*` so browser API requests and the OAuth callback reach the correct Render endpoints.
- Use HTTPS. Verify that cookies work correctly after the Google login redirect.

For this project's previously used deployment naming, the intended production URLs were:

```text
Frontend: https://uhs-corp-member-assistant.vercel.app
Backend:  https://uhs-corp-member-assistant.onrender.com
```

These are **configuration examples based on the project setup**, not proof of currently active deployment. Confirm the actual URLs before documenting or handing them to the Director.

### OAuth callback consistency

A configuration using the Vercel `/api` proxy may use:

```dotenv
FRONTEND_URL=https://uhs-corp-member-assistant.vercel.app
FRONTEND_ORIGINS=https://uhs-corp-member-assistant.vercel.app
GOOGLE_REDIRECT_URI=https://uhs-corp-member-assistant.vercel.app/api/auth/callback
COOKIE_SECURE=true
```

The redirect URI must be registered **exactly** in the Google Cloud OAuth client's authorized redirect URIs. Do not switch between direct-Render and proxied-Vercel callback URLs without updating both Google Cloud and the backend configuration.

### Deployment order

```text
Backup → review and apply SQL migration → deploy backend → deploy frontend
       → check OAuth and Gmail → test sample PDF → restore normal intake
```

---

## Security and privacy

Because the application handles personal information and an authentic signature, treat it as **sensitive administrative infrastructure**.

### Implemented safeguards in the supplied code

- Google identity checks require the configured Director email, verified identity and subject identifier.
- Browser session tokens are random, **hashed in the database**, time-limited and revocable.
- Production cookies are configured `HttpOnly` and `Secure` when `COOKIE_SECURE=true`.
- State-changing actions verify an allowed origin.
- Private PDF endpoints serve data only after authentication, with `Cache-Control: private, no-store`.
- PDF file references are validated as private object keys, not arbitrary local paths.
- Approval and sending are Director-controlled; automatic Gmail intake cannot invoke those actions.
- Signature placement is restricted to recognized, blank Director fields in supported form layouts.
- Audit entries track relevant state transitions and cleanup actions.
- A Gmail network failure with an uncertain outcome is recorded instead of blindly retried.
- The signature asset and PDFs live in private storage rather than public frontend assets.

### Operational safeguards that still matter

1. Give only trusted maintainers access to Render, Supabase, Vercel, GitHub and Google Cloud.
2. Never expose the Supabase service-role key to React or any `VITE_*` variable.
3. Keep `backend/.env`, `.env.local`, `credentials.json`, `token.json`, signing images and PDF samples out of version control.
4. Rotate secrets and revoke old sessions/tokens after suspected compromise or account handover.
5. Review Gmail OAuth permissions regularly and remove authorizations that are no longer required.
6. Limit access to application logs: filenames, state codes, recipients and audit details may be sensitive.
7. Back up database and retained signed PDFs; test restoration.
8. Keep a written institutional retention and deletion policy before discarding records in production.
9. Restrict which form templates can be signed; a valid filename alone is not document authenticity verification.
10. Have an authorized person validate all signing coordinates and document layouts before operational use.

> [!CAUTION]
> Applying a stored signature image is an approval-controlled **image-stamping workflow**, not necessarily a certificate-backed cryptographic PDF digital signature. If institutional policy requires cryptographic signing, nonrepudiation or specific statutory retention, obtain appropriate review and implement those controls separately.

---

## Document lifecycle and retention

| Lifecycle step | Database state | Original PDF | Signed PDF | Clearance history |
| --- | --- | --- | --- | --- |
| Newly imported | `pending_review` | Private, retained | Not present | No change |
| Approved and signed | `signed` | Retained | Private, retained | No change |
| Gmail request reserved | `sending` | Retained | Retained | No change |
| Gmail result uncertain | `send_unknown` | Retained | Retained | No new confirmation |
| Gmail confirms message ID | `sent` | Cleanup attempted | Retained | Clearance only: recorded |
| Director clicks Remove | `deleted_at` populated | Depends on lifecycle | Retained where applicable | Preserved |

### Handling uncertainty

If the application times out after submitting an email, Gmail might have accepted the request. The system keeps `send_unknown` to prevent an automatic second email. **Check Gmail Sent Mail and the corresponding record before taking another action.** A manually reconciled resolution process may still require administrative intervention.

### Deletion is not one operation

- **Remove from dashboard:** Soft delete of visibility (`deleted_at`); does **not** delete signed files or audit records.
- **Discard original after confirmed send:** Delete one object in `original-pdfs` while keeping the signed record.
- **Permanent purge:** A separate, exceptional, policy-governed administrative operation; not the default dashboard behavior.
- **Deleting a bucket:** Not performed by document removal or the database migration.

### Database vs. object storage

Deleting database rows is **not the same** as deleting objects in Supabase Storage. Conversely, deleting PDF objects in Storage does not automatically remove their database rows. Avoid direct `storage.objects` manipulation via SQL; use authorized Storage operations.

---

## Testing checklist

Use **fictional, non-sensitive test records and a test PDF**; do not rely on real corps members' personal information during initial testing.

### Authentication

- [ ] Health check works.
- [ ] Director's configured Google account can log in.
- [ ] An unauthorized Google account is rejected.
- [ ] Logout revokes the current session.
- [ ] Previously revoked sessions cannot access documents.

### Gmail import

- [ ] Recognized clearance PDF imports once.
- [ ] Recognized payment approval PDF imports once.
- [ ] Unsupported filenames are skipped.
- [ ] Duplicate attachments do not reappear as new documents.
- [ ] State code, month and year match the intended record.
- [ ] Submitted PDFs are stored privately and preview successfully.

### Signing and sending

- [ ] Clearance signature appears below “Yours faithfully”; small date appears **beneath** the signature.
- [ ] Payment approval signature is placed in the Director's field, not another signatory's line.
- [ ] Signing is blocked for unrecognized or occupied signature fields.
- [ ] No email or signature is produced from import alone.
- [ ] **Approve, Sign & Send** sends the signed PDF to the expected original sender.
- [ ] A successful signed document is accessible from the private archive.
- [ ] Original cleanup happens only after confirmation; signed PDF remains.
- [ ] Simulated ambiguous Gmail errors do **not** cause blind retries.

### Bulk operation and dashboard

- [ ] Bulk approval shows a clear confirmation and the correct document count.
- [ ] Batch progress and partial failures are visible.
- [ ] Browser refresh/premature closure is treated as an interruption, not completion.
- [ ] The five-minute UI refresh and manual Refresh both work.
- [ ] Search and year/month/document-type filters work.
- [ ] Remove hides the document without destroying audit/history.
- [ ] Restore API returns an intentionally hidden record when authorized.

### Annual clearance history

- [ ] Sent clearance marks the correct state code, year and month.
- [ ] Payment approval does not mark clearance.
- [ ] Pending or signed-but-unsent clearance does not mark completion.
- [ ] Removing a document from dashboard does not erase recorded clearance.
- [ ] December-to-January submissions are assigned/verified with the correct year.

---

## Troubleshooting

| Symptom | Likely causes | First checks |
| --- | --- | --- |
| Cannot sign in | Wrong `DIRECTOR_EMAIL`, unverified/test-user restrictions, wrong OAuth redirect URI, bad cookies | Render variables, Google Cloud OAuth audience and callback URI |
| Login works, Gmail doesn't sync | Missing/expired/revoked Gmail refresh token, wrong mailbox, OAuth client deleted | Backend worker logs, Gmail token store and `verify_director_gmail()` |
| Dashboard has no new PDFs | Worker unavailable, invalid filename, not a PDF attachment, duplicate record, importer failure | Gmail query, Render logs, `documents` table and private Storage |
| `502 Private PDF could not be retrieved` | Missing original object, wrong bucket/key, incorrect Supabase credentials | Check `documents.original_file_path`, `original-pdfs` objects and backend traceback |
| Original preview fails for a sent document | Original was intentionally discarded after sending | Open the **signed-PDF** archive instead |
| Signature field not found | PDF layout/text differs from supported template or target area is occupied | Compare the template against signing-service anchors; do not force coordinates blindly |
| Signed PDF exists but mail wasn't confirmed | Gmail API/network error, revoked scopes or uncertain send | Inspect signed archive, `send_unknown`, Gmail Sent Mail and audit logs |
| Removed PDF reappears | Older code performed hard delete or importer deduplication is broken | Confirm `deleted_at` soft removal and uniqueness constraints |
| Year is wrong | Header date/import fallback doesn't match reporting year | Inspect email date, imported metadata and reporting period |
| Clearance table shows a dash | No **confirmed sent** clearance for that member/month/year | Inspect document status and Gmail confirmation, not just receipt |
| SQLAlchemy error: missing `year`/`deleted_at`/history table | New code deployed before migration | Apply/review `supabase_migration.sql` against the correct project |
| `403 Request origin is not authorized` | Frontend origin missing or mismatched in `FRONTEND_ORIGINS` | Compare the browser's actual `Origin` with configured HTTPS origin |
| Changes pushed but not visible | Vercel/Render deployment error, wrong branch/root directory, stale frontend build | Verify deployment status and logs; hard refresh the browser |

### Logging and diagnostics

- **Render logs:** API startup, database errors, Gmail import/send exceptions, PDF download errors and background worker health.
- **Vercel logs/build output:** Frontend build and proxy/rewrite failures.
- **Supabase SQL Editor:** Record counts, document states and clearance history.
- **Supabase Storage UI:** Whether expected private objects exist; do not expose the signature publicly for debugging.
- **Gmail Sent Mail:** Critical for resolving `send_unknown` before any manual retry.

Useful **read-only** SQL checks:

```sql
SELECT status, COUNT(*)
FROM public.documents
GROUP BY status
ORDER BY status;

SELECT year, COUNT(*)
FROM public.clearance_history
GROUP BY year
ORDER BY year DESC;

SELECT COUNT(*) AS dashboard_visible
FROM public.documents
WHERE deleted_at IS NULL;
```

These queries do not delete records, objects or buckets.

---

## Operations and maintenance

### Daily / routine

- Check that new valid PDF emails appear as pending submissions.
- Monitor failed Gmail syncs and investigate `send_unknown` before retrying.
- Confirm the Director is using the intended Google account.
- Review clearance tracking anomalies and incorrectly assigned years.

### After deployment or configuration changes

- Test login, PDF preview, one individual approval, signing, sending and archive access.
- Test a single-record removal and annual history persistence.
- Verify bucket privacy and Gmail account matching.
- Check the frontend `/api` proxy and cookie path after domain changes.

### Changing the Director's Google account

Changing `DIRECTOR_EMAIL` in Render restricts who can authenticate; it **does not automatically transfer Gmail mailbox authorization**. The replacement Director must explicitly authorize Gmail read/send access, and the encrypted credential store must be updated securely. Revoke old sessions and credentials as appropriate. Retain the original authenticated signature image only if its use remains authorized by the relevant Director.

### Backups and incident response

- Keep recoverable backups of PostgreSQL and retained signed PDFs.
- Document who can restore backups and who can approve irreversible deletion.
- Record secret rotations, OAuth app changes, reauthorization events and deployments.
- If a signature asset or service-role credential may be exposed, immediately restrict access, rotate affected credentials, suspend signing if needed, and investigate audit records.

---

## Known limitations and future improvements

The following distinctions prevent the README from overstating the system:

1. **Browser-driven bulk approval:** The current batch is not a durable server-side queue; a job table, progress endpoint and resumable execution would be more reliable at scale.
2. **Year inference:** Reporting year comes from date metadata/fallback, not a year explicitly required in the filename.
3. **Email acknowledgment:** A Gmail message ID indicates API acceptance, not recipient delivery or reading.
4. **Single Director authorization:** There is no described multi-role staff approval, delegation or institutional SSO integration.
5. **Template-aware image stamping:** It is not generalized signing for arbitrary PDFs or certificate-backed digital-signature infrastructure.
6. **Dashboard removal:** It is soft removal; a restore UI and separately authorized permanent-purge policy could be added later.
7. **Clearance history population:** The history endpoint lists corps members who have **recorded completed clearances**, not necessarily every corps member ever seen in the database.
8. **Import/polling architecture:** The provided worker is started in FastAPI lifespan. Multiple backend workers/replicas may initiate overlapping polls; a dedicated scheduler with distributed locking would be safer.
9. **Database migrations:** Schema changes require explicit, reviewed SQL migrations; `create_all` alone is insufficient.
10. **Validation:** Offline syntax/model checks are not equivalent to Gmail, Google OAuth, Supabase and production hosting integration tests.

Suggested future enhancements include explicit year in submitted filename, email submission acknowledgments, a durable bulk-processing queue, a read-only reconciliation screen for uncertain sends, automated integration tests, configurable retention periods, and export of annual clearance reports.

---

## Project handover

Before the Director uses the system with live documents, complete this handover checklist:

- [ ] Replace the developer's login allowlist with the Director's authorized email.
- [ ] Reauthorize Gmail using the **Director's** account and required scopes.
- [ ] Verify that the private signature asset belongs to the authorized signatory and is correctly placed.
- [ ] Confirm the Google OAuth callback, Vercel proxy, Render backend and Supabase project are all connected.
- [ ] Confirm backups, bucket privacy, secret handling and retention procedures.
- [ ] Demonstrate one real-format **test** clearance and payment approval document.
- [ ] Show individual review, explicit bulk approval, archive retrieval, dashboard removal and annual clearance history.
- [ ] Show how to identify `send_unknown` and check Sent Mail before any retry.
- [ ] Explain that **Remove** does not permanently erase records, and that originals are discarded only after confirmed sending.
- [ ] Document an administrator/maintainer contact and a procedure for revoking access or reporting unexpected behavior.

### One-minute operational summary

**Corps member sends a properly named PDF → Gmail imports the PDF → Director reviews or explicitly approves a batch → the system signs and emails the approved document → the signed PDF and audit record are retained → confirmed monthly clearance is reflected in the annual state-code history.**

---

## License and attribution

**Project:** UHS Director Assistant / UHS Corps Member Assistant  
**Repository:** `damolagabriel58-sys/UHS-Corp-Member-Assistant` (private access may be required)  
**Documentation version:** 28 October 2026

This README does **not** grant an open-source license. Unless a separate `LICENSE` file and rights-holder authorization say otherwise, treat the code, administrative records, forms, and signature assets as private and do not redistribute them. Google, Supabase, Vercel, Render, FastAPI, React and other third-party products remain subject to their respective terms and licenses.

---

<div align="center">

**UHS Director Assistant**  
*An efficient document workflow with approval firmly under the Director's control.*

</div>
