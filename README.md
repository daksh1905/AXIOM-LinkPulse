<div align="center">

# 🔗 LinkPulse

### **Shorten. Share. Measure. Manage.**

*A unified platform for smart URL management, QR sharing, click insights, and administrative control.*

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/Database-PostgreSQL%20%7C%20SQLite-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Deployment](https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render&logoColor=black)](https://render.com/)

**[🌐 Open Live Demo](https://linkpulse-lesk.onrender.com/) · [GitHub Repository](https://github.com/daksh1905/AXIOM-LinkPulse) · [Judge Evaluation](#-judge-evaluation-checklist)**

</div>

> 🚧 **Prototype status:** LinkPulse is a student/hackathon project. The features below describe the intended implementation and should be verified against the deployed build. The project has not been represented as independently security-audited or production-certified.

---

## 🧭 Contents

- [✨ Overview](#-overview)
- [🎯 Problem & Solution](#-problem)
- [🚀 Key Features](#-core-capabilities)
- [🏗️ Architecture](#-technical-architecture)
- [🧰 Technology Stack](#-technology-stack)
- [📁 Repository Structure](#-repository-layout)
- [⚙️ Configuration](#-configuration-reference)
- [💻 Run Locally](#-local-verification)
- [☁️ Deployment](#-deployment-outline-render)
- [🧪 Judge Evaluation](#-judge-evaluation-checklist)
- [🔐 Limitations & Responsible Use](#-limitations-and-responsible-use)

## ✨ Overview

**LinkPulse** is a web application prototype that brings short-link creation, configurable access rules, QR-code generation, click analytics, account-based link management, and administrator controls into one platform.

### At a glance

| | Details |
|---|---|
| **Project category** | Web application · URL management & analytics |
| **Backend** | Python, Flask, SQLAlchemy |
| **Frontend** | HTML, CSS, JavaScript |
| **Data storage** | SQLite locally; PostgreSQL supported through `DATABASE_URL` |
| **Email OTP delivery** | Brevo transactional email API over HTTPS |
| **Deployment target** | Render |
| **Source code** | [AXIOM-LinkPulse on GitHub](https://github.com/daksh1905/AXIOM-LinkPulse) |

## 🌐 Live Demo

> **Public demo:** [https://linkpulse-lesk.onrender.com/](https://linkpulse-lesk.onrender.com/)
>
> Open the live LinkPulse application using the link above. Test the public URL from a separate browser or device before submission.

## 🎯 Problem

- **Project name:** LinkPulse
- **Category:** Web application / URL management and analytics
- **Backend:** Python, Flask, SQLAlchemy
- **Frontend:** HTML, CSS, JavaScript (`static/index.html`, `static/admin.html`)
- **Database:** SQLite for local development; PostgreSQL supported through `DATABASE_URL`
- **Email OTP:** Brevo transactional email API over HTTPS
- **Hosting target:** Render
- **GitHub repository:** https://github.com/daksh1905/AXIOM-LinkPulse
- **Live demo:** [https://linkpulse-lesk.onrender.com/](https://linkpulse-lesk.onrender.com/)

## Problem

Long URLs are inconvenient to share, difficult to organize, and provide little visibility into how links are used. QR-code creation, access restrictions, usage analytics, and administrative review may otherwise require separate tools. LinkPulse brings these tasks into one workflow.

## 💡 Proposed Solution

LinkPulse combines the lifecycle of a shareable link in one interface: create a short link, optionally configure its behavior, distribute it directly or as a QR code, review recorded activity, and manage or disable links when needed. Account and administrative workflows separate ordinary link management from platform-level controls.

The goal is to simplify link sharing and provide useful usage signals without presenting those signals as verified identities or perfect bot detection.

## 🚀 Core Capabilities

### 🔗 1. Short-link creation and lifecycle controls
- Generate short URLs for destination URLs.
- Support custom aliases subject to validation and uniqueness checks.
- Configure optional titles, password protection, click limits, and expiration.
- Enable/disable links and handle links that are expired, inactive, password-protected, or over their click limit.
- Apply configured blocked-domain checks to link creation.

### 👤 2. Accounts and ownership
- Account registration and sign-in using email and password.
- Email OTP verification workflow.
- Passwords are intended to be stored as password hashes rather than plaintext.
- Account-owned link management and administrator-specific access paths.
- Privileged operations are intended to be enforced by backend authorization checks.

### 📱 3. QR-code design
- Generate QR codes for shareable links.
- Customize QR appearance using the options available in the interface.
- Download QR output for digital or printed materials.

### 📊 4. Click analytics
The analytics workflow records click events and can report:
- Recorded click totals and recent event timestamps.
- Device-category and browser-family estimates from user-agent information.
- Referrer information when provided by the client.
- Heuristic bot classification and likely-human event summaries.

These are best-effort indicators. User-agent classification can be inaccurate, referrer information can be absent, and analytics do not establish a clicker's real-world identity.

### 📥 5. Bulk CSV import
Bulk link creation accepts CSV input within the application's configured limits. The expected URL column is `original_url`; optional columns include `title` and `custom_alias`.

Example:

```csv
original_url,title,custom_alias
https://example.com/page,Launch page,launch-page
https://example.org/news,News link,
```

Invalid rows should be reviewed in the import result rather than assumed to have succeeded.

### 🛡️ 6. Administrative governance
The admin interface supports platform-level link and account review, link enable/disable or deletion controls, and management of blocked-domain rules. Administrative access should be enforced by the backend, not by hiding controls in the browser alone.

### 🏷️ 7. Campaigns and tags
The project scope includes organizing links with campaign/tag-style metadata where those controls are available in the current interface. Judges should verify the deployed UI and API behavior for these features during evaluation.

## 🏗️ Technical Architecture

```text
Browser
  ├── static/index.html  — main user interface
  └── static/admin.html  — administrative interface
             │ HTTP requests
             ▼
       Flask application
       ├── account / OTP routes
       ├── link creation and redirects
       ├── QR and analytics routes
       ├── CSV import
       └── admin / blocklist routes
             │ SQLAlchemy
             ▼
       Database configured by DATABASE_URL
       ├── users
       ├── email_otp_verifications
       ├── links
       ├── click_events
       └── blocked_domains

Flask backend ── HTTPS ──► Brevo transactional email API
```

### Database model overview

| Table | Responsibility |
|---|---|
| `users` | Account and authentication-related data |
| `email_otp_verifications` | Email OTP verification records |
| `links` | Short-link destinations, settings, ownership and status |
| `click_events` | Recorded redirect/click activity used by analytics |
| `blocked_domains` | Administrator-managed domain restrictions |

SQLAlchemy's `Base.metadata.create_all()` creates missing tables. The backend also contains targeted compatibility migrations for selected columns; this is not a full versioned migration system for arbitrary future schema changes.

## 🧰 Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Web framework | Flask |
| Database ORM | SQLAlchemy |
| Local database | SQLite |
| Hosted database option | PostgreSQL |
| PostgreSQL driver | Psycopg 3 |
| Email OTP delivery | Brevo API over HTTPS |
| User-agent parsing | `user-agents` |
| Production WSGI server | Gunicorn |
| Deployment target | Render |

## 📁 Repository Layout

```text
AXIOM-LinkPulse/
├── backend.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
└── static/
    ├── index.html
    └── admin.html
```

A local `links.db` may be created when SQLite is used. Environment files and local database files should remain out of version control.

## ⚙️ Configuration Reference

Copy `.env.example` to `.env` for local development and supply private values. For hosted deployment, configure values in the hosting provider's environment-variable dashboard rather than committing `.env`.

| Variable | Purpose |
|---|---|
| `FLASK_SECRET_KEY` | Signs Flask session data; use a long random secret |
| `ADMIN_MASTER_KEY` | Administrator access key used by the backend's admin flow |
| `ADMIN_LOGIN_EMAIL` | Administrator login identifier used by the homepage flow |
| `ADMIN_LOGIN_PASSWORD` | Administrator login password |
| `APP_ENV` | Environment mode; use `production` for hosted deployment when supported by the backend |
| `HOST` | Bind address; hosted services commonly require `0.0.0.0` |
| `PORT` | Local/server port setting where applicable |
| `DATABASE_URL` | Optional SQLAlchemy database URL; omit locally to use the SQLite default |
| `BREVO_API_KEY` | Private Brevo API key for transactional email |
| `MAIL_FROM_EMAIL` | Sender address verified in Brevo |
| `MAIL_FROM_NAME` | Display name for transactional email |

**Secret handling:** `.env` must never be committed. Do not put private keys or administrator credentials in frontend JavaScript, screenshots, issue reports, or this README. Rotate any credential that is exposed.

## 💻 Local Verification

This section supports reproducibility and technical evaluation; it is not a substitute for testing the deployed build.

1. Install a compatible Python version and create a virtual environment.
2. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set private local values. For OTP tests, configure a valid Brevo API key and a sender address verified in Brevo.
4. Leave `DATABASE_URL` unset to use local SQLite, or configure a PostgreSQL URL for a test database.
5. Start the application:

   ```bash
   python backend.py
   ```

6. Open the local address printed by the application. The current configuration normally uses port `8000`.

Use test URLs and test accounts, not real customer data or production credentials.

## ☁️ Deployment Outline (Render)

1. Connect the GitHub repository to a Render Web Service.
2. Build command:

   ```bash
   pip install -r requirements.txt
   ```

3. Start command:

   ```bash
   gunicorn backend:app
   ```

4. Configure the environment variables listed above in Render.
5. If using Render PostgreSQL, configure `DATABASE_URL` with the connection URL appropriate for the service's network location. Prefer the provider's internal URL when the web service and database are in the same region.
6. Confirm production mode, HTTPS, session-cookie settings, email delivery, database access, and application routes.
7. Test the public URL from a separate browser or device.

Free hosting plans may sleep, impose resource limits, or provide ephemeral local filesystems. Use managed PostgreSQL for hosted persistence rather than relying on a local SQLite file on an ephemeral web-service filesystem. Review current hosting limits and database lifecycle policies before a live demonstration.

## 🧪 Judge Evaluation Checklist

The following test plan helps evaluate the prototype without assuming a feature works merely because it is listed.

| Test | Suggested evaluation |
|---|---|
| Registration and OTP | Register with a test mailbox and verify the OTP workflow |
| Authentication | Sign in and sign out; test invalid credentials |
| Short-link creation | Create a short link and follow it to the expected destination |
| Alias validation | Try a valid alias, a duplicate alias, and an invalid alias |
| Password protection | Open a protected link with and without the correct password |
| Expiration and click limit | Test links configured with short expiry/click limits |
| QR generation | Generate, customize, download, and scan a QR code |
| Analytics | Visit a test link and inspect recorded event information |
| Ownership | Check that one ordinary account cannot manage another account's links |
| Admin governance | Review links/accounts and test enable/disable controls |
| Blocklist | Add a test domain, verify expected handling, then remove the rule |
| CSV import | Import valid and invalid rows and inspect the result |
| Persistence | Create a test record, restart/redeploy as appropriate, and verify persistence |
| Secrets | Confirm `.env`, API keys, database credentials, and local DB files are not committed |

Use test URLs and test accounts. Do not test security controls against third-party systems without authorization.

## 🔐 Limitations and Responsible Use

- This is a prototype and has not been presented as independently security-audited or production-certified.
- Analytics and bot classification are heuristic and can be incomplete or incorrect.
- Referrer data may be absent, and click events do not verify a person's identity.
- OTP delivery depends on correct Brevo configuration, a verified sender, network access, and provider availability.
- In-process throttling is not shared across multiple application workers. A multi-worker deployment may require a shared rate-limit store.
- Targeted schema checks cover selected legacy columns only. More complex future changes should use a versioned migration tool.
- Deployment reliability depends on hosting-plan limits, database lifecycle, and configuration.
- Any campaign/tag or advanced feature should be demonstrated in the actual deployed build rather than inferred from this overview.

## 🏁 Project Summary

LinkPulse demonstrates how URL shortening can be combined with access rules, QR-code sharing, event-based analytics, account ownership, and administrative governance in one Flask application. Evaluation should focus on **end-to-end behavior**, **clear technical design**, and a **transparent discussion of limitations**.

---

<div align="center">

**Built as a student project · Designed for clearer, more manageable link sharing**

</div>
