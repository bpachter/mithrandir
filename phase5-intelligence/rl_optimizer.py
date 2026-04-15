"""
rl_optimizer.py — RL-style parameter optimizer for the QV screener

Treats QV screening as a parameter optimization problem:

    State:   Current market regime + recent backtested alpha
    Action:  Screening threshold vector
             [accrual_pct, manipulation_pct, distress_pct,
              min_quality_score, max_value_composite]
    Reward:  Risk-adjusted alpha (Sharpe × Information Ratio proxy)
             estimated from historical signal performance in signals.db

Optimization engine: Optuna (Bayesian TPE) with a SQLite study journal so
results accumulate across runs.  Falls back to random search if optuna is
not installed.

Usage:
    python rl_optimizer.py                 # Run 50 trials, print best params
    python rl_optimizer.py --trials 200    # More trials for higher quality
    python rl_optimizer.py --regime        # Factor in current market regime
    python rl_optimizer.py --apply         # Write best params to config
    python rl_optimizer.py --report        # Print optimization history

The optimizer is regime-aware: in Contraction/Crisis regimes it penalises
loose risk filters and rewards tighter quality gates; in Expansion it can
afford to widen the value net.
"""

import sys
import json
import logging
import sqlite3
import argparse
import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("rl_optimizer")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE          = Path(__file__).parent
_DB_PATH       = _HERE / "signals.db"
_QV_SRC        = _HERE.parent / "phase2-tool-use" / "quant-value" / "src"
_QV_DATA       = Path("C:/Users/benpa/QuantitativeValue")   # external data dir
_STUDY_DB      = _HERE / "rl_optimizer_study.db"
_BEST_PARAMS   = _HERE / "rl_best_params.json"

# Default screening parameters (current production values)
_DEFAULT_PARAMS = {
    "accrual_threshold":      95.0,
    "manipulation_threshold": 95.0,
    "distress_threshold":     95.0,
    "min_quality_score":      50,
    "max_value_composite":    30,
}

# ---------------------------------------------------------------------------
# Parameter search space
# ---------------------------------------------------------------------------

PARAM_SPACE = {
    # Risk filters (higher = more permissive, includes worse companies)
    "accrual_threshold":      (80.0, 99.0),   # exclude worst X% by accruals
    "manipulation_threshold": (80.0, 99.0),
    "distress_threshold":     (80.0, 99.0),
    # Quality gate: only top (100 - min_quality_score)% pass
    "min_quality_score":      (25,   75),
    # Value gate: only cheapest max_value_composite% pass
    "max_value_composite":    (15,   50),
}

# ---------------------------------------------------------------------------
# Market regime (from Phase 3 HMM)
# ---------------------------------------------------------------------------

def _get_regime() -> str:
    """Return the current HMM regime label, or 'Unknown'."""
    try:
        sys.path.insert(0, str(_HERE.parent / "phase3-agents" / "tools"))
        from regime_detector import get_regime
        info = get_regime()
        return info.get("regime", "Unknown")
    except Exception:
        return "Unknown"


# ---------------------------------------------------------------------------
# Reward signal: historical alpha from signals.db
# ---------------------------------------------------------------------------

def _load_signal_performance() -> pd.DataFrame:
    """
    Load all return rows from signals.db performance table.
    Returns DataFrame with columns: ticker, horizon_days, signal_return,
    spy_return, alpha, snapshot_dt.
    """
    if not _DB_PATH.exists():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(_DB_PATH)
        df = pd.read_sql_query(
            """
            SELECT s.ticker, s.snapshot_dt, s.value_composite, s.quality_score,
                   r.horizon_days, r.signal_return, r.spy_return, r.alpha
            FROM   signal_snapshots s
            JOIN   signal_returns   r ON s.id = r.snapshot_id
            WHERE  r.alpha IS NOT NULL
            """,
            conn,
        )
        conn.close()
        return df
    except Exception as e:
        logger.debug(f"Could not load signal performance: {e}")
        return pd.DataFrame()


def _regime_multiplier(regime: str) -> float:
    """
    Scale the reward based on how well a given parameter choice suits the
    current market regime.  Conservative params get a bonus in stressed
    regimes; aggressive params get a bonus in expansions.
    """
    return {
        "Expansion":   1.0,
        "Recovery":    1.0,
        "Contraction": 1.1,   # slight bonus for caution
        "Crisis":      1.2,
    }.get(regime, 1.0)


# ---------------------------------------------------------------------------
# Objective function
# ---------------------------------------------------------------------------

def _load_metrics() -> Optional[pd.DataFrame]:
    """Load the most recent metrics.csv from the QV data directory."""
    candidates = [
        _QV_DATA / "data" / "processed" / "metrics.csv",
        _QV_SRC / ".." / "data" / "processed" / "metrics.csv",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return pd.read_csv(p, low_memory=False)
            except Exception:
                pass
    return None


def _simulate_screen(
    metrics_df: pd.DataFrame,
    accrual_threshold: float,
    manipulation_threshold: float,
    distress_threshold: float,
    min_quality_score: int,
    max_value_composite: int,
) -> dict:
    """
    Run an in-memory simulation of the QV screener with the given params.
    Returns a dict of portfolio characteristics used to compute the reward.

    Uses the already-computed percentile columns in metrics_df rather than
    re-running the full screener to keep each trial fast (~5 ms).
    """
    df = metrics_df.copy()

    # ── Step 1: Risk filters ────────────────────────────────────────────────
    n_start = len(df)

    if "p_accrual_quality" in df.columns:
        df = df[df["p_accrual_quality"] <= accrual_threshold]

    if "p_manipulation" in df.columns:
        df = df[df["p_manipulation"] <= manipulation_threshold]

    if "p_distress" in df.columns:
        df = df[df["p_distress"] <= distress_threshold]

    n_after_risk = len(df)
    if n_after_risk == 0:
        return {"portfolio_size": 0, "reward": -10.0}

    # ── Step 2: Quality filter ──────────────────────────────────────────────
    quality_col = next(
        (c for c in ["quality_score", "p_financial_strength", "p_franchise_power"]
         if c in df.columns),
        None,
    )
    if quality_col:
        df = df[df[quality_col] >= min_quality_score]

    n_after_quality = len(df)
    if n_after_quality == 0:
        return {"portfolio_size": 0, "reward": -10.0}

    # ── Step 3: Value filter ────────────────────────────────────────────────
    value_col = next(
        (c for c in ["value_composite", "p_value_composite", "ev_ebit_percentile"]
         if c in df.columns),
        None,
    )
    if value_col:
        df = df[df[value_col] <= max_value_composite]

    portfolio_size = len(df)
    if portfolio_size == 0:
        return {"portfolio_size": 0, "reward": -10.0}

    # ── Portfolio quality metrics ────────────────────────────────────────────
    # Sector diversification (Shannon entropy, max = log(n_sectors))
    sector_diversity = 0.0
    if "sector" in df.columns:
        sector_counts = df["sector"].value_counts(normalize=True)
        entropy = -(sector_counts * np.log(sector_counts + 1e-9)).sum()
        max_entropy = np.log(max(len(sector_counts), 1))
        sector_diversity = entropy / max_entropy if max_entropy > 0 else 0.0

    # Average value quality (lower EV/EBIT is cheaper = better)
    avg_ev_ebit = None
    if "ev_ebit" in df.columns:
        vals = df["ev_ebit"].dropna()
        vals = vals[(vals > 0) & (vals < 100)]
        avg_ev_ebit = vals.mean() if len(vals) > 0 else None

    # Average F-score
    avg_fscore = None
    if "f_score" in df.columns:
        avg_fscore = df["f_score"].dropna().mean()

    return {
        "portfolio_size":  portfolio_size,
        "n_start":         n_start,
        "n_after_risk":    n_after_risk,
        "n_after_quality": n_after_quality,
        "sector_diversity": sector_diversity,
        "avg_ev_ebit":     avg_ev_ebit,
        "avg_fscore":      avg_fscore,
    }


def _compute_reward(
    sim: dict,
    perf_df: pd.DataFrame,
    params: dict,
    regime: str,
) -> float:
    """
    Compute the scalar reward for a parameter combination.

    Reward components:
    1. Historical alpha (primary): mean risk-adjusted alpha for stocks that
       would pass the quality + value gates, averaged across 90/180-day horizons.
    2. Portfolio size penalty: very small (<10) or very large (>150) portfolios
       are penalised — the former for concentration risk, the latter for dilution.
    3. Sector diversity bonus.
    4. Regime multiplier: tighter filters rewarded more in stress regimes.
    """
    if sim["portfolio_size"] == 0:
        return -10.0

    reward = 0.0

    # ── 1. Historical alpha (if available) ──────────────────────────────────
    if not perf_df.empty:
        # Filter to stocks that would have passed our quality + value gates
        # using the percentile columns stored in the signal snapshot.
        vc_col = "value_composite"
        qs_col = "quality_score"

        sub = perf_df.copy()
        if vc_col in sub.columns:
            sub = sub[sub[vc_col] <= params["max_value_composite"]]
        if qs_col in sub.columns:
            sub = sub[sub[qs_col] >= params["min_quality_score"]]

        # Use 90 and 180-day horizons
        sub = sub[sub["horizon_days"].isin([90, 180])]
        if len(sub) > 0:
            mean_alpha = sub["alpha"].mean()
            sharpe_proxy = mean_alpha / (sub["alpha"].std() + 1e-6)
            reward += 2.0 * sharpe_proxy    # weight historical alpha heavily
    else:
        # No signal history yet — reward based on portfolio characteristics alone
        # Prefer moderate-sized, diverse portfolios with cheap stocks
        if sim.get("avg_ev_ebit") is not None:
            reward += max(0, (20.0 - sim["avg_ev_ebit"]) / 20.0)  # cheaper = better
        if sim.get("avg_fscore") is not None:
            reward += (sim["avg_fscore"] - 5.0) / 4.0              # higher F-score = better

    # ── 2. Portfolio size ────────────────────────────────────────────────────
    size = sim["portfolio_size"]
    if size < 10:
        reward -= 2.0 * (10 - size) / 10      # strong penalty for tiny portfolios
    elif size > 150:
        reward -= (size - 150) / 100           # mild penalty for very large ones
    else:
        reward += 0.5                          # reasonable size bonus

    # ── 3. Sector diversity ──────────────────────────────────────────────────
    reward += sim.get("sector_diversity", 0.0) * 1.0

    # ── 4. Regime multiplier ─────────────────────────────────────────────────
    # Tighter risk filters score better in stressed regimes
    stress_score = (
        (params["accrual_threshold"]      - 80) / 19 +
        (params["manipulation_threshold"] - 80) / 19 +
        (params["distress_threshold"]     - 80) / 19
    ) / 3  # 0 = tightest, 1 = loosest

    rm = _regime_multiplier(regime)
    if regime in ("Contraction", "Crisis"):
        # Tighter = lower stress_score = higher bonus
        reward *= rm * (1 + 0.2 * (1 - stress_score))
    else:
        reward *= rm

    return reward


# ---------------------------------------------------------------------------
# Optuna study
# ---------------------------------------------------------------------------

def _run_optuna(
    metrics_df: pd.DataFrame,
    perf_df: pd.DataFrame,
    regime: str,
    n_trials: int,
) -> dict:
    """Run Bayesian optimisation via Optuna."""
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    storage = f"sqlite:///{_STUDY_DB}"
    study = optuna.create_study(
        study_name="qv_rl_optimizer",
        storage=storage,
        direction="maximize",
        load_if_exists=True,
    )

    def objective(trial):
        params = {
            "accrual_threshold":      trial.suggest_float("accrual_threshold",      *PARAM_SPACE["accrual_threshold"]),
            "manipulation_threshold": trial.suggest_float("manipulation_threshold", *PARAM_SPACE["manipulation_threshold"]),
            "distress_threshold":     trial.suggest_float("distress_threshold",     *PARAM_SPACE["distress_threshold"]),
            "min_quality_score":      trial.suggest_int(  "min_quality_score",      *PARAM_SPACE["min_quality_score"]),
            "max_value_composite":    trial.suggest_int(  "max_value_composite",    *PARAM_SPACE["max_value_composite"]),
        }
        sim    = _simulate_screen(metrics_df, **params)
        reward = _compute_reward(sim, perf_df, params, regime)
        return reward

    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    best_value = study.best_value
    logger.info(f"Optuna best reward: {best_value:.4f}  (over {len(study.trials)} total trials)")
    return best


def _run_random_search(
    metrics_df: pd.DataFrame,
    perf_df: pd.DataFrame,
    regime: str,
    n_trials: int,
) -> dict:
    """Fallback: uniform random search."""
    rng = np.random.default_rng(42)
    best_reward = -1e9
    best_params = dict(_DEFAULT_PARAMS)

    for _ in range(n_trials):
        params = {
            "accrual_threshold":      float(rng.uniform(*PARAM_SPACE["accrual_threshold"])),
            "manipulation_threshold": float(rng.uniform(*PARAM_SPACE["manipulation_threshold"])),
            "distress_threshold":     float(rng.uniform(*PARAM_SPACE["distress_threshold"])),
            "min_quality_score":      int(rng.integers(*PARAM_SPACE["min_quality_score"], endpoint=True)),
            "max_value_composite":    int(rng.integers(*PARAM_SPACE["max_value_composite"], endpoint=True)),
        }
        sim    = _simulate_screen(metrics_df, **params)
        reward = _compute_reward(sim, perf_df, params, regime)
        if reward > best_reward:
            best_reward = reward
            best_params = params

    logger.info(f"Random search best reward: {best_reward:.4f}  ({n_trials} trials)")
    return best_params


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report():
    """Print the optimisation history from the study DB."""
    if not _STUDY_DB.exists():
        print("No optimisation study found. Run the optimizer first.")
        return
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        storage = f"sqlite:///{_STUDY_DB}"
        study = optuna.load_study(study_name="qv_rl_optimizer", storage=storage)
        trials = study.trials_dataframe()
        if trials.empty:
            print("No completed trials yet.")
            return
        param_cols = [c for c in trials.columns if c.startswith("params_")]
        display = trials[["number", "value"] + param_cols].sort_values("value", ascending=False).head(10)
        display.columns = [c.replace("params_", "") for c in display.columns]
        print("\nTop 10 parameter combinations by reward:")
        print(display.to_string(index=False))
        print(f"\nBest params saved to: {_BEST_PARAMS}")
    except Exception as e:
        print(f"Could not load study: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_optimizer(n_trials: int = 50, use_regime: bool = False, apply: bool = False) -> dict:
    """
    Run the RL parameter optimizer and return the best params.

    Args:
        n_trials:   Number of parameter combinations to evaluate
        use_regime: If True, factor in the current HMM market regime
        apply:      If True, write best params to rl_best_params.json

    Returns:
        dict of best screening parameters
    """
    logger.info("Loading QV metrics data…")
    metrics_df = _load_metrics()
    if metrics_df is None:
        logger.warning("metrics.csv not found — using default parameters")
        return dict(_DEFAULT_PARAMS)

    # Filter to most recent annual period per ticker
    if "period_end" in metrics_df.columns and "frequency" in metrics_df.columns:
        annual = metrics_df[metrics_df["frequency"] == "annual"].copy()
        annual["period_end"] = pd.to_datetime(annual["period_end"], errors="coerce")
        metrics_df = annual.sort_values("period_end").groupby("ticker").last().reset_index()
    elif "ticker" in metrics_df.columns:
        metrics_df = metrics_df.groupby("ticker").last().reset_index()

    logger.info(f"Universe: {len(metrics_df)} companies")

    perf_df = _load_signal_performance()
    if perf_df.empty:
        logger.info("No signal performance history yet — optimizing on portfolio structure alone")
    else:
        logger.info(f"Signal performance: {len(perf_df)} return observations")

    regime = _get_regime() if use_regime else "Unknown"
    if use_regime:
        logger.info(f"Current market regime: {regime}")

    logger.info(f"Running optimizer ({n_trials} trials)…")
    try:
        import optuna  # noqa: F401
        best_params = _run_optuna(metrics_df, perf_df, regime, n_trials)
    except ImportError:
        logger.info("optuna not installed — using random search (pip install optuna for Bayesian)")
        best_params = _run_random_search(metrics_df, perf_df, regime, n_trials)

    # Validate sim with best params
    sim = _simulate_screen(metrics_df, **best_params)
    reward = _compute_reward(sim, perf_df, best_params, regime)

    logger.info("=" * 60)
    logger.info("OPTIMAL PARAMETERS FOUND")
    logger.info("=" * 60)
    for k, v in best_params.items():
        default_v = _DEFAULT_PARAMS[k]
        changed = " ← changed" if abs(float(v) - float(default_v)) > 0.5 else ""
        logger.info(f"  {k:<30} {v:>6}  (default: {default_v}){changed}")
    logger.info(f"  Portfolio size: {sim['portfolio_size']} stocks")
    logger.info(f"  Reward:         {reward:.4f}")
    logger.info("=" * 60)

    if apply:
        result = {
            "params":         best_params,
            "reward":         reward,
            "portfolio_size": sim["portfolio_size"],
            "regime":         regime,
            "timestamp":      datetime.datetime.now().isoformat(),
        }
        _BEST_PARAMS.write_text(json.dumps(result, indent=2))
        logger.info(f"Best params written to {_BEST_PARAMS}")

    return best_params


def load_best_params() -> dict:
    """
    Load previously optimised parameters, falling back to defaults.
    Called by quantitative_value.py when --optimized flag is used.
    """
    if _BEST_PARAMS.exists():
        try:
            data = json.loads(_BEST_PARAMS.read_text())
            params = data.get("params", data)
            age_days = (
                datetime.datetime.now() -
                datetime.datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
            ).days
            if age_days > 30:
                logger.warning(
                    f"Saved params are {age_days} days old — consider re-running the optimizer"
                )
            return params
        except Exception as e:
            logger.warning(f"Could not load saved params: {e}")
    return dict(_DEFAULT_PARAMS)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="QV screening parameter optimizer")
    parser.add_argument("--trials",  type=int,  default=50,    help="Number of trials (default 50)")
    parser.add_argument("--regime",  action="store_true",       help="Factor in current market regime")
    parser.add_argument("--apply",   action="store_true",       help="Write best params to rl_best_params.json")
    parser.add_argument("--report",  action="store_true",       help="Print optimization history and exit")
    args = parser.parse_args()

    if args.report:
        _print_report()
        return

    run_optimizer(n_trials=args.trials, use_regime=args.regime, apply=args.apply)


if __name__ == "__main__":
    main()
