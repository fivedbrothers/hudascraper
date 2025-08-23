# NOTES:
---
- rows, cells, cards, list items, nav links, labels → multi_match: true
- buttons, headers, input fields → typically single-match, so left as default
---
### Scrape command using CLI
```bash
uv run python hudascraper_cli_.py --cfg config-sample.json --csv data.csv
```
### Start the scraper server API
```bash
uv run uvicorn hudascraper_api:server --reload --port 8000
```
---
### curl POST + GET
```bash
curl -X POST "http://127.0.0.1:8000/scrape" \
  -H "Content-Type: application/json" \
  -d @config-sample.json
```
```bash
curl -X GET "http://127.0.0.1:8000/results/{run_id}"
```
---
### Check listening TCP port + PID
```bash
ss -tulnp | grep LISTEN
```