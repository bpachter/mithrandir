"""
EDGAR data fetching module: retrieves 10-K and 10-Q filings.
"""
import logging
import json
import time
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import httpx
from edgar import Company, set_identity

logger = logging.getLogger(__name__)


class EdgarFetcher:
    """Fetches financial data from SEC EDGAR."""

    def __init__(self, cache_dir: Path, user_agent: str, cache_enabled: bool = True):
        """
        Initialize EDGAR fetcher.

        Args:
            cache_dir: Directory for caching raw data
            user_agent: User agent string for SEC API
            cache_enabled: Whether to use local cache
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_enabled = cache_enabled
        self.user_agent = user_agent

        # Set identity for SEC API
        logger.info(f"Setting SEC identity: {user_agent}")
        set_identity(user_agent)

    def get_cache_path(self, cik: str) -> Path:
        """Get cache file path for a CIK."""
        return self.cache_dir / f"{cik}.json"

    def fetch_company_facts(self, cik: str, ticker: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Fetch company facts (XBRL data) for a CIK.

        Args:
            cik: 10-digit CIK string
            ticker: Stock ticker (for logging)
            force_refresh: Force download even if cached

        Returns:
            Dictionary of company facts or None if failed
        """
        cache_path = self.get_cache_path(cik)

        # Try to load from cache first
        if self.cache_enabled and not force_refresh and cache_path.exists():
            logger.debug(f"Loading cached data for {ticker} (CIK: {cik})")
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache for {ticker}: {e}")

        # Fetch from SEC EDGAR using direct API call
        logger.info(f"Fetching company facts for {ticker} (CIK: {cik}) from EDGAR")
        try:
            # Use SEC API directly to get raw JSON
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            headers = {"User-Agent": self.user_agent}

            response = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
            response.raise_for_status()

            facts_dict = response.json()

            # Cache the data
            if self.cache_enabled:
                logger.debug(f"Caching data for {ticker}")
                with open(cache_path, 'w') as f:
                    json.dump(facts_dict, f, indent=2)

            return facts_dict

        except Exception as e:
            logger.error(f"Failed to fetch facts for {ticker} (CIK: {cik}): {e}")
            return None

    def extract_filing_metadata(self, cik: str, ticker: str) -> List[Dict]:
        """
        Extract filing metadata for 10-K and 10-Q forms.

        Args:
            cik: 10-digit CIK string
            ticker: Stock ticker

        Returns:
            List of filing metadata dictionaries
        """
        logger.info(f"Extracting filing metadata for {ticker}")

        try:
            company = Company(cik)
            filings = company.get_filings()

            # Filter for 10-K, 10-Q, and 20-F forms
            relevant_forms = ['10-K', '10-Q', '20-F']
            filtered = [
                {
                    'ticker': ticker,
                    'cik': cik,
                    'form': filing.form,
                    'filing_date': str(filing.filing_date),
                    'period_of_report': str(filing.period_of_report),
                    'accession_number': filing.accession_number
                }
                for filing in filings
                if filing.form in relevant_forms
            ]

            logger.info(f"Found {len(filtered)} relevant filings for {ticker}")
            return filtered

        except Exception as e:
            logger.error(f"Failed to get filings for {ticker}: {e}")
            return []

    def fetch_all_companies(self, companies_df: pd.DataFrame, force_refresh: bool = False,
                           batch_size: int = 50, batch_delay: int = 5) -> Dict[str, Dict]:
        """
        Fetch company facts for all companies with batch processing and rate limiting.

        Args:
            companies_df: DataFrame with columns: ticker, cik, name
            force_refresh: Force download even if cached
            batch_size: Number of companies to process per batch
            batch_delay: Seconds to wait between batches

        Returns:
            Dictionary mapping CIK to company facts
        """
        total_companies = len(companies_df)
        logger.info(f"Fetching data for {total_companies} companies")
        logger.info(f"Batch size: {batch_size}, Batch delay: {batch_delay}s")

        all_facts = {}
        request_times = []

        for idx, row in companies_df.iterrows():
            ticker = row['ticker']
            cik = row['cik']

            # Rate limiting: ensure we don't exceed requests per second
            if len(request_times) >= 8:  # Max 8 requests per second
                elapsed = time.time() - request_times[0]
                if elapsed < 1.0:
                    sleep_time = 1.0 - elapsed
                    logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
                    time.sleep(sleep_time)
                request_times.pop(0)

            request_times.append(time.time())

            logger.info(f"[{idx+1}/{total_companies}] Processing {ticker}")

            facts = self.fetch_company_facts(cik, ticker, force_refresh)
            if facts:
                all_facts[cik] = facts
            else:
                logger.warning(f"No facts retrieved for {ticker}")

            # Batch delay: pause after every batch_size companies
            if (idx + 1) % batch_size == 0 and (idx + 1) < total_companies:
                logger.info(f"Completed batch {(idx + 1) // batch_size}. Pausing {batch_delay}s before next batch...")
                time.sleep(batch_delay)

                # Log progress
                success_rate = len(all_facts) / (idx + 1) * 100
                logger.info(f"Progress: {idx+1}/{total_companies} ({success_rate:.1f}% successful)")

        logger.info(f"Successfully fetched data for {len(all_facts)} companies")
        return all_facts

    def get_cached_facts(self, cik: str) -> Optional[Dict]:
        """
        Get cached company facts if available.

        Args:
            cik: 10-digit CIK string

        Returns:
            Company facts dictionary or None
        """
        cache_path = self.get_cache_path(cik)
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load cached facts for CIK {cik}: {e}")
        return None

    def clear_cache(self, cik: str = None):
        """
        Clear cached data.

        Args:
            cik: If specified, clear only this CIK. Otherwise clear all.
        """
        if cik:
            cache_path = self.get_cache_path(cik)
            if cache_path.exists():
                cache_path.unlink()
                logger.info(f"Cleared cache for CIK {cik}")
        else:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
            logger.info("Cleared all cached data")
