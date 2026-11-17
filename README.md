# Job Hunt

A personal job-intelligence pipeline for Vietnam's IT job market. It collects jobs from ITviec, TopCV, and TopDev, normalizes the data, scores each role against a CV, verifies whether a listing is still open, and serves the results through a private dashboard.

## What it does

- Crawls three job boards, deduplicates records by `(source, source_id)`, and tracks discovery history.
- Normalizes titles, skills, seniority, experience, salary, locations, and target roles.
- Scores CV relevance from 0–100 using skills, titles, roles, and experience requirements.
- Verifies job detail pages to determine expiry dates and open/closed status.
- Harvests and enriches a company directory, linking companies to active openings.
- Syncs the local SQLite store to Supabase; serves the dashboard through FastAPI, React, and Vercel.

## Key engineering

- Source-specific HTML and JSON API adapters, with JSON-LD fallbacks.
- TLS impersonation with `curl_cffi`, session warm-up, host-level rate limiting, jitter, retry/backoff, and `Retry-After` support.
- Cloudflare challenge and schema-drift detection that stops unsafe ingestion rather than storing corrupt records.
- SHA-256-addressed, gzip-compressed raw evidence with a manifest and offline parser replay.
- SQLite WAL and FTS5 for the local data plane, with idempotent upserts and budgeted detail verification.
- Windmill orchestration, per-source locks, health watchdogs, and Telegram alerts.
- Precomputed Postgres serving fields, GIN indexes, Google Auth, and Supabase RLS.

## Architecture

```text
ITviec / TopCV / TopDev
        ↓
Crawler → raw evidence → normalize / score / verify
        ↓
SQLite (WAL + FTS5) ──sync──> Supabase Postgres
        ↓                         ↓
  Windmill + health          FastAPI + React / Vercel
```

## Run locally

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+, and Docker if you want to run Windmill.

```bash
git clone https://github.com/huy-dataguy/job-crawler.git
cd job-crawler

uv sync --extra dev
npm --prefix frontend ci

uv run job-crawler migrate
uv run job-crawler all
uv run pytest -q
```

The crawler works with its default configuration. To enable Telegram, Supabase, or cloud deployment, create a `.env` file following [docs/operations.md](docs/operations.md).

Run the local dashboard:

```bash
uv run uvicorn dashboard.main:app --host 127.0.0.1 --port 8130
```

Open `http://127.0.0.1:8130`. To start the local scheduler:

```bash
scripts/local/windmill.sh up
```

## Useful commands

```bash
uv run job-crawler itviec       # crawl one source
uv run job-crawler companies    # harvest and enrich company profiles
uv run job-crawler recheck      # re-verify job detail pages
uv run job-crawler replay       # reparse raw evidence without network access
uv run job-crawler health       # check freshness and pipeline health
uv run job-crawler verify       # run a persisted-data boot gate
uv run job-crawler raw-gc       # remove expired raw evidence
```

See [docs/operations.md](docs/operations.md) for configuration, schedules, Supabase sync, and troubleshooting. See [docs/security.md](docs/security.md) for private deployment setup.

## Quality checks

```bash
uv run pytest -q
npm --prefix frontend run build
```

GitHub Actions runs backend tests and a production frontend build for every push and pull request.

## License

[MIT](LICENSE) © Nguyen Quoc Huy
