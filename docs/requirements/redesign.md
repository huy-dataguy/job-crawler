# Continuous job search and company intelligence

## Business, consumer and scope
The owner searches IT work across Vietnam, including remote work. Primary use case:
find jobs originally published within 14 days that still accept applications.
Secondary use case: build a persistent directory of employers, especially technology
businesses and businesses with an IT department, even when they have no current jobs.
Public information only; missing fields stay unknown. Source profiles are not a claim
to enumerate every Vietnamese legal entity or uniquely identify companies across sites.

## Requirements
- REQ-01: Refresh job listings every 15 minutes and retain history/user marks.
- REQ-02: Default search shows original publication age <=14 days and recently verified
  open jobs. Unknown dates/status remain searchable with explicit filters.
- REQ-03: Collect descriptions, source/company/application links, location, skills,
  salary when public, employment/work mode, publication and deadline evidence.
- REQ-04: Preserve company directory across job lifecycle; discover from paginated
  directories, sitemaps and job company links; enrich continuously with bounded requests.
- REQ-05: Store public company name, website, addresses, industry, size, description,
  working policy and contact/social links when present. Record IT classification evidence.
- REQ-06: One blocked source must not prevent other sources from running. Empty or
  repeated pages, parse drift and errors must be visible. No absence-based closure
  from a partial listing crawl. No invented HCMC location.
- REQ-07: Preserve immutable source artifacts, crawl manifests, error/freshness/coverage
  reports, bounded retry and a single writer lock across local scheduled entrypoints.
- REQ-08: Repair local services for the current checkout, start them, and prove live
  data reaches storage and the dashboard. Do not send Telegram without opt-in.

## Non-goals
Automatic applications, private contacts, paid APIs, claiming exhaustive web coverage,
international remote boards, legal-entity dedup without evidence, and a new warehouse.

## Decisions
- Vietnam including remote confirmed by owner on 2026-10-21.
- Keep existing local SQLite and React/FastAPI: one owner, low QPS, incremental writes,
  tens of thousands of company profiles. No new middleware required.
- Separate discovery, detail verification, company enrichment, serving and operation.
- Retain old/unknown jobs; recency is a view, not a destructive retention operation.
- Prefer structured JobPosting.datePosted over relative listing refresh labels.
- Status open requires a matching posting, unexpired deadline (when present), and
  current apply control; 404/410, explicit closed notices or elapsed deadline close it.
  Challenge, timeout, schema drift and disappearance from a partial crawl do not.
- Additive schema migration is a separate migrate() entrypoint, with SQLite backup.
  Existing data and marks are retained. Implementation/run is within the owner's
  redesign-and-run request. No destructive schema change.
- Telegram disabled for this rollout; existing explicit opt-in entrypoints remain.

## Open issues
Sources may restrict pagination or public fields; coverage and failures must remain
visible. A source's advertised application state cannot guarantee a recruiter reply.

## Verification
Risk: additive local schema migration; automatic SQLite backup before application.
Depends: design -> migration -> acquisition -> detail/contracts -> serving -> schedules.

- Verify: `uv run pytest -q`
- Verify: `cd frontend && npx tsc --noEmit && npm run build`
- Verify: `uv run job-crawler verify` (real storage, schema, freshness, contract and counts)
- Verify: `curl -fsS http://127.0.0.1:8130/api/health`
- Verify: `curl -fsS http://127.0.0.1:8130/api/jobs?limit=3`
- Verify: `systemctl --user is-active job-crawler-crawl.timer job-crawler-companies.timer job-crawler-dashboard.service`
