"""
Quantitative Value screening module.

Implements the methodology from "Quantitative Value" by Wesley Gray and Tobias Carlisle.

AUTHORITATIVE REFERENCE: docs/QUANTITATIVE_VALUE_MODEL.md
This markdown file contains the complete mathematical specification for the model.
All implementations in this module follow that specification exactly.

Data Architecture:
- EDGAR (Primary): All fundamental financial data (revenue, EBIT, assets, liabilities, etc.)
- DefeatBeta (Secondary): Market pricing data only (current prices, market cap)
- Enterprise Value = Market Cap (DefeatBeta) + Net Debt (EDGAR)

Key components:
1. Risk Screening (Step 1): Avoid stocks at risk of permanent loss
2. Value Ranking (Step 2): Find cheapest stocks by EBIT/TEV
3. Quality Ranking (Step 3): Find highest quality stocks
4. Combined screening workflow
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from risk_screening import RiskScreener
from market_data import MarketDataProvider

logger = logging.getLogger(__name__)


class QuantitativeValueScreener:
    """
    Implements complete 3-step Quantitative Value screening methodology.

    Step 1: Avoid stocks at risk of sustaining permanent loss of capital
    Step 2: Find the cheapest stocks (EBIT/TEV ranking)  
    Step 3: Find the highest-quality stocks (franchise power + financial strength)

    Reference: "Quantitative Value" by Wesley Gray and Tobias Carlisle
    """

    def __init__(self, metrics_df: pd.DataFrame, fundamentals_df: pd.DataFrame = None,
                 enable_market_data: bool = True, franchise_power_df: pd.DataFrame = None):
        """
        Initialize screener with metrics data.

        Args:
            metrics_df: DataFrame from metrics.csv (output of compute_metrics.py)
            fundamentals_df: DataFrame from fundamentals.csv (for risk screening)
            enable_market_data: Whether to use real market data for enterprise values
            franchise_power_df: DataFrame from franchise_power_metrics.csv (8-year quality metrics)
        """
        self.metrics_df = metrics_df.copy()
        self.fundamentals_df = fundamentals_df.copy() if fundamentals_df is not None else metrics_df.copy()
        self.franchise_power_df = franchise_power_df.copy() if franchise_power_df is not None else None
        self.latest_data = None
        self.risk_screener = RiskScreener(self.fundamentals_df)

        # Market data integration
        self.enable_market_data = enable_market_data
        if enable_market_data:
            self.market_data_provider = MarketDataProvider()
            logger.info("Market data integration enabled")
        else:
            self.market_data_provider = None
            logger.info("Using book value approximations for enterprise value")

        # Log Franchise Power availability
        if self.franchise_power_df is not None:
            logger.info(f"Franchise Power metrics loaded for {len(self.franchise_power_df)} companies")
        else:
            logger.warning("Franchise Power metrics not loaded - quality score will use F-Score only")

    def get_latest_periods(self, frequency: str = 'annual') -> pd.DataFrame:
        """
        Get the most recent period for each company.

        Args:
            frequency: 'annual' or 'quarterly'

        Returns:
            DataFrame with one row per company (latest period)
        """
        df = self.metrics_df[self.metrics_df['frequency'] == frequency].copy()

        # Sort by period_end and get most recent period per company
        df = df.sort_values('period_end', ascending=False)
        latest = df.groupby('ticker').first().reset_index()

        logger.info(f"Extracted {len(latest)} companies with latest {frequency} data")
        return latest

    def calculate_piotroski_fscore(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Piotroski F-Score (9-point quality score).

        Components:
        Profitability (4 points):
          1. ROA > 0
          2. Operating cash flow > 0
          3. ROA increasing YoY
          4. Accruals < 0 (quality of earnings: CFO > Net Income)

        Leverage/Liquidity (3 points):
          5. Long-term debt decreasing (leverage ratio decreasing)
          6. Current ratio increasing
          7. No new shares issued (shares outstanding not increasing)

        Operating Efficiency (2 points):
          8. Gross margin increasing
          9. Asset turnover increasing

        Args:
            df: DataFrame with company metrics

        Returns:
            DataFrame with additional f_score column
        """
        df = df.copy()

        # Initialize F-Score
        df['f_score'] = 0

        # === PROFITABILITY (4 points) ===

        # 1. ROA > 0
        df['f_roa_positive'] = (df['roa'] > 0).astype(int)
        df['f_score'] += df['f_roa_positive']

        # 2. Operating cash flow > 0
        df['f_cfo_positive'] = (df['cfo'] > 0).astype(int)
        df['f_score'] += df['f_cfo_positive']

        # 3. ROA increasing YoY
        if 'roa_yoy' in df.columns:
            df['f_roa_growth'] = (df['roa_yoy'] > 0).fillna(0).astype(int)
        else:
            df['f_roa_growth'] = 0  # Can't calculate without YoY data
        df['f_score'] += df['f_roa_growth']

        # 4. Accruals < 0 (CFO > Net Income = high earnings quality)
        if 'accrual_ratio' in df.columns:
            df['f_accruals'] = (df['accrual_ratio'] < 0).fillna(0).astype(int)
        else:
            df['f_accruals'] = 0
        df['f_score'] += df['f_accruals']

        # === LEVERAGE/LIQUIDITY (3 points) ===

        # 5. Leverage decreasing (debt-to-equity declining)
        if 'debt_to_equity_yoy' in df.columns:
            df['f_leverage'] = (df['debt_to_equity_yoy'] < 0).fillna(0).astype(int)
        else:
            df['f_leverage'] = 0
        df['f_score'] += df['f_leverage']

        # 6. Current ratio increasing
        if 'current_ratio_yoy' in df.columns:
            df['f_liquidity'] = (df['current_ratio_yoy'] > 0).fillna(0).astype(int)
        else:
            df['f_liquidity'] = 0
        df['f_score'] += df['f_liquidity']

        # 7. Shares outstanding not increasing (no dilution)
        # Using shares_outstanding field if available, otherwise skip
        if 'shares_outstanding' in df.columns and 'shares_outstanding_yoy' in df.columns:
            df['f_shares'] = (df['shares_outstanding_yoy'] <= 0).fillna(0).astype(int)
        else:
            df['f_shares'] = 0  # Can't calculate without share data
        df['f_score'] += df['f_shares']

        # === OPERATING EFFICIENCY (2 points) ===

        # 8. Gross margin increasing
        if 'gross_margin_yoy' in df.columns:
            df['f_margin'] = (df['gross_margin_yoy'] > 0).fillna(0).astype(int)
        else:
            df['f_margin'] = 0
        df['f_score'] += df['f_margin']

        # 9. Asset turnover increasing (revenue growth > asset growth)
        if 'revenue_yoy' in df.columns and 'total_assets_yoy' in df.columns:
            df['f_turnover'] = (df['revenue_yoy'] > df['total_assets_yoy']).fillna(0).astype(int)
        else:
            df['f_turnover'] = 0
        df['f_score'] += df['f_turnover']

        logger.info(f"Calculated Piotroski F-Score for {len(df)} companies")
        logger.info(f"F-Score distribution:\n{df['f_score'].value_counts().sort_index()}")

        return df

    def calculate_quality_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Quality Score combining Franchise Power + Financial Strength.

        Per Quantitative Value model specification:
        - Financial Strength (P_FS): Percentile rank of 10-point score (similar to F-Score)
        - Franchise Power (P_FP): Percentile rank from 8-year historical metrics
        - QUALITY = 0.5 × P_FP + 0.5 × P_FS

        Args:
            df: DataFrame with f_score calculated

        Returns:
            DataFrame with quality_score column added
        """
        df = df.copy()

        # Convert F-Score to percentile ranking (P_FS)
        df['p_financial_strength'] = df['f_score'].rank(pct=True) * 100

        # Merge with Franchise Power metrics if available
        if self.franchise_power_df is not None:
            # Merge on ticker
            fp_cols = ['ticker', 'p_franchise_power', '8yr_roa', '8yr_roc', 'fcfa',
                      'margin_growth', 'margin_stability']
            fp_merge = self.franchise_power_df[
                [col for col in fp_cols if col in self.franchise_power_df.columns]
            ].copy()

            df = df.merge(fp_merge, on='ticker', how='left')

            # Calculate combined Quality Score (50/50 weighting)
            # Only for companies that have both components
            has_fp = df['p_franchise_power'].notna()
            has_fs = df['p_financial_strength'].notna()

            df.loc[has_fp & has_fs, 'quality_score'] = (
                0.5 * df.loc[has_fp & has_fs, 'p_franchise_power'] +
                0.5 * df.loc[has_fp & has_fs, 'p_financial_strength']
            )

            # For companies without Franchise Power, use F-Score percentile only
            df.loc[~has_fp & has_fs, 'quality_score'] = df.loc[~has_fp & has_fs, 'p_financial_strength']

            logger.info(f"Combined Quality Score calculated:")
            logger.info(f"  - Companies with both FP + FS: {(has_fp & has_fs).sum()}")
            logger.info(f"  - Companies with FS only: {(~has_fp & has_fs).sum()}")
            logger.info(f"  - Quality score stats:\n{df['quality_score'].describe()}")
        else:
            # Fallback: Use F-Score percentile as Quality Score
            df['quality_score'] = df['p_financial_strength']
            logger.warning("Using F-Score percentile as Quality Score (Franchise Power not available)")

        return df

    def calculate_enterprise_value(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate enterprise value using real market data when available.

        EV = Market Cap + Total Debt - Cash

        Args:
            df: DataFrame with metrics

        Returns:
            DataFrame with accurate EV columns added
        """
        df = df.copy()
        
        if self.enable_market_data and self.market_data_provider is not None:
            # Get real market data
            tickers = df['ticker'].unique().tolist()
            
            # Try to load from cache first
            market_data = self.market_data_provider.load_market_data_cache()

            missing = set(tickers) - set(market_data['ticker']) if market_data is not None else set(tickers)
            if market_data is None or len(missing) > 0:
                if market_data is not None and len(missing) < len(tickers) * 0.5:
                    # Cache covers >50% of tickers — only fetch the gaps
                    logger.info(f"Fetching {len(missing)} tickers missing from cache...")
                    gap_data = self.market_data_provider.get_current_price_data(list(missing))
                    if not gap_data.empty:
                        import pandas as _pd
                        market_data = _pd.concat([market_data, gap_data], ignore_index=True)
                else:
                    logger.info("Fetching fresh market data...")
                    market_data = self.market_data_provider.get_current_price_data(tickers)
                self.market_data_provider.save_market_data_cache(market_data)
            else:
                logger.info("Using cached market data")
            
            # Calculate accurate enterprise value
            df = self.market_data_provider.calculate_accurate_enterprise_value(df, market_data)
            
            # The enterprise value is now in the 'enterprise_value' column from market_data_provider
            logger.info(f"Using market-based enterprise values for {len(df)} companies")
            
            logger.info(f"Calculated accurate enterprise values using market data for {len(df)} companies")
            
        else:
            # Fallback to book value approximation
            logger.info("Using book value approximation for enterprise value")
            
            # Calculate total debt (using long-term debt; short-term not available in metrics)
            df['total_debt'] = df['long_term_debt'].fillna(0)

            # Enterprise Value (using book equity as market cap proxy)
            df['enterprise_value'] = (
                df['total_equity'].fillna(0) +
                df['total_debt'] -
                df['cash'].fillna(0)
            )

        # Ensure EV is positive for ratios
        df['enterprise_value'] = df['enterprise_value'].replace(0, np.nan)

        return df

    def calculate_value_composite(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Value Composite score using multiple value metrics.

        Metrics ranked (lower percentile = cheaper = better):
        1. EV/EBIT (enterprise multiple)
        2. EV/Revenue (for comparison)
        3. EV/FCF (enterprise value to free cash flow)
        4. P/B (price to book - when market data available)

        Value Composite = Average percentile rank across all metrics

        Args:
            df: DataFrame with metrics including enterprise_value

        Returns:
            DataFrame with value composite score
        """
        df = df.copy()

        # Calculate value metrics
        value_metrics = []

        # 1. EV/EBIT (primary valuation metric)
        if 'ev_ebit' not in df.columns:
            df['ev_ebit'] = df['enterprise_value'] / df['operating_income']
        value_metrics.append('ev_ebit')

        # 2. EV/Revenue (for companies with low/negative EBIT)
        if 'ev_revenue' not in df.columns:
            df['ev_revenue'] = df['enterprise_value'] / df['revenue']
        value_metrics.append('ev_revenue')

        # 3. EV/FCF (if free cash flow available)
        if 'fcf' in df.columns:
            if 'ev_fcf' not in df.columns:
                df['ev_fcf'] = df['enterprise_value'] / df['fcf']
            value_metrics.append('ev_fcf')

        # 4. P/B (if market data available)
        if 'price_to_book' in df.columns:
            value_metrics.append('price_to_book')

        logger.info(f"Using value metrics: {value_metrics}")

        # Remove infinities and extreme outliers
        for metric in value_metrics:
            if metric in df.columns:
                # Remove infinities
                df[metric] = df[metric].replace([np.inf, -np.inf], np.nan)

                # Exclude non-positive ratios — negative EV/EBIT (negative enterprise value)
                # ranks as "cheapest" but is not meaningful; zero is a division artifact
                df.loc[df[metric] <= 0, metric] = np.nan

                # Remove extreme outliers (beyond 99th percentile)
                upper_bound = df[metric].quantile(0.99)
                df.loc[df[metric] > upper_bound, metric] = np.nan

                # Calculate percentile rank (0-100, where 0 = cheapest)
                df[f'{metric}_rank'] = df[metric].rank(pct=True) * 100

        # Value Composite = average of percentile ranks
        rank_cols = [f'{m}_rank' for m in value_metrics if f'{m}_rank' in df.columns]
        
        if rank_cols:
            df['value_composite'] = df[rank_cols].mean(axis=1, skipna=True)
        else:
            logger.warning("No valid value metrics available for composite calculation")
            df['value_composite'] = np.nan

        # Lower composite score = cheaper = better
        logger.info(f"Calculated value composite for {len(df)} companies")
        logger.info(f"Value composite stats:\n{df['value_composite'].describe()}")

        return df

    def screen_stocks(self,
                     min_quality_score: float = 50,
                     max_value_composite: float = 30,
                     exclude_sectors: list = None,
                     min_fscore: int = None) -> pd.DataFrame:
        """
        Run complete Quantitative Value screen.

        Steps:
        1. Get latest annual data
        2. Calculate Piotroski F-Score
        3. Calculate Quality Score (Franchise Power + Financial Strength)
        4. Filter by minimum Quality Score (quality screen)
        5. Calculate enterprise value
        6. Calculate value composite
        7. Filter by value composite (cheapest stocks)
        8. Remove excluded sectors

        Args:
            min_quality_score: Minimum Quality Score percentile (default 50 = top 50%)
            max_value_composite: Maximum value composite percentile (default 30 = cheapest 30%)
            exclude_sectors: List of sectors to exclude (e.g., ['Financials', 'Utilities'])
            min_fscore: (Deprecated) Use min_quality_score instead

        Returns:
            DataFrame with screened stocks, sorted by value composite (ascending)
        """
        logger.info("=" * 80)
        logger.info("Running Quantitative Value Screen")
        logger.info("=" * 80)

        # Get latest annual data
        df = self.get_latest_periods(frequency='annual')
        logger.info(f"Starting with {len(df)} companies")

        # Calculate Piotroski F-Score
        df = self.calculate_piotroski_fscore(df)

        # Calculate Quality Score (combines Franchise Power + Financial Strength)
        df = self.calculate_quality_score(df)

        # Quality filter - use quality_score if available, otherwise fall back to f_score
        if 'quality_score' in df.columns:
            df_quality = df[df['quality_score'] >= min_quality_score].copy()
            logger.info(f"After Quality Score >= {min_quality_score} filter: {len(df_quality)} companies")
        else:
            # Fallback to F-Score if quality_score not available
            fscore_threshold = min_fscore if min_fscore is not None else 5
            df_quality = df[df['f_score'] >= fscore_threshold].copy()
            logger.info(f"After F-Score >= {fscore_threshold} filter: {len(df_quality)} companies")

        # Calculate enterprise value
        df_quality = self.calculate_enterprise_value(df_quality)

        # Require positive EBIT before value ranking — negative EBIT would rank as
        # "cheapest" (most negative EV/EBIT) which is meaningless and misleading
        ebit_col = next((c for c in ['ebit', 'operating_income'] if c in df_quality.columns), None)
        if ebit_col:
            before = len(df_quality)
            df_quality = df_quality[df_quality[ebit_col] > 0].copy()
            logger.info(f"After positive EBIT filter: {len(df_quality)} companies (removed {before - len(df_quality)})")

        # Calculate value composite
        df_quality = self.calculate_value_composite(df_quality)

        # Remove rows with missing value composite
        df_screened = df_quality[df_quality['value_composite'].notna()].copy()

        # Value filter (cheapest X%)
        df_screened = df_screened[df_screened['value_composite'] <= max_value_composite].copy()
        logger.info(f"After value composite <= {max_value_composite} filter: {len(df_screened)} companies")

        # Sector exclusions
        if exclude_sectors:
            # Note: We don't have sector data yet - would need to add from universe
            logger.info(f"Sector exclusions not yet implemented (need sector data)")

        # Sort by value composite (ascending = cheapest first)
        df_screened = df_screened.sort_values('value_composite', ascending=True)

        logger.info("=" * 80)
        logger.info(f"Screen complete: {len(df_screened)} stocks passed")
        logger.info("=" * 80)

        return df_screened

    def run_complete_screening(self,
                             accrual_threshold: float = 95.0,
                             manipulation_threshold: float = 95.0,
                             distress_threshold: float = 95.0,
                             min_quality_score: float = 50,
                             max_value_composite: float = 30,
                             min_fscore: int = None) -> pd.DataFrame:
        """
        Run the complete 3-step Quantitative Value screening process.

        Step 1: Risk Screening - Remove high-risk stocks
        Step 2: Value Ranking - Find cheapest stocks by EBIT/TEV
        Step 3: Quality Ranking - Find highest quality stocks (Franchise Power + Financial Strength)

        Args:
            accrual_threshold: Percentile for accrual quality exclusion (default 95 = worst 5%)
            manipulation_threshold: Percentile for manipulation probability exclusion
            distress_threshold: Percentile for financial distress exclusion
            min_quality_score: Minimum Quality Score percentile (default 50 = top 50%)
            max_value_composite: Maximum value composite percentile for value filter
            min_fscore: (Deprecated) Use min_quality_score instead

        Returns:
            DataFrame with final screened stocks ready for portfolio construction
        """
        logger.info("="*80)
        logger.info("STARTING COMPLETE QUANTITATIVE VALUE SCREENING")
        logger.info("="*80)
        
        # Step 1: Risk Screening
        logger.info("\nSTEP 1: RISK SCREENING - Avoid Permanent Loss of Capital")
        logger.info("-" * 60)
        
        clean_stocks, excluded_stocks_dict = self.risk_screener.screen_high_risk_stocks(
            accrual_threshold=accrual_threshold,
            manipulation_threshold=manipulation_threshold, 
            distress_threshold=distress_threshold
        )
        
        # Filter metrics to only include clean stocks
        clean_tickers = clean_stocks['ticker'].unique()
        filtered_metrics = self.metrics_df[self.metrics_df['ticker'].isin(clean_tickers)].copy()
        
        # Update screener with filtered data
        original_metrics = self.metrics_df
        self.metrics_df = filtered_metrics
        
        # Step 2 & 3: Value and Quality Screening
        logger.info(f"\nSTEP 2 & 3: VALUE AND QUALITY SCREENING")
        logger.info("-" * 60)

        final_portfolio = self.screen_stocks(
            min_quality_score=min_quality_score,
            max_value_composite=max_value_composite,
            min_fscore=min_fscore
        )
        
        # Restore original metrics
        self.metrics_df = original_metrics
        
        logger.info("\n" + "="*80)
        logger.info("COMPLETE SCREENING SUMMARY")
        logger.info("="*80)
        logger.info(f"Started with: {len(self.metrics_df['ticker'].unique())} companies")
        logger.info(f"After risk screening: {len(clean_tickers)} companies")
        logger.info(f"Final portfolio candidates: {len(final_portfolio)} companies")
        logger.info(f"Exclusion rate: {((len(self.metrics_df['ticker'].unique()) - len(final_portfolio)) / len(self.metrics_df['ticker'].unique()) * 100):.1f}%")
        
        # Store excluded stocks for export
        self.excluded_stocks_dict = excluded_stocks_dict
        
        return final_portfolio

    def get_screening_summary(self, screened_df: pd.DataFrame) -> pd.DataFrame:
        """
        Get summary table for screening results.

        Returns key metrics for each stock in a clean format for Excel export.

        Args:
            screened_df: Output from screen_stocks()

        Returns:
            Summary DataFrame suitable for Excel export
        """
        summary_cols = [
            'ticker', 'name',
            'f_score',
            'value_composite',
            'ev_ebit', 'ev_ebitda', 'ev_fcf',
            'roa', 'roe', 'roic',
            'gross_margin', 'operating_margin', 'fcf_margin',
            'revenue_growth_3yr', 'revenue_yoy',
            'debt_to_equity', 'current_ratio',
            'period_end'
        ]

        # Select available columns
        available_cols = [c for c in summary_cols if c in screened_df.columns]
        summary = screened_df[available_cols].copy()

        # Round numeric columns
        numeric_cols = summary.select_dtypes(include=[np.number]).columns
        summary[numeric_cols] = summary[numeric_cols].round(2)

        return summary

    def export_to_excel(self, screened_df: pd.DataFrame, output_path: Path, include_excluded: bool = True):
        """
        Export screening results to Excel with formatting and excluded stocks analysis.

        Args:
            screened_df: Screened stocks DataFrame
            output_path: Path to output Excel file
            include_excluded: Whether to include excluded stocks analysis
        """
        summary = self.get_screening_summary(screened_df)

        # Export to Excel
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Screening results
            summary.to_excel(writer, sheet_name='Final_Portfolio', index=False)

            # Full data
            screened_df.to_excel(writer, sheet_name='Portfolio_Full_Data', index=False)

            # Summary stats (using only available columns)
            stats_cols = ['f_score', 'value_composite', 'roa', 'roe']
            available_stats_cols = [c for c in stats_cols if c in screened_df.columns]
            if available_stats_cols:
                stats = screened_df[available_stats_cols].describe()
                stats.to_excel(writer, sheet_name='Portfolio_Statistics')
                
            # Export excluded stocks if available and requested
            if include_excluded and hasattr(self, 'excluded_stocks_dict'):
                self._export_excluded_stocks_analysis(writer)

        logger.info(f"Exported screening results to {output_path}")

    def _export_excluded_stocks_analysis(self, writer):
        """
        Export detailed analysis of excluded stocks to Excel tabs.
        
        Args:
            writer: ExcelWriter object
        """
        logger.info("Exporting excluded stocks analysis")
        
        # Define the columns to include in each export
        key_columns = [
            'ticker', 'period_end', 'revenue', 'net_income', 'total_assets', 'total_liabilities',
            'cash', 'current_ratio', 'roa', 'roe'
        ]
        
        risk_score_columns = [
            'sta', 'snoa', 'combo_accrual', 'sta_percentile', 'snoa_percentile',
            'mscore', 'manipulation_probability', 'manipulation_percentile',
            'financial_distress_probability', 'distress_percentile'
        ]
        
        # Export each category of excluded stocks
        for sheet_name, excluded_df in self.excluded_stocks_dict.items():
            if len(excluded_df) > 0:
                # Prepare export DataFrame with available columns
                export_columns = []
                
                # Add key financial columns that exist
                for col in key_columns:
                    if col in excluded_df.columns:
                        export_columns.append(col)
                
                # Add risk score columns that exist
                for col in risk_score_columns:
                    if col in excluded_df.columns:
                        export_columns.append(col)
                
                # Add exclusion reason flags for the "All_Excluded" sheet
                if sheet_name == 'All_Excluded':
                    exclusion_flags = ['excluded_accruals', 'excluded_manipulation', 'excluded_distress']
                    for col in exclusion_flags:
                        if col in excluded_df.columns:
                            export_columns.append(col)
                
                # Create export DataFrame
                export_df = excluded_df[export_columns].copy()
                
                # Round numeric columns for readability
                numeric_cols = export_df.select_dtypes(include=[np.number]).columns
                export_df[numeric_cols] = export_df[numeric_cols].round(4)
                
                # Export to sheet
                export_df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                logger.info(f"Exported {len(export_df)} excluded stocks to '{sheet_name}' tab")
        
        # Create summary of exclusions
        self._create_exclusion_summary(writer)
    
    def _create_exclusion_summary(self, writer):
        """
        Create a summary sheet showing exclusion statistics.
        
        Args:
            writer: ExcelWriter object  
        """
        if not hasattr(self, 'excluded_stocks_dict'):
            return
            
        summary_data = []
        
        for category, excluded_df in self.excluded_stocks_dict.items():
            if category == 'All_Excluded':
                continue  # Skip the combined category for individual stats
                
            if len(excluded_df) > 0:
                # Calculate summary statistics for this exclusion category
                summary_data.append({
                    'Exclusion_Category': category.replace('_', ' '),
                    'Count_Excluded': len(excluded_df),
                    'Avg_Revenue_M': (excluded_df['revenue'].mean() / 1e6) if 'revenue' in excluded_df.columns else np.nan,
                    'Avg_Total_Assets_M': (excluded_df['total_assets'].mean() / 1e6) if 'total_assets' in excluded_df.columns else np.nan,
                    'Avg_ROA_Pct': (excluded_df['roa'].mean() * 100) if 'roa' in excluded_df.columns else np.nan,
                    'Avg_Current_Ratio': excluded_df['current_ratio'].mean() if 'current_ratio' in excluded_df.columns else np.nan
                })
        
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df = summary_df.round(2)
            summary_df.to_excel(writer, sheet_name='Exclusion_Summary', index=False)
            
            logger.info("Created exclusion summary sheet")


def main():
    """Example usage with complete 3-step screening."""
    from config import get_config

    # Load configuration
    config = get_config()

    # Load both metrics and fundamentals data
    metrics_path = config.get_metrics_path()
    fundamentals_path = config.get_fundamentals_path()
    franchise_power_path = Path('data/processed/franchise_power_metrics.csv')

    logger.info(f"Loading metrics from {metrics_path}")
    metrics_df = pd.read_csv(metrics_path)

    # metrics.csv has cik but no ticker — join with companies to add it
    companies_path = config.get_companies_path()
    if 'ticker' not in metrics_df.columns and Path(companies_path).exists():
        companies_df = pd.read_csv(companies_path)
        # companies.csv has multiple tickers per CIK (e.g. GOOGL/GOOG) — keep one per CIK
        # to avoid exploding the metrics join; keep first (alphabetically first is fine)
        companies_dedup = companies_df.drop_duplicates(subset='cik', keep='first')[['cik', 'ticker']]
        metrics_df = metrics_df.merge(companies_dedup, on='cik', how='left')
        logger.info(f"Joined metrics with companies: {metrics_df['ticker'].notna().sum()} tickers resolved")

    logger.info(f"Loading fundamentals from {fundamentals_path}")
    fundamentals_df = pd.read_csv(fundamentals_path)

    # Load Franchise Power metrics if available
    franchise_power_df = None
    if franchise_power_path.exists():
        logger.info(f"Loading Franchise Power metrics from {franchise_power_path}")
        franchise_power_df = pd.read_csv(franchise_power_path)
    else:
        logger.warning(f"Franchise Power metrics not found at {franchise_power_path}")
        logger.warning("Quality score will use Financial Strength (F-Score) only")

    # Initialize screener with all datasets
    # Market data enabled using DefeatBeta prices from cache
    screener = QuantitativeValueScreener(
        metrics_df,
        fundamentals_df,
        enable_market_data=True,
        franchise_power_df=franchise_power_df
    )

    # Run complete 3-step screening
    final_portfolio = screener.run_complete_screening(
        accrual_threshold=95.0,     # Exclude worst 5% by accrual quality
        manipulation_threshold=95.0, # Exclude worst 5% by manipulation probability
        distress_threshold=95.0,    # Exclude worst 5% by financial distress
        min_quality_score=50,       # Top 50% by combined quality (Franchise Power + Financial Strength)
        max_value_composite=30      # Cheapest 30% by value
    )

    # Save CSV for Enkidu edgar_screener.py (must be in data/processed/)
    csv_path = Path('data/processed/quantitative_value_portfolio.csv')
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    final_portfolio.to_csv(csv_path, index=False)
    logger.info(f"Portfolio CSV saved to {csv_path} ({len(final_portfolio)} stocks)")

    # Export results with excluded stocks analysis
    output_path = Path('data/reports/quantitative_value_portfolio.xlsx')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    screener.export_to_excel(final_portfolio, output_path, include_excluded=True)

    logger.info(f"Complete analysis exported to {output_path}")
    logger.info("Check the following tabs:")
    logger.info("  - Final_Portfolio: Your investment candidates")
    logger.info("  - All_Excluded: All excluded stocks with reasons")
    logger.info("  - High_Accruals: Stocks excluded for poor accrual quality")
    logger.info("  - High_Manipulation_Risk: Stocks excluded for manipulation risk") 
    logger.info("  - High_Distress_Risk: Stocks excluded for financial distress")
    logger.info("  - Exclusion_Summary: Statistics on excluded companies")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
