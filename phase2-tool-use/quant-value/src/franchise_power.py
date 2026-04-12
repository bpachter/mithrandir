"""
Franchise Power Calculator - 8-Year Historical Quality Metrics

Calculates long-term quality metrics as specified in the Quantitative Value model.
These metrics measure sustainable competitive advantage (economic moat).

Reference: docs/QUANTITATIVE_VALUE_MODEL.md Section 3.1
"""
import logging
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FranchisePowerCalculator:
    """
    Calculates Franchise Power metrics using 8 years of historical data.

    Metrics:
    1. 8yr_ROA - Geometric average Return on Assets
    2. 8yr_ROC - Geometric average Return on Capital
    3. FCFA - Free Cash Flow to Assets (8-year cumulative)
    4. MG - Margin Growth (8-year CAGR)
    5. MS - Margin Stability (mean / standard deviation)
    6. P_FP - Franchise Power percentile score
    """

    def __init__(self, cache_dir: Path = None):
        """
        Initialize calculator.

        Args:
            cache_dir: Directory containing SEC companyfacts JSON files
        """
        if cache_dir is None:
            cache_dir = Path('data/raw/companyfacts')
        self.cache_dir = Path(cache_dir)

        if not self.cache_dir.exists():
            raise ValueError(f"Cache directory not found: {self.cache_dir}")

        logger.info(f"Initialized Franchise Power calculator with cache: {self.cache_dir}")

    def extract_annual_data(self, ticker: str, cik: str, years: int = 8) -> Optional[pd.DataFrame]:
        """
        Extract annual financial data (10-K filings) for a company.

        Args:
            ticker: Stock ticker symbol
            cik: SEC CIK number (with leading zeros)
            years: Number of years to extract (default 8)

        Returns:
            DataFrame with annual metrics, or None if insufficient data
        """
        json_file = self.cache_dir / f"{cik}.json"

        if not json_file.exists():
            logger.debug(f"No JSON file for {ticker} (CIK: {cik})")
            return None

        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            # Extract key metrics from us-gaap taxonomy
            if 'facts' not in data or 'us-gaap' not in data['facts']:
                logger.debug(f"No us-gaap facts for {ticker}")
                return None

            facts = data['facts']['us-gaap']

            # Metrics we need (with alternatives)
            metrics_map = {
                'NetIncomeLoss': 'net_income',
                'Assets': 'total_assets',
                'OperatingIncomeLoss': 'operating_income',
                'Revenues': 'revenue',
                'RevenueFromContractWithCustomerExcludingAssessedTax': 'revenue',  # Alternative
                'CostOfRevenue': 'cost_of_revenue',
                'CostOfGoodsAndServicesSold': 'cost_of_revenue',  # Alternative
                'GrossProfit': 'gross_profit',
                'LiabilitiesCurrent': 'current_liabilities',
                'LiabilitiesNoncurrent': 'noncurrent_liabilities',
                'StockholdersEquity': 'stockholders_equity',
                'NetCashProvidedByUsedInOperatingActivities': 'cfo',
                'NetCashProvidedByUsedInInvestingActivities': 'cfi',
                'PaymentsToAcquirePropertyPlantAndEquipment': 'capex'
            }

            # Extract annual data (10-K forms)
            annual_records = []

            for gaap_name, metric_name in metrics_map.items():
                if gaap_name not in facts:
                    continue

                fact = facts[gaap_name]
                if 'units' not in fact:
                    continue

                # Get USD values
                unit_key = 'USD' if 'USD' in fact['units'] else list(fact['units'].keys())[0]
                values = fact['units'][unit_key]

                # Filter for annual reports (10-K)
                annual_values = [
                    v for v in values
                    if v.get('form') == '10-K' and 'end' in v and 'val' in v
                ]

                # Group by fiscal year and take most recent filing
                fy_data = {}
                for v in annual_values:
                    fy = v.get('fy')
                    if fy:
                        if fy not in fy_data or v['filed'] > fy_data[fy]['filed']:
                            fy_data[fy] = {
                                'fiscal_year': fy,
                                'end_date': v['end'],
                                'value': v['val'],
                                'filed': v['filed']
                            }

                # Add to records
                for fy, record in fy_data.items():
                    annual_records.append({
                        'ticker': ticker,
                        'fiscal_year': fy,
                        'end_date': record['end_date'],
                        'metric': metric_name,
                        'value': record['value']
                    })

            if not annual_records:
                logger.debug(f"No annual data found for {ticker}")
                return None

            # Convert to DataFrame and pivot
            df = pd.DataFrame(annual_records)

            # Group by fiscal year and aggregate (take first non-null value for each metric)
            df_pivot = df.pivot_table(
                index=['ticker', 'fiscal_year'],
                columns='metric',
                values='value',
                aggfunc='first'
            ).reset_index()

            # For each fiscal year, forward-fill any missing values from other filings of same year
            # This handles cases where metrics come from different amendment filings
            df_pivot = df_pivot.groupby(['ticker', 'fiscal_year']).agg(
                lambda x: x.dropna().iloc[0] if len(x.dropna()) > 0 else pd.NA
            ).reset_index()

            # Sort by fiscal year descending
            df_pivot = df_pivot.sort_values('fiscal_year', ascending=False)

            # Remove duplicate fiscal years (keep most complete row)
            df_pivot = df_pivot.groupby('fiscal_year').first().reset_index()

            # Keep most recent N years
            df_pivot = df_pivot.head(years)

            # Check if we have minimum data
            if len(df_pivot) < 3:  # Need at least 3 years for meaningful metrics
                logger.debug(f"Insufficient years for {ticker}: {len(df_pivot)}")
                return None

            # Convert all numeric columns to proper float type
            numeric_cols = [col for col in df_pivot.columns if col not in ['ticker', 'fiscal_year']]
            for col in numeric_cols:
                if col in df_pivot.columns:
                    df_pivot[col] = pd.to_numeric(df_pivot[col], errors='coerce')

            logger.debug(f"Extracted {len(df_pivot)} years for {ticker}")
            return df_pivot

        except Exception as e:
            logger.error(f"Error extracting data for {ticker}: {e}")
            return None

    def calculate_8yr_roa(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate 8-year geometric average Return on Assets.

        ROA = Net Income / Total Assets

        Args:
            df: DataFrame with annual data

        Returns:
            8-year geometric average ROA, or None if insufficient data
        """
        if df is None or len(df) == 0:
            return None

        # Calculate annual ROA
        if 'net_income' not in df.columns or 'total_assets' not in df.columns:
            return None

        df['roa'] = df['net_income'] / df['total_assets']

        # Remove invalid values
        valid_roas = df['roa'].dropna()
        valid_roas = valid_roas[np.isfinite(valid_roas.astype(float))]

        if len(valid_roas) < 3:
            return None

        # Geometric average: (product of (1 + ROA))^(1/n) - 1
        # Handle negative ROAs by using arithmetic mean as fallback
        if (valid_roas < -1).any():
            return valid_roas.mean()

        try:
            geometric_mean = np.power(np.prod(1 + valid_roas), 1.0 / len(valid_roas)) - 1
            return geometric_mean
        except:
            return valid_roas.mean()

    def calculate_8yr_roc(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate 8-year geometric average Return on Capital.

        ROC = EBIT / (Total Assets - Current Liabilities)
        Capital = Total Assets - Current Liabilities

        Args:
            df: DataFrame with annual data

        Returns:
            8-year geometric average ROC, or None if insufficient data
        """
        if df is None or len(df) == 0:
            return None

        # Calculate capital employed
        if 'operating_income' not in df.columns or 'total_assets' not in df.columns:
            return None

        # Capital = Total Assets - Current Liabilities
        if 'current_liabilities' in df.columns:
            df['capital'] = df['total_assets'] - df['current_liabilities']
        else:
            # Fallback: use total assets
            df['capital'] = df['total_assets']

        df['roc'] = df['operating_income'] / df['capital']

        # Remove invalid values
        valid_rocs = df['roc'].dropna()
        valid_rocs = valid_rocs[np.isfinite(valid_rocs)]

        if len(valid_rocs) < 3:
            return None

        # Geometric average
        if (valid_rocs < -1).any():
            return valid_rocs.mean()

        try:
            geometric_mean = np.power(np.prod(1 + valid_rocs), 1.0 / len(valid_rocs)) - 1
            return geometric_mean
        except:
            return valid_rocs.mean()

    def calculate_fcfa(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate Free Cash Flow to Assets (8-year cumulative).

        FCF = Operating Cash Flow - CapEx
        FCFA = Sum(FCF over 8 years) / Current Total Assets

        Args:
            df: DataFrame with annual data

        Returns:
            FCFA ratio, or None if insufficient data
        """
        if df is None or len(df) == 0:
            return None

        # Calculate FCF for each year
        if 'cfo' not in df.columns:
            return None

        # CapEx (capital expenditures)
        if 'capex' in df.columns:
            df['capex_clean'] = pd.to_numeric(df['capex'], errors='coerce').fillna(0).abs()
            df['fcf'] = df['cfo'] - df['capex_clean']  # CapEx usually negative
        else:
            # Fallback: use CFO only
            df['fcf'] = df['cfo']

        # Sum FCF over available years
        total_fcf = df['fcf'].sum()

        # Divide by most recent total assets
        if 'total_assets' not in df.columns:
            return None

        current_assets = df.iloc[0]['total_assets']  # Most recent year (sorted desc)

        if current_assets is None or current_assets <= 0:
            return None

        return total_fcf / current_assets

    def calculate_margin_growth(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate 8-year gross margin CAGR (Compound Annual Growth Rate).

        Gross Margin = Gross Profit / Revenue
        MG = (Final Margin / Initial Margin)^(1/7) - 1

        Args:
            df: DataFrame with annual data (sorted desc by year)

        Returns:
            Margin growth rate, or None if insufficient data
        """
        if df is None or len(df) < 2:
            return None

        # Calculate gross margin for each year
        if 'gross_profit' in df.columns and 'revenue' in df.columns:
            df['gross_margin'] = df['gross_profit'] / df['revenue']
        elif 'cost_of_revenue' in df.columns and 'revenue' in df.columns:
            df['gross_margin'] = (df['revenue'] - df['cost_of_revenue']) / df['revenue']
        else:
            return None

        # Remove invalid margins
        valid_margins = df['gross_margin'].dropna()
        valid_margins = valid_margins[np.isfinite(valid_margins.astype(float))]
        valid_margins = valid_margins[(valid_margins >= 0) & (valid_margins <= 1)]

        if len(valid_margins) < 2:
            return None

        # Get oldest and newest margins (df is sorted desc)
        final_margin = valid_margins.iloc[0]  # Most recent
        initial_margin = valid_margins.iloc[-1]  # Oldest

        if initial_margin <= 0:
            return None

        # CAGR formula
        years_diff = len(valid_margins) - 1
        if years_diff < 1:
            return None

        try:
            cagr = np.power(final_margin / initial_margin, 1.0 / years_diff) - 1
            return cagr
        except:
            return None

    def calculate_margin_stability(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate margin stability (8-year average / standard deviation).

        Higher values = more stable margins

        Args:
            df: DataFrame with annual data

        Returns:
            Margin stability ratio, or None if insufficient data
        """
        if df is None or len(df) < 3:
            return None

        # Calculate gross margin for each year
        if 'gross_profit' in df.columns and 'revenue' in df.columns:
            df['gross_margin'] = df['gross_profit'] / df['revenue']
        elif 'cost_of_revenue' in df.columns and 'revenue' in df.columns:
            df['gross_margin'] = (df['revenue'] - df['cost_of_revenue']) / df['revenue']
        else:
            return None

        # Remove invalid margins
        valid_margins = df['gross_margin'].dropna()
        valid_margins = valid_margins[np.isfinite(valid_margins.astype(float))]
        valid_margins = valid_margins[(valid_margins >= 0) & (valid_margins <= 1)]

        if len(valid_margins) < 3:
            return None

        margin_mean = valid_margins.mean()
        margin_std = valid_margins.std()

        if margin_std == 0 or pd.isna(margin_std):
            return None  # No variation or insufficient data

        return margin_mean / margin_std

    def calculate_franchise_power(self, ticker: str, cik: str) -> Dict[str, Optional[float]]:
        """
        Calculate all Franchise Power metrics for a company.

        Args:
            ticker: Stock ticker
            cik: SEC CIK number

        Returns:
            Dict with all FP metrics
        """
        df = self.extract_annual_data(ticker, cik, years=8)

        return {
            'ticker': ticker,
            '8yr_roa': self.calculate_8yr_roa(df),
            '8yr_roc': self.calculate_8yr_roc(df),
            'fcfa': self.calculate_fcfa(df),
            'margin_growth': self.calculate_margin_growth(df),
            'margin_stability': self.calculate_margin_stability(df),
            'years_available': len(df) if df is not None else 0
        }

    def calculate_for_universe(self, companies_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Franchise Power metrics for all companies in universe.

        Args:
            companies_df: DataFrame with 'ticker' and 'cik' columns

        Returns:
            DataFrame with FP metrics for each company
        """
        logger.info(f"Calculating Franchise Power for {len(companies_df)} companies...")

        results = []

        for idx, row in companies_df.iterrows():
            ticker = row['ticker']
            cik = row['cik']

            # Pad CIK to 10 digits
            cik_padded = str(cik).zfill(10)

            metrics = self.calculate_franchise_power(ticker, cik_padded)
            results.append(metrics)

            if (idx + 1) % 500 == 0:
                logger.info(f"Processed {idx + 1}/{len(companies_df)} companies")

        results_df = pd.DataFrame(results)

        # Calculate percentile rankings
        logger.info("Calculating percentile rankings...")

        for metric in ['8yr_roa', '8yr_roc', 'fcfa', 'margin_growth', 'margin_stability']:
            if metric in results_df.columns:
                results_df[f'p_{metric}'] = results_df[metric].rank(pct=True) * 100

        # Calculate Margin Max (MM) = max(P_MG, P_MS)
        if 'p_margin_growth' in results_df.columns and 'p_margin_stability' in results_df.columns:
            results_df['p_margin_max'] = results_df[['p_margin_growth', 'p_margin_stability']].max(axis=1)

        # Calculate Franchise Power Score
        # P_FP = Percentile of ( (P_8yr_ROA + P_8yr_ROC + P_CFOA + MM) / 4 )
        fp_components = []
        if 'p_8yr_roa' in results_df.columns:
            fp_components.append('p_8yr_roa')
        if 'p_8yr_roc' in results_df.columns:
            fp_components.append('p_8yr_roc')
        if 'p_fcfa' in results_df.columns:
            fp_components.append('p_fcfa')
        if 'p_margin_max' in results_df.columns:
            fp_components.append('p_margin_max')

        if fp_components:
            results_df['fp_score_raw'] = results_df[fp_components].mean(axis=1, skipna=True)
            results_df['p_franchise_power'] = results_df['fp_score_raw'].rank(pct=True) * 100

        logger.info("Franchise Power calculation complete")
        logger.info(f"Companies with sufficient data: {results_df['years_available'].gt(0).sum()}")
        logger.info(f"Average years available: {results_df['years_available'].mean():.1f}")

        return results_df


def main():
    """Test the Franchise Power calculator with a few companies."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    logging.basicConfig(level=logging.INFO)

    # Test with a few well-known companies
    test_companies = pd.DataFrame({
        'ticker': ['AAPL', 'MSFT', 'GOOGL'],
        'cik': [320193, 789019, 1652044]
    })

    calculator = FranchisePowerCalculator()
    results = calculator.calculate_for_universe(test_companies)

    print("\n" + "="*80)
    print("FRANCHISE POWER TEST RESULTS")
    print("="*80)
    print(results.to_string())
    print("="*80)


if __name__ == '__main__':
    main()
