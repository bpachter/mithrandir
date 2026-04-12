#!/usr/bin/env python3

"""
Alpha Vantage Market Data Provider

Free tier: 25 API calls per day, 5 calls per minute
Perfect for pricing data with our patient approach.

Key features:
- Stock quotes and basic market data
- No API key required for basic quotes
- Rate limiting built-in
- Fallback integration ready
"""

import requests
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)

class AlphaVantageProvider:
    """
    Alpha Vantage API provider for stock pricing data.
    Free tier: 25 calls/day, 5 calls/minute.
    """
    
    def __init__(self, api_key: str = None, cache_dir: Path = None, enable_cache: bool = True):
        """
        Initialize Alpha Vantage provider.
        
        Args:
            api_key: Alpha Vantage API key (optional for basic quotes)
            cache_dir: Directory for caching data
            enable_cache: Whether to enable caching
        """
        self.api_key = api_key or "demo"  # Free demo key for basic functionality
        self.base_url = "https://www.alphavantage.co/query"
        self.cache_dir = cache_dir or Path("data/alphavantage_cache")
        self.enable_cache = enable_cache
        
        if self.enable_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Rate limiting: 5 calls per minute max
        self.last_request_time = 0
        self.min_request_interval = 12.0  # 12 seconds between requests (conservative)
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'EDGAR-Fundamentals/1.0'
        })
        
        logger.info(f"Alpha Vantage provider initialized (API key: {'***' + self.api_key[-4:] if len(self.api_key) > 4 else 'demo'})")
    
    def _rate_limit(self):
        """Apply conservative rate limiting."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            logger.info(f"Rate limiting: waiting {sleep_time:.1f} seconds...")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _get_cache_path(self, symbol: str) -> Path:
        """Get cache file path for a symbol."""
        return self.cache_dir / f"{symbol}_alphavantage.json"
    
    def _load_from_cache(self, symbol: str, max_age_hours: int = 24) -> Optional[Dict]:
        """Load cached data if available and recent."""
        if not self.enable_cache:
            return None
        
        cache_file = self._get_cache_path(symbol)
        
        try:
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    cached_data = json.load(f)
                
                # Check if cache is still valid
                cache_time = datetime.fromisoformat(cached_data['timestamp'])
                age_hours = (datetime.now() - cache_time).total_seconds() / 3600
                
                if age_hours <= max_age_hours:
                    logger.info(f"Using cached data for {symbol} (age: {age_hours:.1f}h)")
                    return cached_data
                    
        except Exception as e:
            logger.warning(f"Cache read failed for {symbol}: {e}")
        
        return None
    
    def _save_to_cache(self, symbol: str, data: Dict):
        """Save data to cache."""
        if not self.enable_cache:
            return
        
        try:
            cache_file = self._get_cache_path(symbol)
            data['timestamp'] = datetime.now().isoformat()
            
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Cache save failed for {symbol}: {e}")
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get current quote for a symbol using Alpha Vantage GLOBAL_QUOTE function.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            
        Returns:
            Dict with quote data or None if failed
        """
        # Check cache first
        cached_data = self._load_from_cache(symbol)
        if cached_data:
            return cached_data
        
        # Apply rate limiting
        self._rate_limit()
        
        try:
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.api_key
            }
            
            logger.info(f"Fetching Alpha Vantage quote for {symbol}")
            response = self.session.get(self.base_url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check for API errors
                if 'Error Message' in data:
                    logger.error(f"Alpha Vantage error for {symbol}: {data['Error Message']}")
                    return None
                
                if 'Note' in data:
                    logger.warning(f"Alpha Vantage note for {symbol}: {data['Note']}")
                    return None
                
                if 'Global Quote' in data:
                    quote = data['Global Quote']
                    
                    # Parse the quote data
                    quote_data = {
                        'ticker': symbol,
                        'price': float(quote.get('05. price', 0)),
                        'change': float(quote.get('09. change', 0)),
                        'change_percent': quote.get('10. change percent', '0%').replace('%', ''),
                        'volume': int(quote.get('06. volume', 0)),
                        'latest_trading_day': quote.get('07. latest trading day', ''),
                        'previous_close': float(quote.get('08. previous close', 0)),
                        'open': float(quote.get('02. open', 0)),
                        'high': float(quote.get('03. high', 0)),
                        'low': float(quote.get('04. low', 0)),
                        'source': 'alphavantage',
                        'api_key_type': 'demo' if self.api_key == 'demo' else 'paid'
                    }
                    
                    # Cache the result
                    self._save_to_cache(symbol, quote_data)
                    
                    logger.info(f"✅ Alpha Vantage: {symbol} = ${quote_data['price']:.2f}")
                    return quote_data
                    
                else:
                    logger.warning(f"No Global Quote data for {symbol}")
                    return None
            else:
                logger.error(f"Alpha Vantage API error {response.status_code} for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Alpha Vantage request failed for {symbol}: {e}")
            return None
    
    def get_current_price_data(self, tickers: List[str]) -> pd.DataFrame:
        """
        Get current price data for multiple tickers.
        
        Args:
            tickers: List of stock symbols
            
        Returns:
            DataFrame with standardized market data columns
        """
        logger.info(f"Fetching Alpha Vantage data for {len(tickers)} tickers")
        
        market_data = []
        
        for i, symbol in enumerate(tickers):
            logger.info(f"Processing {symbol} ({i+1}/{len(tickers)})")
            
            quote_data = self.get_quote(symbol)
            
            if quote_data:
                # Convert to standardized format
                standardized = {
                    'ticker': symbol,
                    'price': quote_data['price'],
                    'market_cap': np.nan,  # Alpha Vantage free tier doesn't provide market cap
                    'shares_outstanding': np.nan,
                    'volume': quote_data['volume'],
                    'avg_volume': np.nan,
                    'pe_ratio': np.nan,
                    'beta': np.nan,
                    'fifty_two_week_high': np.nan,
                    'fifty_two_week_low': np.nan,
                    'dividend_yield': np.nan,
                    'open': quote_data['open'],
                    'high': quote_data['high'],
                    'low': quote_data['low'],
                    'previous_close': quote_data['previous_close'],
                    'change': quote_data['change'],
                    'change_percent': quote_data['change_percent'],
                    'latest_trading_day': quote_data['latest_trading_day'],
                    'source': 'alphavantage',
                    'last_updated': datetime.now()
                }
            else:
                # Add placeholder for failed ticker
                standardized = {
                    'ticker': symbol,
                    'price': np.nan,
                    'market_cap': np.nan,
                    'shares_outstanding': np.nan,
                    'volume': np.nan,
                    'avg_volume': np.nan,
                    'pe_ratio': np.nan,
                    'beta': np.nan,
                    'fifty_two_week_high': np.nan,
                    'fifty_two_week_low': np.nan,
                    'dividend_yield': np.nan,
                    'open': np.nan,
                    'high': np.nan,
                    'low': np.nan,
                    'previous_close': np.nan,
                    'change': np.nan,
                    'change_percent': np.nan,
                    'latest_trading_day': '',
                    'source': 'alphavantage_failed',
                    'last_updated': datetime.now()
                }
            
            market_data.append(standardized)
        
        df = pd.DataFrame(market_data)
        
        successful_count = len(df[df['source'] == 'alphavantage'])
        logger.info(f"Alpha Vantage success rate: {successful_count}/{len(df)} ({successful_count/len(df)*100:.1f}%)")
        
        return df

def test_alpha_vantage_provider():
    """Test Alpha Vantage provider functionality."""
    print("="*60)
    print("TESTING ALPHA VANTAGE PROVIDER")
    print("="*60)
    
    provider = AlphaVantageProvider()
    
    # Test with a few major stocks
    test_tickers = ['AAPL', 'GOOGL', 'MSFT']
    print(f"Testing with tickers: {test_tickers}")
    
    market_data = provider.get_current_price_data(test_tickers)
    
    if not market_data.empty:
        print(f"\n✅ Alpha Vantage data retrieved!")
        print(f"Records: {len(market_data)}")
        
        # Show results
        display_cols = ['ticker', 'price', 'volume', 'change', 'source']
        print("\nResults:")
        print(market_data[display_cols].to_string(index=False))
        
        # Show success rate
        success_rate = len(market_data[market_data['source'] == 'alphavantage']) / len(market_data) * 100
        print(f"\nSuccess rate: {success_rate:.1f}%")
        
    else:
        print("❌ No data retrieved")
    
    print(f"\n{'='*60}")
    print("Alpha Vantage Provider Test Complete")
    print(f"{'='*60}")

if __name__ == "__main__":
    test_alpha_vantage_provider()