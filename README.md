# Satellite Model of Singapore (SMS) — Replication

A Python replication of the **Satellite Model of Singapore (SMS)**, originally
developed by the MAS Economic Policy Group with the IMF Research Department
(first version June 2010; financial module added Feb 2011).

Source documents (in `resources/`):

> 1. *MAS EPG (2014). "The Satellite Model of Singapore (SMS): A Technical Overview."*
>    `resources/The Satellite Model of Singapore SMS A Technical Overview.pdf` — **primary specification**
> 2. *MAS (2011). "An Overview of the Satellite Model of Singapore." Macroeconomic Review, Vol. X(2), Special Feature A.*
>    `resources/Overview of SMS.pdf` — non-technical overview, earlier (GPM6-era) simulation results

> **Status:** Phase 0 (environment and skeleton) is complete. Built so far:
> the Bloomberg wrapper and cache (`data/bloomberg.py`), the ticker registry and
> its loader (`config/tickers.yaml`, `data/tickers.py`), a synthetic-data mode,
> and a `run_sms.py` runner whose model steps are still stubs. The model,
> estimation and analysis packages are empty. Progress is tracked in
> [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

---

## What is the SMS?

The SMS is a small, quarterly, New Keynesian semi-structural ("gap") model used
by MAS for:
- Economic forecasting (GDP, inflation, unemployment, exchange rates)
- Monetary policy analysis (exchange-rate-centred BBC framework)
- Scenario simulation (external shocks, credit conditions, capital requirements)

All dynamics are expressed as deviations from unobserved equilibrium (trend)
values. Trends are simple stochastic processes recovered with the Kalman
filter; parameters are partly calibrated and partly estimated by Bayesian
methods. The model is short-run New Keynesian and long-run neoclassical
(money is neutral in the long run; unemployment converges to the NAIRU).

Size (MAS 2011): **37 equations, 5 behavioural equations, 6 domestic observables**.
It has no sectoral or expenditure breakdown, no households or firms, and no
explicit trade block — the trade channel enters through the foreign output gap.

---

## Model Architecture

```
Block A — Stochastic trend processes (unobservable equilibria)
  Eq  (1) Potential output (LGDP_BAR), with drag from trend credit spread
  Eq  (2) Potential growth rate (G)
  Eq  (3) NAIRU level (UNR_BAR)
  Eq  (4) NAIRU drift component (UNR_G)
  Eq  (5) Equilibrium real interest rate (RR_BAR)
  Eq (6-9) Trend nominal / real exchange rates (LS_BAR, LZ_BAR, DOT_LS_BAR, DOT_LZ_BAR)

Block B — Behavioural equations
  Eq (10) Aggregate demand / output gap (Y)            ← main AD equation
  Eq (11-14) Financial linkage (CSI_GAP, E_CSI, E2_CSI)
  Eq (15) Trend credit spread (CSI_BAR) ← Tier-1 capital requirement (CAPREQ_BAR)
  Eq (16) Hybrid Phillips curve (PIE)
  Eq (17) Monetary policy reaction function (DOT_LS)   ← S$NEER Taylor-type rule
  Eq (18) Modified UIP (RS, 3-month interbank rate)
  Eq (19) S$NEER expectations (LS_E)
  Eq (20) Dynamic Okun's law (UNR_GAP)

Block C — Identities and definitions (Appendix B)
  Y, GROWTH, LS, LZ, LS_GAP, LZ_GAP, LCPI, PIE4, RR, UNR, CSI_GAP, YF, LCPIF, PIEF, ...

Exogenous foreign block (supplied by IMF GPM7 in the original)
  YF, LCPIF / PIEF, RR_US, RR_US_BAR, PIETARF
```

**Singapore-specific features:**
- Monetary policy sets the **slope of the S$NEER** (not an interest rate) — the "crawl" of the BBC framework (Parrado 2004)
- The interest rate is pinned down by a modified UIP condition, so the real-rate channel is an *external* effect
- The real exchange rate gap is the main policy transmission channel to output and inflation
- External demand (export-weighted foreign output gap **YF**) enters AD directly

---

## Full Model Specification

This is the specification to implement. It follows **Appendix B** of the 2014
Technical Overview (the equation listing), with the main-text equation numbers
shown for reference. `X(+k)` denotes a lead (model-consistent expectation) and
`X(-k)` a lag. All `RES_*` terms are i.i.d. N(0, σ²) shocks.

### Variable transformations

| Model variable | Construction |
|----------------|--------------|
| `LGDP` | 100 · ln(real GDP, SA) |
| `LCPI` | 100 · ln(CPI, SA) |
| `LS` | 100 · ln(S$NEER); increase = appreciation |
| `LCPIF` | 100 · ln(foreign CPI), import-share weighted over GPM7 blocs |
| `PIE` | 4 · (LCPI − LCPI(-1)) — q-o-q annualised, % |
| `PIE4` | LCPI − LCPI(-4) = (PIE + PIE(-1) + PIE(-2) + PIE(-3)) / 4 |
| `DOT_LS` | 4 · (LS − LS(-1)) — q-o-q annualised S$NEER appreciation |
| `RS` | 3-month nominal interbank rate, % p.a. |
| `UNR` | Total unemployment rate, % |
| `CSI` | Credit spread indicator (consumer loan − deposit rate spread / banks' NIM) |

### Trend processes (Block A)

```
(1)  LGDP_BAR = LGDP_BAR(-1) + G/4 − (μ/4)·(CSI_BAR − CSI_BAR(-40))/40 + RES_LGDP_BAR
(2)  G        = τ·growth_ss + (1−τ)·G(-1) + RES_G
(3)  UNR_BAR  = (1−α3)·UNR_BAR(-1) + α3·unr_ss + UNR_G + RES_UNR_BAR
(4)  UNR_G    = (1−α4)·UNR_G(-1) + RES_UNR_G
(5)  RR_BAR   = ρ·rr_bar_ss + (1−ρ)·RR_BAR(-1) + RES_RR_BAR
(6)  LS_BAR   = LS_BAR(-1) + DOT_LS_BAR/4 + RES_LS_BAR
(7)  LZ_BAR   = LZ_BAR(-1) + DOT_LZ_BAR/4 + RES_LZ_BAR
(8)  DOT_LZ_BAR = ψ2·dot_lz_ss + (1−ψ2)·DOT_LZ_BAR(-1) + RES_DOT_LZ_BAR
(9)  DOT_LS_BAR = DOT_LZ_BAR + PIETARF − PIETAR + RES_DOT_LS_BAR
```

### Behavioural equations (Block B)

```
(10) Y = β1·Y(-1) + β2·Y(+1) − β3·(RR(-1) − RR_BAR(-1)) − β4·LZ_GAP(-1)
         + β5·YF − β6·E2_CSI + RES_Y

(11) CSI_GAP = CSI − CSI_BAR
(12) CSI_GAP = ω·Y(+4) + RES_CSI_GAP
(13) E_CSI   = RES_CSI_GAP
(14) E2_CSI  = 0.12·E_CSI(-1) + 0.12·E_CSI(-2) + 0.12·E_CSI(-3) + 0.16·E_CSI(-4)
             + 0.20·E_CSI(-5) + 0.16·E_CSI(-6) + 0.12·E_CSI(-7)          (weights sum to 1)
(15) CSI_BAR = (1−θ1)·(θ3 − θ2·θ4) + θ1·CSI_BAR(-1) + (1−θ1)·θ2·CAPREQ_BAR(-1) + RES_CSI_BAR
     CAPREQ_BAR = CAPREQ_BAR(-1) + RES_CAPREQ_BAR

(16) PIE = λ1·PIE(+1) + (1−λ1)·PIE(-1) + λ2·Y − λ3·(LZ_GAP − LZ_GAP(-1))
           − λ4·RES_G − λ5·RES_LGDP_BAR + λ6·RES_CAPREQ_BAR − RES_PIE

(17) DOT_LS − DOT_LS_BAR = γ1·(DOT_LS(-1) − DOT_LS_BAR(-1))
           + (1−γ1)·[ γ2·(PIE4(+3) − PIETAR) − γ3·LS_GAP + γ4·Y ] + RES_DOT_LS

(18) RS = κ·[ RR_US + PIEF(+1) − 4·(LS_E − LS_E(-1)) + (RR_BAR(+1) − RR_US_BAR(+1)) ]
          + (1−κ)·RS(-1) + RES_RS_DIFF

(19) LS_E = ψ1·LS(+1) + (1−ψ1)·LS(-1)

(20) UNR_GAP = α1·UNR_GAP(-1) + α2·Y + RES_UNR_GAP
```

### Identities and definitions (Block C)

```
Y          = LGDP − LGDP_BAR
GROWTH     = 4·(LGDP − LGDP(-1))          GROWTH4     = LGDP − LGDP(-4)
GROWTH_BAR = 4·(LGDP_BAR − LGDP_BAR(-1))  GROWTH4_BAR = LGDP_BAR − LGDP_BAR(-4)

LS      = LS(-1) + DOT_LS/4               DOT4_LS = LS − LS(-4)
LZ      = LS − LCPIF + LCPI               (increase = real appreciation)
LS_GAP  = LS − LS_BAR                     LZ_GAP  = LZ − LZ_BAR

LCPI    = LCPI(-1) + PIE/4                PIE4 = (PIE + PIE(-1) + PIE(-2) + PIE(-3))/4
RR      = RS − PIE(+1)

UNR     = UNR_BAR + UNR_GAP

PIETAR  = PIETAR_SS                       PIETARF = PIETARF_SS
```

### Foreign block (exogenous to the SMS)

```
YF    = Σ_i ω_i · Y_i        ω_i = Singapore export share of GPM7 bloc i
LCPIF = Σ_i ξ_i · LCPI_i     ξ_i = Singapore import share of GPM7 bloc i
        i ∈ {US, EU, JA, CH, EA7, LA7, RC7}
PIEF  = 4·(LCPIF − LCPIF(-1))
LCPIF = LCPIF(-1) + PIETARF/4 + RES_LCPIF     (forecast/closure rule when GPM7 is not run)
RR_US, RR_US_BAR : US real rate and its equilibrium, taken from GPM7
```

In the original the foreign variables come from the IMF's GPM7 (Carabenciov et
al. 2013). A standalone replication should either feed them in as observed data
(with simple AR(1) / random-walk closure rules for forecasting) or link to a GPM
implementation.

### Parameters to calibrate or estimate

| Group | Parameters | Expected sign / range |
|-------|-----------|-----------------------|
| Potential output | τ, μ | τ ∈ (0,1); μ > 0 |
| NAIRU | α3, α4 | ∈ (0,1) |
| Equilibrium real rate | ρ | ∈ (0,1) |
| Equilibrium REER | ψ2 | ∈ (0,1) |
| Aggregate demand | β1, β2, β3, β4, β5, β6 | all > 0 (signs are in the equation) |
| Financial | ω, θ1, θ2, θ3, θ4 | θ1 ∈ (0,1); θ3, θ4 calibrated to the prevailing Tier-1 requirement |
| Phillips curve | λ1, λ2, λ3, λ4, λ5, λ6 | λ1 ∈ (0,1); others > 0 |
| Policy rule | γ1, γ2, γ3, γ4 | γ1 ∈ (0,1); others > 0 |
| UIP | κ | ∈ (0,1] |
| S$NEER expectations | ψ1 | ∈ (0,1) |
| Okun's law | α1, α2 | α1 ∈ (0,1); α2 < 0 under `UNR = UNR_BAR + UNR_GAP` |
| Steady states | growth_ss, unr_ss, rr_bar_ss, dot_lz_ss, PIETAR_SS, PIETARF_SS, RR_US_BAR_SS | calibrated |
| Shock std devs | one σ per `RES_*` term (18 shocks) | estimated |

Shocks: `RES_LGDP_BAR, RES_G, RES_UNR_BAR, RES_UNR_G, RES_RR_BAR, RES_LS_BAR,
RES_LZ_BAR, RES_DOT_LZ_BAR, RES_DOT_LS_BAR, RES_Y, RES_CSI_GAP, RES_CSI_BAR,
RES_CAPREQ_BAR, RES_PIE, RES_DOT_LS, RES_RS_DIFF, RES_UNR_GAP, RES_LCPIF`.
There are more shocks than observables; this is intended and handled by the
Bayesian/Kalman set-up.

### Inconsistencies in the source document and resolutions adopted

The 2014 main text (Section 3) and Appendix B differ in places. This
replication follows Appendix B unless noted.

| Item | Main text | Appendix B | Adopted |
|------|-----------|------------|---------|
| CSI_BAR coefficient in eq (1) | ν | μ | μ |
| Equilibrium REER persistence, eq (8) | ψ | ψ2 | ψ2 |
| S$NEER expectations, eq (19) | ρ (clashes with eq 5) | ψ1 | ψ1 |
| Trend-CSI coefficients, eq (15) | χ1–χ4, `CAPREQ_BAR(t)` | θ1–θ4, `CAPREQ_BAR(t−1)` | θ, `CAPREQ_BAR(t−1)` |
| REER term in Phillips curve, eq (16) | λ3·LZ_GAP | λ3·ΔLZ_GAP | ΔLZ_GAP (the text describes it as "the change in the real exchange rate gap") |
| Trend exchange rates, eqs (6)–(7) | DOT_X_BAR = 4·ΔX_BAR + RES | X_BAR = X_BAR(-1) + DOT_X_BAR/4 + RES | Appendix form |
| Unemployment gap sign | UNR_GAP = UNR_BAR − UNR | UNR = UNR_BAR + UNR_GAP | Appendix (UNR_GAP = UNR − UNR_BAR, so α2 < 0) |
| LCPIF closure | — | `LCPIF(-1) − PIETARF/4` as printed | `+PIETARF/4` (the printed minus is inconsistent with PIEF converging to PIETARF) |
| Capital-requirement shock name | RES_CAPREQ_BAR | RES_CAPREP_BAR | RES_CAPREQ_BAR (typo) |

`RES_PIE` enters with a negative sign in both versions; keep that sign so that
IRF directions match Chart 5.2.

---

## What the source documents do *not* provide

An exact numerical replication isn't possible from the public documents alone.
They do **not** report:
- Parameter values (posterior modes/means) or calibrated steady states
- Prior distributions
- Shock standard deviations (IRFs use one-σ shocks, so magnitudes depend on these)
- Estimation sample period or data vintages
- GPM7 bloc composition and export/import weights
- The exact construction of the CSI series
- The solution/estimation software used

The replication target is therefore **structural**: implement the equations
exactly, estimate on Singapore data, and tune priors and calibrations until the
model reproduces the published IRF shapes and simulation magnitudes (see
[Verification](#verification)). This is close to MAS's own process: the 2011
overview says the relative weights on data, priors and model structure "are
determined by examining the model's properties using impulse response
functions".

---

## Project Structure (planned)

Folders and files marked ✓ exist; the rest are planned.

```
Satellite-Model-of-Singapore/
├── config/                     # ✓ tickers.yaml (Bloomberg registry), calibration, priors, blocs, capreq
├── data/
│   ├── bloomberg.py            # ✓ Bloomberg Desktop API wrapper + parquet cache, session-drop retry
│   ├── check_bloomberg.py      # ✓ connectivity smoke test
│   ├── tickers.py              # ✓ loader for config/tickers.yaml
│   ├── panel.py                # ✓ panel columns, load_panel(), synthetic-mode switch
│   ├── synthetic.py            # ✓ seeded synthetic panel (no Bloomberg needed)
│   ├── collect_data.py         # Pull every registry series through bloomberg.py
│   ├── process_data.py         # Transformations → model-ready variables
│   ├── raw/                    # Downloaded raw data files       (git-ignored)
│   ├── processed/              # Transformed quarterly panel     (git-ignored)
│   └── foreign/                # GPM7 bloc data                  (git-ignored)
├── model/
│   ├── equations.py            # Full 37-equation system + SMSParams dataclass
│   ├── state_space.py          # Kalman filter / smoother
│   ├── solver.py               # Rational-expectations solution + IRF engine
│   └── __init__.py
├── estimation/
│   ├── priors.py               # Prior distributions for all parameters
│   ├── mcmc.py                 # Metropolis-Hastings MCMC
│   ├── diagnostics.py          # R-hat, ESS, trace plots
│   └── __init__.py
├── analysis/
│   ├── irf.py                  # Impulse response functions (Charts 5.1–5.6)
│   ├── simulation.py           # Foreign-demand shock, exogenous vs endogenous policy (Chart 6.1)
│   ├── plots.py                # Shared plotting utilities
│   └── __init__.py
├── backtest/                   # Pseudo-out-of-sample forecasts, benchmarks, error metrics
├── report/                     # HTML report template and builder
├── targets/                    # Digitised MAS chart data (committed)
├── tests/                      # ✓ pytest suite, runs in synthetic mode
├── outputs/                    # ✓ per-run outputs/{run_id}/ (git-ignored)
├── notebooks/
│   ├── 01_data_collection.ipynb
│   ├── 02_data_processing.ipynb
│   ├── 03_model_estimation.ipynb
│   ├── 04_irf_analysis.ipynb
│   └── 05_validation.ipynb
├── resources/
│   ├── The Satellite Model of Singapore SMS A Technical Overview.pdf
│   └── Overview of SMS.pdf
├── run_sms.py                  # ✓ End-to-end pipeline runner (steps are stubs for now)
├── tasks.py                    # ✓ Developer tasks: test, lint, bloomberg, pipeline steps
├── pyproject.toml              # ✓ Project metadata, ruff and pytest config, optional extras
├── requirements.txt            # ✓ Exact pins for Python 3.13
└── README.md
```

---

## Implementation Notes

### Solution method
The model has forward-looking terms — `Y(+1)`, `Y(+4)`, `PIE(+1)`, `PIE4(+3)`,
`LS(+1)`, `PIEF(+1)`, `RR_BAR(+1)`, `RR_US_BAR(+1)` — so it must be solved as a
linear rational-expectations system (Blanchard–Kahn / Klein 2000 generalised
Schur, or Sims' gensys). Check the Blanchard–Kahn condition (number of unstable
roots equals number of forward-looking variables) for every parameter draw, and
reject draws that are indeterminate or explosive.

### State-space size
`CSI_BAR(-40)` in eq (1) and `E_CSI(-1…-7)` in eq (14) need auxiliary lag
states (about 40 for CSI_BAR). Add leads beyond one period (`Y(+4)`, `PIE4(+3)`)
as chains of auxiliary one-period-ahead variables.

### Measurement equations
The six domestic observables map one-to-one to model variables with no
measurement error: `LGDP`, `UNR`, `LCPI` (or `PIE`), `RS`, `LS`, `CSI`. The
foreign variables (`YF`, `LCPIF`/`PIEF`, `RR_US`, `RR_US_BAR`) are treated as
observed exogenous inputs. The Kalman smoother then recovers `LGDP_BAR`, `G`,
`UNR_BAR`, `RR_BAR`, `LS_BAR`, `LZ_BAR` and `CSI_BAR`. Initialise the
non-stationary trends with a diffuse prior.

### Monetary policy switch
Section 6 needs two policy settings:
- **Endogenous**: eq (17) active.
- **Exogenous**: hold `LS` at its baseline path by dropping eq (17), or by
  solving for the `RES_DOT_LS` sequence that keeps `LS` on baseline.

### Calibration of capital requirements
θ3 and θ4 are calibrated to the Tier-1 capital requirement current at the time
(MAS Notice 637). With `CAPREQ_BAR` unchanged, eq (15) keeps `CSI_BAR` at its
historical level and potential output is unaffected.

---

## Quick Start (once implemented)

### 1. Install dependencies

Use **Python 3.13**. Every pin in `requirements.txt` has a 3.13 wheel.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
```

**Bloomberg API (`blpapi`).** `blpapi` is not on PyPI, so `pip install -r
requirements.txt` does not install it. Install it from Bloomberg's own index:

```bash
pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi==3.26.9.1
```

It needs a logged-in Bloomberg Terminal on the same machine (the Desktop API
listens on `localhost:8194`). Check the connection with
`python -m data.check_bloomberg`. Without a Terminal, use the synthetic-data
mode (`--synthetic` or `SMS_SYNTHETIC=1`); it needs no `blpapi`.

Optional extras (declared in `pyproject.toml`): `pip install -e ".[fast]"`
(`numba`, for the Kalman filter) and `pip install -e ".[pdf]"` (`pymupdf`, for
chart extraction in P3.1).

### 2. Run the full pipeline (end-to-end demo)

```bash
python run_sms.py --synthetic       # no Bloomberg needed; steps after `data` are stubs for now
python run_sms.py                   # real data (needs data/processed/panel.parquet, P1.13)
python run_sms.py --synthetic irf   # a single step: data, estimate, irf, simulate, backtest, report
```

Developer tasks (plain Python, no `make` needed):

```bash
python tasks.py test                # pytest, in synthetic mode
python tasks.py lint                # ruff check
python tasks.py bloomberg           # Bloomberg connectivity check
SMS_SYNTHETIC=0 python -m pytest -m bloomberg   # live Bloomberg tests, on a Terminal machine
```

Each run writes `outputs/{run_id}/meta.json` (mode, seed, git commit, config hashes).

Intended behaviour once built:
- Generate synthetic data (or load real data if present in `data/processed/`)
- Run a quick MCMC estimation (500 draws)
- Plot the six IRF charts (5.1–5.6)
- Run the foreign-demand shock simulation under both policy settings (6.1)
- Print the verification checklist

### 3. Or run notebooks in order

```
notebooks/01_data_collection.ipynb
notebooks/02_data_processing.ipynb
notebooks/03_model_estimation.ipynb   (adjust N_DRAWS as needed)
notebooks/04_irf_analysis.ipynb
notebooks/05_validation.ipynb
```

---

## Using Real Data

All series are quarterly and seasonally adjusted where applicable.

| Variable | Model name | Source | Notes |
|----------|-----------|--------|-------|
| Real GDP | `LGDP` | [SingStat Table Builder](https://tablebuilder.singstat.gov.sg) / [data.gov.sg](https://data.gov.sg) | Chained-dollar, SA |
| CPI | `LCPI` | SingStat | All-items CPI; seasonally adjust if using NSA series. Base year is irrelevant after logs/differences |
| Unemployment rate | `UNR` | MOM Labour Market Report | Overall unemployment rate, SA |
| 3-month interbank rate | `RS` | MAS Statistics / ABS | 3M SIBOR until its discontinuation (end-2024); splice to 3M compounded SORA afterwards |
| S$NEER | `LS` | Proxy needed | MAS does not publish the S$NEER index. Use the BIS broad NEER for Singapore, or build a trade-weighted index from MAS/SingStat bilateral rates |
| Credit spread indicator | `CSI` | MAS Statistics (banks' lending and deposit rates); MAS Financial Stability Review | Consumer loan rate − deposit rate, combined with banks' net interest margin. The exact construction isn't documented |
| Tier-1 capital requirement | `CAPREQ_BAR` | MAS Notice 637 | Step function of the regulatory minimum |
| Foreign output gaps | `Y_i` → `YF` | IMF WEO / GPM7, or HP-filtered real GDP of each bloc | Weight by Singapore domestic-export shares (SingStat trade data) |
| Foreign CPI | `LCPI_i` → `LCPIF` | IMF IFS / national sources | Weight by Singapore import shares |
| Foreign inflation target | `PIETARF` | Calibrated | Import-weighted average of bloc targets |
| US real rate and its trend | `RR_US`, `RR_US_BAR` | FRED (3M T-bill or fed funds − expected inflation); trend via HP filter or a Laubach–Williams-type r* | |

GPM7 blocs: US, Euro Area (EU), Japan (JA), China (CH), Emerging Asia (EA7),
Latin America (LA7), Rest of Countries (RC7). See Carabenciov et al. (2013)
for the bloc compositions.

---

## Calibrated Parameters (replication assumptions)

The source documents give **no** values for these. The defaults below are
assumptions made for this replication and should be revisited.

| Parameter | Default | Description | Basis |
|-----------|---------|-------------|-------|
| `growth_ss` | 2.5% p.a. | Long-run potential growth | Assumption; adjust to sample period |
| `unr_ss` | 3.0% | Steady-state unemployment (NAIRU) | Assumption |
| `rr_bar_ss` | 1.5% | Steady-state equilibrium real interest rate | Assumption |
| `PIETAR_SS` | 2.0% | Domestic inflation anchor | Assumption. MAS has no formal target; ~2% core inflation is generally treated as consistent with medium-term price stability |
| `PIETARF_SS` | 2.0% | Foreign inflation target | Assumption |
| `RR_US_BAR_SS` | — | Steady-state US equilibrium real rate | Must be set. Note that `rr_bar_ss − RR_US_BAR_SS` is the steady-state Singapore risk premium/discount in eq (18) |
| `dot_lz_ss` | 0.0% | Steady-state REER appreciation | Assumption; a positive value captures Balassa–Samuelson trend appreciation |
| `θ3`, `θ4` | — | Capital-requirement calibration | Prevailing Tier-1 requirement |

Steady-state consistency: `DOT_LS_BAR_ss = dot_lz_ss + PIETARF_SS − PIETAR_SS`.

---

## Estimation

Bayesian estimation via Metropolis-Hastings MCMC on the Kalman-filter likelihood:
1. Find the posterior mode by numerical optimisation, then use the inverse Hessian at the mode as the random-walk proposal covariance.
2. **Prior types:** Beta for persistence and weight parameters on (0,1) (τ, α1, α3, α4, ρ, ψ1, ψ2, θ1, λ1, γ1, κ); Gamma or truncated Normal for sign-restricted slopes (β, λ2–λ6, γ2–γ4, ω, μ); Inverse-Gamma for shock standard deviations. GPM-family papers (Carabenciov et al. 2008, 2013; Berg, Karam & Laxton 2006) are a reasonable starting point for prior means.
3. **Recommended:** 4 chains × 10,000 draws, discard the first 5,000 as burn-in, target acceptance rate 20–35%.
4. **Convergence:** Gelman-Rubin R-hat < 1.01, ESS > 400.
5. **Tune priors against IRFs:** if the posterior IRFs miss the benchmarks below, tighten the priors on the relevant parameters. This follows the documented MAS practice.

---

## Verification

The checklist in `run_sms.py` should test the qualitative IRF properties
described in Section 5 of the 2014 Technical Overview (all shocks = one σ),
plus the Section 6 simulation magnitudes.

### IRF benchmarks (Charts 5.1–5.6)

| Shock | Expected responses |
|-------|--------------------|
| `RES_Y` (AD, Chart 5.1) | Output gap jumps ≈ +0.34% on impact and stays above baseline one more quarter; CPI level rises persistently (~10 quarters); unemployment falls; S$NEER appreciates; all variables return to baseline |
| `RES_PIE` (negative inflation shock, Chart 5.2) | REER depreciates; output gap rises and stays above baseline ~2 years; S$NEER dips on impact, then rises above baseline from the next quarter; unemployment falls |
| `RES_DOT_LS` (faster S$NEER appreciation, Chart 5.3) | Output gap and y-o-y CPI inflation fall; policy then reverses to slower-than-baseline appreciation; unemployment rises |
| `RES_RS_DIFF` (risk premium, Chart 5.4) | Nominal interest rate rises persistently and returns to baseline slowly; output gap and inflation fall; S$NEER appreciation is slower than baseline at first |
| `RES_G` (potential growth, Chart 5.5) | GDP growth permanently higher; output gap barely moves; CPI slightly below baseline |
| `RES_LGDP_BAR` (potential level, Chart 5.6) | GDP growth spikes and reverts quickly; output gap barely moves; CPI slightly below baseline |

### Foreign demand shock (Chart 6.1)

Shock path for foreign GDP (`GDPF`, hence `YF`), % deviation from baseline:
−1.0 for quarters 1–4, then −0.75, −0.50, −0.25, and 0 from quarter 8 onwards.

| Outcome | Exogenous policy (S$NEER on baseline) | Endogenous policy (eq 17 active) |
|---------|---------------------------------------|----------------------------------|
| GDP, Q1 | −1.4% | smaller |
| GDP, peak | ≈ −2.0% after two quarters | −1.4% |
| GDP, year-1 average | −1.6% | smaller |
| CPI, trough | −1.4% in Q5 | −1.2% |
| CPI, year-1 average | −0.9%, and still below baseline in year 2 | smaller |
| S$NEER | unchanged | depreciates relative to baseline |

For reference, the earlier GPM6-era model (MAS 2011, Table 2) gave GDP −1.31%
and CPI −0.71% in year 1 under exogenous policy, and −0.86% and −0.55% with the
policy response. Peak unemployment was +0.3 pp exogenous and +0.2 pp with the
policy response.

### Additional sanity checks (not from the source documents)

- Blanchard–Kahn conditions hold at the posterior mode
- All IRFs return to baseline within 40 quarters (long-run monetary neutrality)
- Steady state reproduces `G = growth_ss`, `UNR = unr_ss`, `RR = rr_bar_ss`, `PIE = PIETAR`, and all gaps equal zero
- Under the posterior, the REER channel (β4) should dominate the real-rate channel (β3) in eq (10). This is a prior expectation for an exchange-rate-centred regime, not a result reported by MAS

---

## References

1. Monetary Authority of Singapore, EPG (2014). *The Satellite Model of Singapore (SMS): A Technical Overview.*
2. Monetary Authority of Singapore (2011). "An Overview of the Satellite Model of Singapore." *Macroeconomic Review*, Vol. X(2), Special Feature A.
3. Carabenciov, I., Freedman, C., Garcia-Saltos, R., Laxton, D., Kamenik, O. & Manchev, P. (2013). *GPM6 — The Global Projection Model with 6 Regions.* IMF WP/13/87.
4. Carabenciov, I., Ermolaev, I., Freedman, C., Juillard, M., Kamenik, O., Korshunov, D., Laxton, D. & Laxton, J. (2008). *A Small Quarterly Multi-Country Projection Model.* IMF WP/08/279.
5. Berg, A., Karam, P. & Laxton, D. (2006). *A Practical Model-Based Approach to Monetary Policy Analysis — Overview.* IMF WP/06/80.
6. Parrado, E. (2004). *Singapore's Unique Monetary Policy: How Does It Work?* MAS Staff Paper No. 31. (The 2011 overview cites the related *Inflation Targeting and Exchange Rate Rules in an Open Economy*, IMF WP/04/21.)
7. Klein, P. (2000). "Using the generalized Schur form to solve a multivariate linear rational expectations model." *Journal of Economic Dynamics and Control*, 24(10).
