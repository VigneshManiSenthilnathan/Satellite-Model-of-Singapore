# SMS Replication — Implementation Plan

Working checklist for building the Satellite Model of Singapore over several
sessions. The model specification (equations, variables, source-document
inconsistencies) is in [README.md](README.md); this file covers **what to build,
in what order, and how to know it's done**.

**Last updated:** 2026-10-27 (session 2: audit + Phase 1 completion)  ·  **Current phase:** 1 (data layer) — panel built and QA'd; exit criteria met except the 3 NODX `gap` primaries (P3.8); Phase 2 can start. See [Status and handoff](#status-and-handoff-2026-10-27)  ·  **User decisions:** D1–D7 plus the session decisions in the [Decision log](#decision-log); open: none blocking (Q8, Q10 and the NODX treatment decided 2026-10-28, to implement in P5.6 / before P4 / P3.8)

---

## Status and handoff (2026-10-27)

### Done

| Area | Tasks | Notes |
|------|-------|-------|
| Phase 0 — environment & skeleton | P0.1–P0.7 ✅ | Exit criteria met. Python 3.13 pins, pyproject + ruff, `tasks.py` / `run_sms.py`, synthetic mode |
| Bloomberg layer | P1.1 ✅, P1.2 ✅, P1.3 ✅ | Cached wrapper with session-drop retry; cache-only `vintage=` reads |
| Ticker registry | P1.4–P1.6 ✅, P1.6b ✅, P1.6a ◐ | 187 → **190** unique tickers (193 series + 88 consensus = 281 pulls, 279 OK; only `ECPOUS 26/27` empty). Added in session 2: `INBGDRQY` (India y/y, bridges a base-year break), `TWRGSARP` (Taiwan SA level, now primary), `TWGDCONY` (Taiwan y/y check); bank company-basis NIM promoted to role `post` |
| Non-Bloomberg sources | P1.7 ✅, P1.8 ✅ | `capreq.yaml` (MAS releases, Tier 1 + buffer); SingStat client — all 51 cross-checked series agree with Bloomberg |
| Processing | P1.10–P1.13 ✅, P1.13a ◐, P1.14 ✅, P1.15 ✅ | Panel built: `data/processed/panel.parquet` 1980Q1–2026Q3, 11 columns, no interior gaps; foreign panel 60 series; `outputs/lineage.csv` 66 rows; `outputs/data_qa.html` — 94 anomalies (\|z\| > 4), **0 unexplained** |
| Tests | — | 99 offline tests pass (1 skipped: live) + 1 live Bloomberg test; ruff clean |

### Session 2 (2026-10-27): audit of session 1, then Phase 1 completion

Audit: every checked claim held (tests, lint, live test, synthetic run, 278-series vintage rebuild, SingStat 51/51, NEER episode agreement and correlations, RS shifts, CAPREQ steps, registry split/groups, git ignores), except: the P1.4 ticker count (164 → 168, now 190; corrected), the stale README status note (corrected), the "X-13 hang" (not reproduced: Hong Kong CPI finishes in 41 s by the same code path; all 21 adjusted series together ≈ 6 min, slowest Malaysia CPI 74 s), the claim that the first principal component equals the CSI blend (false: spread and NIM correlate −0.52, so PC1 ≈ their difference), and the claim that the CSI is NIM-only from 2021Q3 (the T12 NIM turned semi-annual from 2020).

Fixed in session 2 (all with tests):
- **Q9** — X-13 calls have a 300 s limit; on expiry `x13as.exe` itself is killed (verified: no stray processes after any run) and the series falls back to STL, recorded as `stl (x13 timed out)`; X-13 errors fall back as `stl (x13 error)` (Peru CPI). Each call uses its own temp directory (statsmodels left X-13 output files in `%TEMP%`).
- **Bank NIM** — T12 NIM used to the end of its last run of ≥ 4 consecutive quarters (2019Q4 DBS/OCBC, 2020Q2 UOB), then company-basis NIM level-shifted over the overlap.
- **CSI** — one-component segments (spread-only before 2003, NIM-only from 2021Q3) level-matched to the blend over 4 quarters at each join; the 1.5 pp step at 2021Q3 is gone.
- **LS** — IMF NEER back-cast ratio-matched over the first 4 overlap quarters (1994) instead of all of 1994–2026; removes a −4.3 pp artificial step in 1994Q1.
- **India GDP** — `INBGGDRQ` has a base-year break at 2022Q2 (level ×1.49); pre-break levels rescaled ×1.618 so growth across it matches published y/y (`INBGDRQY`).
- **Taiwan GDP** — primary switched to the SA level `TWRGSARP` (reproduces official annual growth; the chained `TWRGSAAR` gave 2008 −2.0% vs +0.7%).
- Smaller: unsorted `concat` index (pandas 3.1) in the NIM mean and foreign panel; `to_quarterly` now drops a daily final quarter ending > 7 days early; `sa_candidates()` = exactly what P1.13 adjusts (21 series); lineage records splice fields from the registry, chain truncation, the YF coverage rule, Indonesia's flat anchor year; `LCPIF` refuses to chain across a coverage gap; registry `validate()` requires `freq`; dead `DEFAULT_FREQ` fallback removed.
- New: `tests/test_process_data.py` (helpers + fake-registry build), `data/qa_report.py` + tests, `tasks.py process` / `tasks.py qa`.

### Phase 1 exit criteria

| Criterion | Status |
|---|---|
| `python -m data.collect_data && python -m data.process_data` builds the panel from cache using only registry tickers | ✅ (CAPREQ from `config/capreq.yaml`) |
| No `gap` / `check_units` entries on primary series | ❌ 3 NODX primaries (`SIEXTOID`, `SIEXTOPH`, `SIEXTOAU`) are `gap` — belongs to the P3.8 weights decision; the provisional YF uses total exports so the panel is unaffected. No `check_units` remain |
| QA report has no unexplained anomalies | ✅ 94 flagged, all explained (`KNOWN_EVENTS` in `data/qa_report.py`) |

### Still open after Phase 1 (decisions taken 2026-10-28; work scheduled)

1. **Q10 — CSI definition (D3).** The CSI does not tighten in 1998 (−0.01 pp) or 2001 (+0.01); it does in 2008–09 (+0.40 blend, +0.17 spread-only). **Decided:** keep D3 through Phases 2–3; before P4, search the Terminal for a market-based lending spread (e.g. SGD corporate bond spreads) and compare it with D3 on the stress check. Stress table is in the QA report.
2. **NODX gaps** (Philippines, Australia; India covers the replication sample) — **decided for P3.8:** NODX shares where available; PH and AU NODX imputed as their total exports × the average NODX / total-exports ratio of the other partners.
3. **Q8 — expected US policy-rate path** — **decided for P5.6:** fed funds futures (generic `FF1`…`FF12 Comdty`, added to the registry when P5.6 starts).
4. **Indonesia GDP level** — built from y/y with a flat anchor year; flagged in lineage; revisit with P3.9 (`IDGDQY` q/q NSA from 2008 could anchor it).

### Git state

Branch `setup/phase-0` (not merged into `main`). Commits: `895151f` (Phase 0), `0cc7c1a` (P1.6b). **Everything from P1.3 onward is uncommitted**, including session 2. New since session 1: `data/qa_report.py`, `tests/test_process_data.py`, `tests/test_qa_report.py`. `git add -n .` lists no data, outputs or `tools/`.

### Open questions needing a user decision

None at the moment. Q8, Q10 and the NODX treatment were decided 2026-10-28 (see the Decision log); their work is scheduled in P5.6, before P4 and in P3.8.

---

## How to use this plan

- Each task has an ID (`P2.4`) so a session can say "continue from P2.4".
- Tick `[x]` when done, `[~]` when partly done (add a note), and leave `[ ]` open.
- At the end of every session:
  1. Update the checkboxes and the **Current phase** line above.
  2. Add an entry to the [Decision log](#decision-log) for every choice made.
  3. Record new unknowns under [Open questions](#open-questions).
- A phase is finished only when its **exit criteria** are met, not just when its boxes are ticked.
- Take Bloomberg tickers only from [config/tickers.yaml](config/tickers.yaml) (see 1B). Add any new series there first, with a comment.
- Don't commit Bloomberg data. `data/raw/`, `data/processed/` and `data/foreign/` are already git-ignored; keep it that way (see [Bloomberg licensing](#bloomberg-licensing)).

### Phase map

```
P0 Environment & skeleton
 └─► P1 Data layer (Bloomberg + supplementary sources)
      └─► P2 Model core (equations, steady state, RE solver, IRFs)     ◄── can start in parallel with P1 using synthetic data
           └─► P3 Backing out unknowns (digitised targets, IRF matching, priors, weights, sample)
                └─► P4 Bayesian estimation on data
                     └─► P5 Outputs (filtering, forecasts, scenarios, decompositions)
                          └─► P5B Backtest & forecast-error evaluation
                               └─► P6 Charting & HTML report
P7 Testing, validation & documentation runs alongside every phase
```

---

## Phase 0 — Environment and project skeleton

**Goal:** a reproducible environment that can run the code and talk to Bloomberg.

- [x] **P0.1** Stay on the installed Python 3.13 (decision D4). `.venv` (Python 3.13.15) has `blpapi` 3.26.9.1 plus everything in `requirements.txt`, all installed from 3.13 wheels.
- [x] **P0.2** Done 2026-10-27: top-level exact pins in `requirements.txt` (numpy 2.5.4, scipy 1.18.1, pandas 3.1.0, statsmodels 0.15.0, matplotlib 3.11.2, arviz 1.3.0, plotly 7.1.0, pytest 9.1.1, ruff 0.17.3, …); `blpapi` installed separately from Bloomberg's index and documented in the README; optional extras `fast` (numba 0.68.0) and `pdf` (pymupdf 2.0) in `pyproject.toml`, wheels confirmed for 3.13. Original task: Re-pin `requirements.txt` for Python 3.13: upgrade `numpy`, `scipy`, `pandas`, `matplotlib`, `statsmodels`, `contourpy` and so on to releases with 3.13 wheels, and confirm `blpapi` has a 3.13 wheel before relying on it. Update the README's Python-version note (it currently says 3.9–3.12). Add:
  - `blpapi` — from Bloomberg's index: `pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi`. Document this in the README because plain `pip install -r` won't find it.
  - `pyarrow` (parquet cache), `pyyaml` (config), `arviz` (MCMC diagnostics), `plotly` (hover-enabled charts in the HTML report), `jinja2` (report template), `pytest`, `jupyter`
  - Optional: `numba` (speeding up the Kalman filter), `pymupdf` (extracting chart data from the PDF, P3.1)
- [x] **P0.3** Done 2026-10-27: empty packages `model/`, `estimation/`, `analysis/`, `backtest/`, `report/`; `tests/`, `targets/`, `outputs/` (git-ignored except `.gitkeep`); config stubs `blocs.yaml`, `capreq.yaml`, `priors.yaml`, `calibration.yaml` (the last seeded with the README's assumed steady states). `notebooks/` and `docs/` are deferred until they have content. Original task: Create the package skeleton from the README's planned structure, plus:
  - `config/` — `tickers.yaml`, `blocs.yaml`, `calibration.yaml`, `priors.yaml`, `capreq.yaml`
  - `data/bloomberg.py` — the Bloomberg client wrapper
  - `targets/` — digitised chart data from the PDF (committed; it's derived from a public document)
  - `backtest/` — pseudo-out-of-sample engine, benchmarks and error metrics (Phase 5B)
  - `outputs/` — run outputs (git-ignored)
  - `tests/`
  - `report/` — HTML report template and builder
- [x] **P0.4** `pyproject.toml` (metadata, dependencies read from `requirements.txt`, optional extras, ruff and pytest config). `ruff check .` passes.
- [x] **P0.5** `tasks.py` (`test`, `lint`, `bloomberg`, `all` and the pipeline steps) forwarding to `run_sms.py`, whose steps `data`, `estimate`, `irf`, `simulate`, `backtest`, `report` are stubs naming the task that implements them. Every run writes `outputs/{run_id}/meta.json`.
- [x] **P0.6** Bloomberg connectivity smoke test — `python -m data.check_bloomberg`, passed 2026-10-27 with `blpapi` 3.26.9.1 on Python 3.13. Its pulls go through the cache. With the Terminal logged in, the Desktop API (`C:\blp\DAPI`, already installed) listens on `localhost:8194`. Script: open a session, open `//blp/refdata`, pull `PX_LAST` for `USGG3M Index` over 5 days.
- [x] **P0.7** Synthetic-data mode: `run_sms.py --synthetic` or `SMS_SYNTHETIC=1`. `data/synthetic.py` generates a seeded quarterly panel with the real panel's columns (`data/panel.py`: 6 observables, `YF`, `LCPIF`, `RR_US`, `RR_US_BAR`, `CAPREQ_BAR`); `data.bloomberg` refuses to open a session in this mode. Tests run in it by default; live tests use the `bloomberg` marker. Replace the AR(1) stand-ins with model-simulated data once Phase 2 exists.

**Exit criteria:** ✅ met 2026-10-27 (27 tests pass; `check_bloomberg` returns data; `run_sms.py --synthetic` runs end to end as a stub). `pytest` runs (even with no tests yet); the Bloomberg smoke test returns data; `python run_sms.py --synthetic` runs end to end as a stub.

---

## Phase 1 — Data layer

**Goal:** a quarterly, model-ready panel of all observables and foreign inputs, reproducible from one command, with lineage recorded.

### 1A. Bloomberg wiring

- [x] **P1.1** `data/bloomberg.py` — built and tested 2026-10-27, including session-drop retry. Contents:
  - `bdh(tickers, fields, start, end, periodicity="QUARTERLY", overrides=...)` → tidy DataFrame, using `HistoricalDataRequest` with `periodicitySelection`, `periodicityAdjustment="CALENDAR"`, `nonTradingDayFillOption`, `currency`
  - `bdp(tickers, fields)` → reference data such as `NAME`, `SECURITY_DES`, `INDX_FREQ`, `INDX_SOURCE`, and seasonal-adjustment flags
  - `search_instruments(query)` via `//blp/instruments` (the API's `SECF`) and `search_fields(query)` via `//blp/apiflds` (the API's `FLDS`) — both cached
  - Error handling: log and continue on per-security errors (`securityError`, `fieldExceptions`); retry on session drop — `SessionConnectionDown` / `SessionTerminated` / `RequestFailure`, timeouts and failed session starts raise `BloombergSessionError`, and the request functions reopen the session and retry (3 attempts, 2 s then 4 s wait). Caller-supplied sessions are not retried. Tested with a fake `blpapi`.
- [x] **P1.2** Cache layer — every pull is written to `data/raw/bloomberg/vintage=YYYY-MM-DD/{bdh|bdp}_{request-hash}.parquet` with a `.json` sidecar (request, pull time, row count, field warnings, blpapi version) **before** it is returned. Same request → read from cache; `refresh=True` forces a live pull. Open-ended requests (`end=None`) key on today's date, so they refresh at most daily. Tested: cache hits make no Bloomberg call and return frames identical to the live pull.
- [x] **P1.3** Vintage handling, done 2026-10-27: refreshes land in dated folders (`vintage=YYYY-MM-DD/`) and normal lookups return the latest vintage. `bdh(..., vintage="YYYY-MM-DD")` / `bdp(..., vintage=...)` read the data as it stood on that date: the newest cached copy at or before the vintage, with `end=None` meaning the vintage date. Vintage reads are cache-only (never call Bloomberg; `FileNotFoundError` if absent). `list_vintages()` lists what is cached; `python -m data.collect_data --vintage YYYY-MM-DD` rebuilds the manifest and registry checks from a vintage without a Terminal (verified on the 2026-10-27 vintage: all 259 series at the time; 278 after the 19 S$ bilateral rates were added for P1.12, re-run in the audit session: 276 OK, 2 empty = `ECPOUS 26/27`). Note that `PX_LAST` returns latest-revised history, not first releases. Record this as a known limitation for real-time output-gap analysis (Okun's law, eq 20, is meant to help real-time estimation).

### 1B. Ticker registry — `config/tickers.yaml`

**[config/tickers.yaml](config/tickers.yaml) is the single source of truth for every Bloomberg series.** Code reads tickers from it and never hard-codes them; any new or replaced series is added there first, with a comment saying what it is. Each entry records `ticker`, `var` (model input it feeds), `role` (primary / history / post / crosscheck / reference), `freq`, `sa`, `form` (level / index / qoq / yoy / rate — drives the transformation in P1.13), `span`, optional `field` (default `PX_LAST`) and optional `status` (`gap` / `check_units`). The file's `known_gaps` section lists open data issues.

- [x] **P1.4** Singapore domestic series — 168 unique tickers across sections 1–4 of the registry (originally miscounted as 164; 187 since the 19 `neer_bilateral` rates were added for P1.12), all resolved and returning history on 2026-10-27 (verification pulls cached). Primaries: `SGDSTOTL` (GDP), `SICPISA` (CPI), `SIQUTOTA` (unemployment), `SIBF3M` → `SORACA3M` with `5766586` back-cast (RS), `NBISSING` with `576.023` back-cast (S$NEER, D2), lending/deposit rates and bank NIM `T12_NET_INT_MARGIN` (CSI, D3).
- [x] **P1.5** Foreign series — US block (incl. `USNRUS` HLW r*), real GDP and CPI for 20 candidate bloc countries (CPI primary = IMF IFS `{code}6639` for one consistent long series), and consensus templates `ECGD/ECPI{cc} {yy}` for 21 countries plus `ECPOUS` (D6).
- [x] **P1.6** Trade by partner — NODX (`SIEXTO*`), total exports (`SEMC*`) and imports (`SIMC*`) for all 20 partners.
- [~] **P1.6a** Session 2 (2026-10-27): only the 3 NODX `gap` primaries remain (P3.8); new data issues found and resolved — bank T12 NIM semi-annual from 2020 (continued with company-basis NIM), India GDP base-year break (bridged with `INBGDRQY`), Taiwan chained GDP inconsistent with official growth (`TWRGSARP` now primary). Earlier progress 2026-10-27: units confirmed (`CGE9ANN` = q/q % SAAR, `PHNAGDP` = q/q % SA; registry corrected); `5766586` behaves like an overnight rate (vs overnight SORA RMSE 0.24 pp; vs 3M SIBOR −0.25 pp bias), so the back-cast is level-shifted in P1.11; Terminal search found no post-2021 lending rate → CSI averages the available components (decision below). Remaining items belong to later tasks: NODX partner breaks (P3.8), Indonesia GDP level (P1.13), bloc membership (P3.7), `ECPOUS` (Q8). Original task: Resolve the registry's `known_gaps` before building the panel:
  - post-2021 Singapore lending rate for the CSI
  - CSI is spread-only before 2003 (bank NIM data start then)
  - NODX partner breaks (India, Philippines, Australia)
  - no SA GDP level for Indonesia
  - units of `CGE9ANN` and `PHNAGDP` (confirm with `DES <GO>`)
  - definition of the pre-1999 RS back-cast (`5766586`)
  - provisional bloc assignment (closes with P3.7)
  - US policy-rate consensus `ECPOUS {yy}` resolves but has no data for any year (found by the P1.6b re-verification; needed by P5.6, see Q8)
- [x] **P1.6b** Done 2026-10-27.
  - `data/tickers.py`: `series()`, `select()`, `expand_template()`, `consensus_tickers()`, `singapore_consensus_tickers()`, with validation of roles, forms, frequencies, statuses and duplicates.
  - `data/collect_data.py` (`python tasks.py collect`): pulls every registry series at native frequency from 1980, one cached request per series, plus consensus tickers for the current and next year. It writes `manifest_YYYY-MM-DD.csv`, then re-verifies the registry (every ticker resolves; pulled spans vs registry `span`) into `verify_YYYY-MM-DD.csv`.
  - First full run, 2026-10-27: 259 series (168 registry tickers + 88 consensus), 257 with data, all tickers resolve. The registry held **168** unique tickers (the P1.4 note's 164 was a miscount); **187** after the 19 S$ bilateral rates (`neer_bilateral`) were added, giving 190 (ticker, field) series + 88 consensus = 278 pulls. Five registry spans were too short and have been corrected (`SIIRPLRT`, `SIIRSADE`, `SIEXPNO`, `SIEXDOME`, `UKRPCJYR`). `ECPOUS 26/27` return no data — added to `known_gaps` and P1.6a.
  - Original task: `data/tickers.py` loader: read the registry, expand consensus templates for a given year, and select series by `var`/`role`. `collect_data.py` pulls everything listed through `data/bloomberg.py`, so all pulls are cached. Re-verify the registry (resolve + span) after each data refresh and on every edit.

### 1C. Non-Bloomberg sources

- [x] **P1.7** Done 2026-10-27. `config/capreq.yaml`: 12 sourced steps from public MAS media releases (1998, 2000, 2004, 2007, 2011): Tier 1 minimum 12% (1992) → 10% (Dec 1998) → 8% (Sep 2000) → 7% (Jun 2004) → 6% (Mar 2007) → Basel III 6/7/8% (2013–15), plus the 2.5% conservation buffer phased in 2016–19. `CAPREQ_BAR` = Tier 1 minimum + buffer (10.5% from 2019); the minimum-only series is kept as a variant. Undefined before 1992. `data/capreq.py` → quarterly series (value in force on the quarter's last day). Post-2019 minima reconfirmed 2026-10-28 against DBS's 30 Jun 2026 Pillar 3 disclosure (MAS Notice 637 Annex 11A template: CET1 6.5 / Tier 1 8.0 / Total 10.0%, CCB 2.5%, no D-SIB buffer); the 2024–26 Notice versions left the minima unchanged. Original task: `config/capreq.yaml`: hand-coded timeline of the minimum Tier-1 capital ratio from MAS Notice 637 and its earlier versions, including the Basel III phase-in dates. Cite the notice version for each step.
- [x] **P1.8** Done 2026-10-27. `data/singstat.py` (`python tasks.py singstat`): Table Builder API client (pages by data points, 5,000 per call), cached like Bloomberg under `data/raw/singstat/vintage=YYYY-MM-DD/` with cache-only `vintage=` reads. `config/singstat.yaml` maps 51 SingStat series to registry tickers: GDP `M015662`, CPI SA `M213752`, NODX `M451301` (S$ **thousand**, scaled), exports `M451521`, imports `M451491`. First cross-check: all 51 agree (GDP, CPI, exports, imports exactly; NODX within 0.014% rounding). SingStat has no euro-area trade row and its NODX covers only 10 markets, so it can't fill the NODX gaps. `collect_data.load_series()` added: cache-only read of a collected series (latest vintage by default). Original task: SingStat Table Builder API fallback for GDP, CPI and trade-by-partner, used to cross-check Bloomberg values (P1.14).
- [x] **P1.9a** ~~BIS NEER download~~ — not needed: the BIS broad NEER for Singapore is on Bloomberg (`NBISSING Index`).
- [x] **P1.9** ~~NY Fed r* download~~ — not needed: HLW US r* is on Bloomberg (`USNRUS Index`). An HP trend of `RR_US` remains the robustness variant.

### 1D. Processing

- [x] **P1.10** Done 2026-10-27. `data/seasonal.py`: `adjust(series)` → (SA series, method used), multiplicative (logs); X-13ARIMA-SEATS build 62 (`tools/x13as/x13as.exe`, git-ignored, from census.gov; `X13PATH` overrides) with automatic outliers, STL fallback when the binary is absent, on X-13 error, or after a 300 s per-call time limit (Q9, session 2: `x13as.exe` is killed on expiry; each call uses its own temp directory). `sa_candidates()` = the 21 primary NSA GDP/CPI series P1.13 adjusts (18 IFS/national CPIs, China CPI after chaining, India GDP, Indonesia GDP after chaining). Timed on the 2026-10-27 vintage: all finish (≈ 6 min in total; slowest Malaysia 74 s, Indonesia 71 s, Hong Kong 41 s CPI); Peru CPI fails in X-13 → STL. On real data X-13 removes more seasonality than STL (Japan CPI seasonal range 0.75 → 0.08 pp vs 0.15; India GDP 14.4 → 1.1 pp vs 2.5). Original task: Seasonal adjustment for any NSA series: X-13ARIMA-SEATS through `statsmodels` (needs the `x13as` binary), or STL as fallback. Record which series were adjusted and how.
- [x] **P1.11** Done 2026-10-27. `data/transform.py`: `to_quarterly()` (mean/sum/last; drops an incomplete final quarter), `splice()` (level or ratio shift by the mean gap over the overlap), `build_rs()`. RS = quarterly-average 3M SIBOR (1999Q3–2024Q4); SORA 3M compounded from 2025Q1 shifted **+0.45 pp** (overlap 2005Q4–2024Q4, 77 quarters); IMF money-market rate before 1999Q3 shifted **+0.25 pp** (overlap 1999Q3–2021Q2, 88 quarters). Result: continuous 1980Q1–2026Q3, no gaps. Original task: SIBOR → SORA splice: use 3M compounded SORA from the cut-over date, with a level adjustment equal to the ISDA/SC-STS fixed spread or the average basis over the overlap window. Record the choice.
- [x] **P1.12** Done 2026-10-27. `data/neer_check.py` (`python -m data.neer_check`).
  - Proxies vs BIS NEER, 12-month changes: IMF NEER corr 0.98 (tracking error 0.47 pp), Bloomberg `SNEER` 0.95 (0.66), Goldman `GSSGSGD` 0.95 (0.72), our trade-weighted index of 19 S$ bilateral rates (registry group `neer_bilateral`, total-trade weights 2003–25) 0.79 (1.76 pp — no third-market weighting, and pulled around by 1997–98 crisis currencies).
  - `config/mas_policy.yaml`: 69 MAS policy decisions 1994–2026 (2001+ from every Monetary Policy Statement, high confidence; 1994–2000 reconstructed from MAS annual reports, medium/low). Spot-checked against the statements of Apr 2004, Apr 2010 and Mar 2020.
  - Episode check (trend slope per policy episode ≥ 6 months; "zero" agrees if |slope| < 2% p.a.): BIS NEER agrees in 14/16 episodes, IMF 15/16, Bloomberg 13/13, Goldman 11/11, TWI 14/16. **Disagreements:** (1) Oct 1997–Jul 1998, announced zero/widened band, BIS +8.7% p.a. — Asian crisis, regional currencies collapsed against the S$ (all proxies show it); (2) Jan 2002–Jul 2003, zero, BIS −2.1% p.a. — just outside tolerance (Bloomberg −1.1, Goldman −0.6). The BIS NEER is a sound policy proxy (D2 stands).
  - Original task: S$NEER validation: check that the BIS NEER slope matches published MAS policy statements (appreciating / neutral / easing episodes), and compare it with a Bloomberg S$NEER proxy and a simple trade-weighted index of SGD bilateral rates. Document any episodes where they disagree.
- [x] **P1.13** Done 2026-10-27 (session 2). `data/process_data.py` (`python tasks.py process` / `python -m data.process_data [--vintage]`) builds `data/processed/panel.parquet` (1980Q1–2026Q3, 11 columns, no interior gaps), `panel.json` (vintage, SA methods, weights), `data/foreign/foreign_panel.parquet` (60 series) from one cached vintage, in ≈ 6 min (X-13). `RR_US = RS_US − PIE_EXP_US`; `LS` = BIS NEER with the IMF NEER ratio-matched over the first 4 overlap quarters before 1994; provisional `YF` (from 1995Q1, ≥ 50% export weight covered) / `LCPIF`; India GDP base-year break bridged with `INBGDRQY`; Taiwan GDP from the SA level `TWRGSARP`. Spans and plausibility checked (growth, inflation, NEER, rates). Tests: `tests/test_process_data.py` (helpers + fake-registry build). Original task: `data/process_data.py`: raw → model-ready panel using the transformations in the README (`100·ln`, `PIE = 4·ΔLCPI`, `DOT_LS = 4·ΔLS`, `LZ = LS − LCPIF + LCPI`, and so on). Output `data/processed/panel.parquet` with one column per observable and per foreign input.
- [~] **P1.13a** Built 2026-10-27: spread = prime lending − 3M fixed deposit (IMF back-casts 1980–82, identical to the MAS series), NIM = mean of DBS/OCBC/UOB (T12 to 2019Q4/2020Q2, then company-basis NIM level-shifted); CSI = mean of available z-scores, one-component segments level-matched to the blend over 4 quarters at each join; window parameter; `variant="spread"` robustness. The first-principal-component variant is **not** the blend up to scale (spread–NIM correlation −0.52 ⇒ PC1 ≈ their difference), so it was not added. **Stress check fails for 1998 (−0.01 pp) and 2001 (+0.01 pp)**, passes 2008–09 (+0.40 pp) → Q10. Original task: CSI construction (D3): `CSI = mean(z(loan − deposit spread), z(NIM))`, with z-scores computed over the estimation sample, rescaled to percentage points of the spread so magnitudes are interpretable. Robustness variants: spread only, and first principal component. Check that the CSI tightens in known stress periods (1998, 2001, 2008–09).
- [x] **P1.14** Done 2026-10-27. `data/qa_report.py` (`python tasks.py qa`) → `outputs/data_qa.html` (self-contained, offline, Plotly hover): panel summary (spans, gaps, outliers, sources), a chart per panel column, build checks (RS splice parts, LS join, CSI variants + stress table, bank NIM), foreign inputs and weights, SA methods, coverage of all 193 raw series (spans, interior gaps), Bloomberg vs SingStat, and the anomaly list. Anomaly = \|z\| > 4 on the quarterly change (annualised for 100·ln levels; level for gaps), matched against `KNOWN_EVENTS`: 94 flagged, 0 unexplained. Original task: Data QA report (`outputs/data_qa.html`): plots of every series, start and end dates, gaps, outliers (|z| > 4), and Bloomberg vs SingStat differences.
- [x] **P1.15** Done 2026-10-27. `outputs/lineage.csv` (66 rows): var / source ticker / field / transformation / vintage (= pull date) / provisional flag for every panel column and per-country foreign series; reviewed — splice shifts and windows, NIM continuation, seasonal-adjustment method (incl. fallbacks), chain truncation, India bridge factor and Indonesia's flat anchor are all recorded. Original task: Lineage table, generated automatically into `outputs/lineage.csv`: model variable ← transformation ← source series ← ticker and field ← pull date.

**Exit criteria:** `python -m data.collect_data && python -m data.process_data` builds the panel from cache using only tickers from `config/tickers.yaml`; the registry has no remaining `gap`/`check_units` entries on primary series; the QA report has no unexplained anomalies.

---

## Phase 2 — Model core (can run with synthetic data)

**Goal:** a correct, tested implementation of the 37-equation system that produces IRFs for any parameter vector.

- [ ] **P2.1** `model/equations.py`: `SMSParams` dataclass with every parameter from the README table, plus symbolic or matrix form of all equations. Follow the adopted resolutions in the README's inconsistencies table.
- [ ] **P2.2** Rewrite in canonical linear RE form `A·E_t[x_{t+1}] = B·x_t + C·ε_t`:
  - Auxiliary variables for multi-period leads (`Y(+4)` in eq 12, `PIE4(+3)` in eq 17) and lags (`CSI_BAR(-40)`, `E_CSI(-1…-7)`, `PIE(-1…-3)`, `LGDP(-4)`)
  - Non-stationary trends (`LGDP_BAR`, `LS_BAR`, `LZ_BAR`, `LCPI`, `LS`, `CAPREQ_BAR`) handled in levels: unit roots are allowed, and the BK count must treat them correctly
- [ ] **P2.3** Steady state: analytic solution for the gaps (all zero) and growth rates. Unit test: plugging the steady state into every equation leaves residuals < 1e-10.
- [ ] **P2.4** `model/solver.py`: Klein (2000) solution via `scipy.linalg.ordqz`, sorting eigenvalues inside the unit circle (with a tolerance of 1 + 1e-6 for unit roots). Return the state transition `T`, shock impact `R`, and a BK flag (determinate / indeterminate / explosive).
- [ ] **P2.5** Cross-check the solver on a 3-equation New Keynesian model with a known closed-form solution.
- [ ] **P2.6** `model/state_space.py`: measurement equations for the 6 observables (no measurement error by default; optional small measurement error for `CSI`). Exogenous foreign inputs enter as observed variables with AR(1) closure processes.
- [ ] **P2.7** Kalman filter and RTS smoother with diffuse initialisation for unit-root states (exact diffuse or a large-κ approximation), supporting a time-varying shock covariance for the COVID variance scaling (D5). Unit test against `statsmodels` `UnobservedComponents` on a local-linear-trend model.
- [ ] **P2.8** IRF engine: one-σ shock to any `RES_*`, 40-quarter horizon, outputs in the units of the MAS charts (% deviation for levels, percentage-point difference for rates).
- [ ] **P2.9** Policy switch: `policy="endogenous" | "exogenous"`. Exogenous holds `LS` on its baseline path by solving for the `RES_DOT_LS` sequence (or replacing eq 17).
- [ ] **P2.10** Deterministic simulation with anticipated or unanticipated exogenous paths — needed for the foreign-demand scenario in Chart 6.1. Implement both (anticipated paths need a stacked-time or news-shock approach).
- [ ] **P2.11** Smoke run with GPM-style placeholder parameters: all six IRFs return to baseline and BK holds.

**Exit criteria:** the unit tests for P2.3, P2.5 and P2.7 pass; IRFs for all 18 shocks run in < 1 s; qualitative signs match the README benchmark table using placeholder parameters.

---

## Phase 3 — Backing out the unknowns

**Goal:** turn what the MAS documents *do* publish (charts and simulation numbers) into quantitative bounds on what they don't (parameters, priors, shock sizes, sample, weights). The approach has three steps: **digitise the published results → find the parameter region that reproduces them → use that region as the Bayesian prior.**

### 3A. Turn published charts into numeric targets

- [ ] **P3.1** Extract Charts 5.1–5.6 and 6.1 from the 2014 PDF:
  - First try vector extraction (`pymupdf` `page.get_drawings()`): if the charts are vector paths, the line coordinates can be recovered exactly and mapped to axis units from the tick labels.
  - Fallback: WebPlotDigitizer at high zoom.
  - Save each series as `targets/chart_5_1_output_gap.csv` and so on, with `quarter, value`.
- [ ] **P3.2** Add the point values stated in the text as hard targets in `targets/text_targets.yaml`. Examples: RES_Y impact on output gap = 0.34; foreign-demand shock under exogenous policy: GDP Q1 −1.4, peak ≈ −2.0 at Q2, year-1 GDP −1.6, CPI trough −1.4 at Q5, year-1 CPI −0.9; endogenous policy: GDP peak −1.4, CPI peak −1.2.
- [ ] **P3.3** Add the 2011 Table 2 numbers as secondary targets (earlier model version; lower weight).
- [ ] **P3.4** Uncertainty band for each target. Digitisation error is about ±2–3% of the axis range; text values are rounded to 0.1. These bands define what "acceptable" means in P3.10.

### 3B. Steady states and sample period

- [ ] **P3.5** Steady states from data. For each period (full sample and the replication sample from P3.6), compute: mean potential growth (≈ mean `GROWTH`); mean unemployment; mean ex-post real rate; mean REER trend appreciation; and the Singapore–US real-rate differential (this pins down `rr_bar_ss − RR_US_BAR_SS`). Use HAC confidence intervals as acceptable ranges for `growth_ss`, `unr_ss`, `rr_bar_ss` and `dot_lz_ss`.
- [ ] **P3.6** Sample period:
  - **Replication sample:** end ≈ 2013Q4–2014Q2 (latest data available to the 2014 document). Start = latest first-available date across the six observables (probably set by `UNR` or the `CSI` components) — check that this is roughly mid-1990s or later.
  - **Current-use sample:** to the latest quarter. COVID (2020Q1–2021Q4) is handled by **scaling shock variances** (D5, Lenza–Primiceri 2022 style): all shock σ's are multiplied by estimated factors `s_2020Q1 … s_2021Q4` (or a peak factor plus geometric decay to save parameters), with Pareto/weak priors on the factors. Implemented in the Kalman filter as time-varying shock covariance (P2.7) and estimated in P4.
  - Robustness: Bai–Perron break tests on `GROWTH`, `PIE` and `DOT_LS`; recursive and rolling estimates in P4.8.

### 3C. GPM7 trade weights and foreign gaps

- [ ] **P3.7** Bloc membership in `config/blocs.yaml`, from public sources only (D1). GPM7 splits China (CH) out of GPM6's emerging Asia. Check membership of EA7, LA7 and RC7 against Carabenciov et al. (2013) and the IMF GPM papers, and record the source. Singapore is excluded from its own foreign aggregate.
- [ ] **P3.8** Weights:
  - `ω_i` (export shares for `YF`): Singapore **domestic exports** by partner, since re-exports add little domestic value. Robustness checks with total exports and OECD TiVA value-added exports.
  - `ξ_i` (import shares for `LCPIF`): retained imports by partner, with total imports as a robustness check.
  - Fixed weights = average over the replication sample; time-varying variant = rolling 3-year averages (chain-linked). Report the range of each weight across these variants as its acceptable range.
- [ ] **P3.9** Bloc output gaps `Y_i`: (a) HP filter (λ = 1600) on GDP-weighted bloc real GDP, (b) one-sided HP filter (real-time-like), (c) IMF WEO output gaps where available (annual, interpolated). Use the spread across methods as uncertainty about `YF`, and test sensitivity of β5.

### 3D. Parameter and shock-size ranges by IRF matching

- [ ] **P3.10** Minimum-distance IRF matching (Christiano–Eichenbaum–Evans style). Find θ minimising `(m(θ) − m̂)' W (m(θ) − m̂)`, where `m̂` stacks the digitised IRF and simulation targets and `W` is the inverse of the target variances from P3.4.
  - Shock σ's are identified by impact magnitudes. For example, `σ_RES_Y` = 0.34 / (impact multiplier of RES_Y on Y).
  - Persistence and slope parameters are identified by the IRF shapes (peak timing, half-lives, sign changes).
  - Steady states are fixed at P3.5 values (IRFs don't identify them).
- [ ] **P3.11** Acceptable-range region. Run a quasi-Bayesian (Laplace-type, Chernozhukov–Hong) MCMC over the matching objective with wide sign-respecting bounds, or ABC/SMC with a tolerance set by the P3.4 bands. The accepted draws define a **region of parameter vectors consistent with MAS's published model**; report the 5–95% range per parameter.
- [ ] **P3.12** Identification checks:
  - Iskrev (2010) rank test on the Jacobian of the IRF targets with respect to θ at the minimum-distance estimate: list parameters that the published IRFs can't identify.
  - For those, fall back to literature priors (P3.13) and single-equation estimates (P3.14).
- [ ] **P3.13** Literature prior table (`config/priors.yaml`, source column required): GPM family (Carabenciov et al. 2008, 2013), Berg–Karam–Laxton (2006), Parrado (2004) for the S$NEER rule, and other small open-economy semi-structural models (e.g. other central banks' QPMs).
- [ ] **P3.14** Single-equation data checks on HP-filtered gaps (OLS / GMM with lagged instruments for forward terms): Okun's law (α1, α2), Phillips curve (λ1–λ3), policy rule (γ1–γ4), UIP (κ). Used for plausibility bounds, not as final estimates.
- [ ] **P3.15** Combine into the final prior. For each parameter:
  - Centre = IRF-matching estimate (P3.10), or the literature value if not identified
  - Spread = wide enough to cover the P3.11 range and the plausible single-equation estimates
  - Distribution: Beta for (0,1) parameters; Gamma for positive slopes; Inverse-Gamma for σ's
  - Also calibrate trend-shock σ's relative to gap-shock σ's (signal-to-noise) so filtered trends are smooth; compare `LGDP_BAR` with an HP(1600) trend as a sanity check
- [ ] **P3.16** Prior predictive check: draw from the prior, compute IRFs, and confirm that ≥ ~70% of draws match the qualitative signs in the README benchmark table and that the published IRFs lie inside the prior predictive band.

**Exit criteria:** `config/priors.yaml` complete with sources; table of 5–95% ranges for every parameter, σ, steady state and trade weight; the minimum-distance fit reproduces all hard text targets within tolerance.

---

## Phase 4 — Bayesian estimation on data

- [ ] **P4.1** Log posterior = Kalman log-likelihood (P2.7) + log prior (P3.15). Return −∞ for BK failures.
- [ ] **P4.2** Posterior mode: multiple starts (L-BFGS-B / Nelder–Mead), followed by a numerical Hessian.
- [ ] **P4.3** Random-walk Metropolis–Hastings: 4 chains × 10,000 draws after 5,000 burn-in; proposal = scaled inverse Hessian; target acceptance 20–35%.
- [ ] **P4.4** Diagnostics via `arviz`: R-hat < 1.01, ESS > 400, trace and rank plots, and prior-vs-posterior plots (flag parameters whose posterior ≈ prior, i.e. not informed by data).
- [ ] **P4.5** Posterior IRFs (median and 68/90% bands) compared against the P3.1 targets. If they diverge, adjust prior tightness and re-run. Log each iteration in the decision log; this is the MAS-style "IRF properties" step.
- [ ] **P4.6** Save posterior draws to `estimation/results/{run_id}/draws.parquet` along with config hashes and the data vintage.
- [ ] **P4.7** Marginal likelihood (modified harmonic mean) for comparing specification variants, e.g. ΔLZ_GAP vs LZ_GAP in the Phillips curve, or fixed vs time-varying weights.
- [ ] **P4.8** Stability: recursive estimates (expanding end date) and rolling estimates. Report parameter drift.

**Exit criteria:** chains converge; posterior IRFs lie within the target bands for every hard text target; results are reproducible from `run_id`.

---

## Phase 5 — Outputs: links and calculations

**Goal:** turn the estimated model into the quantities used for analysis. Each output below lists its calculation chain.

### 5A. History (Kalman smoother)

- [ ] **P5.1** Unobservables at posterior mode and across posterior draws, with bands: `LGDP_BAR`, `Y` (output gap), `G`, `UNR_BAR`, `UNR_GAP`, `RR_BAR`, `LS_BAR`, `LZ_BAR`, `LS_GAP`, `LZ_GAP`, `CSI_BAR`, `CSI_GAP`, `E_CSI`.
  - Chain: panel.parquet → state space at θ → RTS smoother → states → (posterior draws) → percentiles
- [ ] **P5.2** Smoothed shocks (`RES_*` history) plus a normality / autocorrelation check for each.
- [ ] **P5.3** Historical shock decomposition of `Y`, `PIE4` and `DOT_LS` into contributions from: foreign demand, domestic demand, cost-push, monetary policy, risk premium, financial/credit, supply, initial conditions.
- [ ] **P5.4** Rule-implied policy: the S$NEER slope given by eq 17 with `RES_DOT_LS = 0` vs the actual slope, i.e. the history of "policy stance relative to the rule".

### 5B. Forecasts

- [ ] **P5.5** Unconditional baseline forecast (h = 12 quarters) from the last smoothed state.
- [ ] **P5.6** Conditional forecast on foreign paths built from **Bloomberg consensus** (D6):
  - Country consensus GDP growth and CPI forecasts (mostly calendar-year) → interpolate to quarterly paths (Denton / cubic-spline consistent with the annual totals) → bloc aggregates with P3.8 weights
  - Foreign output-gap path `YF` = forecast GDP level minus a trend extended at its latest growth rate (same filter as P3.9)
  - `PIEF` from aggregated CPI paths; `RR_US` from the US policy-rate consensus minus expected inflation
  - Fallback for countries without consensus coverage: AR projections, flagged in the output
  - Hard conditioning via shocks to the foreign AR processes, as GPM feeds the SMS in the original. Optional judgement tunes (e.g. a nowcast for the current quarter)
- [ ] **P5.7** Fan charts: simulate future shocks × posterior parameter draws → 30/60/90% bands.
- [ ] **P5.8** Conversions to headline numbers, in `analysis/outputs.py`:
  - Quarterly SAAR growth: `GROWTH = 4·ΔLGDP` (log approximation); exact form `100·(exp(ΔLGDP/100)^4 − 1)`
  - Year-on-year growth: `100·(exp((LGDP − LGDP(-4))/100) − 1)`
  - **Calendar-year GDP growth**: rebuild levels `exp(LGDP/100)`, sum the four quarters of each year, compute the % change. This is the number comparable with official annual forecasts
  - CPI inflation y-o-y and calendar-year average, computed the same way from `LCPI`. Note: the model's CPI is headline; MAS Core Inflation is not in the model
  - S$NEER policy slope (% p.a.): `DOT_LS`, and the equilibrium slope `DOT_LS_BAR`
  - Unemployment rate level: `UNR = UNR_BAR + UNR_GAP`

### 5C. Scenarios

- [ ] **P5.9** Scenario engine with a YAML spec: shock name or exogenous variable, path, anticipated/unanticipated, and policy endogenous/exogenous. Output = deviation from baseline for every variable, plus the P5.8 conversions.
- [ ] **P5.10** Standard scenario library:
  - Chart 6.1 foreign-demand shock (−1% for 4 quarters, then +0.25 pp per quarter back to 0) under both policy settings — the validation scenario
  - Policy slope change (±1 pp p.a. on `DOT_LS` for N quarters)
  - Risk-premium shock (`RES_RS_DIFF`)
  - Capital-requirement increase (`CAPREQ_BAR` +1 pp) — exercises the financial module (eqs 1, 15, 16)
  - Credit tightening (`E_CSI` > 0 for 4 quarters)
  - Foreign inflation / oil shock via `PIEF`
- [ ] **P5.11** Year-1 and year-2 summary table for each scenario in the format of MAS 2011 Table 2 (GDP, CPI, unemployment; % or pp deviation).

**Exit criteria:** the Chart 6.1 scenario reproduces the hard targets within tolerance; the forecast and fan chart run from a single command; every output is saved to `outputs/{run_id}/` as parquet with metadata.

---

## Phase 5B — Backtesting and forecast-error evaluation

**Goal:** measure how well the SMS forecasts, compared with simple benchmarks and with what forecasters actually expected at the time. The IRF checks in P3/P4 test whether the model *behaves* like MAS's; this phase tests whether it *forecasts* usefully. Lives in `backtest/` (package) and writes to `outputs/{run_id}/backtest/`.

### 5B-A. Design

- [ ] **P5B.1** Pseudo-out-of-sample, expanding window. At each forecast origin *t*:
  1. Truncate the panel at *t*.
  2. Re-estimate. Default: posterior mode re-estimated every origin. Full MCMC once a year (Q4 origins), reused for the next three origins' density forecasts.
  3. Run the Kalman filter to *t*.
  4. Forecast *h* = 1…8 quarters ahead.
  - Origins: quarterly from **2005Q1** (first full year of MAS SPF benchmarks) to the latest quarter with 8 quarters of outcomes, giving about 75 origins. A shorter run from 2010Q1 is the quick variant for development.
- [ ] **P5B.2** Data vintages: Bloomberg `PX_LAST` returns revised history, so this is **pseudo** real-time (revised data, but only data up to *t*).
  - State this limitation in every output.
  - Approximate publication lags at each origin: GDP and unemployment available to *t*−1, CPI to *t*, rates and NEER to *t*.
  - Optional later: a true real-time check on Singapore GDP using the advance-estimate history in `SGDSTOTQ`, if the vintage history is recoverable.
- [ ] **P5B.3** Three conditioning variants, run at every origin:
  - **(a) Unconditional** — foreign block follows its AR closure rules.
  - **(b) Ex-post conditional** — foreign paths set to their *actual* outcomes. Isolates domestic-model error from foreign-outlook error.
  - **(c) Real-time conditional** — foreign paths from the Bloomberg consensus available at *t* (the `ECGD/ECPI{cc} {yy}` history as of that date), exactly as the production forecast would run (P5.6).
  - Comparing (b) and (c) shows how much error comes from the foreign outlook.
- [ ] **P5B.4** Policy setting: endogenous (eq 17 active) by default. Also report a variant with the S$NEER path set to its actual outcome, to separate policy-rule error from the rest of the model.
- [ ] **P5B.5** COVID: report every metric for the full sample **and** excluding forecasts whose target falls in 2020Q1–2021Q4 (D5). GFC (2008Q3–2009Q4) is reported as a separate sub-period, not excluded.

### 5B-B. What is forecast and scored

- [ ] **P5B.6** Target variables, each at h = 1, 2, 4, 8 quarters plus calendar-year (current and next year):
  - Real GDP growth: q/q SAAR, y/y, calendar-year (P5.8 definitions)
  - CPI inflation: y/y and calendar-year
  - Unemployment rate (level)
  - 3M interbank rate (`RS`)
  - S$NEER slope (`DOT_LS`, % p.a.)
  - Outcomes = latest-vintage actuals from the panel.
- [ ] **P5B.7** Output-gap reliability (Orphanides–van Norden). Compare the real-time gap (filtered at origin *t*, end-point estimate) with the final gap (smoothed on the full sample). Report the revision mean, standard deviation, correlation, and sign-agreement rate, for the SMS gap and an HP-filter gap.

### 5B-C. Benchmarks

All benchmark forecasts use only information available at the origin. Their tickers are in `config/tickers.yaml` (`singapore.consensus`, `singapore.mas_spf`).

- [ ] **P5B.8** Statistical benchmarks: no-change random walk (level variables), AR(p) on growth/inflation with BIC lag choice re-estimated each origin, and the historical mean.
- [ ] **P5B.9** Survey benchmarks (calendar-year targets only):
  - **Bloomberg consensus** `ECGDSG/ECPISG {yy}`, taking the value as of each origin date.
  - **MAS SPF** median (`SGCFGDP`, `SGCFCPI`, `SGCFUNEM`; 2004Q3+). Match each survey round to the origin quarter.
  - Surveys have a timing advantage (they see monthly data within the quarter). Note this whenever the SMS is compared with them.
- [ ] **P5B.10** Optional: a hand-entered table of MAS official forecast ranges from past Monetary Policy Statements (`config/mas_official_forecasts.yaml`, midpoint used). Low priority.

### 5B-D. Error metrics and tests

For every variable × horizon × conditioning variant × sub-period, computed in `backtest/metrics.py`:

- [ ] **P5B.11** Point accuracy:
  - **Mean error (bias)** = mean(actual − forecast), with a HAC (Newey–West, lag *h*−1) t-test of bias = 0
  - Mean absolute error, root mean squared error
  - Theil's U = RMSE(SMS) / RMSE(random walk)
  - Relative RMSE against each benchmark
- [ ] **P5B.12** Forecast comparison: Diebold–Mariano tests against each benchmark, with the Harvey–Leybourne–Newbold small-sample correction (squared and absolute loss).
- [ ] **P5B.13** Forecast efficiency: Mincer–Zarnowitz regression `actual = a + b·forecast + e` (H0: a = 0, b = 1, HAC errors), and an error-autocorrelation check for h = 1.
- [ ] **P5B.14** Direction: hit rate for the sign of the change (GDP growth and inflation up/down vs previous period) and for turning points around the GFC and COVID.
- [ ] **P5B.15** Density forecasts (from the P5.7 fan-chart machinery):
  - Empirical coverage of the 68% and 90% bands vs nominal
  - PIT histogram and uniformity test (Berkowitz / Knüppel)
  - CRPS and log predictive score
- [ ] **P5B.16** Rolling diagnostics: 12-origin rolling RMSE and bias for GDP and CPI, to show whether performance has drifted (links to P4.8 parameter stability).
- [ ] **P5B.17** Error decomposition: for GDP and CPI, split total error in variant (c) into the foreign-outlook part (c − b) and the domestic-model part (b − actual). Also run a historical shock decomposition (P5.3) of the forecast errors for the largest misses.

### 5B-E. Outputs and acceptance

- [ ] **P5B.18** Save every origin's forecasts, actuals and errors in long form to `outputs/{run_id}/backtest/forecasts.parquet`. Columns: origin, target, h, variant, model, forecast, actual, plus density quantiles. Metrics tables go to `metrics.parquet`.
- [ ] **P5B.19** Backtest charts for the report (P6.9):
  - RMSE and bias by horizon, SMS vs benchmarks
  - Forecast-vs-actual fan of all origins ("hedgehog" chart) for GDP and CPI
  - Rolling RMSE
  - PIT histograms and band coverage
  - Real-time vs final output gap
- [ ] **P5B.20** Single command: `python run_sms.py backtest [--start 2005Q1] [--variants a,b,c] [--quick]`. Cache per-origin estimates so re-runs only compute new origins.
- [ ] **P5B.21** Acceptance criteria. These are targets, not hard gates; record any misses and their explanation in the decision log:
  - **Bias:** for GDP growth and CPI inflation, no statistically significant bias at h ≤ 4 (5% level, ex-COVID sample).
  - **vs simple benchmarks:** Theil's U < 1 for CPI at all horizons and for GDP at h ≥ 2. Relative RMSE vs AR ≤ 1.0 at h ≤ 4.
  - **vs surveys:** calendar-year RMSE within ~20% of the Bloomberg consensus and MAS SPF. Not expected to beat them, given their timing advantage.
  - **Bands:** 68% and 90% band coverage within ±10 pp of nominal.

**Exit criteria:** backtest runs end to end for all three conditioning variants from a single command; metrics, tests and charts are in the report; acceptance results are recorded in the decision log.

---

## Phase 6 — Charting and HTML report

Output format is a **static HTML report per run** (D7) — no live app. Interactive scenarios are run from the command line or notebooks and then re-rendered into the report.

### 6A. Charts (matplotlib, publication style)

- [x] **P6.1** Output format decided: static HTML report (D7). Charts in matplotlib; optionally Plotly for hover-enabled versions embedded as self-contained HTML.
- [ ] **P6.2** `analysis/plots.py`: shared style (fonts, colours, 2×2 panel layout like the MAS charts, "difference from baseline" vs "% deviation" axis labels).
- [ ] **P6.3** Replication charts: Charts 5.1–5.6 and 6.1 with the **digitised MAS line overlaid** (dashed) on the replicated IRF and its posterior band. This is the main validation visual.
- [ ] **P6.4** History charts: output gap with bands; potential growth; NAIRU vs actual unemployment; r* vs the real rate; S$NEER vs its trend and the rule-implied path; CSI vs its trend.
- [ ] **P6.5** Historical decomposition stacked bars for `Y` and `PIE4` (P5.3).
- [ ] **P6.6** Forecast fan charts for GDP growth, CPI inflation, unemployment and the S$NEER slope.
- [ ] **P6.7** Estimation diagnostics: prior vs posterior densities, trace plots, and recursive-estimate drift.
- [ ] **P6.8** A one-command run report: `outputs/{run_id}/report.html` with all of the above, the data vintage, `run_id` and config hashes.

### 6B. HTML report structure

- [ ] **P6.9** Report sections (one self-contained HTML file, with a table of contents):
  1. **Overview** — latest output gap, inflation, policy stance vs rule, headline forecast table
  2. **History** — unobservables with bands; historical decompositions
  3. **Forecast** — fan charts; quarterly and calendar-year tables; foreign outlook used (consensus vintage, fallbacks flagged)
  4. **Scenarios** — every scenario run in this `run_id`, both policy settings, plus a Table-2-style summary
  5. **IRFs** — all six replication charts, replicated vs MAS-digitised
  6. **Backtest** — P5B.19 charts, metrics tables by variable × horizon × variant, benchmark comparison, acceptance results (P5B.21)
  7. **Model & data** — parameter table (prior / posterior), MCMC diagnostics, data QA, lineage, decision log
- [ ] **P6.10** The report builder reads **only** from `outputs/{run_id}/` (model outputs), never from raw Bloomberg pulls. Chart data shown is model output; raw Bloomberg series appear only as charts (no data tables), and the report is for internal use (see [Bloomberg licensing](#bloomberg-licensing)).
- [ ] **P6.11** Export alongside the report: charts (PNG/SVG) and tables (CSV/XLSX) for briefing notes.
- [ ] **P6.12** Scenario CLI: `python run_sms.py scenario config/scenarios/<name>.yaml` runs a scenario and regenerates the report's Scenarios section.

**Exit criteria:** the report generates from a single command and opens offline in a browser; replication charts show replicated and MAS lines together.

---

## Phase 7 — Testing, validation and documentation (runs throughout)

- [ ] **P7.1** Unit tests: steady-state residuals, identities hold in simulated paths, BK on known cases, Kalman vs `statsmodels`, the transformations in P1.13, and the growth conversions in P5.8.
- [ ] **P7.2** Regression tests: IRFs at a frozen parameter vector match stored values (to 1e-8).
- [ ] **P7.3** Validation checklist in `run_sms.py`, which prints pass/fail for:
  - Every qualitative IRF property in the README benchmark table
  - Hard text targets within tolerance (P3.2)
  - Chart 6.1 targets under both policy settings
  - BK at the posterior mode; all IRFs back to baseline within 40 quarters
  - MCMC convergence (R-hat, ESS)
  - Backtest acceptance criteria (P5B.21), when a backtest has been run
- [ ] **P7.4** CI (GitHub Actions) running tests in synthetic-data mode. No Bloomberg in CI.
- [ ] **P7.5** Keep the README in sync: the "Status" note, Quick Start, and any changes to the specification resolutions.
- [ ] **P7.6** Final replication note (`docs/replication_note.md`): what matches, what doesn't, parameter table, deviations from MAS, known limitations.

---

## Cross-cutting constraints

### Bloomberg licensing
Bloomberg Terminal data is licensed for the user's own use; redistribution is restricted. Hence:
- Raw and processed Bloomberg data are never committed or published (already git-ignored).
- The HTML report is for internal use and shows **model outputs**; check the Bloomberg data-licence terms before circulating it beyond your team.
- The synthetic-data mode (P0.7) is what CI and external collaborators use.

### Reproducibility
Every run records the data vintage, config file hashes, git commit and random seeds in `outputs/{run_id}/meta.json`.

### Known limitations to carry through
- `PX_LAST` gives revised data, so the real-time output gap can't be replicated exactly.
- The S$NEER is a proxy (P1.12), so the policy-rule fit depends on proxy quality.
- GPM7 isn't available; foreign gaps are our own estimates (P3.9).
- The CSI construction is undocumented; ours is an approximation.

---

## Open questions

| # | Question | Needed by | Status |
|---|----------|-----------|--------|
| Q1 | Output format and hosting | P6.1 | Resolved → D7 |
| Q2 | S$NEER source | P1.4 | Resolved → D2 |
| Q3 | Foreign outlook source for conditional forecasts | P5.6 | Resolved → D6 |
| Q4 | COVID handling in the current-use sample | P3.6 | Resolved → D5 |
| Q5 | CSI construction | P1.4 | Resolved → D3 |
| Q6 | GPM7 bloc membership of EA7 / LA7 / RC7 | P3.7 | Research task (public IMF sources, per D1) — no user input needed |
| Q7 | Does `blpapi` publish a Python 3.13 wheel? If not, revisit D4 | P0.2 | Resolved — 3.26.x ships `py3-none-win_amd64` wheels; installed and tested |
| Q8 | Source for the expected US policy-rate path, since `ECPOUS {yy}` has no data: find the field that carries it, or use fed funds futures / OIS | P5.6 | Resolved 2026-10-28 → fed funds futures (`FF1`…`FF12 Comdty`), implemented in P5.6 |
| Q9 | X-13 hangs on some NSA CPI series (Hong Kong > 23 min, Indonesia > 60 s): per-call time limit with STL fallback (recorded per series), or restricted X-13 settings for those series | P1.13 | Resolved 2026-10-27 → 300 s limit + STL fallback (hang not reproduced: all series finish, slowest 74 s) |
| Q10 | CSI definition: the D3 blend does not tighten in 1998 or 2001 (posted-rate spread is sticky and moves with rate cuts; NIM is negatively correlated with it). Keep D3, or redefine (e.g. a market-based lending spread)? | P4 | Decided 2026-10-28 → keep D3 through Phases 2–3; before P4 compare with a market-based lending spread (evidence in `outputs/data_qa.html`) |

---

## Decision log

Add one row per decision, newest at the bottom.

| Date | ID | Decision | Rationale |
|------|----|----------|-----------|
| 2026-10-27 | Spec | Follow Appendix B of the 2014 Technical Overview where it conflicts with the main text; resolutions listed in README | Appendix is the complete equation listing; main text has symbol clashes |
| 2026-10-27 | D1 | No internal MAS materials; build from the two public PDFs plus Bloomberg (including Bloomberg proxies) and other public data | User has public-document access only — Phase 3 reverse-engineering is required |
| 2026-10-27 | D2 | S$NEER = BIS broad NEER for Singapore | Published, documented, monthly; Bloomberg proxies used only as cross-checks |
| 2026-10-27 | D3 | CSI = blend of z-scored loan–deposit spread and local banks' NIM | Closest to the source description of the CSI |
| 2026-10-27 | D4 | Re-pin dependencies for Python 3.13 rather than install 3.12 | User preference; 3.13 already installed (verify blpapi wheel, Q7) |
| 2026-10-27 | D5 | COVID handled by scaling shock variances (Lenza–Primiceri) | Keeps the data while stopping 2020–21 dominating estimates |
| 2026-10-27 | D6 | Foreign outlook from Bloomberg consensus forecasts (ECFC) | Available on the Terminal, updated frequently; AR fallback for uncovered countries |
| 2026-10-27 | D7 | Output = static HTML report per run, no live dashboard | Simplest to share internally; avoids hosting and licensing questions |
| 2026-10-27 | P1.4–P1.6 | `config/tickers.yaml` is the sole ticker source; 168 tickers verified against the Terminal (first written as 164, a miscount; 187 after the `neer_bilateral` additions) | One place to audit and change data sources; every series checked to resolve and return history |
| 2026-10-27 | P1.5 | Foreign CPI primary = IMF IFS `{code}6639` series (national series as cross-checks); euro area, China and Taiwan use national series | IFS gives one consistent, long (1980+) definition per country; national indices often rebase or start late |
| 2026-10-27 | P1.5 | Foreign GDP from national SA levels (or chained q/q growth); Bloomberg Economics `EHGQ*` series rejected | `EHGQ*` tickers resolve but return no data for this login |
| 2026-10-27 | P1.4 | Bank NIM field = `T12_NET_INT_MARGIN`; RS before 1999Q3 back-cast with IMF interbank rate; NEER before 1994 with IMF NEER | Longest consistent coverage for all three banks; extends the sample start limited by SIBOR and BIS NEER |
| 2026-10-27 | P5B | Backtest = expanding-window pseudo-out-of-sample from 2005Q1, three conditioning variants (unconditional / ex-post foreign / real-time consensus foreign), benchmarks = random walk, AR, Bloomberg consensus as of each origin, MAS SPF | Separates domestic-model error from foreign-outlook error; survey benchmarks are information-matched because Bloomberg keeps each target-year consensus history |
| 2026-10-27 | P3 | Prior construction = IRF matching to digitised MAS charts → literature priors for unidentified parameters → Bayesian estimation on data | MAS publishes model responses but no parameters; this mirrors their stated practice of tuning priors via IRF properties |
| 2026-10-27 | P0.2 | `requirements.txt` = exact pins of top-level packages only (transitives resolved by pip); `blpapi` kept out of it and installed from Bloomberg's index | User choice. Short, readable list that is easy to re-pin; synthetic mode and CI need no `blpapi`, and keeping Bloomberg's index out of the requirements file avoids mixing package indexes |
| 2026-10-27 | P0.2 | `arviz` pinned at 1.3.0, the restructured 1.x API (`arviz_base` / `arviz_stats` / `arviz_plots`) | Latest release with 3.13 wheels; P4.4 diagnostics must be written against the 1.x API, not 0.x examples |
| 2026-10-27 | P0.4 | `pyproject.toml` + `requirements.txt`: pyproject holds metadata, ruff/pytest config and optional extras (`fast`, `pdf`), and reads its dependencies from `requirements.txt` | User choice. One config file; pins live in one place. Ruff: line length 110 (existing code reached 108), rules E, W, F, I, B, UP, NPY |
| 2026-10-27 | P0.5 | `tasks.py` (plain Python) wrapping `run_sms.py`; pipeline steps are `run_sms.py` positional steps (no step = all). No Makefile | User choice. `make` is not installed on this Windows machine; matches the `run_sms.py` commands in P5B.20 and P6.12 |
| 2026-10-27 | P0.7 | Synthetic mode = seeded AR(1)/random-walk panel, turned on by `--synthetic` or `SMS_SYNTHETIC=1`; Bloomberg sessions refused in that mode; tests default to it, and live tests use the `bloomberg` pytest marker (`SMS_SYNTHETIC=0 pytest -m bloomberg`) | User choice. Pipeline and CI run without a Terminal, and nothing can reach Bloomberg by accident. To be replaced by model-simulated data after Phase 2 |
| 2026-10-27 | P0.7 | Panel contract (`data/panel.py`): quarterly `PeriodIndex` named `quarter`; columns `LGDP, UNR, LCPI, RS, LS, CSI, YF, LCPIF, RR_US, RR_US_BAR, CAPREQ_BAR` in README units | The synthetic and real panels must be interchangeable; P1.13 must produce this shape |
| 2026-10-27 | P0.3 | Config stubs created with planned shapes; `calibration.yaml` seeded with the README's assumed steady states (`RR_US_BAR_SS`, θ3, θ4 left null); `outputs/` ignored except `.gitkeep`; `notebooks/` and `docs/` deferred | Gives later tasks a fixed place to write to without inventing values |
| 2026-10-27 | P1.6b | Registry flattening defaults: missing `role` → `primary`, missing `status` → `verified`, missing `field` → `meta.default_field`; foreign rows get `var` = `Y_{cc}` (GDP) / `LCPI_{cc}` (CPI), following `Y_US` / `LCPI_US` | Rows such as `SEMCUSA` carry no role while their `SEMCEU` sibling is marked `crosscheck`; one naming scheme for all country series |
| 2026-10-27 | P1.6b | `collect_data.py` pulls at **native frequency** (daily / monthly / quarterly, calendar-aligned) from 1980; quarterly aggregation (averages for rates and indices, sums for flows) is left to P1.13 | User choice. Bloomberg's QUARTERLY periodicity returns end-of-quarter values, which are wrong for CPI, interest rates and trade flows |
| 2026-10-27 | P1.6b | Consensus tickers pulled for the current and next calendar year only, sampled at month-ends; backtest history (2005+) deferred to P5B | User choice. About 90 tickers instead of about 1,000; keeps the pull well inside the Terminal's API data limits |
| 2026-10-27 | P1.6b | One `bdh` request per (ticker, field, frequency), each with its own retry-protected session; trade rows default to monthly | Editing one registry entry re-pulls only that series; one bad ticker can't fail a batch; the registry's trade section is documented as all monthly |
| 2026-10-27 | P1.6b | Re-verification rules: an unresolved ticker, failed/empty pull, changed start or earlier end is a problem; a later end is only reported. Five spans corrected in the registry after the first full run | The registry `span` must describe the data actually available; new data arriving is expected and not a problem |
| 2026-10-27 | P1.3 | Vintage reads use as-of semantics (newest cached copy ≤ the vintage date; `end=None` → the vintage date) and are cache-only | Reproduces exactly what a pipeline run on that date saw, and a vintage read can never silently fetch newer data |
| 2026-10-27 | P1.7 | `CAPREQ_BAR` = minimum Tier 1 CAR **plus** the capital conservation buffer (phased in 2016–19, 10.5% from 2019); minimum-only kept as a robustness variant; countercyclical buffer excluded | User choice: the buffer is the effective constraint, since dipping into it restricts distributions |
| 2026-10-27 | P1.7 | `CAPREQ_BAR` undefined before 1992; quarterly value = requirement in force on the quarter's last day | User choice: no public source before 1992, and the sample starts in the mid-1990s (P3.6); quarter-end matches how the step dates (e.g. 30 Sep 2000, 30 Jun 2004) are announced |
| 2026-10-27 | P1.6a / P1.13a | CSI = mean of the z-scored components available each quarter: loan–deposit spread only before 2003, spread + NIM 2003–2021Q2, NIM only from 2021Q3 | User choice. No Singapore lending rate exists on Bloomberg after 2021Q2; treats both ends of the sample the same way with no new data source |
| 2026-10-27 | P1.11 | RS splice: SORA (after SIBOR ends) and the IMF rate (before 1999Q3) are each shifted by their average gap to 3M SIBOR over the overlap | User choice. One data-driven method for both ends; the IMF rate behaves like an overnight rate (~0.25 pp below SIBOR) |
| 2026-10-27 | P1.10 | Seasonal adjustment by X-13ARIMA-SEATS (statsmodels + Census `x13as.exe` in a git-ignored `tools/`), STL as fallback when the binary is absent | User choice. Statistical-agency standard; handles outliers and trading days |
| 2026-10-27 | P1.13 | Provisional `YF` / `LCPIF` until P3.7–P3.9: country-level (not bloc) aggregation; `YF` = total-export-share-weighted HP(1600) gaps of 100·ln SA real GDP, `LCPIF` = import-share-weighted chain-linked CPI; weights = 2003–2025 average shares, renormalised over countries with data; flagged provisional in the lineage | User choice. Lets the pipeline run end to end on real data now; Phase 3 replaces both |
| 2026-10-27 | P1.13a | CSI z-scores computed over each component's full available sample for now; the window is a parameter for P3.6 | User choice. Avoids guessing the estimation sample before P3.6 |
| 2026-10-27 | P1.13 | Registry: the two legs of `RR_US` get their own vars — `RS_US` (USGG3M, FDTR) and `PIE_EXP_US` (CONSPXMD, CIEFMICH); `RR_US = RS_US − PIE_EXP_US` | Code must find each leg from the registry without hard-coding tickers |
| 2026-10-27 | P1.12 | S$NEER episode check: a new episode starts at each slope change or re-centre; trend = OLS slope of 100·ln NEER within the episode (boundary months dropped, ≥ 6 months); "zero" agrees if \|slope\| < 2% p.a.; simple TWI uses fixed 2003–25 total-trade weights, chain-linked; `SGDPEN` excluded (history from 2025) | The band allows roughly ±2% around its path; short episodes give no reliable trend; chain-linking lets currencies enter mid-sample |
| 2026-10-27 | P1.12 | MAS decision history compiled by a research subagent from MAS primary sources, then spot-checked against three statements before use; pre-2001 entries kept with their low/medium confidence flags | MAS published no statements before Feb 2001; the flags keep weak entries visible |
| 2026-10-27 | P1.1 | Session-drop retry: 3 attempts with 2 s then 4 s backoff, only for dropped/timed-out/unstartable sessions; never for security or field errors, service-open failures, synthetic-mode refusals, or caller-supplied sessions | Transient Terminal disconnects recover automatically; entitlement and ticker errors fail fast; a caller's session can't be reopened from inside the request function |
| 2026-10-27 | Q9 | Each X-13 call has a 300 s time limit; on expiry `x13as.exe` is killed and the series falls back to STL, recorded as `stl (x13 timed out)`; X-13 errors fall back as `stl (x13 error)`. X-13 settings unchanged; each call runs in its own temp directory | User choice. The reported hang was not reproducible (slowest series 74 s), so this is a safety net; statsmodels waits with no limit and left the child running when Python was killed |
| 2026-10-27 | P1.13a | Bank NIM: `T12_NET_INT_MARGIN` up to the end of its last run of ≥ 4 consecutive quarters, then `IS_NET_INT_MARGIN_COMP_BASIS` (registry role `post`) level-shifted by its mean gap over the overlap, per bank | User choice. T12 is reported only half-yearly from 2020; the company-basis series is quarterly from 2013 |
| 2026-10-27 | P1.13a / Q10 | CSI keeps the D3 blend; the spread-only and NIM-only segments are level-matched to the blend over the 4 quarters of the both-component period nearest them. The failed 1998/2001 stress check is recorded and the CSI definition reopened as Q10 (before P4) | User choice. Removes the 1.5 pp composition step at 2021Q3 without changing D3 before more evidence |
| 2026-10-27 | P1.13 | `LS` back-cast: the IMF NEER is ratio-matched to the BIS NEER over the first 4 overlap quarters (1994), not the whole 1994–2026 overlap (`splice(..., join=4)`). RS keeps the full-overlap rule (P1.11) | User choice. The two indices drift apart over 30 years; the full-overlap ratio left a −4.3 pp step at 1994Q1. RS's joins were already smooth |
| 2026-10-27 | P1.13 | India GDP: the base-year break in `INBGGDRQ` at 2022Q2 (registry key `break`) is bridged by rescaling earlier levels so growth over 2022Q2–2023Q1 matches the published y/y series `INBGDRQY` (geometric mean of the 4 implied factors: ×1.618) | User choice. Bloomberg joins the 2011-12 and 2022-23 bases without a link; the 2022Q2 jump (+49%) distorted India's gap and YF |
| 2026-10-27 | P1.13 | Taiwan GDP primary = `TWRGSARP` (SA chained-volume level); `TWRGSAAR` demoted to crosscheck; `TWGDCONY` (y/y) added as crosscheck | User choice. The chained SAAR series missed official annual growth (2008 −2.0% vs +0.7%; 2010 8.3% vs 10.3%); `TWRGSARP` reproduces it |
| 2026-10-27 | P1.13 | Indonesia GDP left as built (y/y chained from a flat anchor year), flagged in lineage and `known_gaps` | User choice. YF is provisional until P3.9 |
| 2026-10-27 | P1.13 | Provisional `YF` / `LCPIF` keep quarters only where countries covering ≥ 50% of the trade weight have data (YF from 1995Q1); `LCPIF` refuses to chain across a coverage gap | Records the rule already in the code (`MIN_WEIGHT`), which was missing from the log |
| 2026-10-27 | P1.10 | `sa_candidates()` = primary NSA GDP/CPI series, i.e. exactly the 21 series P1.13 adjusts (growth-rate forms after chaining); unused history series excluded | Keeps the timing list and the build consistent |
| 2026-10-27 | P1.11 | `to_quarterly`: a daily series' final quarter is dropped when its last observation is more than 7 days before the quarter end | The month-only check kept partial quarters for daily data ending mid-way through a quarter's last month |
| 2026-10-27 | P1.14 | QA anomaly = \|z\| > 4 on the quarterly change (annualised for 100·ln levels; on the level for output gaps); each is matched to a dated explanation in `KNOWN_EVENTS` (`data/qa_report.py`); unmatched ones are reported as unexplained | Makes "no unexplained anomalies" (Phase 1 exit) checkable and repeatable on every refresh |
| 2026-10-28 | Q10 | Keep the D3 CSI blend through Phases 2–3; before P4, search the Terminal for a market-based lending spread (e.g. SGD corporate bond spreads) and compare it with D3 on the 1998 / 2001 / 2008–09 stress check before estimation | User choice. The CSI only matters once estimation starts; the comparison needs a candidate series first |
| 2026-10-28 | Q8 | Expected US policy-rate path for P5.6 = fed funds futures (generic `FF1`…`FF12 Comdty`), read as of each forecast date | User choice. Long history and as-of values, so backtest variant (c) uses what was known at each origin; `ECPOUS` has no data |
| 2026-10-28 | P3.8 | NODX weights: NODX shares where available; Philippines and Australia NODX imputed as total exports × the average NODX / total-exports ratio of the other partners (India's NODX covers the replication sample) | User choice. Keeps every partner in `ω_i` on a domestic-exports basis without dropping ~6% of trade |
| 2026-10-28 | P1.7 | `CAPREQ_BAR` post-2019 minima reconfirmed (CET1 6.5 / Tier 1 8.0 / Total 10.0%, CCB 2.5%, no D-SIB buffer) from DBS's 30 Jun 2026 Pillar 3 disclosure on the Notice 637 Annex 11A template; no data change | Closes the P1.7 note; the 2024–26 Notice versions changed risk-weighting, the countercyclical-buffer calculation and AT1/Tier 2 instruments, not the minima |
