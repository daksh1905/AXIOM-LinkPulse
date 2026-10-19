# LinkPulse — Smart URL Shortener & Link Analytics

**LinkPulse** is a web-based URL-shortening platform designed to make links easier to share, manage, and measure. It combines short-link creation, customizable QR codes, click analytics, account-based link management, and administrative safety controls in one interface.

> **Project status:** Student/hackathon prototype. Features should be tested in the deployment environment before being described as production-ready.

## Project Links

- **Live demo:** `ADD_YOUR_DEPLOYED_URL_HERE`
- **Public GitHub repository:** `ADD_YOUR_GITHUB_REPOSITORY_URL_HERE`
- **Problem statement:** URL Shortener & Analytics Platform

Replace the placeholders above after deployment. Do not submit a localhost URL as the live demo.

## Problem Statement

Long URLs are difficult to share, organize, and track. Teams also need a simple way to see whether their links are being used and to disable links that should no longer be active. LinkPulse brings link creation, redirection, QR-code generation, basic analytics, and link administration into one workflow.

## Proposed Solution

LinkPulse lets visitors create and share shortened URLs, customize QR codes, and inspect recorded link activity. Registered users can manage their own links, while administrators can review platform links and accounts, pause or resume links, delete links, and maintain a blocked-domain list.

## Key Features

### Short-link creation and redirection
- Generate short links for destination URLs.
- Support custom aliases, subject to validation and uniqueness rules.
- Optionally set a link title, password protection, click limit, and expiration.
- Validate link requests and apply the configured blocked-domain rules.
- Pause, resume, or delete links through the available controls.

### QR Design Studio
- Create QR codes for links.
- Customize QR appearance using the options available in the interface.
- Download the generated QR code for sharing.

### Accounts and ownership
- Register and sign in with an email address and password.
- Store account passwords as salted PBKDF2 hashes rather than plaintext.
- Keep account-owned link management tied to the signed-in user.
- Preserve the anonymous/browser-owned link workflow; anonymous links can be associated with an account when the same browser is used to register or sign in.
- Provide an administrator login path from the homepage that redirects a valid administrator to the admin console.

**Email verification and social sign-in (Google/Facebook) are not currently implemented.** An email entered in the current form is not proof that the person controls that mailbox.

### Link analytics
Analytics are available from the existing links panel and can include:
- Recorded redirect/click totals.
- Likely-human events and detected bot events.
- Recent event timestamps.
- Device and browser-family estimates.
- Referrer host, when the browser provides it.

Analytics are best-effort indicators. Bot detection is heuristic, referrer data can be unavailable, and these metrics do not establish the identity of a person who clicked a link.

### Governance Studio (admin)
- View registered accounts and their link counts.
- Review the platform's links.
- Pause/resume or delete links using administrator controls.
- Add or remove blocked-domain rules.
- Use administrator-only endpoints protected by the backend's authorization checks.

### CSV import
- Import multiple links from a CSV file (up to the application's configured limits).
- Required column: `original_url`.
- Optional columns: `title`, `custom_alias`.
- Invalid rows are reported rather than silently treated as successful imports.

Example CSV:

```csv
original_url,title,custom_alias
https://example.com/page,Launch page,launch-page
https://example.org/news,News link,
```

## Technology Stack

- **Backend:** Python, Flask
- **Database:** SQLite
- **Database access:** SQLAlchemy
- **Frontend:** HTML, CSS, JavaScript
- **Configuration:** environment variables with `python-dotenv` for local development
- **User-agent parsing:** `user-agents`
- **Hosting:** deployable to a Python web-service host such as Render

## Project Structure

```text
LinkPulse/
├── backend.py
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example
└── static/
    ├── index.html
    └── admin.html
```

The application creates or migrates its SQLite tables when the backend starts. Back up an existing database before replacing project files or restarting after database changes.

## Run Locally

### Requirements
- Python 3.10 or a compatible Python version supported by the installed dependencies.
- `pip`.

### Setup

1. Clone the repository and enter the project directory.

   ```bash
   git clone ADD_YOUR_GITHUB_REPOSITORY_URL_HERE
   cd LinkPulse
   ```

2. (Recommended) Create and activate a virtual environment.

   ```bash
   python -m venv .venv
   ```

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies.

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and replace every placeholder with a private value. Never commit `.env`.

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   macOS/Linux:

   ```bash
   cp .env.example .env
   ```

5. Start the server.

   ```bash
   python backend.py
   ```

6. Open the local address printed by the application (the current project configuration normally uses `http://127.0.0.1:8000`). A localhost address is only accessible from your own computer; judges need the deployed public URL.

## Environment Variables and Secrets

Use `.env.example` to document the variable names and placeholder values required by the backend. Keep the actual `.env` file private and excluded by `.gitignore`.

For deployment, enter each required variable and its real value in the hosting provider's **Environment Variables** settings. Do not upload `.env` to GitHub or paste secret values into this README. Check `backend.py` and `.env.example` for the exact variable names used by this version.

Administrator credentials and secret keys must remain server-side. Do not embed private administrator keys or passwords in frontend JavaScript.

## Deployment Notes (Render example)

1. Push the project to a **public GitHub repository** if required by the event.
2. Create a Python Web Service in Render and connect the repository.
3. Set the build command to:

   ```bash
   pip install -r requirements.txt
   ```

4. If the backend file is `backend.py` and the Flask object is named `app`, set the start command to:

   ```bash
   gunicorn backend:app
   ```

5. Add the required environment variables in Render's service settings.
6. Deploy, open the public URL, and test the main flows.

Free web-service filesystems may be temporary. Because this project uses SQLite, do not assume a database stored on the service's local filesystem will survive restarts, redeployments, or sleep/wake cycles. Configure supported persistent storage or use a suitable managed database before relying on long-term data retention. Check the host's current pricing and limits before deployment.

## Security, Privacy, and Known Limitations

- The current registration flow does **not** verify that a user owns the email address they enter; email verification is not implemented.
- Google/Facebook sign-in, password-reset email, and multi-factor authentication are not implemented.
- Analytics do not provide verified geographic location or reliable unique-person counts. The application does not store clicker IP addresses in the described analytics flow.
- Bot/human classification is heuristic and may be wrong.
- Device-specific destination targeting and full campaign/tag/workspace management are not implemented in this prototype.
- Anonymous link ownership relies on a browser identifier; clearing browser storage may make those anonymous links difficult to manage from that browser.
- SQLite is suitable for a lightweight prototype, but deployment storage and concurrency requirements should be reviewed before production use.
- Do not claim the project is bug-free or production-ready until it has been tested on the actual deployment.

## Pre-submission / Demo Checklist

- [ ] The live public URL opens from a different device or browser.
- [ ] A user can register, sign in, and sign out.
- [ ] The administrator can sign in and reach Governance Studio.
- [ ] A user can create a short link and follow it to the intended destination.
- [ ] Custom alias validation, expiry, password protection, and click limits are tested where enabled.
- [ ] QR generation, customization, and download work.
- [ ] The links panel displays analytics for a test link.
- [ ] User-owned links cannot be managed by another ordinary user.
- [ ] Pause/resume/delete controls behave correctly.
- [ ] Blocked-domain rules are tested and can be removed again.
- [ ] CSV import is tested with both valid and invalid rows.
- [ ] Database persistence is tested after a restart/redeploy, or the limitation is clearly understood.
- [ ] `.env` and local database files are not committed to GitHub.
- [ ] README live URL, repository URL, and screenshots are updated before submission.

## Acknowledgement

Built as a student/hackathon prototype to demonstrate URL shortening, link management, QR-code customization, basic analytics, and administrative governance in one web application.
