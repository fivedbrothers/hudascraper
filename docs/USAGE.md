HudaScraper usage

Config-driven navigation and authentication

Overview
- The scraper is configured via a JSON file that declares selectors, pagination, normalization and small, ordered `pre_actions` to perform before authentication or extraction.

pre_actions
- `pre_actions` is an ordered array of small actions executed before authentication.
- Supported actions:
  - `click` - clicks the element matched by `selector`.
  - `fill` - fills `value` into the matched control.
  - `select` - selects option by value in a `<select>` control (fallbacks to fill when needed).
  - `navigate` - navigates to a URL (use `value` or `selector` as the URL).
- Each action may include optional `pause_ms` (milliseconds) to wait after the action.

Example (pre-action to click an app sign-in button):
{
  "pre_actions": [
    { "action": "click", "selector": "#ms-signin", "pause_ms": 300 }
  ]
}

Authentication
- Provider-specific auth flows (like Microsoft SSO) are implemented in `MsSsoAuth`.
- Use `pre_actions` to trigger an IdP redirect (app-level click). MsSsoAuth will detect the MS host and complete the login.

Waiting for content / tabs
- If the data to extract is inside a tab panel, add a `pre_action` that activates the tab (click the tab button) and/or add an entry in `wait_targets` for the table selector.

Selectors
- `selectors.table_container` - top-level container for the table rows.
- `selectors.header_cells`, `selectors.row`, `selectors.cell` - used relative to the `table_container`.

Running tests
- Integration tests that use Playwright are gated by an env var to avoid running browsers unintentionally:

```bash
# Run the SSO integration test
env RUN_PLAYWRIGHT_INTEGRATION=1 .venv/bin/pytest -q tests/test_ms_sso_integration.py -s
```

Notes
- The scraper includes defensive waits for `table_container` to reduce flakiness when using pre-actions and restored storage states.
- For public website scraping in tests we rely on stable public pages (e.g., W3Schools) and gate heavy Playwright tests.
