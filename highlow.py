import time
import pandas as pd
import requests
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

# ========= CONFIG =========
API_KEY = "awh2j04pcd83zfvq"
API_SECRET = "gfjmlgcn28pirja9b1e3xtww8ep7xthb"

SCAN_INTERVAL = 180
CANDLE_INTERVAL = "5minute"

VOL_MULT = 1.5
RANGE_MULT = 1.3
MAX_PRICE_MOVE = 1.2

TOP_N = 20

# ========= TELEGRAM =========
BOT = "8060596624:AAEy0fb4tMTGtBJBywF-fHXmwjIYhVDQzjs"
with open("subscribers.txt") as f:
    CHAT_IDS = [x.strip() for x in f if x.strip()]

def tg(msg):
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT}/sendMessage",
                data={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
                timeout=5
            )
        except:
            pass

# ========= KITE =========
with open("access_token.txt") as f:
    ACCESS_TOKEN = f.read().strip()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# ========= INSTRUMENTS =========
df = pd.read_csv("instruments.csv", low_memory=False)
df = df[df["exchange"] == "NSE"]
symbol_to_token = dict(zip(df["tradingsymbol"], df["instrument_token"]))
token_to_symbol = dict(zip(df["instrument_token"], df["tradingsymbol"]))

# ========= WATCHLIST =========
with open("watchlist.txt") as f:
    STOCKS = [s.strip() for s in f if s.strip()]

TOKENS = [symbol_to_token[s] for s in STOCKS if s in symbol_to_token]

# ========= MEMORY =========
prev_gainer_ranks = {}
prev_loser_ranks = {}
tf_break_memory = {}


# ========= SMART MONEY =========
def is_smart_money(token, pct_change, prev_close):
    try:
        if abs(pct_change) > MAX_PRICE_MOVE:
            return False

        now = datetime.now()
        candles = kite.historical_data(
            token,
            now - timedelta(minutes=90),
            now,
            CANDLE_INTERVAL
        )

        if len(candles) < 6:
            return False

        last5 = candles[-6:-1]
        curr = candles[-1]

        avg_vol = sum(c["volume"] for c in last5) / 5
        avg_rng = sum((c["high"] - c["low"]) for c in last5) / 5

        vol_ok = curr["volume"] >= VOL_MULT * avg_vol
        rng_ok = (curr["high"] - curr["low"]) >= RANGE_MULT * avg_rng
        context_ok = curr["close"] >= prev_close

        return vol_ok and rng_ok and context_ok
    except:
        return False

# ========= TIMEFRAMES =========
TIMEFRAMES = {
    "5m":  {"type": "intraday", "candles": 1},
    "10m": {"type": "intraday", "candles": 2},
    "15m": {"type": "intraday", "candles": 3},
    "30m": {"type": "intraday", "candles": 6},
    "1h":  {"type": "intraday", "candles": 12},
    "2h":  {"type": "intraday", "candles": 24},
    "3h":  {"type": "intraday", "candles": 36},
    "4h":  {"type": "intraday", "candles": 48},
    "5h":  {"type": "intraday", "candles": 60},
    "6h":  {"type": "intraday", "candles": 72},

    "1D": {"type": "daily", "days": 1},
    "2D": {"type": "daily", "days": 2},
    "3D": {"type": "daily", "days": 3},
    "4D": {"type": "daily", "days": 4},
    "5D": {"type": "daily", "days": 5},
    "6D": {"type": "daily", "days": 6},
    "7D": {"type": "daily", "days": 7},

    "1W": {"type": "daily", "days": 5},
    "2W": {"type": "daily", "days": 10},
    "3W": {"type": "daily", "days": 15},
    "4W": {"type": "daily", "days": 20},

    "1M": {"type": "daily", "days": 21},
    "2M": {"type": "daily", "days": 42},
    "3M": {"type": "daily", "days": 63},
    "4M": {"type": "daily", "days": 84},
    "5M": {"type": "daily", "days": 105},
    "6M": {"type": "daily", "days": 126},
}

# ========= BREAKOUT CHECK =========
def check_tf_breaks(token, symbol, ltp):
    alerts = []

    try:
        now = datetime.now()

        intraday = kite.historical_data(
            token,
            now - timedelta(minutes=520),
            now,
            "5minute"
        )

        daily = kite.historical_data(
            token,
            now.date() - timedelta(days=160),
            now.date(),
            "day"
        )

        for tf, cfg in TIMEFRAMES.items():
            if cfg["type"] == "intraday":
                n = cfg["candles"]
                if len(intraday) <= n:
                    continue
                subset = intraday[-(n+1):-1]
            else:
                n = cfg["days"]
                if len(daily) <= n:
                    continue
                subset = daily[-(n+1):-1]

            high_tf = max(c["high"] for c in subset)
            low_tf = min(c["low"] for c in subset)

            hk = f"{symbol}_{tf}_HIGH"
            lk = f"{symbol}_{tf}_LOW"

            if ltp > high_tf and not tf_break_memory.get(hk):
                alerts.append(
                    f"🚀 *{symbol}* BREAKS *{tf} HIGH*\n"
                    f"➡️ Price: ₹{ltp}\n"
                    f"📈 Prev High: ₹{round(high_tf,2)}"
                )
                tf_break_memory[hk] = True

            if ltp < low_tf and not tf_break_memory.get(lk):
                alerts.append(
                    f"🩸 *{symbol}* BREAKS *{tf} LOW*\n"
                    f"➡️ Price: ₹{ltp}\n"
                    f"📉 Prev Low: ₹{round(low_tf,2)}"
                )
                tf_break_memory[lk] = True

        return alerts

    except Exception as e:
        print("TF error:", symbol, e)
        return []


# ========= MAIN LOOP =========
while True:
    try:
        quotes = kite.quote(TOKENS)
        rows = []

        for token, q in quotes.items():
            symbol = token_to_symbol[int(token)]
            ltp = q["last_price"]
            prev_close = q["ohlc"]["close"]
            pct = ((ltp - prev_close) / prev_close) * 100

            rows.append({
                "Stock": symbol,
                "Token": int(token),
                "LTP": round(ltp, 2),
                "%Change": round(pct, 2),
                "PrevClose": prev_close
            })

            # 🔥 MULTI-TF BREAK ALERTS
            alerts = check_tf_breaks(int(token), symbol, ltp)
            for a in alerts:
                tg(a)

        df_live = pd.DataFrame(rows)

        bull = len(df_live[df_live["%Change"] > 0])
        bear = len(df_live[df_live["%Change"] < 0])

        sentiment = (
            "🟢 *BULLISH MARKET*" if bull > bear else
            "🔴 *BEARISH MARKET*" if bear > bull else
            "🟡 *SIDEWAYS MARKET*"
        )

        gainers = df_live.sort_values("%Change", ascending=False).head(TOP_N)
        losers = df_live.sort_values("%Change").head(TOP_N)

        msg = (
            "📊 *MARKET SENTIMENT*\n"
            f"🟢 Advancing: {bull}\n"
            f"🔴 Declining: {bear}\n"
            f"{sentiment}\n\n"
        )

        msg += f"📊 *TOP {TOP_N} GAINERS*\n\n"
        for rank, r in enumerate(gainers.to_dict("records"), 1):
            smart = " 🧠 SMART MONEY" if is_smart_money(
                r["Token"], r["%Change"], r["PrevClose"]
            ) else ""
            msg += f"#{rank} 🟢 *{r['Stock']}* | {r['%Change']}% | ₹{r['LTP']}{smart}\n"

        msg += f"\n📉 *TOP {TOP_N} LOSERS*\n\n"
        for rank, r in enumerate(losers.to_dict("records"), 1):
            smart = " 🧠 SMART MONEY" if is_smart_money(
                r["Token"], r["%Change"], r["PrevClose"]
            ) else ""
            msg += f"#{rank} 🔴 *{r['Stock']}* | {r['%Change']}% | ₹{r['LTP']}{smart}\n"

        tg(msg)

    except Exception as e:
        print("❌ Error:", e)

    time.sleep(SCAN_INTERVAL)
