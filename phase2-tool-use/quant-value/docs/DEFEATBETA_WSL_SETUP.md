# DefeatBeta WSL Setup Guide

This guide walks through setting up DefeatBeta API in WSL for our hybrid approach.

## Step 1: Install WSL

**Option A: PowerShell (Recommended)**
```powershell
# Run as Administrator
wsl --install
```

**Option B: Manual Installation**
1. Enable Windows Subsystem for Linux feature
2. Install Ubuntu from Microsoft Store
3. Restart and complete setup

## Step 2: Set Up Python Environment in WSL

```bash
# Update package manager
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install python3 python3-pip python3-venv -y

# Create virtual environment for DefeatBeta
python3 -m venv ~/defeatbeta_env
source ~/defeatbeta_env/bin/activate

# Install DefeatBeta API
pip install defeatbeta-api

# Test installation
python3 -c "import defeatbeta_api; print('DefeatBeta API installed successfully')"
```

## Step 3: Test DefeatBeta Basic Functionality

```bash
# Create test script
cat << 'EOF' > ~/test_defeatbeta.py
from defeatbeta_api.data.ticker import Ticker
import pandas as pd

# Test with Apple
ticker = Ticker('AAPL')
price_data = ticker.price()
print(f"Price data shape: {price_data.shape}")
print(f"Latest price: ${price_data.iloc[-1]['close']:.2f}")
EOF

# Run test
python3 ~/test_defeatbeta.py
```

## Step 4: Test Bridge Integration

From Windows PowerShell:

```powershell
# Navigate to project directory
cd C:\Users\benpa\edgar_fundamentals\src

# Run hybrid approach test
python test_hybrid_approach.py
```

## Troubleshooting

**WSL Not Found:**
```powershell
# Check WSL installation
wsl --version

# If not installed, run:
wsl --install --distribution Ubuntu
```

**DefeatBeta Import Error:**
```bash
# Ensure you're in the right environment
source ~/defeatbeta_env/bin/activate

# Reinstall if needed
pip uninstall defeatbeta-api
pip install defeatbeta-api
```

**Bridge Connection Issues:**
- Ensure WSL can access Windows file system (`/mnt/c/Users/...`)
- Check file permissions on bridge directory
- Verify Python paths in bridge configuration

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Windows Host                        │
│  ┌─────────────────┐    ┌─────────────────────────────┐ │
│  │ EDGAR Pipeline  │    │ Quantitative Value Screener │ │
│  │ • Fundamentals  │───▶│ • Risk Screening           │ │
│  │ • Metrics       │    │ • Value Ranking            │ │
│  │ • Risk Data     │    │ • Quality Metrics          │ │
│  └─────────────────┘    └─────────────────────────────┘ │
│           │                         │                   │
│           ▼                         ▼                   │
│  ┌─────────────────────────────────────────────────────┐ │
│  │            Market Data Provider                    │ │
│  │  • DefeatBeta Bridge (primary)                    │ │
│  │  • Yahoo Finance (fallback)                       │ │
│  └─────────────────────────────────────────────────────┘ │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────────┐ │
│  │         Bridge Data Exchange                       │ │
│  │  • ticker_input.csv                               │ │
│  │  • defeatbeta_market_data.csv                     │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│                     WSL Environment                     │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              DefeatBeta API                        │ │
│  │  • fetch_defeatbeta_data.py                       │ │
│  │  • No rate limits                                 │ │
│  │  • Historical data                                │ │
│  │  • Financial statements                           │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Benefits of This Approach

1. **Low Risk**: Keep existing EDGAR pipeline unchanged
2. **Gradual Migration**: Test DefeatBeta quality over time
3. **Best of Both**: EDGAR fundamentals + DefeatBeta market data
4. **Fallback Ready**: Yahoo Finance backup if WSL issues
5. **Data Validation**: Compare DefeatBeta vs Yahoo Finance accuracy

## Future Migration Path

Once comfortable with DefeatBeta:
1. Compare data quality metrics
2. Validate historical data accuracy
3. Consider full migration to WSL
4. Potentially integrate DefeatBeta fundamentals
5. Leverage LLM analysis features