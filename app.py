from flask import Flask, render_template
import pandas as pd
from kiteconnect import KiteConnect
from datetime import datetime, timedelta

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
    gap_up, gap_down = [], []
    gap_symbols = set()

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

            # ======= AVG 5 DAY VOLUME =======
            avg_5d_vol = avg_volume_last_5_days(token)

            big_player = (
                avg_5d_vol > 0 and
                today_total_volume >= 2 * avg_5d_vol
            )

            # ======= 5 MIN DATA =======
            prev_5m = kite.historical_data(token, yesterday, yesterday, "5minute")
            today_5m = kite.historical_data(token, today, today, "5minute")

            prev_last_5m_vol = prev_5m[-1]["volume"] if prev_5m else 0
            today_first_5m_vol = today_5m[0]["volume"] if today_5m else 0

            buy_signal = (
                prev_last_5m_vol > 0 and
                today_first_5m_vol >= 2 * prev_last_5m_vol
            )

            # ======= GAP LOGIC =======
            if today_5m:
                first = today_5m[0]

                gap_up_pct = round(((first["high"] - prev_close) / prev_close) * 100, 2)
                gap_dn_pct = round(((prev_close - first["low"]) / prev_close) * 100, 2)

                if gap_up_pct >= 1.5:
                    gap_symbols.add(symbol)
                    gap_up.append({
                        "symbol": symbol,
                        "ltp": round(ltp, 2),
                        "gap": gap_up_pct,
                        "volume_fmt": format_volume(today_first_5m_vol),
                        "total_volume_fmt": format_volume(today_total_volume),
                        "buy": buy_signal,
                        "big": big_player
                    })

                elif gap_dn_pct >= 1.5:
                    gap_symbols.add(symbol)
                    gap_down.append({
                        "symbol": symbol,
                        "ltp": round(ltp, 2),
                        "gap": -gap_dn_pct,
                        "volume_fmt": format_volume(today_first_5m_vol),
                        "total_volume_fmt": format_volume(today_total_volume),
                        "buy": False,
                        "big": big_player
                    })

            rows.append({
                "symbol": symbol,
                "ltp": round(ltp, 2),
                "change": change,
                "volume_fmt": format_volume(today_first_5m_vol),
                "total_volume_fmt": format_volume(today_total_volume),
                "buy": buy_signal,
                "big": big_player
            })

        except Exception as e:
            print("ERROR:", e)
            continue

    dfm = pd.DataFrame(rows)
    df_range = dfm[~dfm.symbol.isin(gap_symbols)]

    r1b = df_range[df_range.change >= 2].sort_values("change", ascending=False)
    r1s = df_range[df_range.change <= -2].sort_values("change")
    r2b = df_range[(df_range.change >= 1.5) & (df_range.change < 2)]
    r2s = df_range[(df_range.change <= -1.5) & (df_range.change > -2)]
    r3b = df_range[(df_range.change >= 0.8) & (df_range.change < 1.5)]
    r3s = df_range[(df_range.change <= -0.8) & (df_range.change > -1.5)]

    return render_template(
        "index.html",
        r1b=r1b.to_dict("records"),
        r1s=r1s.to_dict("records"),
        r2b=r2b.to_dict("records"),
        r2s=r2s.to_dict("records"),
        r3b=r3b.to_dict("records"),
        r3s=r3s.to_dict("records"),
        r1b_count=len(r1b), r1s_count=len(r1s),
        r2b_count=len(r2b), r2s_count=len(r2s),
        r3b_count=len(r3b), r3s_count=len(r3s),
        gap_up=gap_up,
        gap_down=gap_down
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001, debug=True)

