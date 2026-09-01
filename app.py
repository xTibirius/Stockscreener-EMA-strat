# =====================================================================
# S&P 500 WEEKLY EMA STACK & MACD SCREENER + TRADE HUB
# =====================================================================
from datetime import datetime
from io import StringIO
import json
import os
import urllib.parse
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ---------------------------------------------------------------------
# 1. SEITEN-KONFIGURATION & STYLING
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="S&P 500 EMA & MACD Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------
# 2. PERSISTENTE SPEICHERUNG (TRADES & NUTZER-PROFILE)
# ---------------------------------------------------------------------
TRADES_FILE = "trades.json"


def load_all_trades() -> dict:
    """Lädt das Gesamtwörterbuch mit den Trades aller Nutzer."""
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_all_trades(all_trades_dict: dict):
    """Speichert die Trades aller Nutzer sicher in der JSON-Datei."""
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(all_trades_dict, f, indent=4, ensure_ascii=False)


all_trades = load_all_trades()

# ---------------------------------------------------------------------
# 3. SIDEBAR: PROFIL & RISIKOMANAGEMENT-EINSTELLUNGEN
# ---------------------------------------------------------------------
st.sidebar.title("👤 Nutzer-Profil")

existing_users = sorted(list(all_trades.keys()))
user_options = existing_users + ["➕ Neuer Nutzer..."]
selected_user_option = st.sidebar.selectbox("Wähle dein Profil:", user_options)

if selected_user_option == "➕ Neuer Nutzer...":
    new_user_name = st.sidebar.text_input(
        "Dein Name:", placeholder="z. B. Thomas"
    ).strip()
    if not new_user_name:
        st.info("👈 Bitte wähle links dein Profil aus oder erstelle ein neues.")
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

st.sidebar.markdown("---")
st.sidebar.subheader("⚖️ Risiko-Kalkulator")
account_size = st.sidebar.number_input(
    "Gesamtdepot (€ / $):",
    min_value=500.0,
    value=10000.0,
    step=500.0,
    help="Dein verfügbares Trading-Kapital.",
)
risk_per_trade_pct = st.sidebar.slider(
    "Max. Risiko pro Trade (%):",
    min_value=0.25,
    max_value=3.0,
    value=1.0,
    step=0.25,
    help="Prozentualer Betrag des Depots, den du maximal verlieren willst, wenn der Stop-Loss greift.",
)
max_risk_amount = account_size * (risk_per_trade_pct / 100.0)
st.sidebar.caption(
    f"Max. Verlust bei SL: **${max_risk_amount:,.2f}** ({risk_per_trade_pct}%"
    " des Depots)"
)


# ---------------------------------------------------------------------
# 4. HILFSFUNKTIONEN: LINKS
# ---------------------------------------------------------------------
def get_tradingview_link(ticker: str) -> str:
    clean_ticker = ticker.replace("-", ".")
    return f"https://www.tradingview.com/chart/?symbol={clean_ticker}"


def get_google_link(ticker: str) -> str:
    query = urllib.parse.quote(f"{ticker} stock price")
    return f"https://www.google.com/search?q={query}"


# ---------------------------------------------------------------------
# 5. DATEN LADEN & STRATEGIE-LOGIK
# ---------------------------------------------------------------------
@st.cache_data(ttl=900)
def load_screener_data():
    """Lädt S&P 500 Ticker, 3 Jahre Tagesdaten und berechnet Weekly EMAs, MACD und Volumen."""
    # 1. Tickerliste von Wikipedia abrufen
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    response = requests.get(url, headers=headers)
    tables = pd.read_html(StringIO(response.text), flavor="html5lib")

    sp500_df = tables[0]
    sp500_df["Symbol_Clean"] = sp500_df["Symbol"].str.replace(
        ".", "-", regex=False
    )
    company_names = dict(zip(sp500_df["Symbol_Clean"], sp500_df["Security"]))
    symbols = sp500_df["Symbol_Clean"].tolist()

    # 2. 3 Jahre Tagesdaten laden (sichert mathematische Stabilität der Indikatoren)
    raw_data = yf.download(
        symbols,
        period="3y",
        interval="1d",
        group_by="column",
        auto_adjust=True,
        progress=False,
    )

    close_d = raw_data["Close"].dropna(how="all", axis=1)
    low_d = raw_data["Low"].dropna(how="all", axis=1)
    vol_d = raw_data["Volume"].dropna(how="all", axis=1)

    # 3. Wöchentliches Resampling (Freitag Schluss)
    close_w = close_d.resample("W-FRI").last()
    low_w = low_d.resample("W-FRI").min()
    vol_w = vol_d.resample("W-FRI").sum()

    daily_change_pct = close_d.pct_change().iloc[-1] * 100.0

    # 4. Indikatoren berechnen
    ema10 = close_w.ewm(span=10, adjust=False).mean()
    ema21 = close_w.ewm(span=21, adjust=False).mean()

    # MACD (12, 26, 9)
    exp12 = close_w.ewm(span=12, adjust=False).mean()
    exp26 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp12 - exp26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    # 10-Wochen-Durchschnittsvolumen
    vol_sma10 = vol_w.rolling(window=10).mean()

    results = []

    for sym in close_w.columns:
        series_close = close_w[sym].dropna()
        if len(series_close) < 30:
            continue

        c_price = series_close.iloc[-1]
        l_price = low_w[sym].dropna().iloc[-1]
        if pd.isna(c_price) or pd.isna(l_price):
            continue

        e10 = ema10[sym].iloc[-1]
        e21 = ema21[sym].iloc[-1]
        e10_prev = ema10[sym].iloc[-2]
        e21_prev = ema21[sym].iloc[-2]

        m_hist = macd_hist[sym].iloc[-1]
        m_hist_prev = macd_hist[sym].iloc[-2]

        # Volumen-Verhältnis
        curr_vol = vol_w[sym].iloc[-1]
        avg_vol = vol_sma10[sym].iloc[-1]
        vol_ratio = (curr_vol / avg_vol) if avg_vol > 0 else 1.0

        # MACD ansteigend (Momentum dreht aufwärts)
        macd_rising = m_hist > m_hist_prev

        # Crossover & Trend
        crossover_now = (e10_prev <= e21_prev) and (e10 > e21)
        trend_bullish = e10 > e21

        # Retest-Definitionen:
        # 1. 10 EMA Retest: Tief dippt an 10 EMA, Kurs bleibt über 21 EMA
        retest_ema10 = (
            trend_bullish
            and (l_price <= e10 * 1.015)
            and (c_price >= e21)
            and not crossover_now
        )
        # 2. 21 EMA Retest: Tief dippt an 21 EMA, Kurs schließt nicht darunter
        retest_ema21 = (
            trend_bullish
            and (l_price <= e21 * 1.015)
            and (c_price >= e21 * 0.985)
            and not crossover_now
        )

        # Vorwarnungs-Signale
        near_crossover = (
            (e10 < e21) and (e10 / e21 > 0.985) and macd_rising
        )
        near_retest = (
            trend_bullish
            and (l_price <= e10 * 1.03)
            and (l_price > e10 * 1.015)
            and macd_rising
        )

        status = None
        typ = None

        if crossover_now and macd_rising:
            status = "BEREIT"
            typ = "10/21 EMA Crossover"
        elif (retest_ema10 or retest_ema21) and macd_rising:
            status = "BEREIT"
            typ = (
                "EMA 10 Retest (Bounce)"
                if retest_ema10
                else "EMA 21 Retest (Deep Bounce)"
            )
        elif near_retest:
            status = "FAST BEREIT"
            typ = "Retest nähert sich (<3% zur EMA 10)"
        elif near_crossover:
            status = "FAST BEREIT"
            typ = "Crossover steht kurz bevor"
        else:
            continue

        # Trade-Kennzahlen
        stop_loss_level = round(e21, 2)
        sl_distance_pct = ((c_price - stop_loss_level) / c_price) * 100.0
        ema_diff_pct = ((e10 - e21) / e21) * 100.0
        dist_to_ema10_pct = abs(c_price - e10) / e10 * 100.0
        has_red_ema = (c_price < e10) or (c_price < e21)

        # Positions-Health
        if c_price < e21:
            health_status = "❌ INVALIDIERT"
            health_color = "red"
        elif c_price <= e21 * 1.015:
            health_status = "⚠️ NAHE STOP-LOSS"
            health_color = "orange"
        else:
            health_status = "✅ IN ORDNUNG"
            health_color = "green"

        comp_name = company_names.get(sym, sym)
        d_change = round(daily_change_pct.get(sym, 0.0), 2)

        results.append(
            {
                "Aktie": sym,
                "Name": comp_name,
                "Status": status,
                "Typ": typ,
                "Kurs": round(c_price, 2),
                "DailyChange": d_change,
                "EMA 10": round(e10, 2),
                "EMA 21": round(e21, 2),
                "Stop Loss": stop_loss_level,
                "SL Distanz %": round(sl_distance_pct, 2),
                "EMA Diff %": round(ema_diff_pct, 2),
                "Dist EMA10 %": dist_to_ema10_pct,
                "MACD Hist": round(m_hist, 3),
                "Volumen Ratio": round(vol_ratio, 2),
                "Has Red EMA": has_red_ema,
                "Health Status": health_status,
                "Health Color": health_color,
            }
        )

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by="Dist EMA10 %", ascending=True)

    return df, close_w, ema10, ema21, company_names, daily_change_pct


# Daten ausführen
(
    df_setups,
    close_w,
    ema10_df,
    ema21_df,
    company_names,
    daily_change_pct,
) = load_screener_data()

st.title(f"📈 S&P 500 EMA Stack Screener — ({current_user})")

# ---------------------------------------------------------
# 6. SEKTION 1: AKTIVE TRADES (PORTFOLIO-TRACKER)
# ---------------------------------------------------------
st.subheader(f"🎯 Aktive Trades von {current_user}")

if len(user_trades) == 0:
    st.info(
        "Noch keine aktiven Trades vorhanden. Wähle unten ein passendes Setup"
        " aus und klicke auf '📌 Trade aufnehmen'!"
    )
else:
    for sym, info in list(user_trades.items()):
        if sym not in close_w.columns:
            continue

        curr_price = close_w[sym].dropna().iloc[-1]
        curr_e10 = ema10_df[sym].dropna().iloc[-1]
        curr_e21 = ema21_df[sym].dropna().iloc[-1]

        # Stop-Loss Check
        if curr_price < curr_e21:
            health = "❌ INVALIDIERT (Wochenschluss unter 21 EMA!)"
            health_color = "red"
        elif curr_price <= curr_e21 * 1.015:
            health = "⚠️ FAST INVALIDIERT (Sehr nahe an 21 EMA)"
            health_color = "orange"
        else:
            health = "✅ IN ORDNUNG (Intakter Aufwärtstrend)"
            health_color = "green"

        ema10_color = "green" if curr_price > curr_e10 else "red"
        ema21_color = (
            "green"
            if curr_price > curr_e10
            else ("red" if curr_price < curr_e21 else "orange")
        )

        d_change = round(daily_change_pct.get(sym, 0.0), 2)
        change_color = "green" if d_change >= 0 else "red"
        change_sign = "+" if d_change >= 0 else ""

        entry_price = info.get("entry_price", curr_price)
        entry_date = info.get("entry_date", "Unbekannt")
        pnl_pct = round(((curr_price - entry_price) / entry_price) * 100, 2)
        pnl_color = "green" if pnl_pct >= 0 else "red"
        pnl_sign = "+" if pnl_pct >= 0 else ""

        tv_link = get_tradingview_link(sym)
        comp_name = company_names.get(sym, sym)

        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([1.8, 2.5, 2.5, 2.2, 1.2])

            with c1:
                st.markdown(
                    f"<span style='color:gray; font-size:12px;'>{comp_name}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"### **[{sym}]({tv_link})**")
                st.caption(f"Einstieg am: {entry_date}")

            with c2:
                st.markdown(
                    f"**P&L seit Entry:** :{pnl_color}[**{pnl_sign}{pnl_pct}%**]"
                    f" *(Entry: ${entry_price})*"
                )
                st.markdown(
                    f"Status: :{health_color}[**{health}**]\n\n"
                    f"*Trade-Status:* **{info.get('status', 'Offen')}**"
                )

            with c3:
                st.markdown(
                    f"**Kurs:** `${round(curr_price, 2)}`"
                    f" (:{change_color}[**{change_sign}{d_change}%**])"
                )
                st.markdown(
                    f"**10 EMA:** :{ema10_color}[${round(curr_e10, 2)}] | **21"
                    f" EMA:** :{ema21_color}[${round(curr_e21, 2)}]"
                )
                st.caption(
                    f"Aktueller Trailing Stop (21 EMA): ${round(curr_e21, 2)}"
                )

            with c4:
                if st.button("💰 50% Gewinn sichern", key=f"tp50_{sym}"):
                    all_trades[current_user][sym]["status"] = (
                        "💰 50% Gewinn realisiert"
                    )
                    save_all_trades(all_trades)
                    st.rerun()

                if st.button("🚀 90% Gewinn sichern", key=f"tp90_{sym}"):
                    all_trades[current_user][sym]["status"] = (
                        "🚀 90% Gewinn realisiert (Runner aktiv)"
                    )
                    save_all_trades(all_trades)
                    st.rerun()

            with c5:
                if st.button(
                    "🗑️ Schließen",
                    key=f"remove_{sym}",
                    use_container_width=True,
                ):
                    del all_trades[current_user][sym]
                    save_all_trades(all_trades)
                    st.rerun()

st.divider()

# ---------------------------------------------------------
# 7. SEKTION 2: FILTER & NEUE MARKT-SETUPS
# ---------------------------------------------------------
st.subheader("🔍 Aktuelle Markt-Setups (S&P 500)")

if df_setups.empty:
    st.write("Aktuell keine aktiven Setups gefunden.")
else:
    available_setups = df_setups[~df_setups["Aktie"].isin(user_trades.keys())]

    # Suchleiste
    search_query = st.text_input(
        "🔍 Suche nach Ticker oder Firmenname:",
        placeholder="z. B. NVDA, Microsoft, AAPL...",
    ).strip()

    # Filter-Schalter
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        show_bereit = st.checkbox("🚀 Nur BEREIT anzeigen", value=True)
    with f_col2:
        show_fast_bereit = st.checkbox("⚠️ FAST BEREIT anzeigen", value=True)
    with f_col3:
        show_in_ordnung = st.checkbox("✅ Nur IN ORDNUNG anzeigen", value=True)
    with f_col4:
        min_vol_filter = st.checkbox(
            "📊 Nur mit erhöhtem Volumen (> 1.0x)", value=False
        )

    # Filterlogik
    filtered_df = available_setups.copy()

    selected_statuses = []
    if show_bereit:
        selected_statuses.append("BEREIT")
    if show_fast_bereit:
        selected_statuses.append("FAST BEREIT")
    filtered_df = filtered_df[filtered_df["Status"].isin(selected_statuses)]

    if show_in_ordnung:
        filtered_df = filtered_df[
            filtered_df["Health Status"] == "✅ IN ORDNUNG"
        ]

    if min_vol_filter:
        filtered_df = filtered_df[filtered_df["Volumen Ratio"] >= 1.0]

    if search_query:
        q = search_query.lower()
        filtered_df = filtered_df[
            filtered_df["Aktie"].str.lower().str.contains(q, na=False)
            | filtered_df["Name"].str.lower().str.contains(q, na=False)
        ]

    st.write(
        f"Gefundene Setups (sortiert nach EMA-Nähe): **{len(filtered_df)}**"
    )

    # Darstellung in 3 Spalten
    cols = st.columns(3)

    for idx, (_, row) in enumerate(filtered_df.iterrows()):
        col = cols[idx % 3]
        sym = row["Aktie"]
        comp_name = row["Name"]
        tv_link = get_tradingview_link(sym)

        d_change = row["DailyChange"]
        change_color = "green" if d_change >= 0 else "red"
        change_sign = "+" if d_change >= 0 else ""

        # Positionsgrößenberechnung basierend auf Sidebar-Risiko
        risk_per_share = max(row["Kurs"] - row["Stop Loss"], 0.05)
        shares_to_buy = int(max_risk_amount / risk_per_share)
        position_val = shares_to_buy * row["Kurs"]

        status_tag = (
            ":green[🚀 **BEREIT**]"
            if row["Status"] == "BEREIT"
            else ":orange[⚠️ **FAST BEREIT**]"
        )

        with col:
            with st.container(border=True):
                # Titelzeile mit TradingView Link
                st.markdown(
                    f"<span style='color:gray; font-size:12px;'>{comp_name}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"### **[{sym}]({tv_link}) — {status_tag}**")
                st.caption(f"Setup-Art: **{row['Typ']}**")

                # Kurs & Tagesperformance
                st.markdown(
                    f"**Kurs:** `${row['Kurs']}`"
                    f" (:{change_color}[**{change_sign}{d_change}%**]) |"
                    f" **EMA-Diff:** `{row['EMA Diff %']}%`"
                )

                # Indikatoren-Werte
                ema10_color = "green" if row["Kurs"] > row["EMA 10"] else "red"
                ema21_color = (
                    "green"
                    if row["Kurs"] > row["EMA 10"]
                    else ("red" if row["Kurs"] < row["EMA 21"] else "orange")
                )

                st.markdown(
                    f"**10 EMA:** :{ema10_color}[${row['EMA 10']}] | **21"
                    f" EMA:** :{ema21_color}[${row['EMA 21']}]"
                )
                st.markdown(
                    f"**MACD Hist:** `{row['MACD Hist']}` | **Volumen:**"
                    f" `{row['Volumen Ratio']}x Avg`"
                )

                # Trade-Planung & Risiko
                st.markdown("---")
                st.markdown(
                    f"🛑 **Stop-Loss:** `${row['Stop Loss']}`"
                    f" (:red[**-{row['SL Distanz %']}%**])"
                )
                st.markdown(
                    f"🎯 **Empfohlene Stückzahl:** **{shares_to_buy} Stück**"
                    f" (~${position_val:,.0f})"
                )

                # Speichern
                if st.button(
                    "📌 Trade aufnehmen",
                    key=f"btn_{sym}",
                    use_container_width=True,
                ):
                    all_trades[current_user][sym] = {
                        "status": "Offen",
                        "entry_price": row["Kurs"],
                        "entry_date": datetime.now().strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                    }
                    save_all_trades(all_trades)
                    st.rerun()
