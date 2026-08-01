# UK Data & Tech Job Market Tracker

Self-sourced (Adzuna API), NLP-driven tracker for the UK data/tech job market:
skill demand extraction, role/seniority classification, salary prediction, and
a dashboard - a FastAPI backend with a dependency-free HTML/CSS/JS frontend.

Portfolio project #2 for a UK job search - built to run alongside live job
applications, since the whole point is watching real demand data accumulate
over the weeks you're applying.

## Why this project

Project 1 (churn prediction) used a static, clean, pre-labeled Kaggle dataset.
This one deliberately doesn't: you collect the data yourself from a live API,
it's messy free-text HTML, and there's no ground-truth label for "what skills
does this posting want" - that's why it's an NLP project rather than another
supervised classification exercise. It also produces something genuinely useful
for the job search itself: real, current in-demand-skill and salary data for the
roles you're applying to.

## Architecture

```
Adzuna API --> src/collect_jobs.py --> data/raw/adzuna_jobs.csv (grows over time)
                                              |
                                              v
                                     src/process_data.py
                    (clean text, classify role/seniority, extract skills)
                                              |
                                              v
                                data/processed/jobs_processed.csv
                                    |                    |
                                    v                    v
                    src/train_salary_model.py       src/analytics.py
                    (Linear/Ridge/RF/XGBoost)      (aggregations)
                          |                              |
                          v                              v
                  models/salary_model.pkl  -------->  api/main.py  (FastAPI)
                                                          |
                                                          v
                                                   web/ (static UI)
```

The frontend talks to the backend over a small JSON API and holds no data
logic of its own; every number on screen is computed by `src/analytics.py`
and covered by tests.

## Repo layout

```
uk-job-market-tracker/
├── data/raw/                        # raw collected postings land here
│   └── sample_jobs_synthetic.csv    # SYNTHETIC data for smoke-testing (see below)
├── data/processed/                  # cleaned + skill-tagged dataset (committed for the demo)
├── src/
│   ├── collect_jobs.py              # Adzuna API collector, dedup + append
│   ├── text_cleaning.py             # HTML/entity/whitespace cleanup
│   ├── skills_taxonomy.py           # curated 56-skill taxonomy across 9 categories
│   ├── skill_extraction.py          # spaCy PhraseMatcher extraction + aggregation
│   ├── title_classification.py      # rule-based role category + seniority
│   ├── process_data.py              # ties cleaning/classification/extraction together
│   ├── analytics.py                 # dataset aggregations the API serves
│   ├── salary_model.py              # feature engineering + preprocessing
│   └── train_salary_model.py        # trains + compares 4 regressors
├── api/
│   ├── main.py                      # FastAPI app (9 endpoints)
│   ├── refresh.py                   # background live-refresh job
│   ├── schemas.py                   # request/response models
│   └── state.py                     # cached dataset + model loading
├── web/
│   ├── index.html                   # 5 views: overview / skills / salary / predict / postings
│   └── assets/{css,js}/             # design system, hand-rolled SVG charts, app controller
├── scripts/generate_synthetic_sample.py
├── tests/                           # 71 tests
├── models/                          # trained model + preprocessor (committed for the demo)
├── reports/                         # comparison tables + figures
├── Dockerfile / render.yaml         # backend deploy (Render)
├── vercel.json                      # frontend deploy (Vercel)
└── requirements.txt / requirements-dev.txt / pyproject.toml
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

The spaCy English model is installed straight from its release wheel (it is
listed in `requirements.txt`). Do **not** use `python -m spacy download
en_core_web_sm` - that command builds a broken URL against current spaCy and
404s.

## Run it

```bash
uvicorn api.main:app --reload
```

Then open <http://127.0.0.1:8000>. The API serves the frontend in development,
so this is the only command you need. Interactive API docs are at `/docs`.

### Smoke test (no API key needed)

```bash
python scripts/generate_synthetic_sample.py --n 400
python -m src.process_data --input data/raw/sample_jobs_synthetic.csv
python -m src.train_salary_model
pytest
uvicorn api.main:app --reload
```

`scripts/generate_synthetic_sample.py` makes up 400 fake-but-realistically-shaped
postings so you can confirm the whole pipeline runs before touching the real API.
**It is not real data - never quote numbers from it.**

## Get real data

1. Sign up free at [developer.adzuna.com](https://developer.adzuna.com/) - instant approval.
2. `cp .env.example .env` and fill in `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`.
3. Collect, process, train:
   ```bash
   python -m src.collect_jobs --pages 5
   python -m src.process_data --input data/raw/adzuna_jobs.csv
   python -m src.train_salary_model
   ```

Collection pulls ~250 postings per search term (5 pages × 50) across the default
UK data/tech queries, appends to `data/raw/adzuna_jobs.csv`, deduped by Adzuna's
job id.

### Automate collection (this is what makes the trend charts real)

Re-run the collector every few days so `collected_at` timestamps spread out and
the "skill mentions per week" chart shows actual movement instead of one flat
spike. Cron example (Mon/Thu 9am):

```
0 9 * * 1,4 cd /path/to/uk-job-market-tracker && .venv/bin/python -m src.collect_jobs --pages 5 >> collect.log 2>&1
```

## Results

Trained on 1,460 real postings collected 2026-08-01 across 6 queries, UK-wide
(`reports/salary_model_comparison.csv`):

| Model | Test R² | CV R² | MAE (£) | RMSE (£) |
|---|---|---|---|---|
| **XGBoost (best)** | **0.308** | 0.307 ± 0.101 | 15,234 | 24,496 |
| Random Forest | 0.261 | 0.284 ± 0.079 | 15,801 | 25,053 |
| Linear Regression | 0.233 | 0.222 ± 0.039 | 15,960 | 24,920 |
| Ridge | 0.231 | 0.224 ± 0.043 | 15,961 | 24,934 |

R² around 0.3 is what role/seniority/region/contract/skill-counts can explain on
their own; the rest is company-level variation the advert never states. Treat
predictions as a guide, which is what the UI says too.

## Live refresh

The dashboard has a **Refresh** button (next to the theme toggle) that pulls the
newest postings from Adzuna on demand:

```
POST /api/refresh          -> 202, starts a background job
GET  /api/refresh/status   -> {status, message, added, total, cooldown_remaining}
```

It collects one page per query (~6 API calls, ~20s), runs the full clean →
classify → extract-skills pipeline over just those rows, and merges them into
the served dataset deduped by Adzuna job id. Merging incrementally is
deliberate: `data/raw/` is not shipped in the image, so rebuilding from raw on a
deployed instance would replace thousands of rows with the few hundred just
fetched.

The button only appears when `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` are set on the
server, and refreshes are rate-limited by `REFRESH_COOLDOWN_SECONDS` (default
300) so a public button cannot burn the free-tier quota.

> **On Render's free tier, refreshed data is not durable.** Free instances have
> no persistent disk, so anything a refresh adds is lost when the instance
> sleeps (~15 min idle) or redeploys, and the dashboard reverts to the committed
> dataset. That is fine for a live demo - "watch it fetch real jobs right now" -
> but the durable path is still to run the pipeline locally and push, or to
> attach a paid instance with a disk.

## Known data limitations

Both of these are real constraints of the free Adzuna tier. They are documented
rather than hidden because knowing your data's limits is the point.

- **Descriptions are truncated to 500 characters.** The search API returns an
  opening snippet, not the full advert (mean = median = max = 500 chars; 99.8%
  end in an ellipsis). Skill extraction therefore runs over the summary, so the
  percentages are a consistent *lower bound* on true demand. Relative ranking
  between skills stays usable; absolute "% of jobs wanting X" does not. The
  dashboard states this on the skills view.
- **~99% of postings carry a salary, but many are Adzuna's own estimates**
  (`salary_is_predicted`). Salaries outside £15k–£250k are treated as day rates
  or data errors and excluded from every salary view and from training.

## Tests, linting, types

```bash
pytest
ruff check .
mypy src/ api/ scripts/
```

71 tests. `tests/test_api.py` exercises **filtered** endpoints specifically:
an unfiltered request never validates the query-parameter models, so filter
bugs sail past any smoke test that only hits bare endpoints.
`test_skill_extraction.py` auto-skips if spaCy isn't installed.

## Deployment - Vercel (frontend) + Render (backend)

The static UI goes on Vercel's CDN; the Python API runs as a container on
Render.

**1. Backend → Render**

[dashboard.render.com](https://dashboard.render.com) → New → Blueprint → pick
this repo. It reads `render.yaml` and builds the `Dockerfile` (which handles
the spaCy model wheel and the `libgomp1` system package XGBoost needs). Health
check is `/api/health`. Note your service URL.

**2. Frontend → Vercel**

Edit the `destination` in [`vercel.json`](vercel.json) to your Render URL, then:

```bash
vercel --prod
```

The rewrite proxies `/api/*` from the Vercel domain to Render, so the browser
only ever makes same-origin requests and CORS never applies. If you'd rather
call Render directly, drop the rewrite, add
`<meta name="api-base" content="https://your-api.onrender.com">` to
`web/index.html`, and set `CORS_ORIGINS` on Render to your Vercel domain.

> Render's free tier sleeps after inactivity, so the first request after an
> idle period takes ~30s to wake. The UI shows a loading state rather than
> failing.

`data/processed/` and `models/` are committed so the deployed demo has data.
Refresh them by re-running collection locally and pushing.

## Design notes / talking points

- **Why PhraseMatcher over a trained NER model**: no labeled UK job-ad dataset
  exists to train against. A curated taxonomy + spaCy's `PhraseMatcher` gets
  high-precision multi-word matching ("power bi", "machine learning") for zero
  labeling cost - a documented trade-off, not a shortcut.
- **Why rule-based title classification**: keyword rules cover the large
  majority of real title phrasing, are trivially debuggable (a misclassification
  is "add one regex", not "re-label and retrain"), and need no labeled data.
- **Salary modeled on the log scale**: UK data-role salaries are right-skewed -
  visible directly in the dashboard's salary histogram. Log-transforming stops a
  few Head-of-Data postings dominating the loss; predictions are exponentiated
  back to £.
- **Region granularity matters**: Adzuna's `location.area` runs broad→specific,
  so taking the last element yields a neighbourhood. Using it as a model feature
  produced 329 one-hot columns that couldn't generalise; taking the region
  (index 1) instead gives 13 and lifted XGBoost R² from 0.271 to 0.308.
- **Deduped, timestamped collection**: `collect_jobs.py` is idempotent -
  re-running never double-counts a posting, and `collected_at` is what makes
  "skill X is trending up" a defensible claim rather than a single snapshot.
- **No frontend framework or charting library**: the four chart types needed
  (line, bar, histogram, box plot) are ~400 lines of SVG that inherit theme
  colours from CSS custom properties and animate on the same spring curve as the
  rest of the UI. No build step, no dependency drift, no bundle.
