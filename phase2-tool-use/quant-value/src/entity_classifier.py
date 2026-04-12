"""
Entity Classifier - Identify and exclude non-operating companies

This module identifies entities that should be excluded from quantitative value screening:
- REITs (Real Estate Investment Trusts)
- Mutual Funds / ETFs / Closed-End Funds
- Business Development Companies (BDCs)
- Master Limited Partnerships (MLPs)
- Other investment vehicles

These entities have different accounting rules, capital structures, and valuation
methodologies that don't fit traditional quantitative value analysis.
"""

import pandas as pd
import numpy as np
import logging
from typing import Set, List

logger = logging.getLogger(__name__)

# SIC Codes for exclusion
REIT_SIC_CODES = [
    '6798',  # Real Estate Investment Trusts
]

FUND_SIC_CODES = [
    '6722',  # Management Investment Offices, Open-End
    '6726',  # Unit Investment Trusts
    '6282',  # Investment Advice
]

BDC_SIC_CODES = [
    '6799',  # Investors, Not Elsewhere Classified (includes BDCs)
]

# Ticker suffix patterns that indicate REITs or special securities
REIT_TICKER_PATTERNS = [
    # Preferred shares and special classes often belong to REITs
    '-',  # Preferred shares indicator (e.g., "BPY-PA")
    '^',  # Also preferred
]

# Name patterns for REITs
REIT_NAME_PATTERNS = [
    ' REIT',
    'REAL ESTATE INVESTMENT TRUST',
    'REALTY TRUST',
    'REALTY INCOME',
    'PROPERTIES TRUST',
    'PROPERTY TRUST',
]

# Name patterns for Funds
FUND_NAME_PATTERNS = [
    'FUND',
    ' ETF',
    'EXCHANGE TRADED',
    'INVESTMENT COMPANY',
    'TRUST SERIES',
    'PORTFOLIO SERIES',
    'CLOSED END',
    'CLOSED-END',
]

# Name patterns for BDCs and MLPs
BDC_NAME_PATTERNS = [
    'BUSINESS DEVELOPMENT',
    'BDC',
]

MLP_NAME_PATTERNS = [
    'MLP',
    'MASTER LIMITED PARTNERSHIP',
    'PARTNERS LP',
    'ENERGY PARTNERS',
]


class EntityClassifier:
    """Classifies entities and identifies those to exclude from screening."""

    def __init__(self, exclusion_list_path: str = None):
        """
        Initialize the entity classifier.

        Args:
            exclusion_list_path: Path to CSV with known REITs/funds to exclude
        """
        self.excluded_tickers = set()
        self.exclusion_reasons = {}

        # Load manual exclusion list if provided
        if exclusion_list_path:
            self._load_exclusion_list(exclusion_list_path)
        else:
            # Try default location
            from pathlib import Path
            default_path = Path(__file__).parent.parent / 'data' / 'processed' / 'reit_fund_exclusion_list.csv'
            if default_path.exists():
                self._load_exclusion_list(str(default_path))

    def _load_exclusion_list(self, path: str):
        """Load manual exclusion list from CSV."""
        try:
            exclusion_df = pd.read_csv(path)
            for _, row in exclusion_df.iterrows():
                ticker = row['ticker']
                entity_type = row['entity_type']
                self.excluded_tickers.add(ticker)
                self.exclusion_reasons[ticker] = entity_type
            logger.info(f"Loaded {len(self.excluded_tickers)} tickers from manual exclusion list")
        except Exception as e:
            logger.warning(f"Could not load exclusion list from {path}: {e}")

    def classify_entities(self, df: pd.DataFrame,
                         ticker_col: str = 'ticker',
                         name_col: str = 'name',
                         sic_col: str = 'sic') -> pd.DataFrame:
        """
        Classify entities and mark those to exclude.

        Args:
            df: DataFrame with company data
            ticker_col: Column name for ticker symbols
            name_col: Column name for company names (optional)
            sic_col: Column name for SIC codes (optional)

        Returns:
            DataFrame with added columns:
                - is_reit: Boolean
                - is_fund: Boolean
                - is_bdc: Boolean
                - exclude_from_screening: Boolean
                - exclusion_reason: String explanation
        """
        df = df.copy()

        # Initialize classification columns
        df['is_reit'] = False
        df['is_fund'] = False
        df['is_bdc'] = False
        df['is_mlp'] = False
        df['is_gse'] = False
        df['exclude_from_screening'] = False
        df['exclusion_reason'] = ''

        # Apply manual exclusion list first
        if self.excluded_tickers:
            for ticker, entity_type in self.exclusion_reasons.items():
                mask = df[ticker_col] == ticker
                if entity_type == 'REIT':
                    df.loc[mask, 'is_reit'] = True
                elif entity_type in ['FUND', 'ETF']:
                    df.loc[mask, 'is_fund'] = True
                elif entity_type == 'BDC':
                    df.loc[mask, 'is_bdc'] = True
                elif entity_type == 'MLP':
                    df.loc[mask, 'is_mlp'] = True
                elif entity_type == 'GSE':
                    df.loc[mask, 'is_gse'] = True

        # Classify by SIC code if available
        if sic_col in df.columns:
            df = self._classify_by_sic(df, sic_col)

        # Classify by company name if available
        if name_col in df.columns:
            df = self._classify_by_name(df, name_col)

        # Classify by ticker patterns
        df = self._classify_by_ticker(df, ticker_col)

        # Classify by financial characteristics (REIT detection)
        df = self._classify_by_financials(df)

        # Mark entities for exclusion
        df['exclude_from_screening'] = (
            df['is_reit'] | df['is_fund'] | df['is_bdc'] | df['is_mlp'] | df['is_gse']
        )

        # Set exclusion reasons
        df.loc[df['is_reit'], 'exclusion_reason'] = 'REIT'
        df.loc[df['is_fund'], 'exclusion_reason'] = 'Investment Fund'
        df.loc[df['is_bdc'], 'exclusion_reason'] = 'Business Development Company'
        df.loc[df['is_mlp'], 'exclusion_reason'] = 'Master Limited Partnership'
        df.loc[df['is_gse'], 'exclusion_reason'] = 'Government-Sponsored Enterprise'

        # Log summary
        excluded_count = df['exclude_from_screening'].sum()
        logger.info(f"Entity classification complete:")
        logger.info(f"  - REITs: {df['is_reit'].sum()}")
        logger.info(f"  - Funds: {df['is_fund'].sum()}")
        logger.info(f"  - BDCs: {df['is_bdc'].sum()}")
        logger.info(f"  - MLPs: {df['is_mlp'].sum()}")
        logger.info(f"  - GSEs: {df['is_gse'].sum()}")
        logger.info(f"  - Total excluded: {excluded_count} ({excluded_count/len(df)*100:.1f}%)")

        return df

    def _classify_by_sic(self, df: pd.DataFrame, sic_col: str) -> pd.DataFrame:
        """Classify entities by SIC code."""
        if sic_col not in df.columns:
            return df

        sic_str = df[sic_col].astype(str)

        # REITs
        for code in REIT_SIC_CODES:
            df.loc[sic_str == code, 'is_reit'] = True

        # Funds
        for code in FUND_SIC_CODES:
            df.loc[sic_str == code, 'is_fund'] = True

        # BDCs
        for code in BDC_SIC_CODES:
            df.loc[sic_str == code, 'is_bdc'] = True

        return df

    def _classify_by_name(self, df: pd.DataFrame, name_col: str) -> pd.DataFrame:
        """Classify entities by company name patterns."""
        if name_col not in df.columns:
            return df

        names_upper = df[name_col].str.upper().fillna('')

        # REITs
        for pattern in REIT_NAME_PATTERNS:
            df.loc[names_upper.str.contains(pattern, regex=False), 'is_reit'] = True

        # Funds
        for pattern in FUND_NAME_PATTERNS:
            df.loc[names_upper.str.contains(pattern, regex=False), 'is_fund'] = True

        # BDCs
        for pattern in BDC_NAME_PATTERNS:
            df.loc[names_upper.str.contains(pattern, regex=False), 'is_bdc'] = True

        # MLPs
        for pattern in MLP_NAME_PATTERNS:
            df.loc[names_upper.str.contains(pattern, regex=False), 'is_mlp'] = True

        return df

    def _classify_by_ticker(self, df: pd.DataFrame, ticker_col: str) -> pd.DataFrame:
        """Classify entities by ticker symbol patterns."""
        tickers = df[ticker_col].fillna('')

        # Preferred shares (often REITs)
        has_dash = tickers.str.contains('-', regex=False)
        has_caret = tickers.str.contains(r'\^', regex=False)

        # Mark as potential REITs (but don't override if already classified)
        df.loc[(has_dash | has_caret) & ~df['is_fund'], 'is_reit'] = True

        return df

    def _classify_by_financials(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify REITs by financial characteristics.

        DISABLED: Financial characteristics approach generates too many false positives.
        Rely on manual exclusion list, ticker patterns, and name patterns instead.
        """
        # Disabled to avoid false positives
        return df

    def get_exclusion_list(self, df: pd.DataFrame) -> List[str]:
        """
        Get list of tickers to exclude.

        Args:
            df: DataFrame with classification columns

        Returns:
            List of ticker symbols to exclude
        """
        if 'exclude_from_screening' not in df.columns:
            df = self.classify_entities(df)

        excluded = df[df['exclude_from_screening']]['ticker'].tolist()
        return excluded

    def filter_dataframe(self, df: pd.DataFrame, ticker_col: str = 'ticker') -> pd.DataFrame:
        """
        Remove excluded entities from DataFrame.

        Args:
            df: DataFrame to filter
            ticker_col: Column name for ticker symbols

        Returns:
            Filtered DataFrame with excluded entities removed
        """
        # Classify if not already done
        if 'exclude_from_screening' not in df.columns:
            df = self.classify_entities(df, ticker_col=ticker_col)

        # Filter
        original_count = len(df)
        filtered_df = df[~df['exclude_from_screening']].copy()
        removed_count = original_count - len(filtered_df)

        logger.info(f"Filtered out {removed_count} entities ({removed_count/original_count*100:.1f}%)")
        logger.info(f"Remaining: {len(filtered_df)} companies")

        return filtered_df
