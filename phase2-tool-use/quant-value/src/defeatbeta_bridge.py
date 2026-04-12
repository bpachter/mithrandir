#!/usr/bin/env python3

"""
WSL DefeatBeta Bridge Module

This module provides a bridge between our Windows-based EDGAR fundamentals system
and WSL-based DefeatBeta API for market data. It handles the data exchange via
CSV files and provides fallback to existing Yahoo Finance when WSL is unavailable.

Hybrid Architecture:
- Windows: EDGAR fundamentals processing, risk screening, main pipeline
- WSL: DefeatBeta API for market data (optional)
- Bridge: CSV-based data exchange between systems

Usage:
1. Generate ticker list from Windows system
2. Use WSL script to fetch DefeatBeta market data
3. Import results back to Windows for integration
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
import subprocess
import logging
from datetime import datetime
import tempfile
import shutil

logger = logging.getLogger(__name__)

class DefeatBetaBridge:
    """
    Bridge to DefeatBeta API running in WSL environment.
    Handles data exchange and fallback to existing market data sources.
    """
    
    def __init__(self,
                 bridge_dir: Path = None,
                 wsl_python_path: str = "/root/defeatbeta_env/bin/python3",
                 enable_wsl: bool = True):
        """
        Initialize DefeatBeta bridge.
        
        Args:
            bridge_dir: Directory for CSV data exchange
            wsl_python_path: Python path in WSL environment
            enable_wsl: Whether to attempt WSL/DefeatBeta usage
        """
        # Use absolute path based on this file's location so it works from any cwd
        self.bridge_dir = bridge_dir or (Path(__file__).parent.parent / "data" / "defeatbeta_bridge")
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        
        self.wsl_python_path = wsl_python_path
        self.enable_wsl = enable_wsl
        self.wsl_available = None  # Lazy evaluation
        
        # File paths for data exchange
        self.ticker_input_file = self.bridge_dir / "ticker_input.csv"
        self.market_data_output = self.bridge_dir / "defeatbeta_market_data.csv"
        self.wsl_script_path = self.bridge_dir / "fetch_defeatbeta_data.py"
        
        logger.info(f"DefeatBeta bridge initialized with directory: {self.bridge_dir}")
    
    def check_wsl_availability(self) -> bool:
        """Check if WSL is available and DefeatBeta is installed."""
        if self.wsl_available is not None:
            return self.wsl_available
        
        if not self.enable_wsl:
            self.wsl_available = False
            return False
        
        try:
            # Test WSL availability
            result = subprocess.run(
                ["wsl", "--version"],
                capture_output=True,
                text=True,
                timeout=30  # Increased to allow for WSL startup
            )
            
            if result.returncode != 0:
                logger.warning("WSL not available")
                self.wsl_available = False
                return False
            
            # Test DefeatBeta installation
            result = subprocess.run(
                ["wsl", "bash", "-c", f"{self.wsl_python_path} -c 'import defeatbeta_api; print(\"OK\")'"],
                capture_output=True,
                text=True,
                timeout=60  # Increased from 15s to allow WSL startup time
            )
            
            if result.returncode == 0 and "OK" in result.stdout:
                logger.info("DefeatBeta API available in WSL")
                self.wsl_available = True
                return True
            else:
                logger.warning("DefeatBeta API not available in WSL")
                self.wsl_available = False
                return False
                
        except Exception as e:
            logger.warning(f"WSL/DefeatBeta check failed: {e}")
            self.wsl_available = False
            return False
    
    def create_wsl_fetch_script(self):
        """Create the Python script that will run in WSL to fetch DefeatBeta data."""
        script_content = '''#!/usr/bin/env python3
"""
WSL script to fetch market data using DefeatBeta API.
This script reads tickers from CSV and outputs market data.
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def fetch_defeatbeta_market_data(ticker_file: str, output_file: str):
    """Fetch market data using DefeatBeta API."""
    try:
        # Import DefeatBeta
        from defeatbeta_api.data.ticker import Ticker
        
        # Read ticker list
        logger.info(f"Reading tickers from {ticker_file}")
        ticker_df = pd.read_csv(ticker_file)
        
        if 'ticker' not in ticker_df.columns:
            raise ValueError("Input CSV must have 'ticker' column")
        
        tickers = ticker_df['ticker'].dropna().unique()
        logger.info(f"Processing {len(tickers)} tickers")
        
        market_data = []
        
        for i, symbol in enumerate(tickers):
            try:
                logger.info(f"Fetching data for {symbol} ({i+1}/{len(tickers)})")
                
                # Get DefeatBeta ticker
                ticker = Ticker(symbol)
                
                # Get latest price data
                price_data = ticker.price()
                
                if price_data is not None and not price_data.empty:
                    # Get most recent row
                    latest = price_data.iloc[-1]

                    # Get market cap from market_capitalization() - price() rows don't carry it
                    market_cap = np.nan
                    try:
                        mc_data = ticker.market_capitalization()
                        if mc_data is not None and not mc_data.empty:
                            market_cap = mc_data.iloc[-1].get('market_capitalization', np.nan)
                    except Exception:
                        pass

                    # Compile market data
                    market_data.append({
                        'ticker': symbol,
                        'price': latest.get('close', np.nan),
                        'market_cap': market_cap,
                        'volume': latest.get('volume', np.nan),
                        'date': latest.get('report_date', ''),
                        'source': 'defeatbeta',
                        'fetch_timestamp': pd.Timestamp.now()
                    })
                    
                else:
                    logger.warning(f"No data available for {symbol}")
                    market_data.append({
                        'ticker': symbol,
                        'price': np.nan,
                        'market_cap': np.nan,
                        'volume': np.nan,
                        'date': '',
                        'source': 'defeatbeta_failed',
                        'fetch_timestamp': pd.Timestamp.now()
                    })
                
            except Exception as e:
                logger.error(f"Error fetching {symbol}: {e}")
                market_data.append({
                    'ticker': symbol,
                    'price': np.nan,
                    'market_cap': np.nan,
                    'volume': np.nan,
                    'date': '',
                    'source': 'defeatbeta_error',
                    'fetch_timestamp': pd.Timestamp.now()
                })
        
        # Save results
        result_df = pd.DataFrame(market_data)
        result_df.to_csv(output_file, index=False)
        
        logger.info(f"Saved {len(result_df)} records to {output_file}")
        logger.info(f"Success rate: {len(result_df[result_df['source'] == 'defeatbeta'])}/{len(result_df)}")
        
        return True
        
    except Exception as e:
        logger.error(f"DefeatBeta fetch failed: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python fetch_defeatbeta_data.py <ticker_input.csv> <market_data_output.csv>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    success = fetch_defeatbeta_market_data(input_file, output_file)
    sys.exit(0 if success else 1)
'''
        
        # Write script to bridge directory
        with open(self.wsl_script_path, 'w') as f:
            f.write(script_content)
        
        logger.info(f"Created WSL fetch script: {self.wsl_script_path}")
    
    def get_market_data_defeatbeta(self, tickers: list) -> pd.DataFrame:
        """
        Get market data using DefeatBeta API via WSL bridge.
        
        Args:
            tickers: List of stock tickers
            
        Returns:
            DataFrame with market data, or empty DataFrame if failed
        """
        logger.info(f"Attempting DefeatBeta fetch for {len(tickers)} tickers")
        
        try:
            # Create ticker input file
            ticker_df = pd.DataFrame({'ticker': tickers})
            ticker_df.to_csv(self.ticker_input_file, index=False)
            
            # Create WSL script
            self.create_wsl_fetch_script()
            
            # Convert Windows paths to WSL paths
            def win_to_wsl_path(path):
                path_str = str(path.resolve()).replace('\\', '/')
                # C:/Users/... -> /mnt/c/Users/...
                if len(path_str) > 2 and path_str[1] == ':':
                    drive = path_str[0].lower()
                    return f'/mnt/{drive}{path_str[2:]}'
                return path_str

            wsl_script = win_to_wsl_path(self.wsl_script_path)
            wsl_input = win_to_wsl_path(self.ticker_input_file)
            wsl_output = win_to_wsl_path(self.market_data_output)

            # Run WSL script
            cmd_str = f"{self.wsl_python_path} {wsl_script} {wsl_input} {wsl_output}"
            cmd = ["wsl", "bash", "-c", cmd_str]
            
            logger.info("Running DefeatBeta fetch in WSL...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout (sufficient for ~7,000 tickers)
            )
            
            if result.returncode == 0:
                # Read results
                if self.market_data_output.exists():
                    market_data = pd.read_csv(self.market_data_output)
                    logger.info(f"DefeatBeta fetch successful: {len(market_data)} records")
                    return market_data
                else:
                    logger.error("DefeatBeta output file not created")
                    return pd.DataFrame()
            else:
                logger.error(f"DefeatBeta fetch failed: {result.stderr}")
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"DefeatBeta bridge error: {e}")
            return pd.DataFrame()
    
    def get_market_data_with_fallback(self, tickers: list, 
                                    fallback_provider=None) -> pd.DataFrame:
        """
        Get market data with DefeatBeta primary, fallback to existing provider.
        
        Args:
            tickers: List of tickers
            fallback_provider: Existing market data provider (e.g., MarketDataProvider)
            
        Returns:
            Combined market data from available sources
        """
        logger.info(f"Getting market data for {len(tickers)} tickers with fallback strategy")
        
        # Try DefeatBeta first if available
        defeatbeta_data = pd.DataFrame()
        
        if self.check_wsl_availability():
            defeatbeta_data = self.get_market_data_defeatbeta(tickers)
        
        # Identify tickers that need fallback
        if not defeatbeta_data.empty:
            successful_tickers = defeatbeta_data[
                defeatbeta_data['source'] == 'defeatbeta'
            ]['ticker'].tolist()
            
            failed_tickers = [t for t in tickers if t not in successful_tickers]
        else:
            failed_tickers = tickers
        
        # Use fallback for failed tickers
        fallback_data = pd.DataFrame()
        
        if failed_tickers and fallback_provider:
            logger.info(f"Using fallback for {len(failed_tickers)} tickers")
            try:
                fallback_data = fallback_provider.get_current_price_data(failed_tickers)
                if not fallback_data.empty:
                    fallback_data['source'] = 'fallback'
            except Exception as e:
                logger.error(f"Fallback provider failed: {e}")
        
        # Combine results
        combined_data = []
        
        for df in [defeatbeta_data, fallback_data]:
            if not df.empty:
                combined_data.append(df)
        
        if combined_data:
            result = pd.concat(combined_data, ignore_index=True)
            
            # Standardize columns
            required_cols = ['ticker', 'price', 'market_cap', 'volume', 'source']
            for col in required_cols:
                if col not in result.columns:
                    result[col] = np.nan
            
            logger.info(f"Combined market data: {len(result)} total records")
            logger.info(f"Source distribution: {dict(result['source'].value_counts())}")
            
            return result[required_cols + ['fetch_timestamp']]
        else:
            logger.warning("No market data retrieved from any source")
            return pd.DataFrame()
    
    def cleanup_bridge_files(self):
        """Clean up temporary bridge files."""
        try:
            for file_path in [self.ticker_input_file, self.market_data_output]:
                if file_path.exists():
                    file_path.unlink()
                    
            logger.info("Bridge files cleaned up")
        except Exception as e:
            logger.warning(f"Bridge cleanup failed: {e}")

def test_defeatbeta_bridge():
    """Test the DefeatBeta bridge functionality."""
    print("="*60)
    print("TESTING DEFEATBETA BRIDGE")
    print("="*60)
    
    bridge = DefeatBetaBridge()
    
    # Test WSL availability
    print(f"WSL Available: {bridge.check_wsl_availability()}")
    
    if bridge.wsl_available:
        # Test with a small sample
        test_tickers = ['AAPL', 'GOOGL', 'MSFT']
        print(f"Testing with tickers: {test_tickers}")
        
        market_data = bridge.get_market_data_defeatbeta(test_tickers)
        
        if not market_data.empty:
            print(f"✅ DefeatBeta fetch successful!")
            print(market_data)
        else:
            print("❌ DefeatBeta fetch failed")
    else:
        print("⚠️ WSL/DefeatBeta not available - would use fallback")

if __name__ == "__main__":
    test_defeatbeta_bridge()