from io import StringIO
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="S&P 500 Trading Hub", page_icon="📈", layout="wide"
)

# ---------------------------------------------------------
# SPEICHER FÜR TRADES (Session State)
# ---------------------------------------------------------
if "my_trades" not in st.session_state:
  st.session_state.my_trades = {}  # Format: {'TICKER': {'status': 'Offen'}}

st.title("📈 S&P 500 Live Screener & Trade Manager")


# ---------------------------------------------------------
# 1. DATEN LADEN & ANALYSIEREN
# ---------------------------------------------------------
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
    enter_fall2 = (
        trend_ok and (l_price <= e10) and macd_ok and (not crossover_now)
    )

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

    ema_diff = abs(e10 - e21)
    has_red_ema = (c_price < e10) or (c_price < e21)

    results.append({
        "Aktie": sym,
        "Status": status,
        "Typ": typ,
        "Kurs": round(c_price, 2),
        "EMA 10": round(e10, 2),
        "EMA 21": round(e21, 2),
        "EMA Differenz": round(ema_diff, 2),
        "Has Red EMA": has_red_ema,
    })

  return pd.DataFrame(results), close_w, ema21, ema10


df_setups, close_w, ema21, ema10 = load_screener_data()

# ---------------------------------------------------------
# SEKTION 1: MEINE GENOMMENEN TRADES (TRACKER & GEWINNE)
# ---------------------------------------------------------
st.subheader("🎯 Meine aktiven Trades")

if len(st.session_state.my_trades) == 0:
  st.info("Noch keine Trades markiert. Wählen Sie unten ein Setup aus!")
else:
  for sym, info in list(st.session_state.my_trades.items()):
    curr_price = close_w[sym].iloc[-1]
    curr_e21 = ema21[sym].iloc[-1]

    # Status-Logik
    if curr_price < curr_e21:
      health = "❌ INVALIDIERT (SL Greift!)"
      health_color = "red"
    elif curr_price <= curr_e21 * 1.02:
      health = "⚠️ FAST INVALIDIERT (Nahe 21 EMA)"
      health_color = "orange"
    else:
      health = "✅ IN ORDNUNG (Im Trend)"
      health_color = "green"

    # Zeile im Portfolio bauen
    with st.container(border=True):
      c1, c2, c3, c4, c5 = st.columns([1.5, 2.5, 2, 2.5, 1.5])

      c1.markdown(f"### **{sym}**")
      c2.markdown(
          f"Status: :{health_color}[**{health}**]\n\n*Profit-Status:* **{info['status']}**"
      )
      c3.markdown(
          f"**Kurs:** ${round(curr_price, 2)}\n\n**21 EMA:**"
          f" ${round(curr_e21, 2)}"
      )

      # Buttons für Gewinnmitnahme
      if c4.button("50% Gewinn genommen", key=f"tp50_{sym}"):
        st.session_state.my_trades[sym]["status"] = "💰 50% Gewinn gesichert"
        st.rerun()

      if c4.button("90% Gewinn genommen", key=f"tp90_{sym}"):
        st.session_state.my_trades[sym]["status"] = (
            "🚀 90% Gewinn gesichert (Rest läuft)"
        )
        st.rerun()

      # Button zum Entfernen aus der Liste
      if c5.button("🗑️ Schließen", key=f"remove_{sym}", use_container_width=True):
        del st.session_state.my_trades[sym]
        st.rerun()

st.divider()

# ---------------------------------------------------------
# SEKTION 2: FILTER & NEUE SETUPS (KÄSTEN-GRID)
# ---------------------------------------------------------
st.subheader("🔍 Aktuelle Markt-Setups (S&P 500)")

if df_setups.empty:
  st.write("Aktuell keine aktiven Setups vorhanden.")
else:
  # Filter-Leiste aufbauen
  f_col1, f_col2 = st.columns([2, 2])

  with f_col1:
    status_filter = st.multiselect(
        "Nach Status filtern:",
        options=["BEREIT", "FAST BEREIT"],
        default=["BEREIT", "FAST BEREIT"],
    )

  with f_col2:
    only_red_ema = st.checkbox(
        "Nur Trades anzeigen, bei denen mind. eine EMA rot ist"
    )

  # Filter anwenden
  filtered_df = df_setups[df_setups["Status"].isin(status_filter)]
  if only_red_ema:
    filtered_df = filtered_df[filtered_df["Has Red EMA"] == True]

  st.write(f"Gefundene Setups: **{len(filtered_df)}**")

  # 3 Kästen pro Zeile anzeigen
  cols = st.columns(3)

  for idx, (_, row) in enumerate(filtered_df.iterrows()):
    col = cols[idx % 3]

    with col:
      with st.container(border=True):
        # 1. Titel mit Emoji & Farbe je nach Status
        if row["Status"] == "BEREIT":
          title_html = (
              f"### **{row['Aktie']} —** :green[🚀 **BEREIT**]"
          )
        else:
          title_html = (
              f"### **{row['Aktie']} —** :orange[⚠️ **FAST BEREIT**]"
          )

        st.markdown(title_html)
        st.caption(f"Setup: {row['Typ']}")

        # 2. Preis & EMA Differenz
        st.markdown(
            f"**Preis:** `${row['Kurs']}` | **EMA-Diff:**"
            f" `${row['EMA Differenz']}`"
        )

        # 3. EMA Farben ermitteln
        ema10_color = "green" if row["Kurs"] > row["EMA 10"] else "red"
        ema21_color = "green" if row["Kurs"] > row["EMA 21"] else "red"

        # EMA-Werte anzeigen
        st.markdown(
            f"**10 EMA:** :{ema10_color}[${row['EMA 10']}] | **21 EMA:**"
            f" :{ema21_color}[${row['EMA 21']}]"
        )

        st.markdown("---")

        # 4. Button "Trade genommen"
        already_taken = row["Aktie"] in st.session_state.my_trades
        if st.button(
            "Trade genommen" if not already_taken else "Im Portfolio",
            key=f"btn_{row['Aktie']}",
            disabled=already_taken,
            use_container_width=True,
        ):
          st.session_state.my_trades[row["Aktie"]] = {"status": "Offen"}
          st.rerun()
