import yfinance as yf
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import twstock
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import bcrypt
from datetime import datetime, timedelta
import jwt
from pydantic import BaseModel

# --- Database Setup ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./simulator.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    balance = Column(Float, default=1000000.0)

class PortfolioItem(Base):
    __tablename__ = "portfolio"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    symbol = Column(String, index=True)
    quantity = Column(Integer, default=0)
    average_price = Column(Float, default=0.0)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Auth Setup ---
SECRET_KEY = "super_secret_key_for_stock_simulator"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# --- Create Default User ---
def init_db():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "testuser").first()
        if not user:
            hashed_password = get_password_hash("123456")
            default_user = User(username="testuser", password_hash=hashed_password, balance=10000000.0) # 給預設大戶一千萬
            db.add(default_user)
            db.commit()
    finally:
        db.close()

init_db()

# --- FastAPI App ---
app = FastAPI(title="Twstock Simulator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserCreate(BaseModel):
    username: str
    password: str

class TradeRequest(BaseModel):
    symbol: str
    quantity: int
    action: str # "buy" or "sell"
    price: float
    total_amount: float # Including fees

@app.post("/api/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, password_hash=hashed_password, balance=1000000.0)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully"}

@app.post("/api/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/me")
def read_users_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
    holdings = [{"symbol": p.symbol, "quantity": p.quantity, "price": p.average_price} for p in portfolio]
    return {
        "username": current_user.username,
        "balance": current_user.balance,
        "holdings": holdings
    }

@app.post("/api/trade")
def trade(req: TradeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.action == "buy":
        if current_user.balance < req.total_amount:
            raise HTTPException(status_code=400, detail="Insufficient funds")
        
        current_user.balance -= req.total_amount
        
        portfolio_item = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id, PortfolioItem.symbol == req.symbol).first()
        if portfolio_item:
            new_qty = portfolio_item.quantity + req.quantity
            new_avg = ((portfolio_item.average_price * portfolio_item.quantity) + req.total_amount) / new_qty
            portfolio_item.quantity = new_qty
            portfolio_item.average_price = new_avg
        else:
            new_item = PortfolioItem(user_id=current_user.id, symbol=req.symbol, quantity=req.quantity, average_price=(req.total_amount/req.quantity))
            db.add(new_item)
            
        db.commit()
        return {"message": "Buy successful", "balance": current_user.balance}
        
    elif req.action == "sell":
        portfolio_item = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id, PortfolioItem.symbol == req.symbol).first()
        if not portfolio_item or portfolio_item.quantity < req.quantity:
            raise HTTPException(status_code=400, detail="Insufficient shares")
            
        current_user.balance += req.total_amount
        portfolio_item.quantity -= req.quantity
        
        if portfolio_item.quantity == 0:
            db.delete(portfolio_item)
            
        db.commit()
        return {"message": "Sell successful", "balance": current_user.balance}
        
    raise HTTPException(status_code=400, detail="Invalid action")

@app.get("/api/quotes")
async def get_quotes(symbols: str = "2330,2317,2454,2303"):
    symbol_list = [s.strip() for s in symbols.split(',') if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")

    try:
        yf_symbols = [f"{s}.TW" for s in symbol_list]
        tickers = yf.Tickers(" ".join(yf_symbols))
        
        results = []
        for i, s in enumerate(symbol_list):
            try:
                ticker = tickers.tickers.get(f"{s}.TW")
                if not ticker:
                    continue
                
                # Fetch fast_info which is much quicker than history
                info = ticker.fast_info
                last_price = info.get("last_price")
                prev_close = info.get("previous_close")
                
                if last_price is None or prev_close is None:
                    continue
                    
                change = last_price - prev_close
                
                # We can fallback to the symbol itself if name is too slow to fetch
                name = s
                try:
                    if s in twstock.codes:
                        name = twstock.codes[s].name
                except:
                    pass
                
                results.append({
                    "symbol": s,
                    "name": name,
                    "price": float(last_price),
                    "change": float(change)
                })
            except Exception as e:
                print(f"Error fetching {s}: {e}")
                continue
                
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
async def get_history(symbol: str):
    if not symbol:
        raise HTTPException(status_code=400, detail="No symbol provided")
    
    try:
        yf_symbol = f"{symbol}.TW"
        ticker = yf.Ticker(yf_symbol)
        
        hist = ticker.history(period="1mo")
        
        if hist.empty:
            yf_symbol = f"{symbol}.TWO"
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1mo")
            if hist.empty:
                return []

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
