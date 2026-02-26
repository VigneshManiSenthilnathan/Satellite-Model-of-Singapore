# Satellite Model of Singapore (SMS) — Replication

A Python replication of the **Satellite Model of Singapore (SMS)**, originally
developed by the MAS Economic Policy Group (2010, revised 2011).

> *MAS EPG (2014). "The Satellite Model of Singapore: A Technical Overview."*
> `resources/The Satellite Model of Singapore SMS A Technical Overview.pdf`

---

## What is the SMS?

The SMS is a New Keynesian semi-structural macroeconomic model used by MAS for:
- Economic forecasting (GDP, inflation, unemployment, exchange rates)
- Monetary policy analysis (exchange-rate-centred BBC framework)
- Scenario simulation (external shocks, financial conditions, capital requirements)

It is a **gap model** — all dynamics are expressed as deviations from
unobserved equilibrium (trend) values estimated via Bayesian methods.

---

## Model Architecture

```
Block A — Stochastic Trend Processes (unobservable equilibria)
  Eq  (1) Potential output (LGDP_BAR)
  Eq  (2) Potential growth rate (G)
  Eq  (3) NAIRU (UNR_BAR)
  Eq  (4) NAIRU growth component (UNR_G)
  Eq  (5) Equilibrium real interest rate (RR_BAR)
  Eq (6-9) Trend exchange rates (DOT_LS_BAR, DOT_LZ_BAR)

Block B — Behavioural Equations (observable dynamics)
  Eq (10) Aggregate demand / Output gap (Y)        ← main AD equation
  Eq (11-14) Financial linkage (CSI_GAP, E_CSI, E2_CSI)
  Eq (15) Trend credit spread (CSI_BAR)
  Eq (16) Hybrid Phillips curve (PIE)              ← inflation
  Eq (17) Monetary policy reaction function (DOT_LS) ← S$NEER Taylor rule
  Eq (18) Modified UIP / SIBOR (RS)
  Eq (19) S$NEER expectations (LS_E)
  Eq (20) Okun's Law (UNR_GAP)

Block C — Accounting identities
  LZ, LZ_GAP, LS_GAP, PIE4, RR, UNR, etc.
```

**Singapore-specific features:**
- Monetary policy targets the **S$NEER** (not interest rates) — BBC framework
- External demand (weighted foreign output gap **YF**) dominates the AD equation
- Financial module (CSI, capital requirements) added Feb 2011

---

## Project Structure

```
SMS-replication/
├── data/
│   ├── collect_data.py         # Data download / stub generation
│   ├── process_data.py         # Transformations → model-ready variables
│   ├── raw/                    # Downloaded raw data files
│   ├── processed/              # Transformed quarterly panel
│   └── foreign/                # GPM7 bloc data
├── model/
│   ├── equations.py            # All 20 SMS equations + SMSParams dataclass
│   ├── state_space.py          # Kalman filter / smoother
│   ├── solver.py               # Transition matrices + IRF engine
│   └── __init__.py
├── estimation/
│   ├── priors.py               # Prior distributions for all parameters
│   ├── mcmc.py                 # Metropolis-Hastings MCMC
│   ├── diagnostics.py          # R-hat, ESS, trace plots
│   └── __init__.py
├── analysis/
│   ├── irf.py                  # Impulse response functions (6 charts)
│   ├── simulation.py           # Policy scenario simulations
│   ├── plots.py                # Shared plotting utilities
│   └── __init__.py
├── notebooks/
│   ├── 01_data_collection.ipynb
│   ├── 02_data_processing.ipynb
│   ├── 03_model_estimation.ipynb
│   ├── 04_irf_analysis.ipynb
│   └── 05_validation.ipynb
├── resources/
│   └── The Satellite Model of Singapore SMS A Technical Overview.pdf
├── run_sms.py                  # End-to-end pipeline runner
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the full pipeline (end-to-end demo)

```bash
python run_sms.py
```

This will:
- Generate synthetic data
- Run a quick MCMC estimation (500 draws)
- Plot all 6 IRF charts
- Run all 4 policy simulations
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

Replace the synthetic stubs in `data/collect_data.py` with actual data:

| Variable | Source | Notes |
|----------|--------|-------|
| Real GDP | [data.gov.sg](https://data.gov.sg) | Quarterly SA, 2015 prices |
| CPI | Singapore DOS | 2019=100 |
| Unemployment | MOM / DOS | Total unemployment rate |
| SIBOR | MAS / Bloomberg | 3-month, % p.a. |
| S$NEER | [MAS Statistics](https://www.mas.gov.sg/statistics) | Index, appreciation = increase |
| Credit spread | MAS FSR / Annual Report | Consumer loan − deposit rate |
| Foreign GDP | IMF WEO | 7 GPM7 blocs |
| Foreign CPI | IMF IFS | Import-share weighted |

---

## Calibrated Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `growth_ss` | 2.5% p.a. | Long-run potential growth |
| `unr_ss` | 3.0% | Structural unemployment |
| `rr_bar_ss` | 1.5% | Neutral real interest rate |
| `PIETAR` | 2.0% | MAS inflation target |
| `dot_lz_ss` | 0.0% | Steady-state REER appreciation |

---

## Estimation

Bayesian estimation via Metropolis-Hastings MCMC:
- **Prior types:** Beta (persistence), Normal (slopes), InvGamma (shock stds)
- **Recommended:** 4 chains × 10,000 draws, discard 5,000 burn-in
- **Convergence:** Gelman-Rubin R-hat < 1.01, ESS > 400

---

## Verification

Run `python run_sms.py` and check the verification checklist output.
All 8 checks should pass with the default parameters.

Key benchmarks from the technical guide (Chart 5.1):
- AD shock → output gap peaks at ~0.34%
- AD shock → S$NEER appreciates
- REER channel coefficient (β₄) > interest rate channel (β₃)
- Taylor coefficient (γ₂) > 1 (nominal anchor maintained)

---

## References

1. MAS EPG (2014). *The Satellite Model of Singapore: A Technical Overview.*
2. Carabenciov et al. (2013). *GPM6 — The Global Projection Model with 6 Regions.* IMF WP/13/87.
3. Parrado (2004). *Singapore's Unique Monetary Policy: How Does It Work?* MAS Staff Paper No. 31.
4. Klein (2000). *Using the generalized Schur form to solve a multivariate LRE model.* JEDC.
