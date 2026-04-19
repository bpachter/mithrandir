"""
Compute derived screening metrics from fundamental data.
"""
import logging
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """Computes derived metrics for fundamental analysis."""

    def __init__(self, fundamentals_df: pd.DataFrame):
        """
        Initialize calculator.

        Args:
            fundamentals_df: DataFrame with fundamental data
        """
        self.fundamentals_df = fundamentals_df.copy()
        self.metrics_df = None

    def compute_all_metrics(self) -> pd.DataFrame:
        """
        Compute all derived metrics.

        Returns:
            DataFrame with fundamentals + derived metrics
        """
        logger.info("Computing derived metrics")

        df = self.fundamentals_df.copy()

        # Ensure numeric types
        numeric_cols = [
            'revenue', 'cogs', 'gross_profit', 'operating_income', 'ebit', 'net_income',
            'total_assets', 'current_assets', 'cash', 'total_liabilities',
            'current_liabilities', 'long_term_debt', 'total_equity',
            'cfo', 'capex', 'dividends_paid', 'shares_diluted', 'shares_outstanding',
            'accounts_receivable', 'depreciation_amortization', 'sga_expense',
            'interest_expense', 'short_term_borrowings', 'current_portion_lt_debt',
            'minority_interest', 'preferred_stock'
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Convert period_end to datetime
        df['period_end'] = pd.to_datetime(df['period_end'])

        # Sort by ticker and period_end
        df = df.sort_values(['ticker', 'period_end'], ascending=[True, True])

        # Compute metrics grouped by ticker
        df = df.groupby('ticker', group_keys=False).apply(self._compute_company_metrics)

        self.metrics_df = df
        logger.info(f"Computed metrics for {len(df)} periods")

        return df

    def _compute_company_metrics(self, company_df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute metrics for a single company.

        Args:
            company_df: DataFrame for one company

        Returns:
            DataFrame with computed metrics
        """
        df = company_df.copy()

        # Compute margins
        df['gross_margin'] = self._safe_divide(df['gross_profit'], df['revenue'])
        df['operating_margin'] = self._safe_divide(df['operating_income'], df['revenue'])
        df['net_margin'] = self._safe_divide(df['net_income'], df['revenue'])

        # Compute free cash flow
        df['fcf'] = df['cfo'] - df['capex'].abs()  # capex is often negative
        df['fcf_margin'] = self._safe_divide(df['fcf'], df['revenue'])

        # Total debt (all interest-bearing obligations per Carlisle/Gray)
        df['total_debt'] = (
            df['long_term_debt'].fillna(0)
            + df['short_term_borrowings'].fillna(0)
            + df['current_portion_lt_debt'].fillna(0)
        )

        # EBITDA = EBIT + D&A (needed for EV/EBITDA value multiple)
        df['ebitda'] = df['ebit'] + df['depreciation_amortization'].fillna(0)

        # Asset turnover = revenue / total assets (used in F-Score efficiency component)
        df['asset_turnover'] = self._safe_divide(df['revenue'], df['total_assets'])

        # Leverage ratios — use total_debt not just long_term_debt
        df['debt_to_equity'] = self._safe_divide(df['total_debt'], df['total_equity'])
        df['debt_to_assets'] = self._safe_divide(df['total_debt'], df['total_assets'])

        # Profitability ratios
        df['roa'] = self._safe_divide(df['net_income'], df['total_assets'])
        df['roe'] = self._safe_divide(df['net_income'], df['total_equity'])

        # Current ratio
        df['current_ratio'] = self._safe_divide(df['current_assets'], df['current_liabilities'])

        # Compute growth rates separately for annual and quarterly
        annual_mask = df['frequency'] == 'annual'
        quarterly_mask = df['frequency'] == 'quarterly'

        # Annual growth (YoY)
        if annual_mask.any():
            df.loc[annual_mask] = self._compute_growth_rates(
                df[annual_mask], periods=1, suffix='_yoy'
            )

        # Quarterly growth (both QoQ and YoY)
        if quarterly_mask.any():
            # Quarter-over-quarter
            df.loc[quarterly_mask] = self._compute_growth_rates(
                df[quarterly_mask], periods=1, suffix='_qoq'
            )
            # Year-over-year (4 quarters)
            df.loc[quarterly_mask] = self._compute_growth_rates(
                df[quarterly_mask], periods=4, suffix='_yoy'
            )

        # Compute accrual ratio
        df['accrual_ratio'] = self._compute_accrual_ratio(df)

        return df

    def _compute_growth_rates(self, df: pd.DataFrame, periods: int, suffix: str) -> pd.DataFrame:
        """
        Compute growth rates for key metrics.

        Args:
            df: DataFrame sorted by date
            periods: Number of periods to look back (1 for QoQ, 4 for YoY quarterly)
            suffix: Suffix for growth columns (e.g., '_yoy', '_qoq')

        Returns:
            DataFrame with growth columns added
        """
        growth_metrics = [
            'revenue', 'net_income', 'fcf', 'ebit',
            # Ratio columns needed for Piotroski F-Score components
            'gross_margin',      # F8: gross margin improving
            'current_ratio',     # F6: current ratio improving
            'debt_to_equity',    # F5: leverage declining
            'roa',               # F3: ROA improving
            'asset_turnover',    # F9: asset turnover improving
            'total_assets',      # used in F9 fallback
            'shares_diluted',    # F7: no share dilution
        ]

        for metric in growth_metrics:
            if metric not in df.columns:
                continue

            # Shift to get previous period value
            prev_col = f'{metric}_prev_{periods}'
            df[prev_col] = df[metric].shift(periods)

            # Calculate growth rate
            growth_col = f'{metric}{suffix}'
            df[growth_col] = self._safe_divide(
                df[metric] - df[prev_col],
                df[prev_col].abs()
            )

            # Drop temporary column
            df = df.drop(columns=[prev_col])

        return df

    def _compute_accrual_ratio(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute accrual ratio: (net_income - cfo) / avg(total_assets).

        Args:
            df: DataFrame with fundamentals

        Returns:
            Series with accrual ratios
        """
        # Get previous period's total assets
        prev_assets = df['total_assets'].shift(1)

        # Average assets
        avg_assets = (df['total_assets'] + prev_assets) / 2

        # Accrual ratio
        accruals = df['net_income'] - df['cfo']
        accrual_ratio = self._safe_divide(accruals, avg_assets)

        return accrual_ratio

    def _safe_divide(self, numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        """
        Safely divide two series, handling division by zero.

        Args:
            numerator: Numerator series
            denominator: Denominator series

        Returns:
            Result series with NaN for invalid divisions
        """
        return np.where(
            (denominator.notna()) & (denominator != 0),
            numerator / denominator,
            np.nan
        )

    def save_metrics(self, output_path):
        """
        Save metrics DataFrame to CSV.

        Args:
            output_path: Path to save CSV
        """
        if self.metrics_df is None:
            raise ValueError("No metrics computed. Run compute_all_metrics() first.")

        logger.info(f"Saving metrics to {output_path}")
        self.metrics_df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(self.metrics_df)} records")

    def get_metrics_summary(self) -> pd.DataFrame:
        """
        Get summary statistics of computed metrics.

        Returns:
            DataFrame with summary stats
        """
        if self.metrics_df is None:
            raise ValueError("No metrics computed. Run compute_all_metrics() first.")

        metric_cols = [
            'gross_margin', 'operating_margin', 'net_margin', 'fcf_margin',
            'revenue_yoy', 'net_income_yoy', 'fcf_yoy',
            'debt_to_equity', 'debt_to_assets',
            'roa', 'roe', 'current_ratio', 'accrual_ratio'
        ]

        available_cols = [col for col in metric_cols if col in self.metrics_df.columns]

        summary = self.metrics_df[available_cols].describe()

        return summary
