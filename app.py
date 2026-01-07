from flask import Flask, render_template
import pandas as pd
from kiteconnect import KiteConnect
from datetime import datetime, timedelta
import time

app = Flask(__name__)

# ================= CONFIG =================
API_KEY = "awh2j04pcd83zfvq"
with open("access_token.txt") as f:
    ACCESS_TOKEN = f.read().strip()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# ================= LOAD INSTRUMENTS =================
df = pd.read_csv("instruments.csv", low_memory=False)
df = df[(df["exchange"] == "NSE") & (df["instrument_type"] == "EQ")]
symbol_token = dict(zip(df["tradingsymbol"], df["instrument_token"]))

# ================= WATCHLIST =================
with open("watchlist.txt") as f:
    WATCHLIST = [x.strip() for x in f if x.strip()]

# ================= HELPERS =================
def format_volume(v):
    if v >= 1_00_00_000:
        return f"{v/1_00_00_000:.2f} Cr"
    elif v >= 1_00_000:
        return f"{v/1_00_000:.2f} L"
    elif v >= 1_000:
        return f"{v/1_000:.1f} K"
    return str(v)

def avg_volume_last_5_days(token):
    to_date = datetime.now().date() - timedelta(days=1)
    from_date = to_date - timedelta(days=7)
    candles = kite.historical_data(token, from_date, to_date, "day")
    vols = [c["volume"] for c in candles[-5:]]
    return sum(vols) / len(vols) if vols else 0

# ================= ROUTE =================
@app.route("/")
def index():

    rows = []

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    tokens = [symbol_token[s] for s in WATCHLIST if s in symbol_token]
    quotes = kite.quote(tokens)

    for symbol in WATCHLIST:
        if symbol not in symbol_token:
            continue

        try:
            token = symbol_token[symbol]
            q = quotes.get(str(token))
            if not q:
                continue

            ltp = q["last_price"]
            prev_close = q["ohlc"]["close"]
            change = round(((ltp - prev_close) / prev_close) * 100, 2)
            today_total_volume = q.get("volume", 0)

            # ---------- HISTORICAL DATA ----------
            today_5m = kite.historical_data(token, today, today, "5minute")
            if not today_5m:
                continue

            prev_5m = kite.historical_data(token, yesterday, yesterday, "5minute")
            yday = kite.historical_data(token, yesterday, yesterday, "day")

            time.sleep(0.35)  # rate-limit safety

            prev_last_5m_vol = prev_5m[-1]["volume"] if prev_5m else 0
            today_first_5m_vol = today_5m[0]["volume"]

            avg_5d_vol = avg_volume_last_5_days(token)

            # ================= 1️⃣ 9:15 AM INTRADAY LOGIC =================
            high_915 = today_5m[0]["high"]
            low_915 = today_5m[0]["low"]

            high_pct = round(((high_915 - prev_close) / prev_close) * 100, 2)
            low_pct = round(((low_915 - prev_close) / prev_close) * 100, 2)
            hl_pct = f"{high_pct}% / {low_pct}%"

            # ================= 2️⃣ 10:00 AM LOGIC =================
            ten_am_high_pct = ""
            ten_am_low_pct = ""

            candles_till_10 = [
                c for c in today_5m
                if c["date"].time() <= datetime.strptime("10:00", "%H:%M").time()
            ]

            if candles_till_10:
                high_10 = max(c["high"] for c in candles_till_10)
                low_10 = min(c["low"] for c in candles_till_10)

                ten_am_high_pct = round(((high_10 - prev_close) / prev_close) * 100, 2)
                ten_am_low_pct = round(((low_10 - prev_close) / prev_close) * 100, 2)



            # ================= 3️⃣ GAP UP / GAP DOWN (SEPARATE LOGIC) =================
            gap_type = None
            gap_pct = None

            if yday:
                y = yday[-1]
                open_915 = today_5m[0]["open"]
                gap_pct = round(((open_915 - y["close"]) / y["close"]) * 100, 2)

                if gap_pct >= 1.5 and open_915 > y["high"]:
                    gap_type = "GAP UP"
                elif gap_pct <= -1.5 and open_915 < y["low"]:
                    gap_type = "GAP DOWN"

            # ================= 4️⃣ BIG PLAYER LOGIC =================
            big_type = None
            if (
                prev_last_5m_vol > 0 and
                today_first_5m_vol >= 2 * prev_last_5m_vol and
                avg_5d_vol > 0 and
                today_total_volume >= 1.5 * avg_5d_vol
            ):
                if change > 0:
                    big_type = "BUY"
                elif change < 0:
                    big_type = "SELL"

            # ================= FINAL ROW =================
            rows.append({
                "symbol": symbol,
                "ltp": round(ltp, 2),
                "change": change,
                "volume_fmt": format_volume(today_first_5m_vol),
                "hl_pct": hl_pct,
                "ten_am_high_pct": ten_am_high_pct,
                "ten_am_low_pct": ten_am_low_pct,
                "total_volume_fmt": format_volume(today_total_volume),
                "big": big_type,
                "gap": gap_pct,
                "gap_type": gap_type
            })

        except Exception as e:
            print("ERROR:", symbol, e)

    dfm = pd.DataFrame(rows)

    # ================= 🔥 KEY FIX: REMOVE GAP STOCKS FROM RANGES =================
    range_df = dfm[dfm.gap_type.isnull()]

    # ================= RANGES (INTRADAY ONLY) =================
    r1b = range_df[range_df.change >= 2].sort_values("change", ascending=False)
    r1s = range_df[range_df.change <= -2].sort_values("change")

    r2b = range_df[(range_df.change >= 1.5) & (range_df.change < 2)].sort_values("change", ascending=False)
    r2s = range_df[(range_df.change <= -1.5) & (range_df.change > -2)].sort_values("change")

    r3b = range_df[(range_df.change >= 0.8) & (range_df.change < 1.5)].sort_values("change", ascending=False)
    r3s = range_df[(range_df.change <= -0.8) & (range_df.change > -1.5)].sort_values("change")

    # ================= GAP SECTION =================
    gap_up = dfm[dfm.gap_type == "GAP UP"]
    gap_down = dfm[dfm.gap_type == "GAP DOWN"]

    return render_template(
        "index.html",
        r1b=r1b.to_dict("records"),
        r1s=r1s.to_dict("records"),
        r2b=r2b.to_dict("records"),
        r2s=r2s.to_dict("records"),
        r3b=r3b.to_dict("records"),
        r3s=r3s.to_dict("records"),
        gap_up=gap_up.to_dict("records"),
        gap_down=gap_down.to_dict("records"),
        r1b_count=len(r1b), r1s_count=len(r1s),
        r2b_count=len(r2b), r2s_count=len(r2s),
        r3b_count=len(r3b), r3s_count=len(r3s)
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001, debug=True)
