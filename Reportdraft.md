# Async Research Assistant — Technical Report (DRAFT)

> **How to use this file.** This is the *content* of your report. Your submission must be
> compiled from the provided LaTeX template (`templates/REPORT_TEMPLATE.tex`) into
> `report/report.pdf` — so paste these sections into that template, not submit this file.
> Everything marked **[FILL IN]** is data only you/your team have (numbers, names,
> machine). Read every section before the defense — you must be able to explain each claim.
> Target length 8–10 pages; trim or expand prose to fit.

**Topic:** 4 — Async Research Assistant
**Repository:** https://github.com/Yunis-Allahverdi/async-research-assistant · **Tag:** v1.0-final

---

## 1. Introduction

The Async Research Assistant answers a natural-language research question by retrieving
excerpts from three independent sources — Wikipedia, arXiv, and a web-search API — **in
parallel**, then using a large language model to synthesize a single 3–6 sentence answer
with inline `[N]` citations back to those sources.

The AI capability itself (the async source fetchers and the citation-aware synthesizer)
was provided to us as a frozen `ai/` package. Our task — and the entirety of what this
report covers — was to build the production software-engineering layer around it:
configuration, concurrency orchestration, caching, retries, timeouts, logging, input
validation, a command-line interface, an offline test suite, and a container image.

## 2. Architecture overview

The system is a layered pipeline. Each layer depends only on the layer below it, and the
provided `ai/` package is treated as a single external dependency accessed through a thin
service wrapper.

```
                 ┌──────────────┐
   CLI  ───────► │ researcher   │  validate question, assemble result
 (ask cmd)       │  (core)      │
                 └──────┬───────┘
                        │
                 ┌──────▼───────┐
                 │ orchestrator │  asyncio.gather fan-out, semaphore, per-source timeout,
                 │ (concurrency)│  graceful degradation
                 └──────┬───────┘
                        │  fetch_source(origin, query) per source
                 ┌──────▼───────┐
                 │ ai_service   │  retry + backoff, timeout, logging, cache lookup/store
                 │ (services)   │
                 └──────┬───────┘
                        │
          ┌─────────────┼──────────────┐
   ┌──────▼─────┐  ┌────▼─────┐   ┌─────▼──────┐
   │ cache_store│  │  ai/*    │   │  config    │
   │ (JSON/TTL) │  │ (frozen) │   │ (Settings) │
   └────────────┘  └──────────┘   └────────────┘
```

> [FILL IN — replace this ASCII sketch with a proper architecture diagram if your template
> supports images; the rubric rewards a real diagram.]

Data crossing module boundaries is always a typed model, never a bare dict: the provided
`Source` / `Citation` / `AnswerWithCitations` schemas from `ai/`, and our own `SourceResult`,
`ResearchResult`, and `CacheEntry` (`src/models.py`).

## 3. Design decisions and trade-offs

**Object-oriented design and the provided abstraction.** The `ai/` package models
providers with an abstract base class (`LLMProvider`, `WebSearchProvider`) plus concrete
subclasses selected by a factory reading environment variables. We deliberately mirrored
this shape rather than fighting it: our `ai_service` dispatches to the right fetcher
through a small registry (`_FETCHERS`), which is composition over a fixed provider set —
adding a source is one dictionary entry, not a new `if/elif` branch.

**Why a filesystem JSON cache (not Postgres or in-memory).** The workload caches
`(origin, query) → sources`. In-memory would not survive process restarts and so would
not count as persistence; Postgres would add a container, a schema, and a connection
pool for what is fundamentally a key→value blob store. A JSON-file-per-key cache is
persistent, trivially inspectable during the demo, needs no extra service in Docker, and
is easy to defend. The trade-off — no concurrent-writer safety and linear directory
growth — is acceptable at this scale and noted as a limitation.

**Why the AI module stays a clean boundary.** Business logic never imports provider SDKs
or calls source APIs directly; every call goes through `ai.fetch_*` / `ai.synthesize`,
wrapped once in `ai_service`. This keeps retry/timeout/logging/caching in exactly one
place and means the rest of the code is unaware of which provider is configured.

**Typed configuration.** `src/config.py` uses `pydantic-settings` to read a `.env` file
into a single typed `Settings` object. API keys are intentionally *not* surfaced here —
the `ai/` layer reads its own keys from the environment, so no secret ever flows through
(or is hard-coded in) our code.

## 4. Concurrency model

The orchestrator queries all requested sources concurrently:

- **`asyncio.gather(..., return_exceptions=True)`** fans out one coroutine per source and
  collects results; a raised exception in one branch does not cancel the others.
- **`asyncio.Semaphore(max_concurrency)`** bounds how many fetches are in flight at once,
  so we never exceed provider rate limits. The bound is configurable via `MAX_CONCURRENCY`.
- **`asyncio.timeout(source_timeout)`** wraps each source as a hard per-source ceiling,
  independent of the inner HTTP timeout, so one slow source cannot stall the whole call.
- **A single shared `httpx.AsyncClient`** is passed to every fetcher so connections are
  reused across the three requests in one research call.

Each branch is reduced to a typed `SourceResult` (ok + sources, or failed + error +
elapsed), which the researcher aggregates into a `ResearchResult`, setting `degraded=True`
if any source failed.

### 4.1 Sequential vs. concurrent benchmark

`scripts/benchmark.py` runs the same query twice — sequentially (await each source in
turn) and concurrently (the orchestrator) — bypassing the cache so both do equal work.

Command:
```
python -m scripts.benchmark "What is photosynthesis?" --sources wiki,arxiv,web
```

Measured on **[FILL IN — machine, OS, date]**:

| Mode | Wall-clock |
|---|---|
| Sequential | **[FILL IN]** s |
| Concurrent | **[FILL IN]** s |
| Speed-up | **[FILL IN]** × |

**Interpretation.** Sequential time is the *sum* of the per-source latencies; concurrent
time is the *maximum* single-source latency. After parallelizing, the bottleneck shifts
from total network time to **the slowest individual source** — [FILL IN: name which source
was slowest in your run, e.g. arXiv]. Beyond that, the semaphore bound and the LLM
synthesis step (which is sequential and runs after all fetches) become the next limits.

## 5. Robustness and error handling

- **Retries with exponential backoff (`tenacity`).** Every `ai.*` call is wrapped in a
  retry policy that fires **only on `ProviderError`** — the transient class (network,
  5xx, 429). Non-transient errors (`ValueError` from empty/oversized input) are not
  retried, because retrying them wastes time and never succeeds. Attempts and backoff are
  configurable (`MAX_RETRIES`, `RETRY_BACKOFF`).
- **Timeouts** on every source (see §4).
- **Input validation.** `validate_question` rejects empty or over-length questions with a
  clear `ValueError`, surfaced to the user as a message — never a stack trace.
- **Structured logging.** The standard-library `logging` module is used throughout (no
  `print`), configured once from `LOG_LEVEL`; INFO records inputs/outputs/timings, DEBUG
  the full payloads, and retries log at WARNING.
- **Graceful degradation.** If some sources fail, the answer is still synthesized from the
  survivors with a note naming what was missing; if *all* fail, the pipeline returns a
  clean "no sources found" result rather than crashing.

## 6. Caching

`src/storage/cache_store.py` stores each `(origin, query)` result as one JSON file.
The key is canonicalised (lower-cased, stripped, hashed) so `"What is X?"` and
`"what is x"` hit the same entry. Reads check the entry's age against `CACHE_TTL` and
treat anything older as a miss. `ai_service` checks the cache before every fetch and
writes non-empty results after; the CLI `--no-cache` flag bypasses it end-to-end.

## 7. Testing

All tests run **offline**: every external call (`ai.fetch_*`, `ai.synthesize`) is replaced
with a fake via `monkeypatch`, so the suite needs no network or API keys and is safe in CI.
Async code is tested with `pytest-asyncio`.

Coverage breakdown includes happy-path, cache hit/miss/expiry, retry-then-succeed,
retry-exhaustion, timeout, invalid-origin, input-validation, and concurrency (one source
failing while others succeed) cases.

- **Measured coverage:** **[FILL IN — run `python -m pytest --cov=src` and paste the %]**
  (target ≥ 60%).
- **Type checking:** `mypy src` was run once; result: **[FILL IN — paste summary, e.g.
  "no issues found in N source files" or the remaining notes]**.
- The provided `tests/test_ai_smoke.py` is unmodified and passes.

## 8. Deployment

A single `Dockerfile` (python:3.12-slim base) installs pinned dependencies, copies the
project (with a `.dockerignore` excluding the venv, caches, and secrets), and defaults to
running the offline demo end-to-end:

```
docker build -t research-assistant .
docker run --rm research-assistant
```

Dependencies are pinned in `requirements.txt` **[FILL IN — confirm you replaced `>=` with
`==` from `pip freeze` before the final tag]**.

## 9. Failure-mode analysis and limitations

**Concrete incident — live sources unreachable.** During live testing, all three sources
failed for reasons inside the frozen `ai/` layer, which the contract forbids us from
editing: arXiv returned HTTP 301 (the fetcher does not follow the http→https redirect),
Wikipedia returned HTTP 403 (no `User-Agent` header is sent), and the pinned
`duckduckgo-search` package was renamed to `ddgs` upstream and now returns empty results.
The system behaved exactly as designed: each source was retried three times with backoff
(visible in the logs), each hit its timeout ceiling independently, and the orchestrator
degraded to a clean "no sources found" response naming the unreachable providers — no
crash, no stack trace. This validated the robustness path end-to-end against real
endpoints.

**Limitations.** (1) Because `ai/` cannot be modified, live retrieval depends on upstream
behaviour we cannot patch; we therefore validate the full pipeline through the offline
demo and mocked tests. (2) The filesystem cache has no concurrent-writer locking and grows
one file per unique query. (3) Synthesis is sequential after fetching, so the LLM call is
the tail latency once retrieval is parallelized.

## 10. Contribution statement

> [FILL IN — this must be your own, and is submitted separately as a signed statement too.]

| Member | Modules owned | Tests owned | PRs | Report/slides |
|---|---|---|---|---|
| [FILL IN] | config, models, cache_store, ai_service, logging, Dockerfile | cache + ai_service | [FILL IN] | §3,5,6,7 infra |
| [FILL IN] | orchestrator, researcher, cli, benchmark | orchestrator, researcher, cli | [FILL IN] | §4 concurrency, §9 analysis |

## 11. Tools and acknowledgements

> [FILL IN — required by the assignment's academic-integrity section. Be honest and
> specific.] AI coding assistants were used as collaborators during development for
> scaffolding, explanation, and debugging; every module was reviewed and is understood by
> its owner. State here which parts were AI-assisted and to what degree.