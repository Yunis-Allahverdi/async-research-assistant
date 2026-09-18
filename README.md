# async-research-assistant

An async research assistant that queries Wikipedia, arXiv, and a web-search API **in
parallel**, then uses an LLM to synthesize a single answer with inline `[N]` citations
back to the retrieved sources.

The AI layer (source fetchers + citation synthesizer, under [`ai/`](ai/)) is provided
and frozen. Everything else — concurrency orchestration, caching, CLI, retries, logging,
input validation, and tests — is the software-engineering layer built around it.

```
Question -> validate -> fetch Wikipedia + arXiv + web CONCURRENTLY -> synthesize
                                                                     -> cited answer
```

## Project layout

```
ai/                        # provided, frozen — fetchers + synthesizer
src/
├── config.py               # typed Settings (env-driven)
├── models.py                # SourceResult, ResearchResult, CacheEntry
├── logging_config.py        # central logging setup
├── services/ai_service.py   # retry + timeout + logging + cache wrapper around ai.*
├── storage/cache_store.py   # filesystem JSON cache, keyed by (origin, query), TTL-aware
├── concurrency/orchestrator.py  # asyncio.gather fan-out, semaphore, per-source timeout
├── core/researcher.py       # validation + pipeline (fetch -> synthesize)
└── cli.py                   # `ask` command implementation
researcher/                 # `python -m researcher` entry point
scripts/benchmark.py        # sequential vs. parallel timing benchmark
tests/                      # offline tests (provided smoke tests + ours)
data/research_questions.json  # sample questions for smoke runs / benchmarking
Dockerfile                  # builds + runs the offline demo end-to-end
```

## Setup

Requires Python 3.11+.

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1

python -m pip install -r requirements-ai.txt -r requirements.txt
```

Copy the env template and fill in the keys for whichever providers you'll use:

```bash
cp .env.example .env
```

| Variable | Meaning | Required? |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` \| `openai` \| `gemini` | yes (for the live CLI) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` | key for the chosen LLM provider | yes (one) |
| `WEB_SEARCH_PROVIDER` | `tavily` \| `serper` \| `duckduckgo` | yes |
| `TAVILY_API_KEY` / `SERPER_API_KEY` | key for the chosen web search provider | only if not `duckduckgo` |
| `CACHE_DIR` | where the filesystem JSON cache is written | no (default `.cache`) |
| `CACHE_TTL` | cache entry lifetime, seconds | no (default `86400`) |
| `SOURCE_TIMEOUT` | hard per-source time ceiling, seconds | no (default `10`) |
| `MAX_CONCURRENCY` | max simultaneous in-flight fetches | no (default `5`) |
| `MAX_RETRIES` / `RETRY_BACKOFF` | retry policy for transient failures | no (defaults `3` / `1.0`) |
| `MIN_QUESTION_LEN` / `MAX_QUESTION_LEN` | input validation bounds | no (defaults `3` / `500`) |
| `LOG_LEVEL` | logging verbosity | no (default `INFO`) |

> The env file is loaded at startup via `python-dotenv`, so both the config layer and the
> provided `ai/` layer see the same values.

## Running it

The canonical, always-works demonstration is the **offline demo**, which exercises the
full pipeline (fetch → synthesize → cited answer) on canned data with no keys or network:

```bash
python demo_ai.py --offline
```

The live CLI queries real sources:

```bash
python -m researcher ask "What is photosynthesis?"
python -m researcher ask "How does CRISPR-Cas9 work?" --sources wiki,arxiv
python -m researcher ask "..." --no-cache
```

`--sources` accepts a comma-separated subset of `wiki`, `arxiv`, `web` (default: all three).
The output includes the synthesized answer, a numbered reference list, and — if any source
failed — a note naming which one and that the answer may be incomplete.

## Testing

```bash
# provided smoke tests (must always pass, per the assignment contract)
python -m pytest tests/test_ai_smoke.py -v

# full suite
python -m pytest tests/ -v

# with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

Everything runs offline — no network calls, no API keys needed. External calls
(`ai.fetch_*`, `ai.synthesize`) are mocked with `monkeypatch` in every test.

## Benchmark: sequential vs. parallel

`scripts/benchmark.py` runs the same query two ways — once awaiting each source one
after another, once via the concurrent orchestrator — always bypassing the cache so
both runs do the same work for a fair comparison.

```bash
python -m scripts.benchmark "What is photosynthesis?" --sources wiki,arxiv,web
```

Measured on `<machine, date>`:

```
sequential: <X.XX>s
parallel:   <Y.YY>s
speed-up:   <Z.Z>x
```

*(Run the command and paste your own numbers — they depend on your network and the
configured web-search provider. Parallel wall-clock ≈ the slowest single source;
sequential ≈ the sum of all three.)*

## Docker

The image builds the project and runs the offline demo end-to-end — no API keys or
network required.

```bash
docker build -t research-assistant .
docker run --rm research-assistant
```

`docker run` executes `python demo_ai.py --offline` inside the container and prints the
cited sample answers. To run the live CLI in the container instead, pass env vars:

```bash
docker run --rm -e WEB_SEARCH_PROVIDER=duckduckgo research-assistant \
  python -m researcher ask "What is photosynthesis?"
```

## Known limitations

Live source fetching is constrained by the frozen `ai/` layer, which we may not modify
(per the assignment contract): arXiv returns HTTP 301 (the fetcher does not follow the
http→https redirect), Wikipedia returns HTTP 403 (no `User-Agent` header is sent), and
the pinned `duckduckgo-search` dependency was renamed to `ddgs` upstream and now returns
no results. The full pipeline is therefore validated via the offline demo and the mocked
test suite; graceful degradation was confirmed against the live endpoints — when every
source fails, the system returns a clean "no sources found" result (with a note naming
the unreachable providers) instead of crashing, after retries and per-source timeouts
fire as designed.

## Design notes / contract

- Nothing under `ai/` is modified — all access goes through `ai.fetch_wikipedia`,
  `ai.fetch_arxiv`, `ai.fetch_web`, and `ai.synthesize`.
- `tests/test_ai_smoke.py` (provided) is left untouched and must keep passing.
- No secrets are hard-coded; API keys are read from the environment only.