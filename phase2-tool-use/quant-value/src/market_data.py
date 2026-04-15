"""
Market Data Integration Module for Quantitative Value Model

Provides real-time and historical market data for accurate enterprise value calculations.
Integrates with Yahoo Finance API for reliable, free market data.

Key functionality:
1. Stock price retrieval (current and historical)
2. Market capitalization calculations
3. Accurate Total Enterprise Value (TEV)
4. Stock returns and volatility metrics
5. Trading volume and liquidity analysis
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import time

# DefeatBeta bridge import (primary source)
try:
    from defeatbeta_bridge import DefeatBetaBridge
    DEFEATBETA_AVAILABLE = True
except ImportError:
    DefeatBetaBridge = None
    DEFEATBETA_AVAILABLE = False

# Yahoo Finance import (fallback for gaps only)
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    YFINANCE_AVAILABLE = False

# Optional Alpha Vantage provider import
try:
    from alphavantage_provider import AlphaVantageProvider
    ALPHAVANTAGE_AVAILABLE = True
except ImportError:
    AlphaVantageProvider = None
    ALPHAVANTAGE_AVAILABLE = False

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """
    Provides market data for the Quantitative Value investment model.

    Uses DefeatBeta API as the primary data source with built-in caching
    for reliable data retrieval without rate limits.
    """

    def __init__(self, cache_dir: Path = None, enable_cache: bool = True, 
                 enable_defeatbeta: bool = True):
        """
        Initialize market data provider.
        
        Args:
            cache_dir: Directory for caching market data
            enable_cache: Whether to cache data locally
            enable_defeatbeta: Whether to try DefeatBeta bridge
        """
        # Use absolute path based on this file's location so it works from any cwd
        self.cache_dir = cache_dir or (Path(__file__).parent.parent / "data" / "market_cache")
        self.enable_cache = enable_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # DefeatBeta bridge setup
        self.enable_defeatbeta = enable_defeatbeta and DEFEATBETA_AVAILABLE
        if self.enable_defeatbeta:
            self.defeatbeta_bridge = DefeatBetaBridge()
            logger.info("DefeatBeta bridge enabled")
        else:
            self.defeatbeta_bridge = None
            if enable_defeatbeta and not DEFEATBETA_AVAILABLE:
                logger.warning("DefeatBeta requested but bridge not available")
        
        # Rate limiting parameters
        self.last_request_time = 0
        self.min_request_interval = 2.0  # 2 seconds between requests (conservative for Yahoo Finance)
        
        logger.info(f"MarketDataProvider initialized with cache: {self.enable_cache}")

    def _rate_limit(self):
        """Apply rate limiting between API requests."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()

    def get_current_price_data(self, tickers: List[str]) -> pd.DataFrame:
        """
        Get current market data using hybrid approach:
        1. DefeatBeta (primary, no rate limits)
        2. Yahoo Finance (fallback for gaps only)

        Args:
            tickers: List of stock tickers

        Returns:
            DataFrame with current price data including:
            - ticker, price, market_cap, volume
        """
        logger.info(f"Fetching current market data for {len(tickers)} tickers")

        all_data = []
        failed_tickers = []

        # Step 1: Try DefeatBeta first (primary source)
        if self.defeatbeta_bridge and self.defeatbeta_bridge.check_wsl_availability():
            try:
                logger.info("Using DefeatBeta for market data (primary source)")
                defeatbeta_data = self.defeatbeta_bridge.get_market_data_defeatbeta(tickers)

                if not defeatbeta_data.empty:
                    # Identify successful and failed tickers
                    successful = defeatbeta_data[defeatbeta_data['source'] == 'defeatbeta']['ticker'].tolist()
                    failed_tickers = [t for t in tickers if t not in successful]

                    logger.info(f"DefeatBeta: {len(successful)} success, {len(failed_tickers)} failed")
                    all_data.append(self._standardize_market_data(defeatbeta_data))
                else:
                    failed_tickers = tickers

            except Exception as e:
                logger.warning(f"DefeatBeta bridge failed: {e}")
                failed_tickers = tickers
        else:
            logger.warning("DefeatBeta not available")
            failed_tickers = tickers

        # Step 2: Use Yahoo Finance for gaps (fallback)
        if failed_tickers and YFINANCE_AVAILABLE:
            logger.info(f"Using Yahoo Finance fallback for {len(failed_tickers)} tickers")
            yfinance_data = self._fetch_yfinance_fallback(failed_tickers)
            if not yfinance_data.empty:
                all_data.append(yfinance_data)
        elif failed_tickers and not YFINANCE_AVAILABLE:
            logger.warning(f"Yahoo Finance not available for {len(failed_tickers)} gap tickers")

        # Combine all data sources
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            logger.info(f"Total market data retrieved: {len(combined)} tickers")
            return combined
        else:
            logger.warning("No market data retrieved from any source")
            return pd.DataFrame()
    
    def _standardize_market_data(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize market data from DefeatBeta to match expected format.

        DefeatBeta provides: ticker, price, market_cap, volume, source, fetch_timestamp
        We need to ensure all expected columns exist with appropriate defaults.

        Args:
            market_data: DataFrame from DefeatBeta bridge

        Returns:
            Standardized DataFrame with all expected columns
        """
        df = market_data.copy()

        # Ensure all expected columns exist
        expected_columns = {
            'ticker': None,
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
            'last_updated': datetime.now()
        }

        for col, default_value in expected_columns.items():
            if col not in df.columns:
                df[col] = default_value

        # Calculate shares_outstanding from market_cap and price if not provided
        if 'shares_outstanding' not in df.columns or df['shares_outstanding'].isna().all():
            df['shares_outstanding'] = df['market_cap'] / df['price']

        # Rename fetch_timestamp to last_updated if it exists
        if 'fetch_timestamp' in df.columns and 'last_updated' in df.columns:
            df['last_updated'] = pd.to_datetime(df['fetch_timestamp'])

        logger.info(f"Standardized {len(df)} market data records from DefeatBeta")

        return df

    def _fetch_yfinance_fallback(self, tickers: List[str]) -> pd.DataFrame:
        """
        Fetch market data using Yahoo Finance as fallback for DefeatBeta gaps.

        Args:
            tickers: List of stock tickers that failed from DefeatBeta

        Returns:
            Standardized DataFrame with market data
        """
        logger.info(f"Fetching Yahoo Finance data for {len(tickers)} gap tickers")
        logger.info("Using conservative rate limiting (2s per ticker + 30s per batch)")
        logger.info(f"Estimated time: {(len(tickers) * 2 + (len(tickers)//10) * 30) / 60:.1f} minutes")

        market_data = []
        batch_size = 10  # Small batches to avoid rate limiting

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            logger.info(f"Processing yfinance batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1} ({len(batch)} tickers)")

            for ticker in batch:
                try:
                    self._rate_limit()  # Apply rate limiting

                    # Fetch ticker info from yfinance
                    stock = yf.Ticker(ticker)
                    info = stock.info

                    # Extract key data points
                    current_price = info.get('currentPrice') or info.get('regularMarketPrice')
                    market_cap = info.get('marketCap')
                    shares = info.get('sharesOutstanding')

                    # Calculate market_cap if missing but we have price and shares
                    if market_cap is None and current_price and shares:
                        market_cap = current_price * shares

                    # Only add if we have at least price data
                    if current_price:
                        market_data.append({
                            'ticker': ticker,
                            'price': current_price,
                            'market_cap': market_cap,
                            'shares_outstanding': shares,
                            'volume': info.get('volume'),
                            'avg_volume': info.get('averageVolume'),
                            'pe_ratio': info.get('trailingPE'),
                            'beta': info.get('beta'),
                            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
                            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
                            'dividend_yield': info.get('dividendYield'),
                            'source': 'yfinance_fallback',
                            'last_updated': datetime.now()
                        })
                    else:
                        logger.warning(f"No price data available for {ticker} from yfinance")
                        market_data.append({
                            'ticker': ticker,
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
                            'source': 'yfinance_failed',
                            'last_updated': datetime.now()
                        })

                except Exception as e:
                    logger.warning(f"Yahoo Finance error for {ticker}: {e}")
                    market_data.append({
                        'ticker': ticker,
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
                        'source': 'yfinance_error',
                        'last_updated': datetime.now()
                    })

            # Longer delay between batches to avoid rate limiting
            if i + batch_size < len(tickers):
                logger.info(f"Waiting 30 seconds before next batch to avoid rate limits...")
                time.sleep(30)  # 30 seconds between batches

        if market_data:
            df = pd.DataFrame(market_data)
            successful = len(df[df['source'] == 'yfinance_fallback'])
            logger.info(f"Yahoo Finance fallback: {successful}/{len(tickers)} successful")
            return df
        else:
            return pd.DataFrame()

    def get_historical_prices(self, tickers: List[str], 
                            start_date: str = None, 
                            end_date: str = None,
                            period: str = "2y") -> pd.DataFrame:
        """
        Historical price data - Not implemented (DefeatBeta does not provide historical data).
        
        Returns empty DataFrame.
        """
        logger.warning("Historical prices not available with DefeatBeta")
        return pd.DataFrame()

    def calculate_returns_and_volatility(self, historical_prices: pd.DataFrame, 
                                       annualize: bool = True) -> pd.DataFrame:
        """
        Calculate stock returns, volatility, and related metrics.
        
        Args:
            historical_prices: DataFrame with historical close prices
            annualize: Whether to annualize volatility metrics
            
        Returns:
            DataFrame with return and volatility metrics
        """
        if historical_prices.empty:
            return pd.DataFrame()
        
        logger.info("Calculating returns and volatility metrics")
        
        # Calculate daily returns
        returns = historical_prices.pct_change().dropna()
        
        metrics = []
        
        for ticker in returns.columns:
            ticker_returns = returns[ticker].dropna()
            
            if len(ticker_returns) < 10:  # Need minimum data
                continue
                
            # Calculate metrics
            annualization_factor = 252 if annualize else 1
            
            metrics.append({
                'ticker': ticker,
                'daily_volatility': ticker_returns.std(),
                'annualized_volatility': ticker_returns.std() * np.sqrt(annualization_factor),
                'total_return': (historical_prices[ticker].iloc[-1] / historical_prices[ticker].iloc[0] - 1),
                'annualized_return': ((historical_prices[ticker].iloc[-1] / historical_prices[ticker].iloc[0]) ** 
                                    (annualization_factor / len(ticker_returns)) - 1) if annualize else np.nan,
                'max_drawdown': self._calculate_max_drawdown(historical_prices[ticker]),
                'sharpe_ratio': (ticker_returns.mean() * annualization_factor) / 
                              (ticker_returns.std() * np.sqrt(annualization_factor)) if annualize else np.nan,
                'downside_volatility': self._calculate_downside_volatility(ticker_returns, annualize),
                'var_95': np.percentile(ticker_returns, 5),  # 95% Value at Risk
                'skewness': ticker_returns.skew(),
                'kurtosis': ticker_returns.kurtosis()
            })
        
        return pd.DataFrame(metrics)

    def _calculate_max_drawdown(self, prices: pd.Series) -> float:
        """Calculate maximum drawdown from price series."""
        cumulative = (1 + prices.pct_change()).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        return drawdown.min()

    def _calculate_downside_volatility(self, returns: pd.Series, annualize: bool) -> float:
        """Calculate downside volatility (volatility of negative returns only)."""
        downside_returns = returns[returns < 0]
        if len(downside_returns) == 0:
            return 0
        annualization_factor = 252 if annualize else 1
        return downside_returns.std() * np.sqrt(annualization_factor) if annualize else downside_returns.std()

    def _get_fx_rates_to_usd(self, currencies: set) -> dict:
        """
        Fetch current spot FX rates so that 1 unit of each currency = X USD.

        Uses yfinance ticker format {CCY}USD=X (e.g. JPYUSD=X, EURUSD=X).
        Falls back to 1.0 for any currency that cannot be fetched so that
        foreign companies are included in the screen (with a warning) rather
        than silently dropped.

        Args:
            currencies: Set of ISO currency codes (e.g. {'JPY', 'EUR'})

        Returns:
            dict mapping currency code -> USD equivalent (e.g. {'JPY': 0.0067})
        """
        rates = {}
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — FX conversion skipped; foreign EV may be incorrect")
            return {c: 1.0 for c in currencies}

        for currency in currencies:
            ticker_sym = f'{currency}USD=X'
            try:
                info = yf.Ticker(ticker_sym).fast_info
                rate = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
                if rate and float(rate) > 0:
                    rates[currency] = float(rate)
                    logger.info(f"FX rate fetched: 1 {currency} = {rate:.6f} USD")
                else:
                    logger.warning(f"FX rate for {currency} returned zero/None — defaulting to 1.0")
                    rates[currency] = 1.0
            except Exception as e:
                logger.warning(f"Could not fetch FX rate for {currency} ({ticker_sym}): {e} — defaulting to 1.0")
                rates[currency] = 1.0

        return rates

    def calculate_accurate_enterprise_value(self, fundamentals_df: pd.DataFrame,
                                          market_data_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate accurate enterprise value using real market data.
        
        EV = Market Cap + Total Debt - Cash
        
        Args:
            fundamentals_df: DataFrame with fundamental data
            market_data_df: DataFrame with current market data
            
        Returns:
            DataFrame with accurate enterprise value calculations
        """
        logger.info("Calculating accurate enterprise values")

        # Handle empty market data
        if market_data_df.empty:
            logger.warning("No market data available - using book value approximation")
            # Return fundamentals with enterprise_value calculated from book values
            df = fundamentals_df.copy()
            df['market_cap_final'] = np.nan
            df['enterprise_value'] = (
                df.get('total_equity', df.get('stockholders_equity', 0)).fillna(0) +
                df.get('long_term_debt', 0).fillna(0) -
                df.get('cash', 0).fillna(0)
            )
            df['enterprise_value'] = df['enterprise_value'].replace(0, np.nan)

            # Calculate valuation ratios
            if 'revenue' in df.columns:
                df['ev_revenue'] = df['enterprise_value'] / df['revenue']
            if 'operating_income' in df.columns:
                df['ev_ebit'] = df['enterprise_value'] / df['operating_income']
            if 'fcf' in df.columns:
                df['ev_fcf'] = df['enterprise_value'] / df['fcf']

            return df

        # Merge fundamental and market data
        merged = fundamentals_df.merge(market_data_df, on='ticker', how='left', suffixes=('', '_market'))

        # Calculate accurate enterprise value
        # Prioritize shares_outstanding from fundamentals (EDGAR - source of truth)
        # Only use market data if fundamentals don't have it
        if 'shares_outstanding' in merged.columns:
            shares_col = 'shares_outstanding'  # from EDGAR fundamentals (preferred)
        elif 'shares_outstanding_market' in merged.columns:
            shares_col = 'shares_outstanding_market'  # from market data (fallback)
        else:
            logger.warning("No shares_outstanding data available")
            shares_col = None

        if shares_col:
            merged['market_cap_calculated'] = merged['price'] * merged[shares_col]
        else:
            merged['market_cap_calculated'] = np.nan
        
        # Use market cap from API if available, otherwise use calculated
        merged['market_cap_final'] = merged['market_cap'].fillna(merged['market_cap_calculated'])
        
        # Calculate net debt (total debt - cash)
        # Use available column names from our data
        debt_col = 'long_term_debt'
        cash_col = 'cash'
        
        merged['net_debt'] = merged[debt_col].fillna(0) - merged[cash_col].fillna(0)

        # FX conversion: EDGAR reports fundamentals in the company's native currency
        # (e.g. JPY for MUFG/KYOCF, EUR for ASML) while market_cap_final is always USD.
        # Convert net_debt to USD before combining with market cap.
        if 'reporting_currency' in merged.columns:
            non_usd_currencies = set(
                merged['reporting_currency'].dropna().unique()
            ) - {'USD'}
            if non_usd_currencies:
                fx_rates = self._get_fx_rates_to_usd(non_usd_currencies)
                for currency, rate in fx_rates.items():
                    mask = merged['reporting_currency'] == currency
                    if mask.any():
                        n = mask.sum()
                        logger.info(
                            f"FX: converting net_debt for {n} {currency} companies "
                            f"(1 {currency} = {rate:.6f} USD)"
                        )
                        merged.loc[mask, 'net_debt'] = merged.loc[mask, 'net_debt'] * rate
                        # Also convert EBIT/revenue/FCF so ratios stay internally consistent
                        for col in ['operating_income', 'revenue', 'fcf', 'ebit']:
                            if col in merged.columns:
                                merged.loc[mask, col] = merged.loc[mask, col] * rate

        # Enterprise Value = Market Cap (USD) + Net Debt (now USD)
        merged['enterprise_value'] = merged['market_cap_final'] + merged['net_debt']
        
        # Calculate key valuation ratios using available columns
        if 'revenue' in merged.columns:
            merged['ev_revenue'] = merged['enterprise_value'] / merged['revenue']
        if 'operating_income' in merged.columns:
            merged['ev_ebit'] = merged['enterprise_value'] / merged['operating_income']
        if 'fcf' in merged.columns:
            merged['ev_fcf'] = merged['enterprise_value'] / merged['fcf']
        
        # Market-based metrics
        merged['log_market_cap'] = np.log(merged['market_cap_final'].replace(0, np.nan))
        
        logger.info(f"Calculated accurate enterprise values for {len(merged)} companies")
        
        return merged

    def enhance_distress_model_with_market_data(self, df_with_ev: pd.DataFrame,
                                              returns_data: pd.DataFrame) -> pd.DataFrame:
        """
        Enhance financial distress model with market-based variables.
        
        This implements components from the Campbell financial distress model
        that require market data.
        
        Args:
            df_with_ev: DataFrame with enterprise value calculations
            returns_data: DataFrame with return and volatility metrics
            
        Returns:
            DataFrame with enhanced distress probability
        """
        logger.info("Enhancing distress model with market data")
        
        # Merge with returns data
        enhanced = df_with_ev.merge(returns_data, on='ticker', how='left')
        
        # Market-based variables for Campbell model
        
        # 1. Relative size (log of market cap relative to market)
        # Note: Would need market total for exact calculation, using log market cap as proxy
        enhanced['relative_size'] = enhanced['log_market_cap'] - enhanced['log_market_cap'].median()
        
        # 2. Market-to-book ratio (already calculated)
        enhanced['mb_ratio'] = enhanced['market_to_book']
        
        # 3. Stock volatility (annualized)
        enhanced['stock_volatility'] = enhanced['annualized_volatility']
        
        # 4. Recent excess returns (vs market - using total return as proxy)
        market_return_proxy = enhanced['total_return'].median()  # Simple market proxy
        enhanced['excess_returns'] = enhanced['total_return'] - market_return_proxy
        
        # 5. Cash to market assets
        enhanced['cash_to_market_assets'] = enhanced['cash'] / enhanced['market_cap_final']
        
        # Enhanced distress probability using market variables
        # Simplified Campbell-style model coefficients
        enhanced['market_distress_score'] = (
            -2.0  # Base level
            - 5.0 * enhanced['roa_distress'].fillna(0)  # Profitability 
            + 3.0 * enhanced['leverage_distress'].fillna(0.5)  # Leverage
            - 4.0 * enhanced['cash_to_market_assets'].fillna(0.05)  # Liquidity
            + 2.0 * enhanced['stock_volatility'].fillna(0.3)  # Volatility penalty
            - 1.0 * enhanced['relative_size'].fillna(0)  # Size effect
            + 1.0 * enhanced['mb_ratio'].fillna(1)  # Growth/distress signal
            - 2.0 * enhanced['excess_returns'].fillna(0)  # Recent performance
        )
        
        # Convert to probability using logistic function
        enhanced['market_distress_probability'] = 1 / (1 + np.exp(-enhanced['market_distress_score']))
        
        logger.info("Enhanced distress model with market data completed")
        
        return enhanced

    def save_market_data_cache(self, market_data: pd.DataFrame, 
                             filename: str = "market_data_cache.csv"):
        """Save market data to cache for future use."""
        if self.enable_cache:
            cache_path = self.cache_dir / filename
            market_data.to_csv(cache_path, index=False)
            logger.info(f"Market data cached to {cache_path}")

    def load_market_data_cache(self, filename: str = "market_data_cache.csv",
                             max_age_hours: int = 24) -> Optional[pd.DataFrame]:
        """Load cached market data if it's recent enough."""
        if not self.enable_cache:
            return None
            
        cache_path = self.cache_dir / filename
        
        if not cache_path.exists():
            return None
            
        # Check if cache is fresh enough
        cache_age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        
        if cache_age.total_seconds() > max_age_hours * 3600:
            logger.info(f"Cache is {cache_age} old, refreshing")
            return None
            
        try:
            cached_data = pd.read_csv(cache_path)
            cached_data['last_updated'] = pd.to_datetime(cached_data['last_updated'])
            logger.info(f"Loaded cached market data with {len(cached_data)} entries")
            return cached_data
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return None