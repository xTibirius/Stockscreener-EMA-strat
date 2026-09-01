# =====================================================================
# S&P 500 WEEKLY EMA & MACD TRADING HUB PRO
# Features: Dual Currency (EUR/USD), CRV-Rechner (2R/3R), Sektor-Filter,
# Relative Stärke (RS-Score), Favoriten & Live-Portfoliotracking
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
# 1. SEITEN-KONFIGURATION
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="S&P 500 Screener Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------
# 2. PERSISTENTE DATENSPEICHERUNG (TRADES & FAVORITEN)
# ---------------------------------------------------------------------
DATA_FILE = "trades.json"


def load_user_data() -> dict:
    """Lädt Trades und Favoriten aller Nutzer aus der JSON-Datei."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_user_data(all_data: dict):
    """Speichert die Nutzerdaten sicher in der JSON-Datei."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)


all_users_data = load_user_data()

# ---------------------------------------------------------------------
# 3. SIDEBAR: PROFIL, RISIKOMANAGEMENT & WECHSELKURS
# ---------------------------------------------------------------------
st.sidebar.title("👤 Nutzer-Profil")

existing_users = sorted(list(all_users_data.keys()))
user_options = existing_users + ["➕ Neuer Nutzer..."]
selected_user = st.sidebar.selectbox("Profil auswählen:", user_options)

if selected_user == "➕ Neuer Nutzer...":
    new_user = st.sidebar.text_input(
        "Dein Name:", placeholder="z. B. Alex"
    ).strip()
    if not new_user:
        st.info("👈 Bitte Profil auswählen oder Namen eingeben.")
        st.stop()
    else:
        current_user = new_user
        if current_user not in all_users_data:
            all_users_data[current_user] = {"trades": {}, "favorites": []}
            save_user_data(all_users_data)
            st.rerun()
else:
    current_user = selected_user

# Datenstruktur initialisieren
if current_user not in all_users_data:
    all_users_data[current_user] = {"trades": {}, "favorites": []}
if "trades" not in all_users_data[current_user]:
    all_users_data[current_user]["trades"] = {}
if "favorites" not in all_users_data[current_user]:
    all_users_data[current_user]["favorites"] = []

user_trades = all_users_data[current_user]["trades"]
user_favorites = set(all_users_data[current_user]["favorites"])

st.sidebar.success(f"Angemeldet als: **{current_user}**")
st.sidebar.markdown("---")

# Risikorechner
st.sidebar.subheader("⚖️ Positionsgrößen-Rechner")
account_currency = st.sidebar.radio("Depotwährung:", ["EUR (€)", "USD ($)"])
account_size = st.sidebar.number_input(
    "Gesamtdepot:", min_value=500.0, value=10000.0, step=500.0
)
risk_pct = st.sidebar.slider(
    "Risiko pro Trade (%):",
    min_value=0.25,
    max_value=3.0,
    value=1.0,
    step=0.25,
)
max_risk_amount = account_size * (risk_pct / 100.0)
curr_symbol = "€" if account_currency == "EUR (€)" else "$"
st.sidebar.caption(
    f"Max. Verlust bei SL: **{curr_symbol}{max_risk_amount:,.2f}** ({risk_pct}%"
    " vom Depot)"
)


# ---------------------------------------------------------------------
# 4. HILFSFUNKTIONEN: LINKS
# ---------------------------------------------------------------------
def get_google_link(ticker: str) -> str:
    query = urllib.parse.quote(f"{ticker} stock price")
    return f"https://www.google.com/search?q={query}"


def get_tradingview_link(ticker: str) -> str:
    clean_ticker = ticker.replace("-", ".")
    return f"https://www.tradingview.com/chart/?symbol={clean_ticker}"


# ---------------------------------------------------------------------
# 5. DATEN LADEN & STRATEGIE-ENGINE
# ---------------------------------------------------------------------
@st.cache_data(ttl=900)
def load_screener_data():
    # 1. EUR/USD Wechselkurs abrufen
    try:
        fx_data = yf.download(
            "EURUSD=X", period="5d", interval="1d", progress=False
        )
        usd_to_eur_rate = 1.0 / float(fx_data["Close"].iloc[-1])
    except Exception:
        usd_to_eur_rate = 0.92

    # 2. S&P 500 Liste mit Sektoren von Wikipedia laden
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
    company_sectors = dict(
        zip(sp500_df["Symbol_Clean"], sp500_df["GICS Sector"])
    )
    symbols = sp500_df["Symbol_Clean"].tolist()

    # 3. Kursdaten laden (inkl. SPY als Benchmark für Relative Stärke)
    download_symbols = symbols + ["SPY"]
    raw = yf.download(
        download_symbols,
        period="3y",
        interval="1d",
        group_by="column",
        auto_adjust=True,
        progress=False,
    )

    close_d = raw["Close"].dropna(how="all", axis=1)
    low_d = raw["Low"].dropna(how="all", axis=1)
    vol_d = raw["Volume"].dropna(how="all", axis=1)

    # Weekly Resampling (Freitags-Schlusskurse)
    close_w = close_d.resample("W-FRI").last()
    low_w = low_d.resample("W-FRI").min()
    vol_w = vol_d.resample("W-FRI").sum()

    daily_change_pct = close_d.pct_change().iloc[-1] * 100.0

    # SPY 12-Wochen-Performance (Benchmark)
    spy_12w_perf = 0.0
    if "SPY" in close_w.columns and len(close_w["SPY"].dropna()) >= 13:
        spy_series = close_w["SPY"].dropna()
        spy_12w_perf = (
            (spy_series.iloc[-1] - spy_series.iloc[-13]) / spy_series.iloc[-13]
        ) * 100.0

    # 4. Indikatoren berechnen
    ema10 = close_w.ewm(span=10, adjust=False).mean()
    ema21 = close_w.ewm(span=21, adjust=False).mean()

    exp12 = close_w.ewm(span=12, adjust=False).mean()
    exp26 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp12 - exp26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    vol_sma10 = vol_w.rolling(window=10).mean()

    results = []

    for sym in close_w.columns:
        if sym == "SPY":
            continue

        series_close = close_w[sym].dropna()
        if len(series_close) < 30:
            continue

        c_usd = series_close.iloc[-1]
        l_usd = low_w[sym].dropna().iloc[-1]
        if pd.isna(c_usd) or pd.isna(l_usd):
            continue

        e10_usd = ema10[sym].iloc[-1]
        e21_usd = ema21[sym].iloc[-1]
        e10_prev = ema10[sym].iloc[-2]
        e21_prev = ema21[sym].iloc[-2]

        m_hist = macd_hist[sym].iloc[-1]
        m_hist_prev = macd_hist[sym].iloc[-2]

        # 12-Wochen Relative Stärke berechnen
        stock_12w_perf = 0.0
        if len(series_close) >= 13:
            stock_12w_perf = (
                (series_close.iloc[-1] - series_close.iloc[-13])
                / series_close.iloc[-13]
            ) * 100.0
        rs_score = round(stock_12w_perf - spy_12w_perf, 2)

        # Volumen-Verhältnis
        curr_vol = vol_w[sym].iloc[-1]
        avg_vol = vol_sma10[sym].iloc[-1]
        vol_ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # Signale
        macd_rising = m_hist > m_hist_prev
        crossover_now = (e10_prev <= e21_prev) and (e10_usd > e21_usd)
        trend_bullish = e10_usd > e21_usd

        # Retest-Logik
        retest_ema10 = (
            trend_bullish
            and (l_usd <= e10_usd * 1.015)
            and (c_usd >= e21_usd)
            and not crossover_now
        )
        retest_ema21 = (
            trend_bullish
            and (l_usd <= e21_usd * 1.015)
            and (c_usd >= e21_usd * 0.985)
            and not crossover_now
        )

        near_crossover = (
            (e10_usd < e21_usd) and (e10_usd / e21_usd > 0.985) and macd_rising
        )
        near_retest = (
            trend_bullish
            and (l_usd <= e10_usd * 1.03)
            and (l_usd > e10_usd * 1.015)
            and macd_rising
        )

        status, typ = None, None
        entry_min_usd, entry_max_usd = 0.0, 0.0

        if crossover_now and macd_rising:
            status = "BEREIT"
            typ = "10/21 EMA Crossover"
            entry_min_usd = c_usd
            entry_max_usd = c_usd * 1.015
        elif (retest_ema10 or retest_ema21) and macd_rising:
            status = "BEREIT"
            if retest_ema10:
                typ = "EMA 10 Retest"
                entry_min_usd = e10_usd
                entry_max_usd = e10_usd * 1.015
            else:
                typ = "EMA 21 Retest"
                entry_min_usd = e21_usd
                entry_max_usd = e21_usd * 1.015
        elif near_retest:
            status = "FAST BEREIT"
            typ = "Retest nähert sich (<3% zur EMA 10)"
            entry_min_usd = e10_usd
            entry_max_usd = e10_usd * 1.015
        elif near_crossover:
            status = "FAST BEREIT"
            typ = "Crossover steht kurz bevor"
            entry_min_usd = c_usd
            entry_max_usd = c_usd * 1.015
        else:
            continue

        # Stop-Loss & Kursziele (CRV 1:2 und 1:3)
        sl_usd = e21_usd
        risk_per_share_usd = max(c_usd - sl_usd, c_usd * 0.02)
        tp1_usd = c_usd + (2.0 * risk_per_share_usd)
        tp2_usd = c_usd + (3.0 * risk_per_share_usd)

        sl_dist_pct = ((c_usd - sl_usd) / c_usd) * 100.0
        ema_diff_pct = ((e10_usd - e21_usd) / e21_usd) * 100.0
        dist_ema10_pct = abs(c_usd - e10_usd) / e10_usd * 100.0

        # Health-Status
        if c_usd < e21_usd:
            health_status = "❌ INVALIDIERT"
            health_color = "red"
        elif c_usd <= e21_usd * 1.015:
            health_status = "⚠️ NAHE STOP-LOSS"
            health_color = "orange"
        else:
            health_status = "✅ IN ORDNUNG"
            health_color = "green"

        results.append(
            {
                "Aktie": sym,
                "Name": company_names.get(sym, sym),
                "Sektor": company_sectors.get(sym, "Sonstige"),
                "Status": status,
                "Typ": typ,
                "Kurs_USD": round(c_usd, 2),
                "Kurs_EUR": round(c_usd * usd_to_eur_rate, 2),
                "DailyChange": round(daily_change_pct.get(sym, 0.0), 2),
                "EMA10_USD": round(e10_usd, 2),
                "EMA10_EUR": round(e10_usd * usd_to_eur_rate, 2),
                "EMA21_USD": round(e21_usd, 2),
                "EMA21_EUR": round(e21_usd * usd_to_eur_rate, 2),
                "StopLoss_USD": round(sl_usd, 2),
                "StopLoss_EUR": round(sl_usd * usd_to_eur_rate, 2),
                "EntryZone_Min_USD": round(entry_min_usd, 2),
                "EntryZone_Max_USD": round(entry_max_usd, 2),
                "EntryZone_Min_EUR": round(entry_min_usd * usd_to_eur_rate, 2),
                "EntryZone_Max_EUR": round(entry_max_usd * usd_to_eur_rate, 2),
                "TP1_USD": round(tp1_usd, 2),
                "TP1_EUR": round(tp1_usd * usd_to_eur_rate, 2),
                "TP2_USD": round(tp2_usd, 2),
                "TP2_EUR": round(tp2_usd * usd_to_eur_rate, 2),
                "SL Distanz %": round(sl_dist_pct, 2),
                "EMA Diff %": round(ema_diff_pct, 2),
                "Dist EMA10 %": dist_ema10_pct,
                "RS Score": rs_score,
                "MACD Hist": round(m_hist, 3),
                "Volumen Ratio": vol_ratio,
                "Health Status": health_status,
                "Health Color": health_color,
            }
        )

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by="Dist EMA10 %", ascending=True)

    return (
        df,
        close_w,
        ema10,
        ema21,
        company_names,
        daily_change_pct,
        usd_to_eur_rate,
    )


# Daten abrufen
(
    df_setups,
    close_w,
    ema10_df,
    ema21_df,
    company_names,
    daily_change_pct,
    usd_to_eur_rate,
) = load_screener_data()

st.sidebar.caption(
    f"Aktueller Wechselkurs: **1 USD = {usd_to_eur_rate:.4f} EUR**"
)

# ---------------------------------------------------------------------
# 6. HAUPTBEREICH: STRUKTURIERTE TABS
# ---------------------------------------------------------------------
st.title(f"📈 S&P 500 Trading Hub — ({current_user})")

tab1, tab2, tab3 = st.tabs(
    ["🔍 Markt-Setups (Screener)", "🎯 Meine Trades", "⭐ Favoriten / Watchlist"]
)

# =====================================================================
# TAB 1: SCREENER & SETUPS
# =====================================================================
with tab1:
    if df_setups.empty:
        st.info("Aktuell keine aktiven Setups gefunden.")
    else:
        # Filter-Leiste
        f_col1, f_col2, f_col3, f_col4 = st.columns([2, 1.5, 1.2, 1.2])

        with f_col1:
            search_query = st.text_input(
                "🔍 Suche nach Ticker oder Firmenname:",
                placeholder="z. B. NVDA oder Apple",
            ).strip()

        all_sectors = sorted(df_setups["Sektor"].unique().tolist())
        with f_col2:
            selected_sectors = st.multiselect(
                "🏢 Sektor filtern:",
                options=all_sectors,
                default=[],
                placeholder="Alle Sektoren",
            )

        with f_col3:
            show_only_favs = st.checkbox("⭐ Nur Favoriten", value=False)
            show_bereit = st.checkbox("🚀 Nur BEREIT", value=True)
            show_fast_bereit = st.checkbox("⚠️ FAST BEREIT", value=True)

        with f_col4:
            min_vol_filter = st.checkbox("📊 Starkes Volumen (≥1.0x)", value=False)
            only_outperformers = st.checkbox(
                "⚡ Nur Outperformer (RS > 0)", value=False
            )

        # Filter anwenden
        filtered_df = df_setups.copy()

        if search_query:
            q = search_query.lower()
            filtered_df = filtered_df[
                filtered_df["Aktie"].str.lower().str.contains(q, na=False)
                | filtered_df["Name"].str.lower().str.contains(q, na=False)
            ]

        if selected_sectors:
            filtered_df = filtered_df[
                filtered_df["Sektor"].isin(selected_sectors)
            ]

        if show_only_favs:
            filtered_df = filtered_df[
                filtered_df["Aktie"].isin(user_favorites)
            ]

        selected_statuses = []
        if show_bereit:
            selected_statuses.append("BEREIT")
        if show_fast_bereit:
            selected_statuses.append("FAST BEREIT")
        filtered_df = filtered_df[filtered_df["Status"].isin(selected_statuses)]

        if min_vol_filter:
            filtered_df = filtered_df[filtered_df["Volumen Ratio"] >= 1.0]

        if only_outperformers:
            filtered_df = filtered_df[filtered_df["RS Score"] > 0]

        st.caption(f"Gefundene Setups: **{len(filtered_df)}**")

        # 3-Spalten-Layout
        cols = st.columns(3)

        for idx, (_, row) in enumerate(filtered_df.iterrows()):
            col = cols[idx % 3]
            sym = row["Aktie"]
            is_fav = sym in user_favorites

            google_link = get_google_link(sym)
            tv_link = get_tradingview_link(sym)

            d_change = row["DailyChange"]
            change_color = "green" if d_change >= 0 else "red"
            change_sign = "+" if d_change >= 0 else ""

            # Farbliche Kennzeichnung des Volumens
            if row["Volumen Ratio"] >= 1.0:
                vol_badge = f":green[**{row['Volumen Ratio']}x** (Stark)]"
            else:
                vol_badge = f":orange[**⚠️ {row['Volumen Ratio']}x** (Niedrig)]"

            # Relative Stärke Badge
            rs_color = "green" if row["RS Score"] >= 0 else "red"
            rs_sign = "+" if row["RS Score"] >= 0 else ""
            rs_badge = f":{rs_color}[**⚡ RS: {rs_sign}{row['RS Score']}% vs SPY**]"

            status_badge = (
                ":green[🚀 **BEREIT**]"
                if row["Status"] == "BEREIT"
                else ":orange[⚠️ **FAST BEREIT**]"
            )

            # Positionsberechnung
            risk_per_share_usd = max(
                row["Kurs_USD"] - row["StopLoss_USD"], 0.10
            )
            shares_to_buy = int(
                (max_risk_amount / usd_to_eur_rate) / risk_per_share_usd
                if account_currency == "EUR (€)"
                else max_risk_amount / risk_per_share_usd
            )
            pos_vol_usd = shares_to_buy * row["Kurs_USD"]
            pos_vol_eur = pos_vol_usd * usd_to_eur_rate

            with col:
                with st.container(border=True):
                    # Header
                    head_left, head_right = st.columns([3.5, 1])
                    with head_left:
                        st.markdown(
                            f"<span style='color:gray; font-size:12px;'>{row['Name']} • {row['Sektor']}</span>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"### **[{sym}]({google_link})** — {status_badge}"
                        )
                    with head_right:
                        fav_label = "⭐" if is_fav else "✩"
                        if st.button(
                            fav_label,
                            key=f"fav_{sym}",
                            help="Zu Favoriten hinzufügen / entfernen",
                        ):
                            if is_fav:
                                all_users_data[current_user]["favorites"].remove(
                                    sym
                                )
                            else:
                                all_users_data[current_user]["favorites"].append(
                                    sym
                                )
                            save_user_data(all_users_data)
                            st.rerun()

                    st.caption(f"Setup: **{row['Typ']}** | {rs_badge}")

                    # Kursanzeige
                    st.markdown(
                        f"**Kurs:** `${row['Kurs_USD']}` | `€{row['Kurs_EUR']}`"
                        f" (:{change_color}[**{change_sign}{d_change}%**])"
                    )

                    # EMAs
                    ema10_color = (
                        "green" if row["Kurs_USD"] > row["EMA10_USD"] else "red"
                    )
                    ema21_color = (
                        "green" if row["Kurs_USD"] > row["EMA21_USD"] else "red"
                    )
                    st.markdown(
                        f"**10 EMA:** :{ema10_color}[${row['EMA10_USD']}] | **21"
                        f" EMA:** :{ema21_color}[${row['EMA21_USD']}]"
                    )
                    st.markdown(
                        f"**MACD Hist:** `{row['MACD Hist']}` | **Volumen:**"
                        f" {vol_badge}"
                    )

                    st.markdown("---")

                    # Einstiegszone, Stop-Loss & Kursziele
                    st.markdown(
                        f"🎯 **Einstiegszone:** `${row['EntryZone_Min_USD']} - ${row['EntryZone_Max_USD']}` "
                        f"*(€{row['EntryZone_Min_EUR']} - €{row['EntryZone_Max_EUR']})*"
                    )
                    st.markdown(
                        f"🛑 **Stop-Loss (21 EMA):** `${row['StopLoss_USD']}` | `€{row['StopLoss_EUR']}` "
                        f"(:red[**-{row['SL Distanz %']}%**])"
                    )
                    st.markdown(
                        f"🏁 **Ziel 1 (2R / CRV 1:2):** `${row['TP1_USD']}` | `€{row['TP1_EUR']}`\n\n"
                        f"🚀 **Ziel 2 (3R / CRV 1:3):** `${row['TP2_USD']}` | `€{row['TP2_EUR']}`"
                    )

                    st.markdown(
                        f"💼 **Empfohlene Stückzahl:** **{shares_to_buy} Stück** "
                        f"(*~${pos_vol_usd:,.0f} / ~€{pos_vol_eur:,.0f}*)"
                    )

                    # Buttons
                    b1, b2 = st.columns(2)
                    with b1:
                        st.link_button(
                            "📊 TradingView", tv_link, use_container_width=True
                        )
                    with b2:
                        if st.button(
                            "📌 Kaufen",
                            key=f"buy_{sym}",
                            use_container_width=True,
                        ):
                            all_users_data[current_user]["trades"][sym] = {
                                "status": "Offen",
                                "entry_price_usd": row["Kurs_USD"],
                                "entry_price_eur": row["Kurs_EUR"],
                                "entry_date": datetime.now().strftime(
                                    "%Y-%m-%d %H:%M"
                                ),
                            }
                            save_user_data(all_users_data)
                            st.rerun()

# =====================================================================
# TAB 2: AKTIVE TRADES
# =====================================================================
with tab2:
    if len(user_trades) == 0:
        st.info("Noch keine aktiven Trades vorhanden.")
    else:
        for sym, info in list(user_trades.items()):
            if sym not in close_w.columns:
                continue

            curr_usd = close_w[sym].dropna().iloc[-1]
            curr_eur = curr_usd * usd_to_eur_rate
            curr_e21_usd = ema21_df[sym].dropna().iloc[-1]
            curr_e21_eur = curr_e21_usd * usd_to_eur_rate

            entry_usd = info.get("entry_price_usd", curr_usd)
            entry_eur = info.get("entry_price_eur", curr_eur)
            pnl_pct = round(((curr_usd - entry_usd) / entry_usd) * 100, 2)
            pnl_color = "green" if pnl_pct >= 0 else "red"
            pnl_sign = "+" if pnl_pct >= 0 else ""

            if curr_usd < curr_e21_usd:
                health = "❌ INVALIDIERT (SL Greift!)"
                health_color = "red"
            elif curr_usd <= curr_e21_usd * 1.015:
                health = "⚠️ FAST INVALIDIERT (Nahe 21 EMA)"
                health_color = "orange"
            else:
                health = "✅ IN ORDNUNG"
                health_color = "green"

            google_link = get_google_link(sym)
            tv_link = get_tradingview_link(sym)

            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([1.5, 2.5, 2.5, 2, 1])

                with c1:
                    st.markdown(
                        f"<span style='color:gray; font-size:12px;'>{company_names.get(sym, sym)}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"### **[{sym}]({google_link})**")
                    st.caption(f"Entry: {info.get('entry_date', '-')}")
                    st.link_button("📊 Chart", tv_link)

                with c2:
                    st.markdown(
                        f"**P&L:** :{pnl_color}[**{pnl_sign}{pnl_pct}%**]\n\n"
                        f"Entry: `${entry_usd}` / `€{entry_eur}`\n\n"
                        f"Aktuell: `${round(curr_usd, 2)}` / `€{round(curr_eur, 2)}`"
                    )

                with c3:
                    st.markdown(
                        f"Status: :{health_color}[**{health}**]\n\n"
                        f"Trailing Stop (21 EMA): `${round(curr_e21_usd, 2)}` /"
                        f" `€{round(curr_e21_eur, 2)}`"
                    )

                with c4:
                    if st.button("💰 50% TP", key=f"tp50_{sym}"):
                        all_users_data[current_user]["trades"][sym]["status"] = (
                            "💰 50% realisiert"
                        )
                        save_user_data(all_users_data)
                        st.rerun()
                    if st.button("🚀 90% TP", key=f"tp90_{sym}"):
                        all_users_data[current_user]["trades"][sym]["status"] = (
                            "🚀 90% realisiert"
                        )
                        save_user_data(all_users_data)
                        st.rerun()

                with c5:
                    if st.button(
                        "🗑️ Close",
                        key=f"close_{sym}",
                        use_container_width=True,
                    ):
                        del all_users_data[current_user]["trades"][sym]
                        save_user_data(all_users_data)
                        st.rerun()

# =====================================================================
# TAB 3: FAVORITEN / WATCHLIST
# =====================================================================
with tab3:
    if len(user_favorites) == 0:
        st.info(
            "Noch keine Favoriten vorhanden. Klicke im Screener auf das"
            " '⭐'-Symbol einer Aktie!"
        )
    else:
        fav_df = df_setups[df_setups["Aktie"].isin(user_favorites)]
        if fav_df.empty:
            st.write(
                "Keine deiner favorisierten Aktien hat aktuell ein offenes"
                " Signal."
            )
        else:
            st.dataframe(
                fav_df[
                    [
                        "Aktie",
                        "Name",
                        "Sektor",
                        "Status",
                        "Typ",
                        "Kurs_USD",
                        "Kurs_EUR",
                        "StopLoss_USD",
                        "TP1_USD",
                        "TP2_USD",
                        "RS Score",
                        "Volumen Ratio",
                    ]
                ],
                use_container_width=True,
            )
