Test site for MsSsoAuth/login flow

Files:
- index.html — app page with a "Sign in with Microsoft" button
- ms-login.html — fake Microsoft login page with email/next/password/signin
- success.html — post-login success page

Run a local server from repo root to serve these files:

```bash
# from the repository root
python3 -m http.server --directory test-site 8000

# then point your scraper or browser at:
http://127.0.0.1:8000/index.html
```

Or use the provided Playwright harness located at `test_harness/run_test.py` which will
start a local server and exercise the flow automatically (requires Playwright):

```bash
pip install playwright
playwright install
python test_harness/run_test.py
```

The fake MS login does not perform real authentication — it's solely for exercising
redirects and form selectors in a deterministic local environment.
