# =====================================================================
# S&P 500 WEEKLY EMA STACK & MACD TRADING HUB PRO
# =====================================================================
from datetime import datetime
from io import StringIO
import json
import math
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
    """Lädt Trades und Favoriten aus der lokalen JSON-Datei."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_user_data(all_data: dict):
    """Speichert die Trades und Favoriten sicher ab."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)


all_users_data = load_user_data()

# ---------------------------------------------------------------------
# 3. SIDEBAR: PROFIL & RISIKO-MANAGEMENT
# ---------------------------------------------------------------------
st.sidebar.title("👤 Profil & Einstellungen")

existing_users = sorted(list(all_users_data.keys()))
user_options = existing_users + ["➕ Neuer Nutzer..."]
selected_user = st.sidebar.selectbox("Profil auswählen:", user_options)

if selected_user == "➕ Neuer Nutzer...":
    new_user = st.sidebar.text_input(
        "Dein Name:", placeholder="z. B. Alex"
    ).strip()
    if not new_user:
        st.info("👈 Bitte erstelle links ein Profil oder wähle eines aus.")
        st.stop()
    else:
        current_user = new_user
        if current_user not in all_users_data:
            all_users_data[current_user] = {"trades": {}, "favorites": []}
            save_user_data(all_users_data)
            st.rerun()
else:
    current_user = selected_user

# Datenstruktur initialisieren & bereinigen
if current_user not in all_users_data:
    all_users_data[current_user] = {"trades": {}, "favorites": []}
if "trades" not in all_users_data[current_user]:
    all_users_data[current_user]["trades"] = {}
if "favorites" not in all_users_data[current_user]:
    all_users_data[current_user]["favorites"] = []

# Leere Einträge bereinigen
cleaned_trades = {
    str(k).strip(): v
    for k, v in all_users_data[current_user]["trades"].items()
    if k and str(k).strip() != "" and isinstance(v, dict)
}
if cleaned_trades != all_users_data[current_user]["trades"]:
    all_users_data[current_user]["trades"] = cleaned_trades
    save_user_data(all_users_data)

user_trades = all_users_data[current_user]["trades"]
user_favorites = set(all_users_data[current_user]["favorites"])

st.sidebar.success(f"Angemeldet als: **{current_user}**")
st.sidebar.markdown("---")

# Risiko- und Positionsgrößen-Management
st.sidebar.subheader("⚖️ Risiko-Management")
account_currency = st.sidebar.radio("Depotwährung:", ["EUR (€)", "USD ($)"])
account_size = st.sidebar.number_input(
    "Gesamtdepot:", min_value=500.0, value=5000.0, step=500.0
)
risk_pct = st.sidebar.slider(
    "Max. Verlust pro Trade (%):",
    min_value=0.25,
    max_value=3.0,
    value=1.0,
    step=0.25,
    help="Wie viel Prozent des Gesamtdepots du bei Auslösen des Stop-Loss maximal verlierst.",
)
max_allocation_pct = st.sidebar.slider(
    "Max. Depotanteil pro Aktie (%):",
    min_value=5,
    max_value=40,
    value=20,
    step=5,
    help="Verhindert Klumpenrisiko. Z. B. maximal 20% des Depots in eine einzige Aktie.",
)

max_risk_amount = account_size * (risk_pct / 100.0)
max_pos_capital = account_size * (max_allocation_pct / 100.0)

curr_sym = "€" if account_currency == "EUR (€)" else "$"
st.sidebar.caption(
    f"Max. Stop-Loss Verlust: **{curr_sym}{max_risk_amount:,.2f}**\n\n"
    f"Max. Positionsgröße: **{curr_sym}{max_pos_capital:,.2f}**"
)


# ---------------------------------------------------------------------
# 4. HILFSFUNKTIONEN
# ---------------------------------------------------------------------
def get_google_link(ticker: str) -> str:
    query = urllib.parse.quote(f"{ticker} stock price")
    return f"https://www.google.com/search?q={query}"


def get_tradingview_link(ticker: str) -> str:
    clean_ticker = ticker.replace("-", ".")
    return f"https://www.tradingview.com/chart/?symbol={clean_ticker}"


def get_next_50_level(price: float) -> float:
    """Berechnet die nächste psychologische Marke im 50er-Raster über dem Kurs."""
    next_lvl = math.ceil(price / 50.0) * 50.0
    if next_lvl <= price:
        next_lvl += 50.0
    return float(next_lvl)


# ---------------------------------------------------------------------
# 5. DATEN LADEN & STRATEGIE-ENGINE
# ---------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner="Lade & berechne S&P 500 Daten...")
def load_screener_data():
    # 1. Wechselkurs EUR/USD abrufen
    try:
        fx_data = yf.download(
            "EURUSD=X", period="5d", interval="1d", progress=False
        )
        usd_to_eur_rate = 1.0 / float(fx_data["Close"].iloc[-1])
    except Exception:
        usd_to_eur_rate = 0.92

    # 2. S&P 500 Tickerliste abrufen
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    response = requests.get(url, headers=headers)
    tables = pd.read_html(StringIO(response.text), flavor="html5lib")
    sp500_df = tables[0]

    sp500_df["Symbol_Clean"] = (
        sp500_df["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False)
    )

    company_names = dict(zip(sp500_df["Symbol_Clean"], sp500_df["Security"]))
    company_sectors = dict(
        zip(sp500_df["Symbol_Clean"], sp500_df["GICS Sector"])
    )
    symbols = sorted(list(set(sp500_df["Symbol_Clean"].tolist())))

    # 3. Kursdaten laden
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
    high_d = raw["High"].dropna(how="all", axis=1)
    low_d = raw["Low"].dropna(how="all", axis=1)
    vol_d = raw["Volume"].dropna(how="all", axis=1)

    # Weekly Resampling (Freitags-Schlusskurse)
    close_w = close_d.resample("W-FRI").last()
    high_w = high_d.resample("W-FRI").max()
    low_w = low_d.resample("W-FRI").min()
    vol_w = vol_d.resample("W-FRI").sum()

    daily_change_pct = close_d.pct_change().iloc[-1] * 100.0

    # SPY Benchmark Performance (12 Wochen)
    spy_12w_perf = 0.0
    if "SPY" in close_w.columns and len(close_w["SPY"].dropna()) >= 13:
        spy_s = close_w["SPY"].dropna()
        spy_12w_perf = ((spy_s.iloc[-1] - spy_s.iloc[-13]) / spy_s.iloc[-13]) * 100.0

    # Indikatoren berechnen
    ema10 = close_w.ewm(span=10, adjust=False).mean()
    ema21 = close_w.ewm(span=21, adjust=False).mean()

    exp12 = close_w.ewm(span=12, adjust=False).mean()
    exp26 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp12 - exp26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    vol_sma10 = vol_w.rolling(window=10).mean()

    # Relevante Swing Highs berechnen
    high_20w = high_w.rolling(window=20, min_periods=5).max()
    high_ath = high_w.max()  # Maximales Hoch im 3-Jahres-Zeitraum (ATH)

    results = []

    for sym in close_w.columns:
        if sym == "SPY":
            continue

        series_close = close_w[sym].dropna()
        if len(series_close) < 25:
            continue

        c_usd = series_close.iloc[-1]
        l_usd = low_w[sym].dropna().iloc[-1]
        if pd.isna(c_usd) or pd.isna(l_usd):
            continue

        c_prev_usd = series_close.iloc[-2]
        e10_prev = ema10[sym].iloc[-2]
        e21_prev = ema21[sym].iloc[-2]

        e10_usd = ema10[sym].iloc[-1]
        e21_usd = ema21[sym].iloc[-1]

        m_hist = macd_hist[sym].iloc[-1]
        m_hist_prev = macd_hist[sym].iloc[-2]

        # 12-Wochen Relative Stärke
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

        # Bedingungen
        macd_rising = m_hist > m_hist_prev
        trend_bullish = e10_usd > e21_usd
        price_above_ema21 = c_usd >= e21_usd

        # Kerzenkörper-Bestätigungen
        prev_body_above_10ema = c_prev_usd > e10_prev
        curr_body_above_10ema = c_usd > e10_usd

        # Signal-Muster
        crossover_event = (e10_prev <= e21_prev) and (e10_usd > e21_usd)
        retest_ema10_event = (
            trend_bullish
            and (l_usd <= e10_usd * 1.015)
            and not crossover_event
        )
        retest_ema21_event = (
            trend_bullish
            and (l_usd <= e21_usd * 1.015)
            and not crossover_event
        )

        # Crossover steht kurz bevor (EMA 10 nähert sich EMA 21 von unten an)
        near_crossover_event = (
            (e10_usd < e21_usd)
            and (e10_usd / e21_usd >= 0.985)
            and price_above_ema21
            and macd_rising
        )

        status = "NEUTRAL"
        typ = "Kein Setup"
        entry_min_usd = c_usd
        entry_max_usd = c_usd * 1.015

        # 1. Status: BEREIT (Vorwoche hat mit Körper ÜBER 10 EMA geschlossen)
        if prev_body_above_10ema and price_above_ema21 and macd_rising:
            if crossover_event:
                status = "BEREIT"
                typ = "10/21 EMA Crossover (Bestätigt)"
                entry_min_usd = c_usd
                entry_max_usd = c_usd * 1.015
            elif retest_ema10_event or retest_ema21_event:
                status = "BEREIT"
                typ = (
                    "EMA 10 Retest (Bestätigt)"
                    if retest_ema10_event
                    else "EMA 21 Retest (Bestätigt)"
                )
                entry_min_usd = e10_usd if retest_ema10_event else e21_usd
                entry_max_usd = entry_min_usd * 1.015

        # 2. Status: FAST BEREIT (Laufende Kerze steigt über 10 EMA ODER Crossover steht kurz bevor)
        elif near_crossover_event:
            status = "FAST BEREIT"
            typ = "10/21 EMA Crossover steht kurz bevor (<1.5% Abstand)"
            entry_min_usd = c_usd
            entry_max_usd = c_usd * 1.015
        elif (
            curr_body_above_10ema
            and price_above_ema21
            and macd_rising
            and (trend_bullish or crossover_event)
        ):
            status = "FAST BEREIT"
            typ = "Körper steigt in laufender Woche über 10 EMA"
            entry_min_usd = e10_usd
            entry_max_usd = e10_usd * 1.015

        # Stop-Loss (21 EMA)
        sl_usd = e21_usd
        risk_per_share_usd = max(c_usd - sl_usd, c_usd * 0.015)

        # --- TAKE-PROFIT LOGIK (SWING HIGHS & 50er-PSYCHOLOGISCHE MARKEN BEI ATH) ---
        swing_20w = high_20w[sym].iloc[-1]
        ath_val = high_ath[sym]

        # Befindet sich die Aktie bereits an/nahe dem ATH (innerhalb 1.5%)?
        is_at_ath = c_usd >= (ath_val * 0.985)

        if is_at_ath:
            # Am ATH: 50er-Schritte als psychologische Kursziele
            tp1_usd = get_next_50_level(c_usd)
            tp2_usd = get_next_50_level(tp1_usd)
            tp_label = "Psychologische 50er-Marken (am ATH)"
        else:
            # Vor dem ATH: Zuerst bisheriges 20-Wochen-Hoch bzw. ATH als Ziel
            if pd.notna(swing_20w) and swing_20w > c_usd * 1.02:
                tp1_usd = swing_20w
            else:
                tp1_usd = ath_val if ath_val > c_usd * 1.02 else get_next_50_level(c_usd)

            # Zweites Ziel: ATH oder nächster 50er-Schritt
            if ath_val > tp1_usd * 1.02:
                tp2_usd = ath_val
            else:
                tp2_usd = get_next_50_level(tp1_usd)
            tp_label = "Lokale Hochs & ATH"

        sl_dist_pct = ((c_usd - sl_usd) / c_usd) * 100.0
        ema_diff_pct = ((e10_usd - e21_usd) / e21_usd) * 100.0
        dist_ema10_pct = abs(c_usd - e10_usd) / e10_usd * 100.0

        # Health-Status
        if not price_above_ema21:
            health_status = "❌ INVALIDIERT"
            health_color = "red"
        elif c_usd <= e21_usd * 1.015:
            health_status = "⚠️ NAHE 21 EMA"
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
                "RiskPerShare_USD": risk_per_share_usd,
                "EntryZone_Min_USD": round(entry_min_usd, 2),
                "EntryZone_Max_USD": round(entry_max_usd, 2),
                "EntryZone_Min_EUR": round(entry_min_usd * usd_to_eur_rate, 2),
                "EntryZone_Max_EUR": round(entry_max_usd * usd_to_eur_rate, 2),
                "TP1_USD": round(tp1_usd, 2),
                "TP1_EUR": round(tp1_usd * usd_to_eur_rate, 2),
                "TP2_USD": round(tp2_usd, 2),
                "TP2_EUR": round(tp2_usd * usd_to_eur_rate, 2),
                "TP_Label": tp_label,
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
    df_all_stocks,
    close_w,
    ema10_df,
    ema21_df,
    company_names,
    daily_change_pct,
    usd_to_eur_rate,
) = load_screener_data()

st.sidebar.caption(f"Wechselkurs: **1 USD = {usd_to_eur_rate:.4f} EUR**")


# ---------------------------------------------------------------------
# 6. MODULARE KARTEN-DARSTELLUNG
# ---------------------------------------------------------------------
def render_stock_card(row, key_prefix="card"):
    sym = row["Aktie"]
    is_fav = sym in user_favorites

    google_link = get_google_link(sym)
    tv_link = get_tradingview_link(sym)

    d_change = row["DailyChange"]
    change_color = "green" if d_change >= 0 else "red"
    change_sign = "+" if d_change >= 0 else ""

    # Volumen Badge
    if row["Volumen Ratio"] >= 1.0:
        vol_badge = f":green[**{row['Volumen Ratio']}x**]"
    else:
        vol_badge = f":orange[**⚠️ {row['Volumen Ratio']}x**]"

    # Relative Stärke Badge
    rs_color = "green" if row["RS Score"] >= 0 else "red"
    rs_sign = "+" if row["RS Score"] >= 0 else ""
    rs_badge = f":{rs_color}[**⚡ RS: {rs_sign}{row['RS Score']}%**]"

    # Status Tag
    if row["Status"] == "BEREIT":
        status_tag = ":green[🚀 **BEREIT**]"
    elif row["Status"] == "FAST BEREIT":
        status_tag = ":orange[⚠️ **FAST BEREIT**]"
    else:
        status_tag = ":gray[**NEUTRAL**]"

    # Positionsgrößen-Berechnung
    risk_in_usd = (
        max_risk_amount / usd_to_eur_rate
        if account_currency == "EUR (€)"
        else max_risk_amount
    )
    shares_by_risk = int(risk_in_usd / row["RiskPerShare_USD"])

    max_cap_in_usd = (
        max_pos_capital / usd_to_eur_rate
        if account_currency == "EUR (€)"
        else max_pos_capital
    )
    shares_by_allocation = int(max_cap_in_usd / row["Kurs_USD"])

    shares_to_buy = max(min(shares_by_risk, shares_by_allocation), 1)
    pos_vol_usd = shares_to_buy * row["Kurs_USD"]
    pos_vol_eur = pos_vol_usd * usd_to_eur_rate

    with st.container(border=True):
        h_left, h_right = st.columns([3.5, 1])
        with h_left:
            st.markdown(
                f"<span style='color:gray; font-size:12px;'>{row['Name']} • {row['Sektor']}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"### **[{sym}]({google_link})** — {status_tag}")
        with h_right:
            fav_label = "⭐" if is_fav else "✩"
            if st.button(
                fav_label,
                key=f"fav_{key_prefix}_{sym}",
                help="Zu Favoriten hinzufügen / entfernen",
            ):
                if is_fav:
                    all_users_data[current_user]["favorites"].remove(sym)
                else:
                    all_users_data[current_user]["favorites"].append(sym)
                save_user_data(all_users_data)
                st.rerun()

        st.caption(f"Setup: **{row['Typ']}** | {rs_badge}")

        st.markdown(
            f"**Kurs:** `${row['Kurs_USD']}` | `€{row['Kurs_EUR']}`"
            f" (:{change_color}[**{change_sign}{d_change}%**])"
        )

        ema10_col = "green" if row["Kurs_USD"] > row["EMA10_USD"] else "red"
        ema21_col = "green" if row["Kurs_USD"] > row["EMA21_USD"] else "red"

        st.markdown(
            f"**10 EMA:** :{ema10_col}[${row['EMA10_USD']}] | **21 EMA:**"
            f" :{ema21_col}[${row['EMA21_USD']}]"
        )
        st.markdown(
            f"**MACD Hist:** `{row['MACD Hist']}` | **Vol:** {vol_badge}"
        )

        with st.expander("🎯 Trade-Plan, Stop & Kursziele"):
            st.markdown(
                f"🎯 **Einstiegszone:** `${row['EntryZone_Min_USD']} - ${row['EntryZone_Max_USD']}` "
                f"*(€{row['EntryZone_Min_EUR']} - €{row['EntryZone_Max_EUR']})*"
            )
            st.markdown(
                f"🛑 **Stop-Loss (21 EMA):** `${row['StopLoss_USD']}` | `€{row['StopLoss_EUR']}` "
                f"(:red[**-{row['SL Distanz %']}%**])"
            )
            st.markdown(
                f"🏁 **Ziel 1:** `${row['TP1_USD']}` | `€{row['TP1_EUR']}`\n\n"
                f"🚀 **Ziel 2:** `${row['TP2_USD']}` | `€{row['TP2_EUR']}`\n\n"
                f"<span style='color:gray; font-size:11px;'>Logik: {row['TP_Label']}</span>",
                unsafe_allow_html=True,
            )
            st.markdown("---")
            st.markdown(
                f"💼 **Empfohlene Stückzahl:** **{shares_to_buy} Stück**\n\n"
                f"*(Volumen: ~${pos_vol_usd:,.0f} / ~€{pos_vol_eur:,.0f} | max."
                f" {max_allocation_pct}% Depotanteil)*"
            )

        b1, b2 = st.columns(2)
        with b1:
            st.link_button("📊 TradingView", tv_link, use_container_width=True)
        with b2:
            if st.button(
                "📌 Kaufen",
                key=f"buy_{key_prefix}_{sym}",
                use_container_width=True,
            ):
                all_users_data[current_user]["trades"][sym] = {
                    "status": "Offen",
                    "entry_price_usd": row["Kurs_USD"],
                    "entry_price_eur": row["Kurs_EUR"],
                    "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                save_user_data(all_users_data)
                st.rerun()


# ---------------------------------------------------------------------
# 7. METRIKEN: HEADERZEILE (AKTIVE TRADES & TP-STATUS)
# ---------------------------------------------------------------------
st.title(f"📈 S&P 500 Trading Hub — ({current_user})")

total_active = len(user_trades)
at_risk_count = 0
invalidated_count = 0
tp_reached_count = 0

for sym, info in user_trades.items():
    if sym in close_w.columns:
        c_price = close_w[sym].dropna().iloc[-1]
        e21_val = ema21_df[sym].dropna().iloc[-1]

        trade_status_str = str(info.get("status", ""))
        if "50%" in trade_status_str or "90%" in trade_status_str:
            tp_reached_count += 1

        if c_price < e21_val:
            invalidated_count += 1
        elif c_price <= e21_val * 1.015:
            at_risk_count += 1

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric(label="🎯 Aktive Positionen", value=f"{total_active} Trades")
with m2:
    st.metric(
        label="💰 TP Teilgewinn genommen",
        value=f"{tp_reached_count} Positionen",
        delta="Gewinne gesichert" if tp_reached_count > 0 else "Keine",
        delta_color="normal" if tp_reached_count > 0 else "off",
    )
with m3:
    st.metric(
        label="⚠️ Nahe 21 EMA (Gefährdet)",
        value=f"{at_risk_count} Positionen",
        delta="Testet Support" if at_risk_count > 0 else "Alles stabil",
        delta_color="inverse" if at_risk_count > 0 else "off",
    )
with m4:
    st.metric(
        label="❌ Invalidiert (Wochenschluss < 21 EMA)",
        value=f"{invalidated_count} Positionen",
        delta="SL greift!" if invalidated_count > 0 else "Keine",
        delta_color="inverse" if invalidated_count > 0 else "off",
    )

st.markdown("---")

# ---------------------------------------------------------------------
# 8. TABS MIT PAGINIERUNG
# ---------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "🔍 Markt-Setups (Screener)",
        "🎯 Meine Trades",
        "⭐ Favoriten / Watchlist",
        "🌐 Alle Aktien (Marktübersicht)",
    ]
)

ITEMS_PER_PAGE = 24

# =====================================================================
# TAB 1: SCREENER (NUR AKTIVE SETUPS)
# =====================================================================
with tab1:
    screener_df = df_all_stocks[
        df_all_stocks["Status"].isin(["BEREIT", "FAST BEREIT"])
    ]

    f1, f2, f3, f4, f5 = st.columns([2, 1.5, 1.5, 1.2, 1.2])
    with f1:
        search_query = st.text_input(
            "🔍 Suche:", placeholder="z. B. NVDA oder Apple", key="s_tab1"
        ).strip()
    with f2:
        all_sectors = sorted(screener_df["Sektor"].unique().tolist())
        sel_sectors = st.multiselect(
            "🏢 Sektor:",
            options=all_sectors,
            default=[],
            placeholder="Alle Sektoren",
            key="sec_tab1",
        )
    with f3:
        sort_by = st.selectbox(
            "↕️ Sortieren nach:",
            options=[
                "🎯 EMA 10 Nähe (Standard)",
                "⚡ Höchste Relative Stärke (RS)",
                "📊 Höchstes Volumen",
                "🚀 Beste Tagesperformance (%)",
            ],
            key="sort_tab1",
        )
    with f4:
        show_bereit = st.checkbox(
            "🚀 Nur BEREIT", value=True, key="chk_bereit"
        )
        show_fast_bereit = st.checkbox(
            "⚠️ FAST BEREIT", value=True, key="chk_fast"
        )
    with f5:
        min_vol = st.checkbox(
            "📊 Starkes Vol. (≥1.0x)", value=False, key="chk_vol"
        )
        show_held = st.checkbox(
            "Bereits gekaufte einblenden", value=False, key="chk_held"
        )

    f_df = screener_df.copy()

    if not show_held:
        f_df = f_df[~f_df["Aktie"].isin(user_trades.keys())]

    if search_query:
        q = search_query.lower()
        f_df = f_df[
            f_df["Aktie"].str.lower().str.contains(q, na=False)
            | f_df["Name"].str.lower().str.contains(q, na=False)
        ]

    if sel_sectors:
        f_df = f_df[f_df["Sektor"].isin(sel_sectors)]

    selected_statuses = []
    if show_bereit:
        selected_statuses.append("BEREIT")
    if show_fast_bereit:
        selected_statuses.append("FAST BEREIT")
    f_df = f_df[f_df["Status"].isin(selected_statuses)]

    if min_vol:
        f_df = f_df[f_df["Volumen Ratio"] >= 1.0]

    if sort_by == "⚡ Höchste Relative Stärke (RS)":
        f_df = f_df.sort_values(by="RS Score", ascending=False)
    elif sort_by == "📊 Höchstes Volumen":
        f_df = f_df.sort_values(by="Volumen Ratio", ascending=False)
    elif sort_by == "🚀 Beste Tagesperformance (%)":
        f_df = f_df.sort_values(by="DailyChange", ascending=False)
    else:
        f_df = f_df.sort_values(by="Dist EMA10 %", ascending=True)

    st.caption(f"Gefundene Setups: **{len(f_df)}**")

    if f_df.empty:
        st.info(
            "Aktuell keine Setups mit Kerzenkörper-Bestätigung über der 10 EMA."
            " Schau in **Tab 4 (Alle Aktien)**."
        )
    else:
        total_pages = max(1, math.ceil(len(f_df) / ITEMS_PER_PAGE))
        current_page = (
            st.number_input(
                "Seite:",
                min_value=1,
                max_value=total_pages,
                value=1,
                key="p_tab1",
            )
            if total_pages > 1
            else 1
        )

        start_idx = (current_page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = f_df.iloc[start_idx:end_idx]

        cols = st.columns(4)
        for idx, (_, row) in enumerate(page_items.iterrows()):
            with cols[idx % 4]:
                render_stock_card(row, key_prefix="screener")

# =====================================================================
# TAB 2: MEINE AKTIVEN TRADES (OHNE P&L-ANZEIGE)
# =====================================================================
with tab2:
    if len(user_trades) == 0:
        st.info("Noch keine aktiven Trades vorhanden.")
    else:
        for sym, info in list(user_trades.items()):
            if sym not in close_w.columns:
                continue

            series_close = close_w[sym].dropna()
            curr_usd = series_close.iloc[-1]
            curr_eur = curr_usd * usd_to_eur_rate

            curr_e10_usd = ema10_df[sym].dropna().iloc[-1]
            curr_e21_usd = ema21_df[sym].dropna().iloc[-1]
            curr_e21_eur = curr_e21_usd * usd_to_eur_rate

            entry_usd = info.get("entry_price_usd", curr_usd)
            entry_eur = info.get("entry_price_eur", curr_eur)

            # Wochenschluss-Invalidierung
            if curr_usd < curr_e21_usd:
                health = "❌ INVALIDIERT (Wochenschluss unter 21 EMA!)"
                health_color = "red"
            elif curr_usd <= curr_e21_usd * 1.015:
                health = "⚠️ FAST INVALIDIERT (Testet 21 EMA)"
                health_color = "orange"
            else:
                health = "✅ IM TREND (Über 21 EMA)"
                health_color = "green"

            trade_status = info.get("status", "Offen")
            if "50%" in trade_status:
                status_display = ":green[**💰 50% TP Erreicht & Gesichert**]"
            elif "90%" in trade_status:
                status_display = (
                    ":green[**🚀 90% TP Erreicht (Runner aktiv)**]"
                )
            else:
                status_display = f"**{trade_status}**"

            google_link = get_google_link(sym)
            tv_link = get_tradingview_link(sym)

            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([1.5, 2.5, 2.5, 2, 1])

                with c1:
                    st.markdown(
                        f"<span style='color:gray;"
                        f" font-size:12px;'>{company_names.get(sym, sym)}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"### **[{sym}]({google_link})**")
                    st.caption(f"Einstieg: {info.get('entry_date', '-')}")
                    st.link_button("📊 Chart", tv_link)

                with c2:
                    # P&L Prozentanzeige entfernt
                    st.markdown(
                        f"Status: {status_display}\n\n"
                        f"**Einstiegskurs:** `${entry_usd}` | `€{entry_eur}`\n\n"
                        f"**Aktueller Kurs:** `${round(curr_usd, 2)}` |"
                        f" `€{round(curr_eur, 2)}`"
                    )

                with c3:
                    st.markdown(
                        f"Trend: :{health_color}[**{health}**]\n\n"
                        f"10 EMA: `${round(curr_e10_usd, 2)}` | Trailing Stop"
                        f" (21 EMA): `${round(curr_e21_usd, 2)}` /"
                        f" `€{round(curr_e21_eur, 2)}`"
                    )

                with c4:
                    if st.button("💰 50% TP", key=f"tp50_{sym}"):
                        all_users_data[current_user]["trades"][sym]["status"] = (
                            "💰 50% TP Erreicht"
                        )
                        save_user_data(all_users_data)
                        st.rerun()
                    if st.button("🚀 90% TP", key=f"tp90_{sym}"):
                        all_users_data[current_user]["trades"][sym]["status"] = (
                            "🚀 90% TP Erreicht"
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
            "Du hast noch keine Favoriten markiert. Klicke im Screener auf das"
            " '⭐'-Symbol einer Aktie!"
        )
    else:
        fav_df = df_all_stocks[df_all_stocks["Aktie"].isin(user_favorites)]
        st.caption(f"Gespeicherte Favoriten: **{len(fav_df)}**")

        cols = st.columns(4)
        for idx, (_, row) in enumerate(fav_df.iterrows()):
            with cols[idx % 4]:
                render_stock_card(row, key_prefix="fav")

# =====================================================================
# TAB 4: ALLE AKTIEN (SUCHE INKL. APPLE, TESLA, NVIDIA)
# =====================================================================
with tab4:
    st.caption(
        "Hier findest du alle 500 S&P-Aktien (auch AAPL, NVDA etc., selbst"
        " wenn sie neutral sind)."
    )

    af1, af2 = st.columns([2, 2])
    with af1:
        search_all = st.text_input(
            "🔍 Suche nach Ticker oder Name:",
            placeholder="z. B. AAPL, Apple, NVDA, Tesla...",
            key="s_tab4",
        ).strip()
    with af2:
        all_sec_list = sorted(df_all_stocks["Sektor"].unique().tolist())
        sel_all_sec = st.multiselect(
            "🏢 Sektor:",
            options=all_sec_list,
            default=[],
            placeholder="Alle Sektoren",
            key="sec_tab4",
        )

    all_filtered_df = df_all_stocks.copy()

    if search_all:
        q = search_all.lower()
        all_filtered_df = all_filtered_df[
            all_filtered_df["Aktie"].str.lower().str.contains(q, na=False)
            | all_filtered_df["Name"].str.lower().str.contains(q, na=False)
        ]

    if sel_all_sec:
        all_filtered_df = all_filtered_df[
            all_filtered_df["Sektor"].isin(sel_all_sec)
        ]

    st.caption(f"Angezeigte Aktien: **{len(all_filtered_df)}**")

    total_pages_all = max(1, math.ceil(len(all_filtered_df) / ITEMS_PER_PAGE))
    current_page_all = (
        st.number_input(
            "Seite:",
            min_value=1,
            max_value=total_pages_all,
            value=1,
            key="p_tab4",
        )
        if total_pages_all > 1
        else 1
    )

    start_idx = (current_page_all - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items_all = all_filtered_df.iloc[start_idx:end_idx]

    cols = st.columns(4)
    for idx, (_, row) in enumerate(page_items_all.iterrows()):
        with cols[idx % 4]:
            render_stock_card(row, key_prefix="all")
