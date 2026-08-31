from io import StringIO
import json
import os
import urllib.parse
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="S&P 500 Trading Hub", page_icon="📈", layout="wide"
)

# ---------------------------------------------------------
# DAUERHAFTES SPEICHERN (Multi-User & User-Liste in JSON)
# ---------------------------------------------------------
TRADES_FILE = "trades.json"


def load_all_trades():
  """Lädt das Gesamtwörterbuch mit den Trades aller Nutzer."""
  if os.path.exists(TRADES_FILE):
    try:
      with open(TRADES_FILE, "r") as f:
        data = json.load(f)
        if isinstance(data, dict):
          return data
    except Exception:
      return {}
  return {}


def save_all_trades(all_trades_dict):
  """Speichert die Trades aller Nutzer in der JSON-Datei."""
  with open(TRADES_FILE, "w") as f:
    json.dump(all_trades_dict, f, indent=4)


# Alle bisher gespeicherten Trades und Nutzer laden
all_trades = load_all_trades()

# ---------------------------------------------------------
# BENUTZER-AUSWAHL (SIDEBAR)
# ---------------------------------------------------------
st.sidebar.title("👤 Nutzer-Profil")

# Nutzerliste dynamisch aus den bisher gespeicherten Nutzern generieren
existing_users = sorted(list(all_trades.keys()))
user_options = existing_users + ["➕ Neuer Nutzer..."]

selected_user_option = st.sidebar.selectbox("Wähle dein Profil:", user_options)

if selected_user_option == "➕ Neuer Nutzer...":
  new_user_name = st.sidebar.text_input(
      "Dein Name:", placeholder="z.B. Thomas"
  ).strip()
  if not new_user_name:
    st.info("👈 Bitte wähle links dein Profil aus oder gib deinen Namen ein.")
    st.stop()
  else:
    current_user = new_user_name
    if current_user not in all_trades:
      all_trades[current_user] = {}
      save_all_trades(all_trades)
      st.rerun()
else:
  current_user = selected_user_option

st.sidebar.success(f"Angemeldet als: **{current_user}**")

user_trades = all_trades.get(current_user, {})

st.title(f"📈 S&P 500 Trading Hub — ({current_user})")


# ---------------------------------------------------------
# HELPER: GOOGLE SEARCH LINK
# ---------------------------------------------------------
def get_google_link(ticker):
  query = urllib.parse.quote(f"{ticker} stock price")
  return f"https://www.google.com/search?q={query}"


# ---------------------------------------------------------
# 1. DATEN LADEN & ANALYSIEREN
# ---------------------------------------------------------
@st.cache_data(ttl=900)
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

    ema_diff_pct = (abs(e10 - e21) / e21) * 100.0
    dist_to_ema10_pct = abs(c_price - e10) / e10 * 100.0
    has_red_ema = (c_price < e10) or (c_price < e21)

    if c_price < e21:
      health_status = "❌ INVALIDIERT"
      health_color = "red"
    elif c_price <= e21 * 1.02:
      health_status = "⚠️ FAST INVALIDIERT"
      health_color = "orange"
    else:
      health_status = "✅ IN ORDNUNG"
      health_color = "green"

    results.append({
        "Aktie": sym,
        "Status": status,
        "Typ": typ,
        "Kurs": round(c_price, 2),
        "EMA 10": round(e10, 2),
        "EMA 21": round(e21, 2),
        "EMA Diff %": round(ema_diff_pct, 2),
        "Dist EMA10 %": dist_to_ema10_pct,
        "Has Red EMA": has_red_ema,
        "Health Status": health_status,
        "Health Color": health_color,
    })

  df = pd.DataFrame(results)
  if not df.empty:
    df = df.sort_values(by="Dist EMA10 %", ascending=True)

  return df, close_w, ema21, ema10


df_setups, close_w, ema21, ema10 = load_screener_data()

# ---------------------------------------------------------
# SEKTION 1: MEINE GENOMMENEN TRADES (NUR FÜR NUTZER)
# ---------------------------------------------------------
st.subheader(f"🎯 Aktive Trades von {current_user}")

if len(user_trades) == 0:
  st.info("Noch keine Trades markiert. Wählen Sie unten ein Setup aus!")
else:
  for sym, info in list(user_trades.items()):
    curr_price = close_w[sym].iloc[-1]
    curr_e21 = ema21[sym].iloc[-1]

    if curr_price < curr_e21:
      health = "❌ INVALIDIERT (SL Greift!)"
      health_color = "red"
    elif curr_price <= curr_e21 * 1.02:
      health = "⚠️ FAST INVALIDIERT (Nahe 21 EMA)"
      health_color = "orange"
    else:
      health = "✅ IN ORDNUNG (Im Trend)"
      health_color = "green"

    link = get_google_link(sym)

    with st.container(border=True):
      c1, c2, c3, c4, c5 = st.columns([1.5, 2.5, 2, 2.5, 1.5])

      c1.markdown(f"### **[{sym}]({link})**")
      c2.markdown(
          f"Status: :{health_color}[**{health}**]\n\n*Profit-Status:*"
          f" **{info['status']}**"
      )
      c3.markdown(
          f"**Kurs:** ${round(curr_price, 2)}\n\n**21 EMA:**"
          f" ${round(curr_e21, 2)}"
      )

      if c4.button("50% Gewinn genommen", key=f"tp50_{sym}"):
        all_trades[current_user][sym]["status"] = "💰 50% Gewinn gesichert"
        save_all_trades(all_trades)
        st.rerun()

      if c4.button("90% Gewinn genommen", key=f"tp90_{sym}"):
        all_trades[current_user][sym]["status"] = (
            "🚀 90% Gewinn gesichert (Rest läuft)"
        )
        save_all_trades(all_trades)
        st.rerun()

      if c5.button("🗑️ Schließen", key=f"remove_{sym}", use_container_width=True):
        del all_trades[current_user][sym]
        save_all_trades(all_trades)
        st.rerun()

st.divider()

# ---------------------------------------------------------
# SEKTION 2: FILTER & NEUE SETUPS
# ---------------------------------------------------------
st.subheader("🔍 Aktuelle Markt-Setups (S&P 500)")

if df_setups.empty:
  st.write("Aktuell keine aktiven Setups vorhanden.")
else:
  available_setups = df_setups[~df_setups["Aktie"].isin(user_trades.keys())]

  f_col1, f_col2, f_col3 = st.columns(3)

  with f_col1:
    show_bereit = st.checkbox("🚀 BEREIT anzeigen", value=True)

  with f_col2:
    show_fast_bereit = st.checkbox("⚠️ FAST BEREIT anzeigen", value=True)

  with f_col3:
    only_red_ema = st.checkbox("Nur mit mind. 1 roten EMA")

  filtered_df = available_setups.copy()

  selected_statuses = []
  if show_bereit:
    selected_statuses.append("BEREIT")
  if show_fast_bereit:
    selected_statuses.append("FAST BEREIT")

  filtered_df = filtered_df[filtered_df["Status"].isin(selected_statuses)]

  if only_red_ema:
    filtered_df = filtered_df[filtered_df["Has Red EMA"] == True]

  st.write(
      f"Gefundene Setups (sortiert nach EMA-Nähe): **{len(filtered_df)}**"
  )

  cols = st.columns(3)

  for idx, (_, row) in enumerate(filtered_df.iterrows()):
    col = cols[idx % 3]
    sym = row["Aktie"]
    link = get_google_link(sym)

    with col:
      with st.container(border=True):
        # 1. Titel mit Google-Link auf dem Kürzel
        if row["Status"] == "BEREIT":
          status_tag = ":green[🚀 **BEREIT**]"
        else:
          status_tag = ":orange[⚠️ **FAST BEREIT**]"

        st.markdown(f"### **[{sym}]({link}) — {status_tag}**")
        st.caption(f"Setup: {row['Typ']}")

        # 2. Preis & EMA Differenz in %
        st.markdown(
            f"**Preis:** `${row['Kurs']}` | **EMA-Diff:**"
            f" `{row['EMA Diff %']}%`"
        )

        # 3. EMA Farben ermitteln
        ema10_color = "green" if row["Kurs"] > row["EMA 10"] else "red"
        ema21_color = "green" if row["Kurs"] > row["EMA 21"] else "red"

        # EMA-Werte anzeigen
        st.markdown(
            f"**10 EMA:** :{ema10_color}[${row['EMA 10']}] | **21 EMA:**"
            f" :{ema21_color}[${row['EMA 21']}]"
        )

        # 4. Status der Position
        st.markdown(
            f"Position Status:"
            f" :{row['Health Color']}[**{row['Health Status']}**]"
        )

        st.markdown("---")

        # 5. Button "Trade genommen"
        if st.button(
            "Trade genommen", key=f"btn_{sym}", use_container_width=True
        ):
          all_trades[current_user][sym] = {"status": "Offen"}
          save_all_trades(all_trades)
          st.rerun()
