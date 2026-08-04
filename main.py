import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import twstock
from typing import List

app = FastAPI(title="Twstock Simulator API")

# Setup CORS to allow React frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict to localhost:5173
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/quotes")
async def get_quotes(symbols: str = "2330,2317,2454,2303"):
    """
    Fetch real-time stock quotes using twstock.
    Expects a comma-separated list of stock symbols.
    """
    symbol_list = [s.strip() for s in symbols.split(',') if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")

    try:
        data = twstock.realtime.get(symbol_list)
        results = []
        for symbol, info in data.items():
            if symbol == 'success' or symbol == 'rtmessage':
                continue
            if isinstance(info, dict) and info.get('success'):
                realtime = info['realtime']
                info_data = info['info']
                
                # Sometime twstock returns '-' for latest_trade_price when market just opens or is closed
                latest_price = realtime.get('latest_trade_price', '-')
                if latest_price == '-':
                    # Fallback to open price or first best bid
                    latest_price = realtime.get('open', '-')
                    if latest_price == '-':
                        bids = realtime.get('best_bid_price', [])
                        if bids and bids[0] != '-':
                            latest_price = bids[0]
                        else:
                            latest_price = '0'

                price = float(latest_price)
                
                results.append({
                    "symbol": info_data.get('code', symbol),
                    "name": info_data.get('name', symbol),
                    "price": price,
                    "change": 0.0 # Placeholder for change
                })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
async def get_history(symbol: str):
    """
    Fetch 1-month historical stock prices using yfinance.
    """
    if not symbol:
        raise HTTPException(status_code=400, detail="No symbol provided")
    
    try:
        # TWSE stocks have a .TW suffix on Yahoo Finance
        yf_symbol = f"{symbol}.TW"
        ticker = yf.Ticker(yf_symbol)
        
        # Get 1 month of historical data
        hist = ticker.history(period="1mo")
        
        if hist.empty:
            # Maybe it's a Taipei Exchange (OTC) stock, suffix is .TWO
            yf_symbol = f"{symbol}.TWO"
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1mo")
            if hist.empty:
                return []

        # Convert index to string dates and collect OHLC prices
        results = []
        for date, row in hist.iterrows():
            results.append({
                "time": date.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"])
            })
            
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
