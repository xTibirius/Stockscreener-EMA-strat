from io import StringIO
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="S&P 500 Trading Hub", page_icon="📈", layout="wide"
)

# Speicher für aktive Trades im Sitzungsspeicher (Session State)
if "my_trades" not in st.session_state:
  st.session_state.my_trades = []

st.title("📈 S&P 500 Live Screener & Trade Manager")


# 1. Daten laden und analysieren
@st.cache_data(ttl=3600)
def load_screener_data():
  url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }
  response = requests.get(url, headers=headers)
  tables = pd.read_html(StringIO(response.text), flavor="html5lib")
  symbols = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()

  raw_data = yf.download(
      symbols, period="1y", interval="1d", group_by="column", auto_adjust=True
  )

  close_w = raw_data["Close"].dropna(how="all", axis=1).resample("W").last()
  low_w = raw_data["Low"].dropna(how="all", axis=1).resample("W").min()

  ema10 = close_w.ewm(span=10, adjust=False).mean()
  ema21 = close_w.ewm(span=21, adjust=False).mean()

  exp1 = close_w.ewm(span=12, adjust=False).mean()
  exp2 = close_w.ewm(span=26, adjust=False).mean()
  macd_hist = (exp1 - exp2) - (exp1 - exp2).ewm(span=9, adjust=False).mean()

  results = []
  for sym in close_w.columns:
    c_price = close_w[sym].iloc[-1]
    l_price = low_w[sym].iloc[-1]
    if pd.isna(c_price):
      continue

    e10, e21 = ema10[sym].iloc[-1], ema21[sym].iloc[-1]
    e10_prev, e21_prev = ema10[sym].iloc[-2], ema21[sym].iloc[-2]
    m_hist, m_hist_prev = macd_hist[sym].iloc[-1], macd_hist[sym].iloc[-2]

    macd_ok = (m_hist > 0) or (m_hist > m_hist_prev)
    crossover_now = (e10_prev <= e21_prev) and (e10 > e21)
    trend_ok = e10 > e21

    enter_fall1 = crossover_now and macd_ok
    enter_fall2 = trend_ok and (l_price <= e10) and macd_ok and (not crossover_now)

    near_retest = trend_ok and (l_price <= e10 * 1.02) and (l_price > e10)
    near_crossover = (
        (e10 < e21) and (e10 / e21 > 0.985) and (m_hist > m_hist_prev)
    )

    if enter_fall1:
      status = "BEREIT"
      typ = "Fall 1 (Crossover)"
    elif enter_fall2:
      status = "BEREIT"
      typ = "Fall 2 (Retest)"
    elif near_retest:
      status = "FAST BEREIT"
      typ = "Fall 2 (Retest nah)"
    elif near_crossover:
      status = "FAST BEREIT"
      typ = "Fall 1 (Cross nah)"
    else:
      continue

    results.append({
        "Aktie": sym,
        "Status": status,
        "Typ": typ,
        "Kurs": round(c_price, 2),
        "EMA 10": round(e10, 2),
        "EMA 21": round(e21, 2),
    })

  return pd.DataFrame(results), close_w, ema21, ema10


df_setups, close_w, ema21, ema10 = load_screener_data()

# ==========================================
# SEKTION 1: MEINE GENOMMENEN TRADES (TRACKER)
# ==========================================
st.subheader("🎯 Meine aktiven Trades")

if len(st.session_state.my_trades) == 0:
  st.info("Noch keine Trades markiert. Wählen Sie unten ein Setup aus!")
else:
  trade_data = []
  for sym in st.session_state.my_trades:
    curr_price = close_w[sym].iloc[-1]
    curr_e21 = ema21[sym].iloc[-1]

    if curr_price < curr_e21:
      health = "❌ INVALIDIERT (SL Greift!)"
    elif curr_price <= curr_e21 * 1.02:
      health = "⚠️ FAST INVALIDIERT (Nahe 21 EMA)"
    else:
      health = "✅ IN ORDNUNG (Im Trend)"

    trade_data.append({
        "Aktie": sym,
        "Aktueller Kurs": f"${round(curr_price, 2)}",
        "21 EMA (Stopp)": f"${round(curr_e21, 2)}",
        "Trade Status": health,
    })

  st.dataframe(pd.DataFrame(trade_data), use_container_width=True)

st.divider()

# ==========================================
# SEKTION 2: NEUE SETUPS (KÄSTEN-GRID)
# ==========================================
st.subheader("🔍 Aktuelle Markt-Setups (S&P 500)")

if df_setups.empty:
  st.write("Aktuell keine aktiven Setups vorhanden.")
else:
  # 3 Kästen pro Zeile anzeigen
  cols = st.columns(3)

  for idx, row in df_setups.iterrows():
    col = cols[idx % 3]

    with col:
      # Kasten (Container) erstellen
      with st.container(border=True):
        # 1. Obere Zeile: Fett Name + Status
        st.markdown(f"### **{row['Aktie']} — {row['Status']}**")
        st.caption(f"Setup: {row['Typ']}")

        # 2. Zweite Zeile: Aktueller Preis
        st.markdown(f"**Preis:** `${row['Kurs']}`")

        # 3. Farb-Logik für EMA 10
        if row["Kurs"] > row["EMA 10"]:
          ema10_color = "green"
        else:
          ema10_color = "red"

        # 4. Farb-Logik für EMA 21
        if row["Kurs"] > row["EMA 21"]:
          ema21_color = "green"
        else:
          ema21_color = "red"

        # EMA-Werte mit Farbcodierung anzeigen
        st.markdown(
            f"**10 EMA:** :{ema10_color}[${row['EMA 10']}] | **21 EMA:**"
            f" :{ema21_color}[${row['EMA 21']}]"
        )

        st.markdown("---")

        # 5. Untere Zeile: Button "Trade genommen"
        already_taken = row["Aktie"] in st.session_state.my_trades
        if st.button(
            "Trade genommen" if not already_taken else "Im Portfolio",
            key=f"btn_{row['Aktie']}",
            disabled=already_taken,
            use_container_width=True,
        ):
          st.session_state.my_trades.append(row["Aktie"])
          st.rerun()
