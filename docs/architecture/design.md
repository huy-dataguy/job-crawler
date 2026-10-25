# Architecture review — 2026-10-21

## Workload and system of record
One local user reads search/results/company profiles, paginated with low latency.
Discovery polls public listings every 15 minutes, detail verification refreshes jobs
on a bounded queue, companies refresh independently. SQLite is the canonical system
of record; append-only files preserve raw evidence. The SPA reads the API.

## Data model and integrity
Job identity=(source,source_id); company profile identity=(source,slug).
Jobs link to company profile URL; marks retain the job identity. First seen,
last seen, source publication, expiry and detail verification are separate timestamps.
Fields unavailable from sources remain NULL. Source profiles may represent the same
company; report profile counts explicitly. No automatic speculative entity merging.

## Boundaries and pipeline
Source HTTP adapter -> immutable raw + manifest -> listing/detail parser -> validated
canonical record -> SQLite upsert + FTS -> API -> dashboard. Raw HTML is replayable;
parsers are pure where possible. The directory queue uses stored timestamps/checkpoints,
not scans of the raw filesystem. No separate lakehouse/DWH/OLAP is needed for this workload.

Discovery updates last_seen and nonempty listing fields without erasing richer detail.
Detail verification takes precedence for original dates, description, work mode,
deadline and status. Jobs are rechecked on a budget with oldest checks first; initial
unverified recent listings have priority. Company enrichment prioritizes evidence of
IT and active hiring but reserves capacity for general directory profiles.

## Failure/recovery and security
Transport/server/rate-limit failures: bounded retries, honor Retry-After; challenges
stop the source. Empty first page/repeated pagination is reported, not silently counted
as exhaustive coverage. Per-source failures produce partial/error summaries but do
not skip healthy sources. Local commands share an advisory file lock. No network IO
while holding a long SQLite transaction. Schema work runs only through migrate().
Keep secrets in .env; do not log them. Dashboard binds loopback. No outbound messages
enabled during this rollout. Source URLs checked against their source hosts before detail fetch.

## Serving and quality
Default: source date in last 14 days AND status=open AND detail checked in last
24 hours AND deadline not elapsed. This expires dynamically even during outages.
Unknown and closed records available through explicit filters. Company hiring/counts
derive from verified open jobs; a partial page scan never resets unrelated employers.
Same query semantics apply to jobs, stats, facets and trend. Health reports per-source
runs and evidence coverage. SQLite query plans inspected for the serving workload.

## Implementation sequence / review
1. Explicit additive migration + backup, raw artifact writer, shared contracts.
2. National listing adapters, stable date/location/skill extraction, drift detection.
3. Detail verification and bounded job/company queues, source error isolation.
4. API/UI filters, job details, company profiles/export and runtime health.
5. Relocatable service installer, independent timers and shared lock.
6. Unit/contract failures -> live small crawl -> repeated idempotent crawl -> API -> services.

Coherence review: recency, status and company independence satisfy business goals;
no destructive pruning or absence inference; source restrictions remain observable.
