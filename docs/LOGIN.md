Authentication & session handling (summary)
=========================================

This project includes automation for Microsoft SSO (MsSsoAuth) plus a simple
manual-login fallback and session persistence so you can avoid re-authenticating
on every run.

Quick overview
--------------
- Automated login on redirect: when the app redirects to a Microsoft-hosted
  login page (e.g. login.microsoftonline.com), `MsSsoAuth` will fill `email`,
  click `next`, fill `password`, and click `sign-in` if the credentials were
  supplied to the scraper.
- Trigger from the app page: if the base app page exposes a "Sign in with
  Microsoft" control, the scraper will try to click that control to start the
  redirect (selector configurable).
- Manual login support: if no valid session exists, the scraper waits up to the
  configured auth timeout (`session.auth_timeout_s`) for a human to complete
  login in a visible browser. To do this, run with `headless: false` for that
  run (see note below).
- Session persistence: after a successful login the browser storage state is
  saved (if `session.save_on_success` is true). Subsequent runs will reuse that
  storage state when `session.reuse` is true.

Important config keys
---------------------
- `selectors.ms_app_signin` — (optional) selector on the app page to click to
  trigger Microsoft redirect. If absent, the scraper will wait for a redirect
  to the Microsoft host.
- `selectors.ms_email`, `selectors.ms_next`, `selectors.ms_password`,
  `selectors.ms_signin` — selector candidate sets used to locate the MS form
  fields and submit buttons. These must be present for automated MS fill.
- `selectors.ms_redirect_wait_s` — optional short wait (seconds) to allow the
  redirect to reach the Microsoft page after clicking the app sign-in control
  (default: min(auth timeout, 8s)).
- `session.auth_timeout_s` — how long to wait for login to complete (manual or
  automated). The production config uses 600s by default.
- `session.reuse` and `session.save_on_success` — control loading and saving the
  stored session state.
- `headless` (top-level) — set to `false` for runs where you must interact
  manually (e.g., to complete MFA on first-run).

Where the session file is written
---------------------------------
By default the session file is written to:

  ~/.scraper/sessions/<site_host>/<user>.json

This can be overridden by setting `session.path` in the config to an absolute
path.

Manual first-run guidance
-------------------------
1. Edit your production config (for example `config-aker-weld-manager.json`) and
   set `headless: false` for the run that will complete the manual login.
2. Ensure `session.auth_timeout_s` is large enough to finish any interactive
   login (MFA may require several minutes). The production config uses 600s.
3. Run the scraper (CLI or web API). When you complete login in the opened
   browser, the scraper will detect the post-login condition and save the
   session state.
4. For future runs you can set `headless: true` and the saved session will be
   reused automatically.

Testing locally (deterministic harness)
---------------------------------------
There is a small local test-site that emulates the app -> Microsoft -> success
flow. To run the harness (Playwright required):

  pip install playwright
  playwright install
  python test_harness/run_test.py

This starts a temporary HTTP server serving `test-site/` and runs the fake SSO
flow end-to-end; it's useful for validating selectors and the redirect logic
without using the company site or real credentials.

Notes & caveats
---------------
- MFA and non-standard SSO flows: if your organization uses MFA, device codes,
  or pop-up windows, full automated login may not complete. Use a manual headed
  first run to capture session state or extend the auth strategy to handle the
  special flow (for example, detect new pages or use device-code auth).
- Popups/new pages: current automation targets the same `Page` object; if the
  real SSO opens a separate window/tab, `MsSsoAuth` must be extended to detect
  and target the new Playwright `Page`.

If you want, I can add an optional helper that automatically forces `headless`
to `false` on the very first run when a session file is not present (it will
then save the session and not require manual edits). Ask and I will implement it.
