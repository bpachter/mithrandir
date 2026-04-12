"""
Risk Screening Module for Quantitative Value Model

Implements Step 1: Avoid Stocks at Risk of Sustaining a Permanent Loss of Capital

Components:
1. Accrual Quality Screening (STA, SNOA)
2. Beneish M-Score (Fraud/Manipulation Detection)
3. Campbell Financial Distress Probability

Reference: "Quantitative Value" by Wesley Gray and Tobias Carlisle
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Tuple
from scipy.stats import norm

logger = logging.getLogger(__name__)


class RiskScreener:
    """
    Implements comprehensive risk screening to identify:
    1. Companies with poor accrual quality (earnings manipulation risk)
    2. Companies with high manipulation probability (Beneish M-Score)
    3. Companies with high financial distress probability (Campbell model)
    """

    def __init__(self, fundamentals_df: pd.DataFrame):
        """
        Initialize risk screener with fundamental data.
        
        Args:
            fundamentals_df: DataFrame with fundamental accounting data
        """
        self.fundamentals_df = fundamentals_df.copy()

    def calculate_accrual_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate accrual quality metrics: STA and SNOA.
        
        Scaled Total Accruals (STA):
        STA = (ΔCA - ΔCL - DEP) / Total Assets
        
        Where:
        - ΔCA = Change in current assets minus change in cash/equivalents
        - ΔCL = Change in current liabilities minus change in long-term debt in current liabilities 
                minus change in income taxes payable
        - DEP = Depreciation and amortization expense
        
        Scaled Net Operating Assets (SNOA):
        SNOA = (Operating Assets - Operating Liabilities) / Total Assets
        
        Args:
            df: DataFrame with fundamental data including year-over-year changes
            
        Returns:
            DataFrame with STA and SNOA columns added
        """
        df = df.copy()
        
        # Sort by company and period for change calculations
        df = df.sort_values(['ticker', 'period_end'])
        
        # Calculate year-over-year changes
        df['delta_current_assets'] = df.groupby('ticker')['current_assets'].diff()
        df['delta_cash'] = df.groupby('ticker')['cash'].diff()
        df['delta_current_liabilities'] = df.groupby('ticker')['current_liabilities'].diff()
        
        # Scaled Total Accruals (STA)
        # Simplified calculation - in practice would need more granular balance sheet data
        df['delta_ca_excl_cash'] = df['delta_current_assets'] - df['delta_cash']
        df['delta_cl_adjusted'] = df['delta_current_liabilities']  # Simplified
        
        # Note: Depreciation expense not directly available in current data structure
        # Would need to extract from cash flow statement or calculate from changes in PP&E
        # For now, we'll approximate using a simplified approach
        df['depreciation_approx'] = df['total_assets'] * 0.05  # Rough 5% estimate
        
        df['sta'] = (
            (df['delta_ca_excl_cash'] - df['delta_cl_adjusted'] - df['depreciation_approx']) 
            / df['total_assets']
        )
        
        # Scaled Net Operating Assets (SNOA)
        # Operating Assets ≈ Total Assets - Cash
        # Operating Liabilities ≈ Total Liabilities - Long-term Debt
        df['operating_assets'] = df['total_assets'] - df['cash'].fillna(0)
        df['operating_liabilities'] = df['total_liabilities'] - df['long_term_debt'].fillna(0)
        
        df['snoa'] = (
            (df['operating_assets'] - df['operating_liabilities']) 
            / df['total_assets']
        )
        
        logger.info("Calculated accrual quality metrics (STA, SNOA)")
        return df

    def calculate_beneish_mscore(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Beneish M-Score for manipulation probability.
        
        M-Score = -4.84 + 0.92×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI 
                  + 0.115×DEPI - 0.172×SGAI + 4.679×TATA - 0.327×LVGI
        
        Where:
        - DSRI: Days Sales in Receivables Index
        - GMI: Gross Margin Index  
        - AQI: Asset Quality Index
        - SGI: Sales Growth Index
        - DEPI: Depreciation Index
        - SGAI: SG&A Expenses Index
        - TATA: Total Accruals to Total Assets
        - LVGI: Leverage Index
        
        Args:
            df: DataFrame with fundamental data
            
        Returns:
            DataFrame with M-Score and component indices
        """
        df = df.copy()
        df = df.sort_values(['ticker', 'period_end'])
        
        # Calculate year-over-year metrics for indices
        for col in ['revenue', 'total_assets', 'gross_profit', 'long_term_debt']:
            if col in df.columns:
                df[f'{col}_lag'] = df.groupby('ticker')[col].shift(1)
        
        # 1. Days Sales in Receivables Index (DSRI)
        # Note: Receivables not in current data - would need accounts receivable
        # Approximating as 0 for now - this is a significant limitation
        df['dsri'] = 1.0  # Neutral value when receivables data unavailable
        
        # 2. Gross Margin Index (GMI)
        df['gross_margin_lag'] = df['gross_profit_lag'] / df['revenue_lag']
        df['gross_margin_current'] = df['gross_profit'] / df['revenue']
        df['gmi'] = df['gross_margin_lag'] / df['gross_margin_current']
        
        # 3. Asset Quality Index (AQI) 
        # AQI = (1 - (PPE + Current Assets)/Total Assets) current / prior
        # Approximating PPE as Total Assets - Current Assets
        df['ppe'] = df['total_assets'] - df['current_assets']
        df['ppe_lag'] = df['total_assets_lag'] - df.groupby('ticker')['current_assets'].shift(1)
        
        df['asset_quality'] = 1 - (df['ppe'] + df['current_assets']) / df['total_assets']
        df['asset_quality_lag'] = 1 - (df['ppe_lag'] + df.groupby('ticker')['current_assets'].shift(1)) / df['total_assets_lag']
        df['aqi'] = df['asset_quality'] / df['asset_quality_lag']
        
        # 4. Sales Growth Index (SGI)
        df['sgi'] = df['revenue'] / df['revenue_lag']
        
        # 5. Depreciation Index (DEPI) - requires depreciation data not available
        df['depi'] = 1.0  # Neutral when depreciation data unavailable
        
        # 6. SG&A Index (SGAI) - requires SG&A expense data not available
        df['sgai'] = 1.0  # Neutral when SG&A data unavailable
        
        # 7. Total Accruals to Total Assets (TATA)
        # TATA = (Net Income - CFO) / Total Assets
        df['tata'] = (df['net_income'] - df['cfo']) / df['total_assets']
        
        # 8. Leverage Index (LVGI)
        df['leverage'] = df['long_term_debt'] / df['total_assets']
        df['leverage_lag'] = df['long_term_debt_lag'] / df['total_assets_lag']
        df['lvgi'] = df['leverage'] / df['leverage_lag']
        
        # Calculate M-Score (handling missing values)
        df['mscore'] = (
            -4.84 
            + 0.92 * df['dsri'].fillna(1)
            + 0.528 * df['gmi'].fillna(1) 
            + 0.404 * df['aqi'].fillna(1)
            + 0.892 * df['sgi'].fillna(1)
            + 0.115 * df['depi'].fillna(1)
            - 0.172 * df['sgai'].fillna(1)
            + 4.679 * df['tata'].fillna(0)
            - 0.327 * df['lvgi'].fillna(1)
        )
        
        # Convert to probability using normal CDF
        df['manipulation_probability'] = norm.cdf(df['mscore'])
        
        logger.info("Calculated Beneish M-Score for manipulation detection")
        return df

    def calculate_financial_distress_probability(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Campbell Financial Distress Probability.
        
        This is a simplified implementation. The full model requires:
        - Market data (stock returns, volatility, market cap)
        - More granular balance sheet data
        - Weighted averages over time
        
        For now, implementing a basic version with available data.
        
        Args:
            df: DataFrame with fundamental data
            
        Returns:
            DataFrame with financial distress probability
        """
        df = df.copy()
        
        # Simplified financial distress indicators using available data
        
        # 1. Profitability indicator (ROA equivalent)
        df['roa_distress'] = df['net_income'] / df['total_assets']
        
        # 2. Leverage indicator  
        df['leverage_distress'] = df['total_liabilities'] / df['total_assets']
        
        # 3. Liquidity indicator
        df['liquidity_distress'] = df['cash'] / df['total_assets']
        
        # 4. Interest coverage (simplified)
        # Note: Interest expense not available, using operating income as proxy
        df['interest_coverage_proxy'] = np.where(
            df['operating_income'] > 0, 
            np.log(df['operating_income'] / df['total_assets']),
            -5  # Penalty for negative operating income
        )
        
        # Simple logistic regression approximation for financial distress
        # Coefficients estimated to penalize: low profitability, high leverage, low liquidity
        df['distress_score'] = (
            -3.0  # Intercept
            - 10.0 * df['roa_distress'].fillna(0)  # Penalize low/negative ROA
            + 5.0 * df['leverage_distress'].fillna(0.5)  # Penalize high leverage  
            - 8.0 * df['liquidity_distress'].fillna(0.05)  # Penalize low cash
            + df['interest_coverage_proxy'].fillna(-2)  # Penalize low coverage
        )
        
        # Convert to probability using logistic function
        df['financial_distress_probability'] = 1 / (1 + np.exp(-df['distress_score']))
        
        logger.info("Calculated financial distress probability")
        return df

    def calculate_combined_accrual_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate combined accrual score as specified in the model.
        
        COMBOACCRUAL = (P_STA + P_SNOA) / 2
        
        Where P_STA and P_SNOA are percentile ranks among all firms.
        
        Args:
            df: DataFrame with STA and SNOA calculated
            
        Returns:
            DataFrame with combined accrual score
        """
        df = df.copy()
        
        # Calculate percentile ranks (higher percentile = worse accruals)
        df['sta_percentile'] = df['sta'].rank(pct=True) * 100
        df['snoa_percentile'] = df['snoa'].rank(pct=True) * 100
        
        # Combined accrual score
        df['combo_accrual'] = (df['sta_percentile'] + df['snoa_percentile']) / 2
        
        return df

    def screen_high_risk_stocks(self, 
                              accrual_threshold: float = 95.0,
                              manipulation_threshold: float = 95.0, 
                              distress_threshold: float = 95.0) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """
        Complete risk screening to identify high-risk stocks for exclusion.
        
        Args:
            accrual_threshold: Percentile threshold for accrual quality (default 95 = worst 5%)
            manipulation_threshold: Percentile threshold for manipulation probability 
            distress_threshold: Percentile threshold for financial distress probability
            
        Returns:
            Tuple of (clean_stocks_df, excluded_stocks_dict)
            where excluded_stocks_dict contains separate DataFrames for each risk category
        """
        logger.info("Starting comprehensive risk screening")
        
        # Get latest data for each company
        df = self.fundamentals_df.copy()
        df['period_end'] = pd.to_datetime(df['period_end'])
        latest_df = df.sort_values('period_end').groupby('ticker').tail(1)
        
        logger.info(f"Starting with {len(latest_df)} companies")
        
        # Calculate all risk metrics
        df_with_metrics = self.calculate_accrual_metrics(latest_df)
        df_with_metrics = self.calculate_beneish_mscore(df_with_metrics)
        df_with_metrics = self.calculate_financial_distress_probability(df_with_metrics)
        df_with_metrics = self.calculate_combined_accrual_score(df_with_metrics)
        
        # Calculate percentile ranks for screening thresholds
        df_with_metrics['manipulation_percentile'] = (
            df_with_metrics['manipulation_probability'].rank(pct=True) * 100
        )
        df_with_metrics['distress_percentile'] = (
            df_with_metrics['financial_distress_probability'].rank(pct=True) * 100
        )
        
        # Create separate exclusion categories
        high_accruals = df_with_metrics[df_with_metrics['combo_accrual'] >= accrual_threshold].copy()
        high_manipulation = df_with_metrics[df_with_metrics['manipulation_percentile'] >= manipulation_threshold].copy()
        high_distress = df_with_metrics[df_with_metrics['distress_percentile'] >= distress_threshold].copy()
        
        # Identify all high-risk stocks (any category)
        high_risk_mask = (
            (df_with_metrics['combo_accrual'] >= accrual_threshold) |
            (df_with_metrics['manipulation_percentile'] >= manipulation_threshold) |
            (df_with_metrics['distress_percentile'] >= distress_threshold)
        )
        
        all_excluded_stocks = df_with_metrics[high_risk_mask].copy()
        clean_stocks = df_with_metrics[~high_risk_mask].copy()
        
        # Add exclusion reason flags to all excluded stocks
        all_excluded_stocks['excluded_accruals'] = all_excluded_stocks['combo_accrual'] >= accrual_threshold
        all_excluded_stocks['excluded_manipulation'] = all_excluded_stocks['manipulation_percentile'] >= manipulation_threshold
        all_excluded_stocks['excluded_distress'] = all_excluded_stocks['distress_percentile'] >= distress_threshold
        
        # Sort each category by risk score (worst first)
        high_accruals = high_accruals.sort_values('combo_accrual', ascending=False)
        high_manipulation = high_manipulation.sort_values('manipulation_percentile', ascending=False)
        high_distress = high_distress.sort_values('distress_percentile', ascending=False)
        all_excluded_stocks = all_excluded_stocks.sort_values('combo_accrual', ascending=False)
        
        excluded_stocks_dict = {
            'All_Excluded': all_excluded_stocks,
            'High_Accruals': high_accruals,
            'High_Manipulation_Risk': high_manipulation,
            'High_Distress_Risk': high_distress
        }
        
        logger.info(f"Risk screening results:")
        logger.info(f"  Excluded for high accruals: {len(high_accruals)}")
        logger.info(f"  Excluded for manipulation risk: {len(high_manipulation)}")
        logger.info(f"  Excluded for distress risk: {len(high_distress)}")
        logger.info(f"  Total excluded: {len(all_excluded_stocks)}")
        logger.info(f"  Clean stocks remaining: {len(clean_stocks)}")
        
        return clean_stocks, excluded_stocks_dict