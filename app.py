# =====================================================================
# S&P 500 & NASDAQ WEEKLY EMA STACK & MACD TRADING HUB PRO (OPTIMIERT)
# =====================================================================
# Features:
# - Robuste EUR/USD Wechselkurs-Ermittlung & transparente Umrechnung
# - Theme-freundliches Layout (Lesbar in Light- und Dark-Mode)
# - Empfohlene Einstiegszone prominent oben auf jeder Karte
# - Diskrete Tagesperformance-Anzeige oben rechts
# - SPY Markt-Regime-Filter & 12-Wochen RS-Score
# - Break-Even Stop nach TP 1 & interaktive Toggle-Buttons in Tab 2
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
    page_title="Weekly Trading Hub Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------
# 2. PERSISTENTE DATENSPEICHERUNG (TRADES & FAVORITEN)
# ---------------------------------------------------------------------
DATA_FILE = "trades.json"


def load_user_data() -> dict:
    """Lädt gespeicherte Trades und Favoriten aus der lokalen JSON-Datei."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_user_data(all_data: dict):
    """Speichert Nutzerdaten sicher in der JSON-Datei ab."""
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

# Datenstruktur absichern
if current_user not in all_users_data:
    all_users_data[current_user] = {"trades": {}, "favorites": []}
if "trades" not in all_users_data[current_user]:
    all_users_data[current_user]["trades"] = {}
if "favorites" not in all_users_data[current_user]:
    all_users_data[current_user]["favorites"] = []

# Bereinigung leere Keys
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

# Risiko-Parameter
st.sidebar.subheader("⚖️ Risiko-Management")
account_currency = st.sidebar.radio("Depotwährung:", ["EUR (€)", "USD ($)"])
account_size = st.sidebar.number_input(
    "Gesamtdepot:", min_value=500.0, value=10000.0, step=500.0
)
risk_pct = st.sidebar.slider(
    "Max. Verlust pro Trade (%):",
    min_value=0.5,
    max_value=3.0,
    value=2.0,
    step=0.25,
    help="Optimal laut Backtest: 2.0% des Depots.",
)
max_allocation_pct = st.sidebar.slider(
    "Max. Depotanteil pro Aktie (%):",
    min_value=5,
    max_value=30,
    value=20,
    step=5,
    help="Schutz vor Klumpenrisiko. Max. 20% in einen Trade.",
)

max_risk_amount = account_size * (risk_pct / 100.0)
max_pos_capital = account_size * (max_allocation_pct / 100.0)

curr_sym = "€" if account_currency == "EUR (€)" else "$"
st.sidebar.caption(
    f"Max. Notfall-SL Verlust: **{curr_sym}{max_risk_amount:,.2f}**\n\n"
    f"Max. Positionsgröße: **{curr_sym}{max_pos_capital:,.2f}**"
)

st.sidebar.markdown("---")
if st.sidebar.button(
    "🔄 Daten manuell aktualisieren", use_container_width=True
):
    st.cache_data.clear()
    st.rerun()


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
    """Rundet auf die nächste psychologische 50er-Marke über dem Kurs auf."""
    next_lvl = math.ceil(price / 50.0) * 50.0
    return float(next_lvl if next_lvl > price else next_lvl + 50.0)


def calculate_dynamic_volume_ratio(
    daily_volume_df: pd.DataFrame, weekly_volume_df: pd.DataFrame, ticker: str
) -> float:
    """Berechnet das tagesgewichtete RVOL (Montag bis heute)."""
    if ticker not in daily_volume_df.columns or ticker not in weekly_volume_df.columns:
        return 1.0

    vol_d = daily_volume_df[ticker].dropna()
    vol_w = weekly_volume_df[ticker].dropna()

    if len(vol_d) < 15 or len(vol_w) < 5:
        return 1.0

    recent_daily = vol_d.iloc[-60:].copy()
    df_vol = pd.DataFrame(
        {
            "Volume": recent_daily,
            "Weekday": recent_daily.index.weekday,
            "Week": recent_daily.index.to_period("W-FRI"),
        }
    )

    week_totals = df_vol.groupby("Week")["Volume"].transform("sum")
    df_vol["Day_Share"] = df_vol["Volume"] / week_totals
    mean_weekday_shares = df_vol.groupby("Weekday")["Day_Share"].mean()

    default_profile = {0: 0.17, 1: 0.19, 2: 0.19, 3: 0.20, 4: 0.25}
    for day in range(5):
        if day not in mean_weekday_shares or pd.isna(
            mean_weekday_shares.get(day)
        ):
            mean_weekday_shares[day] = default_profile[day]

    total_share = mean_weekday_shares.loc[0:4].sum()
    normalized_shares = mean_weekday_shares.loc[0:4] / total_share

    current_weekday = min(datetime.now().weekday(), 4)
    cumulative_expected_share = normalized_shares.loc[0:current_weekday].sum()

    avg_full_week_vol = (
        vol_w.iloc[-11:-1].mean()
        if len(vol_w) >= 11
        else vol_w.iloc[:-1].mean()
    )
    expected_vol_to_date = avg_full_week_vol * cumulative_expected_share
    current_week_vol = vol_w.iloc[-1]

    if expected_vol_to_date > 0 and pd.notna(current_week_vol):
        return round(float(current_week_vol / expected_vol_to_date), 2)
    return 1.0


# ---------------------------------------------------------------------
# 5. DATEN-ENGINE (ROBUSTER WECHSELKURS, MARKTFILTER & INDIKATOREN)
# ---------------------------------------------------------------------
@st.cache_data(
    ttl=86400,
    show_spinner="Stufe 1/2: Lade S&P 500 & Nasdaq Universum (> 2 Mrd. $)...",
)
def get_qualified_universe(min_market_cap_usd=2_000_000_000):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
    }
    company_names = {}
    company_sectors = {}
    raw_symbols = []

    # S&P 500
    try:
        sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        sp500_res = requests.get(sp500_url, headers=headers, timeout=15)
        sp500_tables = pd.read_html(StringIO(sp500_res.text), flavor="html5lib")
        for table in sp500_tables:
            sym_col = next(
                (col for col in table.columns if str(col).lower() in ["symbol", "ticker"]),
                None,
            )
            sec_col = next(
                (col for col in table.columns if "security" in str(col).lower() or "company" in str(col).lower()),
                None,
            )
            gics_col = next(
                (col for col in table.columns if "gics sector" in str(col).lower() or "sector" in str(col).lower()),
                None,
            )
            if sym_col and len(table) >= 400:
                for _, row in table.iterrows():
                    sym = str(row[sym_col]).strip().replace(".", "-")
                    if sym and sym != "nan":
                        company_names[sym] = str(row[sec_col]) if sec_col else sym
                        company_sectors[sym] = str(row[gics_col]) if gics_col else "Sonstige"
                        raw_symbols.append(sym)
                break
    except Exception as e:
        st.warning(f"Hinweis S&P 500: {e}")

    # Nasdaq 100
    try:
        nasdaq_url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        nasdaq_res = requests.get(nasdaq_url, headers=headers, timeout=15)
        nasdaq_tables = pd.read_html(StringIO(nasdaq_res.text), flavor="html5lib")
        for table in nasdaq_tables:
            sym_col = next(
                (col for col in table.columns if str(col).lower() in ["ticker", "symbol"]),
                None,
            )
            comp_col = next(
                (col for col in table.columns if "company" in str(col).lower() or "security" in str(col).lower()),
                None,
            )
            gics_col = next(
                (col for col in table.columns if "gics sector" in str(col).lower() or "sector" in str(col).lower()),
                None,
            )
            if sym_col and len(table) >= 50:
                for _, row in table.iterrows():
                    sym = str(row[sym_col]).strip().replace(".", "-")
                    if sym and sym != "nan":
                        if sym not in company_names:
                            company_names[sym] = str(row[comp_col]) if comp_col else sym
                            company_sectors[sym] = str(row[gics_col]) if gics_col else "Technology"
                        raw_symbols.append(sym)
                break
    except Exception as e:
        st.warning(f"Hinweis Nasdaq: {e}")

    unique_symbols = sorted(list(set(raw_symbols)))
    qualified_symbols = []

    for sym in unique_symbols:
        try:
            t = yf.Ticker(sym)
            mcap = t.fast_info.get("market_cap", None)
            if mcap is None or mcap >= min_market_cap_usd:
                qualified_symbols.append(sym)
        except Exception:
            qualified_symbols.append(sym)

    return qualified_symbols, company_names, company_sectors


@st.cache_data(
    ttl=3600, show_spinner="Stufe 2/2: Aktualisiere Kurse & Indikatoren (1h)..."
)
def load_screener_data():
    symbols, company_names, company_sectors = get_qualified_universe()

    # -------------------------------------------------------------
    # ROBUSTE WECHSELKURS-BERECHNUNG (EURUSD=X)
    # EURUSD=X gibt an: Wie viel USD kostet 1 EUR (z.B. 1 EUR = 1.085 USD)
    # 1 USD in EUR ist demnach = 1.0 / (EURUSD Kurs)
    # -------------------------------------------------------------
    eur_usd_pair_price = 1.08  # Realistischer Standardwert
    try:
        fx_ticker = yf.Ticker("EURUSD=X")
        fx_fast = fx_ticker.fast_info.get("last_price", None)
        if fx_fast is not None and fx_fast > 0:
            eur_usd_pair_price = float(fx_fast)
        else:
            fx_data = yf.download(
                "EURUSD=X", period="5d", interval="1d", progress=False
            )
            if not fx_data.empty:
                c_series = (
                    fx_data["Close"]["EURUSD=X"]
                    if "EURUSD=X" in fx_data["Close"]
                    else fx_data["Close"]
                )
                eur_usd_pair_price = float(c_series.dropna().iloc[-1])
    except Exception:
        eur_usd_pair_price = 1.08

    usd_to_eur_rate = 1.0 / eur_usd_pair_price

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

    # Weekly Resampling
    close_w = close_d.resample("W-FRI").last()
    high_w = high_d.resample("W-FRI").max()
    low_w = low_d.resample("W-FRI").min()
    vol_w = vol_d.resample("W-FRI").sum()

    daily_change_pct = close_d.pct_change().iloc[-1] * 100.0

    # Indikatoren berechnen
    ema10 = close_w.ewm(span=10, adjust=False).mean()
    ema21 = close_w.ewm(span=21, adjust=False).mean()

    exp12 = close_w.ewm(span=12, adjust=False).mean()
    exp26 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp12 - exp26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    high_20w = high_w.rolling(window=20, min_periods=5).max()
    high_52w = high_w.rolling(window=52, min_periods=10).max()
    ath_rolling = high_w.cummax()

    # SPY Markt-Regime
    spy_market_bullish = False
    spy_12w_perf = 0.0
    spy_close_val = 0.0
    spy_e21_val = 0.0

    if "SPY" in close_w.columns and len(close_w["SPY"].dropna()) >= 13:
        spy_s = close_w["SPY"].dropna()
        spy_close_val = spy_s.iloc[-1]
        spy_e21_val = ema21["SPY"].dropna().iloc[-1]
        spy_e10_val = ema10["SPY"].dropna().iloc[-1]

        spy_market_bullish = (spy_close_val >= spy_e21_val) and (
            spy_e10_val >= spy_e21_val
        )
        spy_12w_perf = ((spy_s.iloc[-1] - spy_s.iloc[-13]) / spy_s.iloc[-13]) * 100.0

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

        vol_ratio = calculate_dynamic_volume_ratio(vol_d, vol_w, sym)

        macd_rising = m_hist > m_hist_prev
        trend_bullish = e10_usd > e21_usd
        price_above_ema21 = c_usd >= e21_usd

        prev_body_above_10ema = c_prev_usd > e10_prev
        curr_body_above_10ema = c_usd > e10_usd

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

        near_crossover_event = (
            (e10_usd < e21_usd)
            and (e10_usd / e21_usd >= 0.985)
            and price_above_ema21
            and macd_rising
        )

        status = "NEUTRAL"
        typ = "Kein Setup"
        entry_min_usd = e10_usd
        entry_max_usd = e10_usd * 1.015

        if prev_body_above_10ema and price_above_ema21 and macd_rising:
            if crossover_event:
                status = "BEREIT"
                typ = "10/21 EMA Crossover (Bestätigt)"
                entry_min_usd = e10_usd
                entry_max_usd = e10_usd * 1.015
            elif retest_ema10_event or retest_ema21_event:
                status = "BEREIT"
                typ = (
                    "EMA 10 Retest (Bestätigt)"
                    if retest_ema10_event
                    else "EMA 21 Retest (Bestätigt)"
                )
                entry_min_usd = e10_usd if retest_ema10_event else e21_usd
                entry_max_usd = entry_min_usd * 1.015

        elif near_crossover_event:
            status = "FAST BEREIT"
            typ = "10/21 EMA Crossover steht bevor (<1.5%)"
            entry_min_usd = e10_usd
            entry_max_usd = e10_usd * 1.015
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

        # Einstiegs-Nähe Einstufung
        dist_from_10ema_pct = ((c_usd - e10_usd) / e10_usd) * 100.0

        if -0.5 <= dist_from_10ema_pct <= 1.5:
            entry_grade = "OPTIMAL"
            entry_desc = f"Optimal ({dist_from_10ema_pct:+.1f}%)"
        elif 1.5 < dist_from_10ema_pct <= 3.0:
            entry_grade = "NAH"
            entry_desc = f"Nah ({dist_from_10ema_pct:+.1f}%)"
        else:
            entry_grade = "WEIT"
            entry_desc = f"Überdehnt ({dist_from_10ema_pct:+.1f}%)"

        # 2-Stufen-Stop
        invalidation_usd = e21_usd
        emergency_sl_usd = e21_usd * 0.97
        risk_per_share_usd = max(c_usd - emergency_sl_usd, c_usd * 0.02)

        # Take-Profit Logik
        swing_20w_val = high_20w[sym].iloc[-1]
        swing_52w_val = high_52w[sym].iloc[-1]
        ath_val = ath_rolling[sym].iloc[-1]

        # TP 1
        crv_20w = (
            ((swing_20w_val - c_usd) / risk_per_share_usd)
            if pd.notna(swing_20w_val) and swing_20w_val > c_usd
            else 0.0
        )
        if crv_20w >= 3.0:
            tp1_usd = swing_20w_val
            tp1_label = f"20W-Hoch (CRV 1:{crv_20w:.1f})"
        else:
            calc_tp1 = c_usd + (3.0 * risk_per_share_usd)
            if calc_tp1 >= ath_val * 0.985:
                tp1_usd = get_next_50_level(max(ath_val, calc_tp1))
                tp1_label = "50er-Marke ATH"
            else:
                tp1_usd = calc_tp1
                tp1_label = "Fester 1:3 CRV"

        # TP 2
        crv_52w = (
            ((swing_52w_val - c_usd) / risk_per_share_usd)
            if pd.notna(swing_52w_val) and swing_52w_val > tp1_usd * 1.01
            else 0.0
        )
        if crv_52w > 3.0:
            tp2_usd = swing_52w_val
            tp2_label = f"52W-Hoch (CRV 1:{crv_52w:.1f})"
        else:
            calc_tp2 = c_usd + (5.0 * risk_per_share_usd)
            if tp1_usd >= ath_val * 0.985 or calc_tp2 >= ath_val * 0.985:
                tp2_usd = get_next_50_level(max(ath_val, tp1_usd))
                tp2_label = "50er-Marke ATH"
            else:
                tp2_usd = calc_tp2
                tp2_label = "Fester 1:5 CRV"

        emergency_sl_dist_pct = ((c_usd - emergency_sl_usd) / c_usd) * 100.0
        dist_ema10_pct = abs(dist_from_10ema_pct)

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
                "Invalidation_USD": round(invalidation_usd, 2),
                "Invalidation_EUR": round(
                    invalidation_usd * usd_to_eur_rate, 2
                ),
                "EmergencySL_USD": round(emergency_sl_usd, 2),
                "EmergencySL_EUR": round(emergency_sl_usd * usd_to_eur_rate, 2),
                "EmergencySL_Dist_Pct": round(emergency_sl_dist_pct, 2),
                "RiskPerShare_USD": risk_per_share_usd,
                "EntryZone_Min_USD": round(entry_min_usd, 2),
                "EntryZone_Max_USD": round(entry_max_usd, 2),
                "EntryZone_Min_EUR": round(entry_min_usd * usd_to_eur_rate, 2),
                "EntryZone_Max_EUR": round(entry_max_usd * usd_to_eur_rate, 2),
                "TP1_USD": round(tp1_usd, 2),
                "TP1_EUR": round(tp1_usd * usd_to_eur_rate, 2),
                "TP1_Label": tp1_label,
                "TP2_USD": round(tp2_usd, 2),
                "TP2_EUR": round(tp2_usd * usd_to_eur_rate, 2),
                "TP2_Label": tp2_label,
                "Dist_Entry_Pct": round(dist_from_10ema_pct, 2),
                "Dist_Abs_10EMA": dist_ema10_pct,
                "Entry_Grade": entry_grade,
                "Entry_Desc": entry_desc,
                "RS Score": rs_score,
                "MACD Hist": round(m_hist, 3),
                "Volumen Ratio": vol_ratio,
                "Health Status": health_status,
                "Health Color": health_color,
            }
        )

    df = pd.DataFrame(results)

    if not df.empty:
        df = df.sort_values(by="Dist_Abs_10EMA", ascending=True)

    return (
        df,
        close_w,
        ema10,
        ema21,
        company_names,
        daily_change_pct,
        usd_to_eur_rate,
        eur_usd_pair_price,
        spy_market_bullish,
        spy_close_val,
        spy_e21_val,
    )


# Daten laden
(
    df_all_stocks,
    close_w,
    ema10_df,
    ema21_df,
    company_names,
    daily_change_pct,
    usd_to_eur_rate,
    eur_usd_pair_price,
    spy_market_bullish,
    spy_close_val,
    spy_e21_val,
) = load_screener_data()

st.sidebar.caption(
    f"💱 **Wechselkurs Live:**\n\n"
    f"• 1 EUR = **{eur_usd_pair_price:.4f} USD**\n\n"
    f"• 1 USD = **{usd_to_eur_rate:.4f} EUR**"
)


# ---------------------------------------------------------------------
# 6. MODULARE KARTEN-DARSTELLUNG (OPTIMIERTES LAYOUT & FARBEN)
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
    vol_badge = (
        f":green[**{row['Volumen Ratio']}x**]"
        if row["Volumen Ratio"] >= 1.0
        else f":orange[**⚠️ {row['Volumen Ratio']}x**]"
    )

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

    # -----------------------------------------------------------------
    # THEME-SICHERE FARB-BADGES (FÜR LIGHT- & DARK-MODE)
    # -----------------------------------------------------------------
    if row["Entry_Grade"] == "OPTIMAL":
        badge_html = (
            "<span style='background: rgba(22, 163, 74, 0.18); color: #22c55e;"
            " border: 1px solid rgba(34, 197, 94, 0.4); padding: 1px 6px;"
            " border-radius: 4px; font-size: 11px; font-weight: 700;'>"
            f"🎯 OPTIMAL ({row['Dist_Entry_Pct']:+.1f}%)</span>"
        )
    elif row["Entry_Grade"] == "NAH":
        badge_html = (
            "<span style='background: rgba(132, 204, 22, 0.18); color: #84cc16;"
            " border: 1px solid rgba(132, 204, 22, 0.4); padding: 1px 6px;"
            " border-radius: 4px; font-size: 11px; font-weight: 700;'>"
            f"⚡ NAH ({row['Dist_Entry_Pct']:+.1f}%)</span>"
        )
    else:
        badge_html = (
            "<span style='background: rgba(148, 163, 184, 0.15); color: #94a3b8;"
            " border: 1px solid rgba(148, 163, 184, 0.3); padding: 1px 6px;"
            " border-radius: 4px; font-size: 11px;'>"
            f"⚠️ Überdehnt ({row['Dist_Entry_Pct']:+.1f}%)</span>"
        )

    # Positionsgrößen-Berechnung (2.0% Risiko vs. 20% Cap)
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
        # 1. ZEILE: NAME & SEKTOR
        st.markdown(
            f"<span style='color:gray; font-size:11.5px;'>{row['Name']} • {row['Sektor']}</span>",
            unsafe_allow_html=True,
        )

        # 2. ZEILE: TICKER + STATUS-TAG LINKS, TAGESÄNDERUNG & FAVORIT RECHTS
        h_left, h_right = st.columns([3, 1.2])
        with h_left:
            st.markdown(
                f"### **[{sym}]({google_link})** — {status_tag}",
                unsafe_allow_html=True,
            )
        with h_right:
            fav_label = "⭐" if is_fav else "✩"
            b_fav, b_chg = st.columns([1, 2])
            with b_fav:
                if st.button(
                    fav_label,
                    key=f"fav_{key_prefix}_{sym}",
                    help="Zu Favoriten hinzufügen",
                ):
                    if is_fav:
                        all_users_data[current_user]["favorites"].remove(sym)
                    else:
                        all_users_data[current_user]["favorites"].append(sym)
                    save_user_data(all_users_data)
                    st.rerun()
            with b_chg:
                st.markdown(
                    f"<div style='text-align:right; font-size:12px; margin-top:6px;'>"
                    f":{change_color}[**{change_sign}{d_change}%**]</div>",
                    unsafe_allow_html=True,
                )

        # 3. ZEILE: EMPFOHLENER EINSTIEG PROMINENT OBEN
        st.markdown(
            f"<div style='background: rgba(37, 99, 235, 0.10); border-left: 3px solid #2563eb; padding: 4px 8px; border-radius: 4px; margin: 4px 0 8px 0; font-size: 12px;'>"
            f"🎯 <b>Kaufzone (10 EMA):</b> <code>${row['EntryZone_Min_USD']} - ${row['EntryZone_Max_USD']}</code> "
            f"<i>(€{row['EntryZone_Min_EUR']} - €{row['EntryZone_Max_EUR']})</i>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 4. ZEILE: AKTUELLER KURS + EINSTIEGS-BADGE
        st.markdown(
            f"**Kurs:** `${row['Kurs_USD']}` *(€{row['Kurs_EUR']})* &nbsp; {badge_html}",
            unsafe_allow_html=True,
        )

        # 5. ZEILE: SETUP-TYP & RELATIVE STÄRKE
        st.caption(f"Setup: **{row['Typ']}** | {rs_badge}")

        # 6. ZEILE: EMAs, MACD & VOLUMEN
        ema10_col = "green" if row["Kurs_USD"] > row["EMA10_USD"] else "red"
        ema21_col = "green" if row["Kurs_USD"] > row["EMA21_USD"] else "red"

        st.markdown(
            f"**10 EMA:** :{ema10_col}[${row['EMA10_USD']}] | **21 EMA:**"
            f" :{ema21_col}[${row['EMA21_USD']}]"
        )
        st.markdown(
            f"**MACD Hist:** `{row['MACD Hist']}` | **Vol:** {vol_badge}"
        )

        # 7. AUSKLAPPBARER TRADE-PLAN
        with st.expander("🎯 Stops, Kursziele & Stückzahl"):
            st.markdown(
                f"⚠️ **Trend-Invalidierung:** Wochenschluss `< ${row['Invalidation_USD']}` *(€{row['Invalidation_EUR']})*\n\n"
                f"<span style='color:gray; font-size:11px;'>👉 Erst am Freitagabend manuell schließen, falls die Wochenkerze darunter schließt.</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"🛡️ **Notfall-Stop im Broker:** `${row['EmergencySL_USD']}` | `€{row['EmergencySL_EUR']}` "
                f"(:red[**-{row['EmergencySL_Dist_Pct']}%**])\n\n"
                f"<span style='color:gray; font-size:11px;'>👉 Fester Stop-Loss im Broker (3% Puffer gegen Flash-Crashes).</span>",
                unsafe_allow_html=True,
            )
            st.markdown("---")
            st.markdown(
                f"🏁 **Ziel 1:** `${row['TP1_USD']}` | `€{row['TP1_EUR']}` "
                f"<span style='color:gray; font-size:11px;'>({row['TP1_Label']})</span>\n\n"
                f"🚀 **Ziel 2:** `${row['TP2_USD']}` | `€{row['TP2_EUR']}` "
                f"<span style='color:gray; font-size:11px;'>({row['TP2_Label']})</span>",
                unsafe_allow_html=True,
            )
            st.markdown("---")
            st.markdown(
                f"💼 **Empfohlene Stückzahl:** **{shares_to_buy} Stück**\n\n"
                f"*(Volumen: ~${pos_vol_usd:,.0f} / ~€{pos_vol_eur:,.0f} | 2%"
                f" Risiko, max. {max_allocation_pct}% Depot)*"
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
                    "invalidation_usd": row["Invalidation_USD"],
                    "invalidation_eur": row["Invalidation_EUR"],
                    "emergency_sl_usd": row["EmergencySL_USD"],
                    "emergency_sl_eur": row["EmergencySL_EUR"],
                    "tp1_usd": row["TP1_USD"],
                    "tp1_eur": row["TP1_EUR"],
                    "tp1_label": row["TP1_Label"],
                    "tp2_usd": row["TP2_USD"],
                    "tp2_eur": row["TP2_EUR"],
                    "tp2_label": row["TP2_Label"],
                    "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                save_user_data(all_users_data)
                st.rerun()


# ---------------------------------------------------------------------
# 7. HEADER & MARKT-AMPEL
# ---------------------------------------------------------------------
st.title(f"📈 Weekly Trading Hub Pro — ({current_user})")

if spy_market_bullish:
    st.success(
        f"🟢 **MARKT-STATUS: BULLENMARKT AKTIV** — S&P 500 (${spy_close_val:.2f}) notiert über seiner 21 EMA (${spy_e21_val:.2f}). "
        f"Kaufsignale sind freigegeben und werden nach optimalem Einstiegsabstand sortiert!"
    )
else:
    st.error(
        f"🔴 **MARKT-STATUS: KORREKTUR / BÄRENMARKT** — S&P 500 (${spy_close_val:.2f}) notiert unter seiner 21 EMA (${spy_e21_val:.2f}). "
        f"⚠️ **100% Cash-Schutz aktiv:** Laut Backtest-Regelwerk sollten aktuell keine neuen Long-Positionen eröffnet werden!"
    )

total_active = len(user_trades)
at_risk_count = 0
invalidated_count = 0
tp_ready_count = 0

for sym, info in user_trades.items():
    if sym in close_w.columns:
        c_price = close_w[sym].dropna().iloc[-1]
        e21_val = ema21_df[sym].dropna().iloc[-1]

        if c_price < e21_val:
            invalidated_count += 1
        elif c_price <= e21_val * 1.015:
            at_risk_count += 1

        tp1_val = info.get("tp1_usd", 0.0)
        tp2_val = info.get("tp2_usd", 0.0)
        trade_status = str(info.get("status", "Offen"))

        if trade_status == "Offen" and tp1_val > 0 and c_price >= tp1_val:
            tp_ready_count += 1
        elif "50%" in trade_status and tp2_val > 0 and c_price >= tp2_val:
            tp_ready_count += 1

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric(label="🎯 Aktive Positionen", value=f"{total_active} Trades")
with m2:
    st.metric(
        label="💰 Teilgewinne bereit",
        value=f"{tp_ready_count} Trades",
        delta="Kurs an Zielzone!" if tp_ready_count > 0 else "Warten auf Targets",
        delta_color="normal" if tp_ready_count > 0 else "off",
    )
with m3:
    st.metric(
        label="⚠️ Nahe 21 EMA (Gefährdet)",
        value=f"{at_risk_count} Trades",
        delta="Testet Support" if at_risk_count > 0 else "Alles stabil",
        delta_color="inverse" if at_risk_count > 0 else "off",
    )
with m4:
    st.metric(
        label="❌ Invalidiert (Wochenschluss < 21 EMA)",
        value=f"{invalidated_count} Trades",
        delta="Freitagsschluss < 21 EMA" if invalidated_count > 0 else "Keine",
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
# TAB 1: SCREENER (SORTIERT NACH OPTIMALEM EINSTIEG)
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
                "🎯 Optimaler Einstieg (Nächste 10 EMA zuerst) [Standard]",
                "⚡ Höchste Relative Stärke (RS)",
                "📊 Höchstes Volumen (RVOL)",
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
        only_near_entries = st.checkbox(
            "🎯 Nur Nahe & Optimal (≤ 3.0%)",
            value=False,
            key="chk_near_entry",
            help="Filtert überdehnte Aktien heraus, die mehr als 3.0% über der 10 EMA liegen.",
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

    if only_near_entries:
        f_df = f_df[f_df["Entry_Grade"].isin(["OPTIMAL", "NAH"])]

    # Sortierung anwenden
    if sort_by == "⚡ Höchste Relative Stärke (RS)":
        f_df = f_df.sort_values(by="RS Score", ascending=False)
    elif sort_by == "📊 Höchstes Volumen (RVOL)":
        f_df = f_df.sort_values(by="Volumen Ratio", ascending=False)
    elif sort_by == "🚀 Beste Tagesperformance (%)":
        f_df = f_df.sort_values(by="DailyChange", ascending=False)
    else:
        f_df = f_df.sort_values(by="Dist_Abs_10EMA", ascending=True)

    st.caption(
        f"Gefundene Setups: **{len(f_df)}** (Automatisch nach bester Einstiegszone"
        " geordnet)"
    )

    if f_df.empty:
        st.info(
            "Aktuell keine Setups gefunden. Passe die Filter an oder schau in"
            " **Tab 4 (Alle Aktien)**."
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
# TAB 2: MEINE AKTIVEN TRADES
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
            curr_e10_eur = curr_e10_usd * usd_to_eur_rate

            curr_e21_usd = ema21_df[sym].dropna().iloc[-1]
            curr_e21_eur = curr_e21_usd * usd_to_eur_rate

            entry_usd = info.get("entry_price_usd", curr_usd)
            entry_eur = info.get("entry_price_eur", curr_eur)

            tp1_usd = info.get("tp1_usd", curr_usd * 1.10)
            tp1_eur = info.get("tp1_eur", tp1_usd * usd_to_eur_rate)
            tp1_lbl = info.get("tp1_label", "Ziel 1")

            tp2_usd = info.get("tp2_usd", curr_usd * 1.20)
            tp2_eur = info.get("tp2_eur", tp2_usd * usd_to_eur_rate)
            tp2_lbl = info.get("tp2_label", "Ziel 2")

            trade_status = str(info.get("status", "Offen"))
            is_50_saved = "50%" in trade_status
            is_90_saved = "90%" in trade_status

            if is_50_saved or is_90_saved:
                em_sl_usd = max(entry_usd, curr_e21_usd * 0.97)
                sl_label = "🛡️ Break-Even Stop (Broker)"
            else:
                em_sl_usd = info.get("emergency_sl_usd", curr_e21_usd * 0.97)
                sl_label = "🛡️ Notfall-Stop (Broker)"

            em_sl_eur = em_sl_usd * usd_to_eur_rate

            is_invalidated = curr_usd < curr_e21_usd
            is_below_e10 = curr_usd < curr_e10_usd
            is_near_e10 = (curr_usd >= curr_e10_usd) and (
                curr_usd <= curr_e10_usd * 1.015
            )

            if is_invalidated:
                ema10_color = "orange"
                ema21_color = "orange"
                health = "❌ INVALIDIERT (Wochenschluss unter 21 EMA!)"
                health_color = "red"
            elif is_below_e10:
                ema10_color = "red"
                ema21_color = "orange"
                health = "⚠️ KURS UNTER 10 EMA (Testet Richtung 21 EMA)"
                health_color = "orange"
            elif is_near_e10:
                ema10_color = "orange"
                ema21_color = "green"
                health = "✅ IM TREND (Testet 10 EMA Support)"
                health_color = "green"
            else:
                ema10_color = "green"
                ema21_color = "green"
                health = "✅ IM TREND (Deutlich über 10 EMA)"
                health_color = "green"

            if trade_status == "Offen" and curr_usd >= tp1_usd:
                status_display = (
                    ":orange[**⚡ ZIEL 1 ERREICHT! (50% TP Bereit)**]"
                )
            elif is_50_saved and curr_usd >= tp2_usd:
                status_display = (
                    ":orange[**⚡ ZIEL 2 ERREICHT! (90% TP Bereit)**]"
                )
            elif is_50_saved:
                status_display = (
                    ":green[**💰 50% TP Gesichert (Stop auf BE)**]"
                )
            elif is_90_saved:
                status_display = (
                    ":green[**🚀 90% TP Gesichert (Runner aktiv)**]"
                )
            else:
                status_display = f"**{trade_status}**"

            tp1_raw = f"🎯 **TP 1:** `${tp1_usd}` | `€{tp1_eur}` <span style='color:gray; font-size:11px;'>({tp1_lbl})</span>"
            tp2_raw = f"🚀 **TP 2:** `${tp2_usd}` | `€{tp2_eur}` <span style='color:gray; font-size:11px;'>({tp2_lbl})</span>"

            if is_90_saved:
                tp1_formatted = f"<s>{tp1_raw}</s> ✅ *(realisiert)*"
                tp2_formatted = f"<s>{tp2_raw}</s> ✅ *(realisiert)*"
            elif is_50_saved:
                tp1_formatted = f"<s>{tp1_raw}</s> ✅ *(realisiert)*"
                tp2_formatted = tp2_raw
            else:
                tp1_formatted = tp1_raw
                tp2_formatted = tp2_raw

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
                    st.markdown(
                        f"Status: {status_display}\n\n"
                        f"**Einstieg:** `${entry_usd}` | `€{entry_eur}`\n\n"
                        f"**Aktueller Kurs:** `${round(curr_usd, 2)}` | `€{round(curr_eur, 2)}`\n\n"
                        f"**10 EMA:** :{ema10_color}[${round(curr_e10_usd, 2)} / €{round(curr_e10_eur, 2)}] | "
                        f"**21 EMA:** :{ema21_color}[${round(curr_e21_usd, 2)} / €{round(curr_e21_eur, 2)}]"
                    )

                with c3:
                    st.markdown(
                        f"Trend: :{health_color}[**{health}**]\n\n"
                        f"{tp1_formatted}\n\n"
                        f"{tp2_formatted}\n\n"
                        f"{sl_label}: `${round(em_sl_usd, 2)}` | `€{round(em_sl_eur, 2)}`",
                        unsafe_allow_html=True,
                    )

                with c4:
                    btn_50_label = (
                        "✅ 50% Gesichert"
                        if is_50_saved
                        else "💰 50% TP sichern"
                    )
                    btn_50_type = "primary" if is_50_saved else "secondary"

                    if st.button(
                        btn_50_label,
                        key=f"tp50_{sym}",
                        type=btn_50_type,
                        use_container_width=True,
                    ):
                        if is_50_saved:
                            all_users_data[current_user]["trades"][sym]["status"] = "Offen"
                        else:
                            all_users_data[current_user]["trades"][sym]["status"] = "💰 50% TP Gesichert"
                        save_user_data(all_users_data)
                        st.rerun()

                    btn_90_label = (
                        "✅ 90% Gesichert"
                        if is_90_saved
                        else "🚀 90% TP sichern"
                    )
                    btn_90_type = "primary" if is_90_saved else "secondary"

                    if st.button(
                        btn_90_label,
                        key=f"tp90_{sym}",
                        type=btn_90_type,
                        use_container_width=True,
                    ):
                        if is_90_saved:
                            all_users_data[current_user]["trades"][sym]["status"] = "Offen"
                        else:
                            all_users_data[current_user]["trades"][sym]["status"] = "🚀 90% TP Gesichert"
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
# TAB 4: ALLE AKTIEN (S&P 500 & NASDAQ MARKTÜBERSICHT)
# =====================================================================
with tab4:
    st.caption(
        "Hier findest du alle qualifizierten S&P 500 & Nasdaq Aktien (> 2"
        " Mrd. $ Market Cap)."
    )

    af1, af2 = st.columns([2, 2])
    with af1:
        search_all = st.text_input(
            "🔍 Suche nach Ticker oder Name:",
            placeholder="z. B. AAPL, NVDA, AMZN, MSFT...",
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
