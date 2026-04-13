"""
regime_detector.py — HMM market regime detection for Enkidu

Trains a Gaussian HMM on SPY features (weekly return, rolling volatility,
price/200MA ratio) to identify 4 hidden market states, then labels each state
by its mean return and volatility profile:

    Expansion   — positive returns, low volatility
    Contraction — negative/flat returns, moderate volatility
    Crisis      — sharply negative returns, high volatility
    Recovery    — positive returns, elevated volatility (bouncing off lows)

Usage:
    from regime_detector import get_regime

    info = get_regime()
    # info = {
    #     "regime": "Expansion",
    #     "confidence": 0.91,
    #     "weekly_return": 0.012,
    #     "volatility_30d": 0.011,
    #     "price_vs_200ma": 1.04,
    #     "summary": "Expansion (91% confidence)..."
    # }

The trained model is cached at tools/regime_model.pkl so it loads instantly
after the first run. Call retrain() to force a fresh download + retrain.
"""

import os
import pickle
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_PATH = os.path.join(_HERE, "regime_model.pkl")

# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _fetch_features(years: int = 10) -> pd.DataFrame:
    """
    Download SPY history and compute 3 HMM features:
        weekly_return    — 5-day log return
        volatility_30d   — rolling 30-day std of daily log returns
        price_vs_200ma   — close / 200-day SMA ratio
    Returns a clean DataFrame with no NaNs, indexed by date.
    """
    end = datetime.today()
    start = end - timedelta(days=365 * years + 60)  # extra buffer for MA warmup

    spy = yf.download("SPY", start=start.strftime("%Y-%m-%d"),
                      end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)

    if spy.empty:
        raise RuntimeError("yfinance returned empty data for SPY")

    close = spy["Close"].squeeze()

    log_ret = np.log(close / close.shift(1))
    weekly_ret = np.log(close / close.shift(5))
    vol_30 = log_ret.rolling(30).std()
    ma_200 = close.rolling(200).mean()
    price_vs_ma = close / ma_200

    df = pd.DataFrame({
        "weekly_return": weekly_ret,
        "volatility_30d": vol_30,
        "price_vs_200ma": price_vs_ma,
    }).dropna()

    return df


# ---------------------------------------------------------------------------
# Regime labeling
# ---------------------------------------------------------------------------

def _label_states(model: GaussianHMM, n_states: int) -> dict[int, str]:
    """
    Assign human-readable regime names to HMM states based on their
    mean weekly return and volatility.

    States sorted by mean return (descending):
        highest return  → Expansion
        second highest  → Recovery
        second lowest   → Contraction
        lowest return   → Crisis
    """
    means = model.means_  # shape (n_states, n_features)
    # feature order: weekly_return, volatility_30d, price_vs_200ma
    ret_means = means[:, 0]

    order = np.argsort(ret_means)[::-1]  # descending by return

    names = ["Expansion", "Recovery", "Contraction", "Crisis"]
    if n_states < 4:
        names = names[:n_states]

    return {int(order[i]): names[i] for i in range(len(names))}


# ---------------------------------------------------------------------------
# Train / load model
# ---------------------------------------------------------------------------

def retrain(years: int = 10, n_states: int = 4, n_iter: int = 200) -> dict:
    """
    Download fresh SPY data, train the HMM, save to disk, and return
    the current regime info.
    """
    df = _fetch_features(years=years)
    X_raw = df[["weekly_return", "volatility_30d", "price_vs_200ma"]].values

    scaler = StandardScaler()
    X = scaler.fit_transform(X_raw)

    model = GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=n_iter,
        random_state=42,
    )
    model.fit(X)

    labels = _label_states(model, n_states)
    payload = {
        "model": model,
        "scaler": scaler,
        "labels": labels,
        "feature_df": df,
        "trained_at": datetime.now().isoformat(),
    }

    with open(_MODEL_PATH, "wb") as f:
        pickle.dump(payload, f)

    return _predict_current(payload, df)


def _load_or_train() -> dict:
    """Load cached model if it exists and is <7 days old, else retrain."""
    if os.path.exists(_MODEL_PATH):
        try:
            with open(_MODEL_PATH, "rb") as f:
                payload = pickle.load(f)
            trained_at = datetime.fromisoformat(payload["trained_at"])
            if (datetime.now() - trained_at).days < 7:
                return payload
        except Exception:
            pass

    return {"model": None, "labels": {}, "feature_df": pd.DataFrame(),
            "trained_at": "", "_needs_train": True}


# ---------------------------------------------------------------------------
# Current regime prediction
# ---------------------------------------------------------------------------

def _predict_current(payload: dict, df: pd.DataFrame) -> dict:
    model: GaussianHMM = payload["model"]
    labels: dict = payload["labels"]
    scaler: StandardScaler = payload.get("scaler")

    X_raw = df[["weekly_return", "volatility_30d", "price_vs_200ma"]].values
    X = scaler.transform(X_raw) if scaler is not None else X_raw

    # Predict state sequence and get posterior probabilities for last row
    hidden_states = model.predict(X)
    posteriors = model.predict_proba(X)

    current_state = int(hidden_states[-1])
    current_proba = float(posteriors[-1, current_state])
    current_label = labels.get(current_state, f"State {current_state}")

    last = df.iloc[-1]
    weekly_ret = float(last["weekly_return"])
    vol = float(last["volatility_30d"])
    vs_ma = float(last["price_vs_200ma"])

    summary = (
        f"{current_label} ({current_proba:.0%} confidence) — "
        f"SPY weekly return: {weekly_ret:+.2%}, "
        f"30d volatility: {vol:.2%}, "
        f"price vs 200MA: {vs_ma:.3f}x"
    )

    return {
        "regime": current_label,
        "confidence": round(current_proba, 3),
        "weekly_return": round(weekly_ret, 4),
        "volatility_30d": round(vol, 4),
        "price_vs_200ma": round(vs_ma, 4),
        "summary": summary,
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_regime() -> dict:
    """
    Return the current market regime and key stats.
    Loads cached model if available and recent; retrains if stale or missing.
    """
    payload = _load_or_train()

    if payload.get("_needs_train") or payload["model"] is None:
        return retrain()

    df = payload["feature_df"]

    # If feature data is >3 days stale, fetch fresh features for current prediction
    # (model weights stay the same; only the input changes)
    last_date = df.index[-1]
    if (datetime.now() - last_date.to_pydatetime().replace(tzinfo=None)).days > 3:
        try:
            df = _fetch_features(years=1)  # lightweight refresh
            payload["feature_df"] = df
        except Exception:
            pass  # fall back to cached features

    return _predict_current(payload, df)


def get_regime_context() -> str:
    """
    Returns a plain-English context block for injection into the system prompt.
    Never raises — returns a neutral string on failure.
    """
    try:
        r = get_regime()
        screening_note = {
            "Expansion":   "Standard QV thresholds are appropriate.",
            "Recovery":    "Consider slightly relaxed value thresholds — quality matters more in recovery.",
            "Contraction": "Tighten value filters; prioritize high F-Score and low debt.",
            "Crisis":      "Extreme caution. Favor cash-rich, low-debt names; avoid cyclicals.",
        }.get(r["regime"], "")

        return (
            f"[MARKET REGIME — {r['as_of']}]\n"
            f"Current regime: {r['regime']} (confidence: {r['confidence']:.0%})\n"
            f"SPY weekly return: {r['weekly_return']:+.2%} | "
            f"30d volatility: {r['volatility_30d']:.2%} | "
            f"Price vs 200MA: {r['price_vs_200ma']:.3f}x\n"
            f"Screening guidance: {screening_note}"
        )
    except Exception as e:
        return f"[MARKET REGIME] Unavailable ({e})"


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Training / loading HMM regime model...")
    info = get_regime()
    print(f"\nCurrent regime: {info['regime']}")
    print(f"Confidence:     {info['confidence']:.0%}")
    print(f"As of:          {info['as_of']}")
    print(f"\nSummary: {info['summary']}")
    print(f"\nContext block:\n{get_regime_context()}")
