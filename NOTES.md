rows, cells, cards, list items, nav links, labels → multi_match: true
buttons, headers, input fields → typically single-match, so left as default

uv run python hudascraper_cli_.py --cfg config-sample.json --csv data.csv

uv run uvicorn hudascraper_app:app --reload --port 8000

curl -X POST "http://127.0.0.1:8000/scrape" \
  -H "Content-Type: application/json" \
  -d @config-sample.json

curl -X GET "http://127.0.0.1:8000/results/{run_id}"