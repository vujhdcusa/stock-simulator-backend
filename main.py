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
            if info['success']:
                realtime = info['realtime']
                info_data = info['info']
                
                # Sometime twstock returns '-' for latest_trade_price when market just opens or is closed
                latest_price = realtime.get('latest_trade_price', '-')
                if latest_price == '-':
                    # Use best bid or best ask as fallback, or just skip if no price
                    continue

                price = float(latest_price)
                
                # Calculate change (this might require fetching previous close, but twstock provides open or yesterday's close in 'info' usually? Actually we can calculate from open or high/low if we want, but let's just use open if available or just return 0 for now to keep it simple, or calculate from 'open')
                # Wait, twstock realtime doesn't give a direct % change easily without history. 
                # Let's mock the change for simplicity if we can't easily derive it, or derive from 'best_bid_price' and 'best_ask_price'
                # Actually we can just return price and symbol.
                
                results.append({
                    "symbol": info_data.get('code', symbol),
                    "name": info_data.get('name', symbol),
                    "price": price,
                    "change": 0.0 # Placeholder for change
                })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
