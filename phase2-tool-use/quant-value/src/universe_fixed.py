"""
Fixed universe management using direct CIK lookups.
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd
from edgar import Company, set_identity
import httpx

logger = logging.getLogger(__name__)


class UniverseFixed:
    """Manages the investment universe - fixed version."""

    def __init__(self, tickers_path: Path, companies_output_path: Path, user_agent: str = None):
        """Initialize universe manager."""
        self.tickers_path = tickers_path
        self.companies_output_path = companies_output_path
        self.companies_df = None

        if user_agent:
            logger.info(f"Setting SEC identity: {user_agent}")
            set_identity(user_agent)
            self.user_agent = user_agent

    def load_tickers(self) -> List[str]:
        """Load tickers from tickers.txt file."""
        logger.info(f"Loading tickers from {self.tickers_path}")
        with open(self.tickers_path, 'r') as f:
            tickers = [line.strip().upper() for line in f if line.strip()]
        logger.info(f"Loaded {len(tickers)} tickers")
        return tickers

    def fetch_company_tickers_json(self) -> Dict:
        """Fetch company tickers JSON directly from SEC."""
        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {"User-Agent": self.user_agent}

        logger.info("Fetching company tickers from SEC")
        response = httpx.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()

        return response.json()

    def map_ticker_to_cik(self, ticker: str, tickers_map: Dict) -> Optional[Dict[str, str]]:
        """Map a ticker to CIK using the tickers map."""
        ticker_lower = ticker.lower()

        for key, company_info in tickers_map.items():
            if company_info.get('ticker', '').lower() == ticker_lower:
                cik = str(company_info['cik_str']).zfill(10)
                return {
                    'ticker': ticker,
                    'cik': cik,
                    'name': company_info['title']
                }

        logger.warning(f"Ticker {ticker} not found in SEC database")
        return None

    def build_companies_table(self, tickers: List[str] = None) -> pd.DataFrame:
        """Build companies table by mapping all tickers to CIKs."""
        if tickers is None:
            tickers = self.load_tickers()

        logger.info(f"Building companies table for {len(tickers)} tickers")

        # Fetch all company tickers from SEC
        tickers_map = self.fetch_company_tickers_json()

        companies = []
        for ticker in tickers:
            company_info = self.map_ticker_to_cik(ticker, tickers_map)
            if company_info:
                companies.append(company_info)
            else:
                logger.warning(f"Skipping {ticker} - unable to map to CIK")

        self.companies_df = pd.DataFrame(companies)
        logger.info(f"Successfully mapped {len(self.companies_df)} companies")

        return self.companies_df

    def build_universe_from_sec(self, filters: Dict = None) -> pd.DataFrame:
        """
        Build universe from ALL SEC companies.

        Args:
            filters: Optional dict to filter companies
                - 'exclude_otc': Exclude OTC stocks (ticker length > 4)
                - 'min_ticker_length': Minimum ticker length
                - 'max_ticker_length': Maximum ticker length

        Returns:
            DataFrame with all SEC companies matching filters
        """
        logger.info("Fetching ALL companies from SEC")

        # Fetch master company list from SEC
        tickers_map = self.fetch_company_tickers_json()

        # Convert to DataFrame
        companies = []
        for key, info in tickers_map.items():
            ticker = info.get('ticker', '').upper()
            if not ticker:
                continue

            companies.append({
                'ticker': ticker,
                'cik': str(info['cik_str']).zfill(10),
                'name': info['title']
            })

        df = pd.DataFrame(companies)
        logger.info(f"Found {len(df)} total SEC filers")

        # Apply filters if provided
        if filters:
            df = self._apply_filters(df, filters)
            logger.info(f"After filtering: {len(df)} companies")

        self.companies_df = df
        return df

    def _apply_filters(self, df: pd.DataFrame, filters: Dict) -> pd.DataFrame:
        """Apply filtering criteria to companies DataFrame."""
        original_count = len(df)

        # Filter by ticker length (excludes most OTC stocks)
        if filters.get('exclude_otc', False):
            df = df[df['ticker'].str.len() <= 4]
            logger.info(f"Excluded OTC: {original_count} -> {len(df)} companies")

        if 'min_ticker_length' in filters:
            df = df[df['ticker'].str.len() >= filters['min_ticker_length']]

        if 'max_ticker_length' in filters:
            df = df[df['ticker'].str.len() <= filters['max_ticker_length']]

        # Exclude common suffixes that indicate non-standard securities
        exclude_patterns = [
            r'\.',  # Dots (often preferred shares)
            r'-',   # Dashes (often warrants, units)
        ]
        for pattern in exclude_patterns:
            df = df[~df['ticker'].str.contains(pattern, regex=True)]

        return df

    def build_universe(self, mode: str = 'manual', filters: Dict = None,
                      test_mode: bool = False, test_size: int = 20) -> pd.DataFrame:
        """
        Build universe based on mode.

        Args:
            mode: 'manual', 'all_sec', or 'filtered_sec'
            filters: Filtering criteria (for filtered_sec mode)
            test_mode: If True, limit to test_size companies
            test_size: Number of companies for testing

        Returns:
            DataFrame with companies
        """
        logger.info(f"Building universe in '{mode}' mode")

        if mode == 'manual':
            tickers = self.load_tickers()
            df = self.build_companies_table(tickers)

        elif mode == 'all_sec':
            df = self.build_universe_from_sec(filters=None)

        elif mode == 'filtered_sec':
            df = self.build_universe_from_sec(filters=filters)

        else:
            raise ValueError(f"Unknown universe mode: {mode}")

        # Apply test mode if requested
        if test_mode:
            logger.info(f"TEST MODE: Limiting to {test_size} companies")
            df = df.head(test_size)

        self.companies_df = df
        return df

    def save_companies_table(self):
        """Save companies table to CSV."""
        if self.companies_df is None:
            raise ValueError("No companies table to save")

        logger.info(f"Saving companies table to {self.companies_output_path}")
        self.companies_df.to_csv(self.companies_output_path, index=False)
        logger.info(f"Saved {len(self.companies_df)} companies")

    def load_companies_table(self) -> pd.DataFrame:
        """Load companies table from CSV."""
        logger.info(f"Loading companies table from {self.companies_output_path}")
        self.companies_df = pd.read_csv(self.companies_output_path, dtype={'cik': str})
        logger.info(f"Loaded {len(self.companies_df)} companies")
        return self.companies_df

    def get_companies(self) -> pd.DataFrame:
        """Get companies table."""
        if self.companies_df is None:
            if self.companies_output_path.exists():
                return self.load_companies_table()
            else:
                raise ValueError("No companies table available")
        return self.companies_df

    def refresh_universe(self) -> pd.DataFrame:
        """Refresh the universe."""
        logger.info("Refreshing universe")
        self.build_companies_table()
        self.save_companies_table()
        return self.companies_df
