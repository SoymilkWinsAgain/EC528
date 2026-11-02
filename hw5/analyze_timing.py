import csv
import json
import re
from pathlib import Path

evidence = Path(__file__).resolve().parent / "evidence"

# Keep only requests from the formal load test.
with (evidence / "stress-request-ids.csv").open(
    encoding="utf-8-sig", newline=""
) as file:
    request_ids = {int(row["request_id"]) for row in csv.DictReader(file)}

names = ["headers_ns", "storage_ns", "response_ns", "database_ns"]
totals = dict.fromkeys(names, 0)
counts = dict.fromkeys(names, 0)
seen = set()
cache_hits = 0

text = (evidence / "stress-server.log").read_text(encoding="utf-8-sig")
decoder = json.JSONDecoder()

# Some JSON records share a line, so decode from each event marker.
for match in re.finditer(r'\{"event_type": "request_timing"', text):
    event, _ = decoder.raw_decode(text, match.start())
    request_id = event["request_id"]

    if request_id not in request_ids or request_id in seen:
        continue

    seen.add(request_id)
    timings = event["timings_ns"]

    if event["status_code"] == 200 and timings["storage_ns"] is None:
        cache_hits += 1

    for name in names:
        if timings[name] is not None:
            totals[name] += timings[name]
            counts[name] += 1

assert seen == request_ids, "Some timing records are missing."

print(f"Requests analyzed: {len(seen)}")
print(f"Successful cache hits: {cache_hits}")

for name in names:
    mean_ms = totals[name] / counts[name] / 1_000_000
    print(f"{name}: count={counts[name]}, mean_ms={mean_ms:.3f}")