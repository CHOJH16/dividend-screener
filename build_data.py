# -*- coding: utf-8 -*-
"""
S&P 500 + 나스닥 100 + 대표 배당 ETF의
10년 배당수익률 밴드 데이터를 만들어 data/screener_us.json 으로 저장한다.
"""

import io
import os
import json
import time
import datetime as dt

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ----------------------------------------------------------- 설정값
HISTORY_YEARS   = 10      # 밴드 계산에 쓸 기간
MIN_YEARS       = 3       # 배당 이력이 이보다 짧으면 제외
FLAT_TOLERANCE  = 0.02    # 2% 이내 감소는 '유지'로 인정 (반올림 오차 흡수)
SPECIAL_DIV_CAP = 2.0     # 직전 3년 중앙값의 2배 초과분은 특별배당으로 보고 잘라냄
MAX_YIELD       = 40.0    # 이보다 높은 수익률은 데이터 오류로 보고 제외
CHUNK           = 25      # 한 번에 받아올 종목 수
SLEEP           = 2.0     # 묶음 사이 쉬는 시간(초) — 야후 차단 방지

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ----------------------------------------------------------- 배당 ETF 목록
DIVIDEND_ETFS = {
    "SCHD": "Schwab US Dividend Equity ETF",
    "DGRO": "iShares Core Dividend Growth ETF",
    "DGRW": "WisdomTree US Quality Dividend Growth",
    "VYM":  "Vanguard High Dividend Yield ETF",
    "VIG":  "Vanguard Dividend Appreciation ETF",
    "NOBL": "ProShares S&P 500 Dividend Aristocrats",
    "SDY":  "SPDR S&P Dividend ETF",
    "DVY":  "iShares Select Dividend ETF",
    "HDV":  "iShares Core High Dividend ETF",
    "SPYD": "SPDR Portfolio S&P 500 High Dividend",
    "RDVY": "First Trust Rising Dividend Achievers",
    "FDVV": "Fidelity High Dividend ETF",
    "SPHD": "Invesco S&P 500 High Div Low Vol",
    "PEY":  "Invesco High Yield Equity Dividend Achievers",
    "DIVO": "Amplify CWP Enhanced Dividend Income",
    "JEPI": "JPMorgan Equity Premium Income ETF",
    "JEPQ": "JPMorgan Nasdaq Equity Premium Income",
    "SCHY": "Schwab International Dividend Equity",
}

# 나스닥100 목록을 못 가져올 때만 쓰는 비상용 목록
NDX_FALLBACK = """
AAPL ABNB ADBE ADI ADP ADSK AEP AMAT AMD AMGN AMZN APP ARM ASML AVGO AXON AZN
BIIB BKNG BKR CCEP CDNS CDW CEG CHTR CMCSA COST CPRT CRWD CSCO CSGP CSX CTAS
CTSH DASH DDOG DXCM EA EXC FANG FAST FTNT GEHC GFS GILD GOOG GOOGL HON IDXX
INTC INTU ISRG KDP KHC KLAC LIN LRCX LULU MAR MCHP MDLZ MELI META MNST MRVL
MSFT MSTR MU NFLX NVDA NXPI ODFL ON ORLY PANW PAYX PCAR PDD PEP PLTR PYPL
QCOM REGN ROP ROST SBUX SNPS TEAM TMUS TSLA TTD TTWO TXN VRSK VRTX WBD WDAY
XEL ZS
""".split()


# ----------------------------------------------------------- 종목 목록
def read_html_ua(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def get_sp500():
    urls = [
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            low = {c.lower().strip(): c for c in df.columns}
            c_sym = low.get("symbol")
            c_nm = low.get("name") or low.get("security")
            c_se = low.get("sector") or low.get("gics sector")
            out = {}
            for _, row in df.iterrows():
                t = str(row[c_sym]).strip().upper().replace(".", "-")
                nm = str(row[c_nm]).strip() if c_nm else t
                se = str(row[c_se]).strip() if c_se else "-"
                if t and t != "NAN":
                    out[t] = (nm, se)
            if len(out) > 400:
                print(f"[S&P500] {len(out)}개 확보")
                return out
        except Exception as e:
            print("[S&P500] 실패:", e)

    try:
        for tb in read_html_ua("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"):
            cols = [str(c) for c in tb.columns]
            if "Symbol" in cols and "Security" in cols and len(tb) > 400:
                out = {}
                for _, row in tb.iterrows():
                    t = str(row["Symbol"]).strip().upper().replace(".", "-")
                    se = str(row.get("GICS Sector", "-")).strip()
                    out[t] = (str(row["Security"]).strip(), se)
                print(f"[S&P500] 위키피디아에서 {len(out)}개 확보")
                return out
    except Exception as e:
        print("[S&P500] 위키피디아도 실패:", e)

    return {}


def get_ndx100():
    try:
        for tb in read_html_ua("https://en.wikipedia.org/wiki/Nasdaq-100"):
            cols = {str(c).lower(): c for c in tb.columns}
            key = cols.get("ticker") or cols.get("symbol")
            if key is not None and 90 <= len(tb) <= 115:
                syms = set()
                for s in tb[key].dropna():
                    s = str(s).strip().upper().replace(".", "-")
                    if 0 < len(s) <= 6 and s.replace("-", "").isalpha():
                        syms.add(s)
                if len(syms) >= 90:
                    print(f"[NDX100] {len(syms)}개 확보")
                    return syms
    except Exception as e:
        print("[NDX100] 실패:", e)
    print(f"[NDX100] 비상 목록 사용 ({len(NDX_FALLBACK)}개)")
    return set(NDX_FALLBACK)


def build_universe():
    uni = {}
    for t, (nm, se) in get_sp500().items():
        uni[t] = {"name": nm, "sec": se, "idx": ["SP500"], "etf": False}
    for t in get_ndx100():
        if t in uni:
            uni[t]["idx"].append("NDX100")
        else:
            uni[t] = {"name": t, "sec": "", "idx": ["NDX100"], "etf": False}
    for t, nm in DIVIDEND_ETFS.items():
        uni[t] = {"name": nm, "sec": "ETF", "idx": ["DIVETF"], "etf": True}
    print(f"[유니버스] 총 {len(uni)}종목")
    return uni


# ----------------------------------------------------------- 데이터 수집
def to_naive(idx):
    idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return idx


def fetch_all(tickers):
    frames, missing = {}, []
    for i in range(0, len(tickers), CHUNK):
        part = tickers[i:i + CHUNK]
        print(f"  다운로드 {i + 1}~{i + len(part)} / {len(tickers)}")
        try:
            raw = yf.download(part, period=f"{HISTORY_YEARS}y", interval="1d",
                              actions=True, auto_adjust=False, group_by="ticker",
                              threads=2, progress=False)
        except Exception as e:
            print("   묶음 실패:", e)
            missing += part
            time.sleep(SLEEP * 2)
            continue
        for t in part:
            try:
                df = raw[t].dropna(how="all")
                if df.empty:
                    missing.append(t)
                else:
                    frames[t] = df
            except Exception:
                missing.append(t)
        time.sleep(SLEEP)

    for rnd in range(2):
        if not missing:
            break
        print(f"  재시도 {rnd + 1}회차: {len(missing)}종목")
        again = []
        for t in missing:
            try:
                df = yf.Ticker(t).history(period=f"{HISTORY_YEARS}y", interval="1d",
                                          auto_adjust=False, actions=True)
                if df is not None and not df.empty:
                    frames[t] = df
                else:
                    again.append(t)
            except Exception:
                again.append(t)
            time.sleep(1.2)
        missing = again

    print(f"[수집] 성공 {len(frames)}종목 / 실패 {len(missing)}종목")
    return frames


# ----------------------------------------------------------- 배당 증가(유지) 기간
def dividend_streak(div, today):
    """동결도 유지로 인정. 감액이 나오는 순간 끊긴다."""
    if div.empty:
        return 0

    yr_sum = div.groupby(div.index.year).sum()
    yr_cnt = div.groupby(div.index.year).size()
    yr_sum = yr_sum[yr_sum.index < today.year]     # 진행 중인 올해는 제외
    yr_cnt = yr_cnt[yr_cnt.index < today.year]
    if len(yr_sum) < 2:
        return 0
    if int(max(yr_sum.index)) < today.year - 1:    # 최근에 배당이 끊긴 종목
        return 0

    modal = int(yr_cnt[yr_cnt > 0].median())       # 연간 표준 지급 횟수

    norm = {}
    for y in yr_sum.index:
        s, c = float(yr_sum[y]), int(yr_cnt[y])
        if modal > 0 and c > 0 and c != modal:
            s = s / c * modal                      # 지급 횟수 어긋남 보정
        norm[int(y)] = s

    asc = sorted(norm)
    capped = {}
    for i, y in enumerate(asc):
        prev = [capped[p] for p in asc[max(0, i - 3):i]]
        v = norm[y]
        if len(prev) >= 2:
            v = min(v, float(np.median(prev)) * SPECIAL_DIV_CAP)
        capped[y] = v

    desc = sorted(capped, reverse=True)
    run = 0
    for a, b in zip(desc, desc[1:]):
        if a - b != 1 or capped[b] <= 0:
            break
        if capped[a] < capped[b] * (1 - FLAT_TOLERANCE):
            break
        run += 1
    return run + 1 if run > 0 else 1


# ----------------------------------------------------------- 종목 분석
BANDS = [(10, "매우 고평가", -2), (30, "고평가", -1),
         (70, "중립", 0), (90, "저평가", 1), (101, "매우 저평가", 2)]


def analyze(sym, meta, df, today):
    if df is None or df.empty or "Close" not in df or "Dividends" not in df:
        return None

    px = pd.to_numeric(df["Close"], errors="coerce").dropna()
    dv = pd.to_numeric(df["Dividends"], errors="coerce").fillna(0.0)
    px.index, dv.index = to_naive(px.index), to_naive(dv.index)
    dv = dv[dv > 0]
    if len(px) < 250 or dv.empty:
        return None

    idx = px.index.union(dv.index).sort_values()
    p = px.reindex(idx).ffill()
    d = dv.reindex(idx).fillna(0.0)
    ttm = d.rolling("365D").sum()

    y = (ttm / p * 100.0).replace([np.inf, -np.inf], np.nan).dropna()
    y = y[(y > 0) & (y < MAX_YIELD)]
    y = y[y.index >= y.index[-1] - pd.Timedelta(days=365.25 * HISTORY_YEARS)]
    yw = y.resample("W").last().dropna()
    if len(yw) < MIN_YEARS * 52:
        return None

    cur_p = float(p.iloc[-1])
    cur_ttm = float(ttm.iloc[-1])
    cur_y = cur_ttm / cur_p * 100.0
    if cur_y <= 0 or cur_y >= MAX_YIELD:
        return None

    pct = float((yw < cur_y).mean() * 100.0)
    label, band = next((l, b) for th, l, b in BANDS if pct < th)

    return {
        "sym": sym,
        "name": meta["name"],
        "sec": meta["sec"] or "-",
        "idx": meta["idx"],
        "etf": meta["etf"],
        "px": round(cur_p, 2),
        "ttm": round(cur_ttm, 4),
        "y": round(cur_y, 2),
        "y10": round(float(np.percentile(yw, 10)), 2),
        "y25": round(float(np.percentile(yw, 25)), 2),
        "y50": round(float(np.percentile(yw, 50)), 2),
        "y75": round(float(np.percentile(yw, 75)), 2),
        "y90": round(float(np.percentile(yw, 90)), 2),
        "pct": round(pct, 1),
        "band": band,
        "bandLabel": label,
        "streak": dividend_streak(dv, today),
        "yrs": round((yw.index[-1] - yw.index[0]).days / 365.25, 1),
    }


# ----------------------------------------------------------- 실행
def main():
    today = dt.date.today()
    uni = build_universe()
    if len(uni) < 200:
        raise SystemExit("종목 목록을 가져오지 못했습니다. 잠시 후 다시 실행하세요.")

    frames = fetch_all(sorted(uni))

    items = []
    for t in sorted(frames):
        try:
            r = analyze(t, uni[t], frames[t], today)
        except Exception as e:
            print("   분석 실패", t, e)
            r = None
        if r:
            items.append(r)

    # 섹터가 비어 있는 종목만 개별 조회
    for it in items:
        if it["sec"] in ("", "-"):
            try:
                s = yf.Ticker(it["sym"]).info.get("sector")
                it["sec"] = s if s else "-"
            except Exception:
                it["sec"] = "-"
            time.sleep(0.4)

    if len(items) < 100:
        raise SystemExit(f"수집 결과가 너무 적습니다({len(items)}개). 다시 실행하세요.")

    items.sort(key=lambda x: -x["pct"])
    os.makedirs("data", exist_ok=True)
    payload = {
        "updated": (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST"),
        "universe": len(uni),
        "count": len(items),
        "items": items,
    }
    with open("data/screener_us.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[완료] {len(items)}종목 저장")


if __name__ == "__main__":
    main()
