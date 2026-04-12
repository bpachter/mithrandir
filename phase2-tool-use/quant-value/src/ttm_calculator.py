"""
Trailing Twelve Months (TTM) Calculator

Calculates rolling 12-month metrics from quarterly data for more current screening.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TTMCalculator:
    """Calculates Trailing Twelve Months (TTM) metrics from quarterly data."""

    def __init__(self):
        """Initialize TTM calculator."""
        # Income statement items that should be summed over 4 quarters
        self.income_statement_items = [
            'revenue', 'cogs', 'gross_profit', 'operating_income', 'ebit',
            'net_income', 'cfo', 'capex', 'dividends_paid'
        ]

        # Balance sheet items that should use the most recent quarter (point-in-time)
        self.balance_sheet_items = [
            'total_assets', 'current_assets', 'cash', 'total_liabilities',
            'current_liabilities', 'long_term_debt', 'total_equity', 'shares_diluted'
        ]

        # Derived metrics to recalculate after TTM
        self.derived_metrics = [
            'gross_margin', 'operating_margin', 'net_margin', 'fcf', 'fcf_margin',
            'debt_to_equity', 'debt_to_assets', 'roa', 'roe', 'current_ratio'
        ]

    def calculate_ttm(self, metrics_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate TTM metrics from quarterly and annual data.

        Args:
            metrics_df: DataFrame with both annual and quarterly metrics

        Returns:
            DataFrame with TTM metrics for each company
        """
        logger.info("Calculating Trailing Twelve Months (TTM) metrics")

        # Separate quarterly and annual data
        quarterly_df = metrics_df[metrics_df['frequency'] == 'quarterly'].copy()
        annual_df = metrics_df[metrics_df['frequency'] == 'annual'].copy()

        if quarterly_df.empty:
            logger.warning("No quarterly data found. Cannot calculate TTM.")
            return pd.DataFrame()

        # Sort by ticker and period to ensure proper ordering
        quarterly_df = quarterly_df.sort_values(['ticker', 'period_end'])

        # Calculate TTM for each company
        ttm_records = []

        for ticker in quarterly_df['ticker'].unique():
            ticker_data = quarterly_df[quarterly_df['ticker'] == ticker].copy()

            # Get most recent 4 quarters (or whatever is available)
            recent_quarters = ticker_data.tail(4)

            if len(recent_quarters) < 4:
                # Need at least 4 quarters for TTM, try to supplement with annual data
                logger.debug(f"{ticker}: Only {len(recent_quarters)} quarters available")
                # For now, skip companies without 4 quarters
                # Could enhance later to use annual + partial quarters
                continue

            ttm_record = self._calculate_ttm_for_company(ticker, recent_quarters, annual_df)

            if ttm_record is not None:
                ttm_records.append(ttm_record)

        if not ttm_records:
            logger.warning("No TTM records generated")
            return pd.DataFrame()

        ttm_df = pd.DataFrame(ttm_records)
        logger.info(f"Generated TTM metrics for {len(ttm_df)} companies")

        return ttm_df

    def _calculate_ttm_for_company(self, ticker: str, quarters: pd.DataFrame,
                                   annual_df: pd.DataFrame) -> Optional[dict]:
        """Calculate TTM metrics for a single company.

        Args:
            ticker: Stock ticker
            quarters: Last 4 quarters of data
            annual_df: Annual data (for fallback/validation)

        Returns:
            Dictionary with TTM metrics
        """
        if len(quarters) < 4:
            return None

        # Start with metadata from most recent quarter
        latest = quarters.iloc[-1]

        ttm_record = {
            'ticker': ticker,
            'cik': latest['cik'],
            'period_end': latest['period_end'],  # Most recent quarter end
            'ttm_end_date': latest['period_end'],
            'frequency': 'ttm',
            'data_quality': 'complete' if len(quarters) == 4 else 'partial'
        }

        # Sum income statement items over 4 quarters
        for item in self.income_statement_items:
            if item in quarters.columns:
                ttm_record[item] = quarters[item].sum() if quarters[item].notna().any() else np.nan

        # Use most recent quarter for balance sheet items (point-in-time)
        for item in self.balance_sheet_items:
            if item in latest.index:
                ttm_record[item] = latest[item]

        # Calculate derived metrics
        ttm_record.update(self._calculate_derived_metrics(ttm_record))

        # Calculate F-Score and Value Composite (requires specific logic)
        ttm_record['f_score'] = self._calculate_f_score(ttm_record, quarters)
        # Value composite will be calculated later during screening (needs all companies)

        return ttm_record

    def _calculate_derived_metrics(self, record: dict) -> dict:
        """Calculate derived metrics from base TTM data.

        Args:
            record: TTM record with base metrics

        Returns:
            Dictionary with derived metrics
        """
        derived = {}

        # Margins
        revenue = record.get('revenue', np.nan)
        if pd.notna(revenue) and revenue != 0:
            derived['gross_margin'] = record.get('gross_profit', np.nan) / revenue
            derived['operating_margin'] = record.get('operating_income', np.nan) / revenue
            derived['net_margin'] = record.get('net_income', np.nan) / revenue

        # Free Cash Flow
        cfo = record.get('cfo', np.nan)
        capex = record.get('capex', np.nan)
        if pd.notna(cfo) and pd.notna(capex):
            derived['fcf'] = cfo - capex
            if pd.notna(revenue) and revenue != 0:
                derived['fcf_margin'] = derived['fcf'] / revenue

        # Leverage ratios
        total_equity = record.get('total_equity', np.nan)
        total_assets = record.get('total_assets', np.nan)
        long_term_debt = record.get('long_term_debt', np.nan)

        if pd.notna(total_equity) and total_equity != 0:
            derived['debt_to_equity'] = long_term_debt / total_equity if pd.notna(long_term_debt) else np.nan

        if pd.notna(total_assets) and total_assets != 0:
            derived['debt_to_assets'] = long_term_debt / total_assets if pd.notna(long_term_debt) else np.nan

        # Profitability ratios
        net_income = record.get('net_income', np.nan)
        if pd.notna(total_assets) and total_assets != 0:
            derived['roa'] = net_income / total_assets if pd.notna(net_income) else np.nan

        if pd.notna(total_equity) and total_equity != 0:
            derived['roe'] = net_income / total_equity if pd.notna(net_income) else np.nan

        # Liquidity
        current_assets = record.get('current_assets', np.nan)
        current_liabilities = record.get('current_liabilities', np.nan)
        if pd.notna(current_assets) and pd.notna(current_liabilities) and current_liabilities != 0:
            derived['current_ratio'] = current_assets / current_liabilities

        return derived

    def _calculate_f_score(self, ttm_record: dict, quarters: pd.DataFrame) -> Optional[float]:
        """Calculate Piotroski F-Score for TTM period.

        F-Score is a 0-9 score measuring financial strength.

        Args:
            ttm_record: TTM metrics
            quarters: Last 4 quarters for trend analysis

        Returns:
            F-Score (0-9) or None
        """
        score = 0

        # Profitability signals (4 points)
        if pd.notna(ttm_record.get('roa')) and ttm_record['roa'] > 0:
            score += 1

        if pd.notna(ttm_record.get('cfo')) and ttm_record['cfo'] > 0:
            score += 1

        # ROA increasing (compare recent 4Q vs previous 4Q)
        if len(quarters) >= 8:
            recent_4q = quarters.tail(4)
            previous_4q = quarters.iloc[-8:-4]
            recent_roa = recent_4q.get('roa', pd.Series([np.nan])).mean()
            previous_roa = previous_4q.get('roa', pd.Series([np.nan])).mean()
            if pd.notna(recent_roa) and pd.notna(previous_roa) and recent_roa > previous_roa:
                score += 1

        # Quality of earnings (CFO > Net Income)
        net_income = ttm_record.get('net_income', np.nan)
        cfo = ttm_record.get('cfo', np.nan)
        if pd.notna(net_income) and pd.notna(cfo) and cfo > net_income:
            score += 1

        # Leverage, liquidity, and source of funds (3 points)
        # Decreasing long-term debt
        if len(quarters) >= 2:
            current_debt = quarters.iloc[-1].get('long_term_debt', np.nan)
            previous_debt = quarters.iloc[-2].get('long_term_debt', np.nan)
            if pd.notna(current_debt) and pd.notna(previous_debt) and current_debt < previous_debt:
                score += 1

        # Increasing current ratio
        if len(quarters) >= 2:
            current_cr = quarters.iloc[-1].get('current_ratio', np.nan)
            previous_cr = quarters.iloc[-2].get('current_ratio', np.nan)
            if pd.notna(current_cr) and pd.notna(previous_cr) and current_cr > previous_cr:
                score += 1

        # No new shares issued (shares not increasing)
        if len(quarters) >= 2:
            current_shares = quarters.iloc[-1].get('shares_diluted', np.nan)
            previous_shares = quarters.iloc[-2].get('shares_diluted', np.nan)
            if pd.notna(current_shares) and pd.notna(previous_shares) and current_shares <= previous_shares:
                score += 1

        # Operating efficiency (2 points)
        # Increasing gross margin
        if len(quarters) >= 2:
            current_gm = quarters.iloc[-1].get('gross_margin', np.nan)
            previous_gm = quarters.iloc[-2].get('gross_margin', np.nan)
            if pd.notna(current_gm) and pd.notna(previous_gm) and current_gm > previous_gm:
                score += 1

        # Increasing asset turnover (Revenue/Assets)
        if len(quarters) >= 8:
            recent_4q_rev = quarters.tail(4)['revenue'].sum()
            previous_4q_rev = quarters.iloc[-8:-4]['revenue'].sum()
            current_assets = quarters.iloc[-1].get('total_assets', np.nan)
            previous_assets = quarters.iloc[-5].get('total_assets', np.nan)

            if all(pd.notna(x) and x != 0 for x in [recent_4q_rev, previous_4q_rev, current_assets, previous_assets]):
                current_turnover = recent_4q_rev / current_assets
                previous_turnover = previous_4q_rev / previous_assets
                if current_turnover > previous_turnover:
                    score += 1

        return float(score) if score > 0 else np.nan


def calculate_ttm_from_csvs():
    """Calculate TTM metrics from existing CSV files."""
    from config import get_config

    config = get_config()
    metrics_path = config.get_metrics_path()

    if not metrics_path.exists():
        logger.error(f"Metrics file not found at {metrics_path}")
        return None

    logger.info(f"Loading metrics from {metrics_path}")
    metrics_df = pd.read_csv(metrics_path)

    calculator = TTMCalculator()
    ttm_df = calculator.calculate_ttm(metrics_df)

    # Save TTM data
    ttm_path = Path('data/processed/metrics_ttm.csv')
    ttm_df.to_csv(ttm_path, index=False)
    logger.info(f"Saved TTM metrics to {ttm_path}")

    return ttm_df


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    calculate_ttm_from_csvs()
