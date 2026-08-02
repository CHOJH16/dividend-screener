# -*- coding: utf-8 -*-
"""
S&P 500 + 나스닥 100 + 대표 배당 ETF의
10년 배당수익률 밴드 + 10년 PER 밴드 + 모닝스타 해자 등급 데이터를 만들어
data/screener_us.json 으로 저장한다.

PER은 SEC EDGAR의 공개 XBRL 데이터에서 분기 EPS를 받아
최근 12개월 EPS 시계열을 만들고, 야후 주가로 나눠 계산한다.
"""

import io, os, json, time, datetime as dt
import numpy as np, pandas as pd, requests, yfinance as yf

# ----------------------------------------------------------- 설정값
HISTORY_YEARS   = 10
FETCH_YEARS     = 12
MIN_YEARS       = 3
FLAT_TOLERANCE  = 0.02
SPECIAL_DIV_CAP = 2.0
STALE_FACTOR    = 1.8
MAX_YIELD       = 40.0
CHUNK           = 25
SLEEP           = 2.0

START_DATE = (dt.date.today() - dt.timedelta(days=int(365.25 * FETCH_YEARS))).isoformat()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 모닝스타 해자 등급 (영국 사이트의 공개 스크리너 엔드포인트)
MS_URL = "https://tools.morningstar.co.uk/api/rest.svc/klr5zyak8x/security/screener"
MS_UNIVERSE = "E0EXG$XNYS|E0EXG$XNAS|E0EXG$XASE"

# ----------------------------------------------------------- SEC EDGAR (PER용)
# SEC는 접속자를 식별할 수 있는 User-Agent를 요구한다. 본인 이메일로 바꿔도 된다.
SEC_CONTACT     = "dividend-screener/1.0 (github.com/CHOJH16)"
SEC_HDR         = {"User-Agent": SEC_CONTACT, "Accept-Encoding": "gzip, deflate"}
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL     = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{ns}/{tag}.json"
SEC_PAUSE       = 0.13          # 초당 10회 제한을 넉넉히 지킨다
PE_MAX          = 300.0

EPS_CONCEPTS = [
    ("us-gaap",   "EarningsPerShareDiluted"),
    ("us-gaap",   "EarningsPerShareBasicAndDiluted"),
    ("us-gaap",   "EarningsPerShareBasic"),
    ("ifrs-full", "DilutedEarningsLossPerShare"),
    ("ifrs-full", "BasicEarningsLossPerShare"),
]

# PER은 낮을수록 싸다. 백분위가 낮을수록 저평가.
PE_BANDS = [(10, "매우 저평가", 2), (30, "저평가", 1), (70, "중립", 0),
            (90, "고평가", -1), (101, "매우 고평가", -2)]

PE_KEYS = ("pe", "peps", "pe10", "pe25", "pe50", "pe75", "pe90",
           "peavg", "pepct", "peband", "pebandLabel", "peyrs")

# ----------------------------------------------------------- 섹터 한글 이름
SECTOR_KO = {
    "Information Technology": "정보기술",
    "Health Care":            "헬스케어",
    "Financials":             "금융",
    "Consumer Discretionary": "경기소비재",
    "Consumer Staples":       "필수소비재",
    "Communication Services": "커뮤니케이션",
    "Industrials":            "산업재",
    "Energy":                 "에너지",
    "Utilities":              "유틸리티",
    "Real Estate":            "부동산",
    "Materials":              "소재",
    "Technology":             "정보기술",
    "Healthcare":             "헬스케어",
    "Financial Services":     "금융",
    "Consumer Cyclical":      "경기소비재",
    "Consumer Defensive":     "필수소비재",
    "Basic Materials":        "소재",
    "Industrial Goods":       "산업재",
    "Services":               "서비스",
    "ETF":                    "ETF",
}

def ko_sector(name):
    if not name:
        return "기타"
    s = str(name).strip()
    if s in ("", "-", "nan", "None"):
        return "기타"
    return SECTOR_KO.get(s, s)

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

# ----------------------------------------------------------- 모닝스타 해자 등급
def fetch_moat_map():
    """티커 -> {moat, qmoat, star} 사전. 실패하면 빈 사전을 돌려준다."""
    out, page = {}, 1
    while page <= 12:
        try:
            r = requests.get(MS_URL, params={
                "page": page, "pageSize": 1000, "outputType": "json", "version": 1,
                "languageId": "en-GB", "currencyId": "USD",
                "universeIds": MS_UNIVERSE,
                "securityDataPoints": "Ticker|EconomicMoat|QuantitativeMoat|StarRating",
                "sortOrder": "Ticker asc",
            }, headers=UA, timeout=40)
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            print(f"[해자] {page}페이지 실패:", e)
            break

        rows = j.get("rows", [])
        if not rows:
            break
        for row in rows:
            t = row.get("Ticker")
            if not t:
                continue
            out[t] = {
                "moat":  row.get("EconomicMoat"),
                "qmoat": row.get("QuantitativeMoat"),
                "star":  row.get("StarRating"),
            }
        total = j.get("total", 0)
        print(f"  해자 {page}페이지 · 누적 {len(out)} / {total}")
        if page * 1000 >= total:
            break
        page += 1
        time.sleep(1.0)

    print(f"[해자] 총 {len(out)}종목 확보")
    return out

def lookup_moat(sym, moat_map):
    """야후는 BF-B, 모닝스타는 BF.B 처럼 표기가 다를 수 있어 몇 가지로 시도한다."""
    for key in (sym, sym.replace("-", "."), sym.replace(".", "-")):
        if key in moat_map:
            return moat_map[key]
    return {}

def load_prev_moat():
    """해자 수집이 실패했을 때 쓸 직전 결과."""
    try:
        with open("data/screener_us.json", encoding="utf-8") as f:
            old = json.load(f)
        return {x["sym"]: {"moat": x.get("moat"), "qmoat": x.get("qmoat"),
                           "star": x.get("star")}
                for x in old.get("items", []) if x.get("moat") or x.get("qmoat")}
    except Exception:
        return {}

def load_prev_pe():
    """PER 수집이 실패했을 때 쓸 직전 결과."""
    try:
        with open("data/screener_us.json", encoding="utf-8") as f:
            old = json.load(f)
        return {x["sym"]: {k: x.get(k) for k in PE_KEYS}
                for x in old.get("items", []) if x.get("pe")}
    except Exception:
        return {}

# ----------------------------------------------------------- SEC 재무 데이터
def sec_get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=SEC_HDR, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1.0 + i * 1.5)
    return None

def fetch_cik_map():
    """티커 -> CIK 번호."""
    j = sec_get(SEC_TICKERS_URL)
    out = {}
    if not j:
        print("[PER] SEC 티커 목록을 받지 못했습니다.")
        return out
    src = j.values() if isinstance(j, dict) else j
    for v in src:
        try:
            t = str(v.get("ticker", "")).strip().upper().replace(".", "-")
            c = int(v.get("cik_str"))
        except Exception:
            continue
        if t and c:
            out.setdefault(t, c)
    print(f"[PER] SEC 티커 {len(out)}개 확보")
    return out

def eps_quarters(js):
    """companyconcept 응답 -> {분기말일: (EPS, 공시일)}"""
    units = (js or {}).get("units", {})
    facts = []
    for k, arr in units.items():
        if "share" in str(k).lower():
            facts.extend(arr)
    if not facts:
        return {}

    ok_form = ("10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "40-F", "20-F/A")
    per = {}
    for f in facts:
        s, e, v = f.get("start"), f.get("end"), f.get("val")
        if s is None or e is None or v is None:
            continue
        if str(f.get("form", "")) not in ok_form:
            continue
        try:
            s = pd.Timestamp(s); e = pd.Timestamp(e); v = float(v)
        except Exception:
            continue
        d = (e - s).days
        if d < 55 or d > 400:
            continue
        filed = str(f.get("filed") or e.date())
        cur = per.get((s, e))
        if cur is None or filed >= cur[1]:      # 정정 공시가 있으면 최신 것을 쓴다
            per[(s, e)] = (v, filed)

    q, ann = {}, {}
    for (s, e), (v, filed) in per.items():
        d = (e - s).days
        if 55 <= d <= 130:
            cur = q.get(e)
            if cur is None or filed >= cur[1]:
                q[e] = (v, filed)
        elif 330 <= d <= 400:
            ann[(s, e)] = (v, filed)

    # 4분기 값을 따로 공시하지 않는 회사는 (연간 - 앞의 세 분기)로 채운다
    for (s, e), (v, filed) in sorted(ann.items()):
        if e in q:
            continue
        inside = [q[k][0] for k in list(q) if s < k < e]
        if len(inside) == 3:
            q[e] = (v - sum(inside), filed)
    return q

def eps_ttm(qmap):
    """분기 EPS -> 최근 12개월 EPS 시계열(공시일 기준)."""
    ends = sorted(qmap)
    out = {}
    for i in range(3, len(ends)):
        win = ends[i - 3:i + 1]
        span = (win[-1] - win[0]).days
        if span < 230 or span > 320:            # 4개 분기가 이어져 있어야 한다
            continue
        val = sum(qmap[e][0] for e in win)
        avail = max([pd.Timestamp(qmap[e][1]) for e in win] + [win[-1]])
        out[avail] = val                        # 실제로 알 수 있게 된 날짜에 반영
    if not out:
        return pd.Series(dtype=float)
    s = pd.Series(list(out.values()),
                  index=pd.DatetimeIndex(list(out.keys()))).sort_index()
    return s[~s.index.duplicated(keep="last")]

def split_factor(splits, dates):
    """각 날짜 이후에 일어난 액면분할 비율의 누적곱.
       SEC의 EPS는 당시 공시값이라 이후 분할만큼 나눠 줘야 주가와 기준이 맞는다."""
    idx = pd.DatetimeIndex(dates)
    if splits is None or len(splits) == 0:
        return pd.Series(1.0, index=idx)
    s = splits.sort_index()
    cum = s[::-1].cumprod()[::-1]
    pos = cum.index.searchsorted(idx, side="right")
    vals = [float(cum.iloc[p]) if p < len(cum) else 1.0 for p in pos]
    return pd.Series(vals, index=idx)

def compute_pe(df, qmap, today):
    """10년 PER 밴드 계산."""
    if df is None or df.empty or "Close" not in df:
        return None
    px = pd.to_numeric(df["Close"], errors="coerce").dropna()
    px.index = to_naive(px.index)
    px = px.groupby(px.index).last().sort_index()
    if len(px) < 250:
        return None

    sp = pd.Series(dtype=float)
    if "Stock Splits" in df:
        sp = pd.to_numeric(df["Stock Splits"], errors="coerce").fillna(0.0)
        sp.index = to_naive(sp.index)
        sp = sp[(sp > 0) & (sp != 1.0)]
        sp = sp.groupby(sp.index).prod().sort_index()

    ttm = eps_ttm(qmap)
    if ttm.empty:
        return None
    if (pd.Timestamp(today) - ttm.index[-1]).days > 420:   # 1년 넘게 공시가 끊긴 경우
        return None

    eps = (ttm / split_factor(sp, ttm.index)).sort_index()
    e = eps.reindex(px.index, method="ffill")
    per = (px / e).where(e > 0)
    per = per.replace([np.inf, -np.inf], np.nan).dropna()
    per = per[(per > 0) & (per < PE_MAX)]
    if per.empty:
        return None

    per = per[per.index >= per.index[-1] - pd.Timedelta(days=365.25 * HISTORY_YEARS)]
    pw = per.resample("W").last().dropna()
    if len(pw) < MIN_YEARS * 52:
        return None

    last_eps = e.iloc[-1]
    cur_eps = float(last_eps) if pd.notna(last_eps) else 0.0
    cur_px = float(px.iloc[-1])
    if cur_eps <= 0:                       # 적자 기업은 PER을 쓰지 않는다
        return None
    cur_pe = cur_px / cur_eps
    if cur_pe <= 0 or cur_pe >= PE_MAX:
        return None

    pct = float((pw < cur_pe).mean() * 100.0)
    label, band = next((l, b) for th, l, b in PE_BANDS if pct < th)
    yrs = min((pw.index[-1] - pw.index[0]).days / 365.25, float(HISTORY_YEARS))
    return {
        "pe":    round(cur_pe, 1),
        "peps":  round(cur_eps, 4),
        "pe10":  round(float(np.percentile(pw, 10)), 1),
        "pe25":  round(float(np.percentile(pw, 25)), 1),
        "pe50":  round(float(np.percentile(pw, 50)), 1),
        "pe75":  round(float(np.percentile(pw, 75)), 1),
        "pe90":  round(float(np.percentile(pw, 90)), 1),
        "peavg": round(float(np.mean(pw)), 1),
        "pepct": round(pct, 1),
        "peband": band,
        "pebandLabel": label,
        "peyrs": round(yrs, 1),
    }

def fetch_eps_map(sym, cik_map):
    """티커 하나의 분기 EPS 사전을 SEC에서 받아온다."""
    cik = cik_map.get(sym) or cik_map.get(sym.replace("-", ".")) \
        or cik_map.get(sym.replace(".", "-"))
    if not cik:
        return None
    best = None
    for ns, tag in EPS_CONCEPTS:
        js = sec_get(CONCEPT_URL.format(cik=cik, ns=ns, tag=tag), tries=2)
        time.sleep(SEC_PAUSE)
        if not js:
            continue
        q = eps_quarters(js)
        if len(q) >= 12:
            return q
        if q and (best is None or len(q) > len(best)):
            best = q
    return best

# ----------------------------------------------------------- 데이터 수집
def to_naive(idx):
    idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return idx

def fetch_all(tickers):
    frames, missing = {}, []
    print(f"[수집] {START_DATE} 이후 데이터를 내려받습니다.")
    for i in range(0, len(tickers), CHUNK):
        part = tickers[i:i + CHUNK]
        print(f"  다운로드 {i + 1}~{i + len(part)} / {len(tickers)}")
        try:
            raw = yf.download(part, start=START_DATE, interval="1d",
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
                df = yf.Ticker(t).history(start=START_DATE, interval="1d",
                                          auto_adjust=False, actions=True)
                if df is not None and not df.empty:
                    frames[t] = df
                else:
                    again.append(t)
            except Exception:
                again.append(t)
            time.sleep(1.2)
        missing = again
    if missing:
        print("[수집 실패 목록]", " ".join(sorted(missing)))
    print(f"[수집] 성공 {len(frames)}종목 / 실패 {len(missing)}종목")
    return frames

# ----------------------------------------------------------- 배당 주기 · 연환산
def detect_freq(dv):
    d = dv[dv.index >= dv.index[-1] - pd.Timedelta(days=1100)]
    if len(d) < 3:
        d = dv
    if len(d) < 2:
        return 1
    gaps = d.index.to_series().diff().dt.days.dropna()
    gaps = gaps[gaps > 3]
    if gaps.empty:
        return 1
    g = float(gaps.median())
    return min([1, 2, 4, 12], key=lambda f: abs(g - 365.25 / f))

def annualized(dv, idx, freq):
    rolled = dv.rolling(freq, min_periods=freq).sum()
    a = rolled.reindex(idx, method="ffill")
    last = pd.Series(dv.index, index=dv.index).reindex(idx, method="ffill")
    gap = (pd.Series(idx, index=idx) - last).dt.days
    stale = gap > (365.25 / freq) * STALE_FACTOR
    return a.where(~stale, 0.0).fillna(0.0)

# ----------------------------------------------------------- 배당 증가(유지) 기간
def dividend_streak(dv, today):
    if dv.empty:
        return 0
    yr_sum = dv.groupby(dv.index.year).sum()
    yr_cnt = dv.groupby(dv.index.year).size()
    yr_sum = yr_sum[yr_sum.index < today.year]
    yr_cnt = yr_cnt[yr_cnt.index < today.year]
    if len(yr_sum) < 2:
        return 0
    if int(max(yr_sum.index)) < today.year - 1:
        return 0
    pos = yr_cnt[yr_cnt > 0]
    modal = int(pos.median()) if not pos.empty else 0
    norm = {}
    for y in yr_sum.index:
        s, c = float(yr_sum[y]), int(yr_cnt[y])
        if modal > 0 and c > 0 and c != modal:
            s = s / c * modal
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
BANDS = [(10, "매우 고평가", -2), (30, "고평가", -1), (70, "중립", 0),
         (90, "저평가", 1), (101, "매우 저평가", 2)]

def analyze(sym, meta, df, today):
    if df is None or df.empty or "Close" not in df or "Dividends" not in df:
        return None
    px = pd.to_numeric(df["Close"], errors="coerce").dropna()
    dv = pd.to_numeric(df["Dividends"], errors="coerce").fillna(0.0)
    px.index, dv.index = to_naive(px.index), to_naive(dv.index)
    dv = dv[dv > 0]
    dv = dv.groupby(dv.index).sum().sort_index()
    px = px.groupby(px.index).last().sort_index()
    if len(px) < 250 or dv.empty:
        return None
    idx = px.index.union(dv.index).sort_values()
    p = px.reindex(idx).ffill()
    freq = detect_freq(dv)
    ann = annualized(dv, idx, freq)
    y = (ann / p * 100.0).replace([np.inf, -np.inf], np.nan).dropna()
    y = y[(y > 0) & (y < MAX_YIELD)]
    if y.empty:
        return None
    y = y[y.index >= y.index[-1] - pd.Timedelta(days=365.25 * HISTORY_YEARS)]
    yw = y.resample("W").last().dropna()
    if len(yw) < MIN_YEARS * 52:
        return None
    cur_p = float(p.iloc[-1])
    cur_ann = float(ann.iloc[-1])
    if cur_p <= 0 or cur_ann <= 0:
        return None
    cur_y = cur_ann / cur_p * 100.0
    if cur_y <= 0 or cur_y >= MAX_YIELD:
        return None
    pct = float((yw < cur_y).mean() * 100.0)
    label, band = next((l, b) for th, l, b in BANDS if pct < th)
    yrs = min((yw.index[-1] - yw.index[0]).days / 365.25, float(HISTORY_YEARS))
    return {
        "sym": sym,
        "name": meta["name"],
        "sec": meta["sec"],
        "idx": meta["idx"],
        "etf": meta["etf"],
        "px": round(cur_p, 2),
        "ttm": round(cur_ann, 4),
        "y": round(cur_y, 2),
        "y10": round(float(np.percentile(yw, 10)), 2),
        "y25": round(float(np.percentile(yw, 25)), 2),
        "y50": round(float(np.percentile(yw, 50)), 2),
        "y75": round(float(np.percentile(yw, 75)), 2),
        "y90": round(float(np.percentile(yw, 90)), 2),
        "pct": round(pct, 1),
        "band": band,
        "bandLabel": label,
        "freq": freq,
        "streak": dividend_streak(dv, today),
        "yrs": round(yrs, 1),
    }

# ----------------------------------------------------------- 실행
def main():
    today = dt.date.today()
    uni = build_universe()
    if len(uni) < 200:
        raise SystemExit("종목 목록을 가져오지 못했습니다. 잠시 후 다시 실행하세요.")

    # 해자 등급을 먼저 받아둔다. 실패해도 빌드는 계속한다.
    prev_moat = load_prev_moat()
    try:
        moat_map = fetch_moat_map()
    except Exception as e:
        print("[해자] 전체 실패:", e)
        moat_map = {}
    if len(moat_map) < 1000:
        print(f"[해자] 결과가 부족합니다({len(moat_map)}개). 직전 데이터를 사용합니다.")
        moat_map = {}

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

    # 섹터 한글화 + 해자 등급 결합
    n_moat = 0
    for it in items:
        if str(it["sec"]).strip() in ("", "-", "nan", "None"):
            try:
                s = yf.Ticker(it["sym"]).info.get("sector")
                it["sec"] = s if s else ""
            except Exception:
                it["sec"] = ""
            time.sleep(0.4)
        it["sec"] = ko_sector(it["sec"])

        info = lookup_moat(it["sym"], moat_map) if moat_map else prev_moat.get(it["sym"], {})
        it["moat"]  = info.get("moat")
        it["qmoat"] = info.get("qmoat")
        it["star"]  = info.get("star")
        if it["moat"]:
            n_moat += 1

    # PER 밴드 (SEC EDGAR)
    prev_pe = load_prev_pe()
    try:
        cik_map = fetch_cik_map()
    except Exception as e:
        print("[PER] 티커 목록 실패:", e)
        cik_map = {}

    n_pe, n_stale, done = 0, 0, 0
    targets = [x for x in items if not x["etf"]]
    print(f"[PER] {len(targets)}종목 계산 시작")
    for it in targets:
        sym = it["sym"]
        blk = None
        if cik_map:
            try:
                qmap = fetch_eps_map(sym, cik_map)
                if qmap:
                    blk = compute_pe(frames.get(sym), qmap, today)
            except Exception as e:
                print("   PER 실패", sym, e)
        if blk is None:
            old = prev_pe.get(sym)
            if old and old.get("peps"):
                blk = {k: old.get(k) for k in PE_KEYS}
                try:
                    blk["pe"] = round(float(it["px"]) / float(old["peps"]), 1)
                except Exception:
                    pass
                blk["pestale"] = True
                n_stale += 1
        if blk:
            it.update(blk)
            n_pe += 1
        done += 1
        if done % 50 == 0:
            print(f"  PER 진행 {done}/{len(targets)} · 성공 {n_pe}")

    if len(items) < 100:
        raise SystemExit(f"수집 결과가 너무 적습니다({len(items)}개). 다시 실행하세요.")

    short = sum(1 for x in items if x["yrs"] < 9.5)
    wide = sum(1 for x in items if x.get("moat") == "Wide")
    narrow = sum(1 for x in items if x.get("moat") == "Narrow")
    none_ = sum(1 for x in items if x.get("moat") == "None")
    print(f"[점검] 이력 10년 미만: {short}개 / 전체 {len(items)}개")
    print(f"[해자] 등급 있음 {n_moat}개 · 넓음 {wide} · 좁음 {narrow} · 없음 {none_}")
    print(f"[PER] 값 있음 {n_pe}개 / 대상 {len(targets)}개 (직전 EPS 재사용 {n_stale}개)")

    for chk in ("AAPL", "PFE", "KO", "BF-B", "MRSH", "SCHD", "JEPQ"):
        hit = next((x for x in items if x["sym"] == chk), None)
        if hit:
            print(f"[확인] {chk} {hit['name']} · {hit['sec']} · 수익률 {hit['y']}% · "
                  f"백분위 {hit['pct']} · 유지 {hit['streak']}년 · "
                  f"해자 {hit.get('moat') or '-'} (퀀트 {hit.get('qmoat')}) · "
                  f"PER {hit.get('pe') or '-'} (10년중앙 {hit.get('pe50') or '-'} · "
                  f"백분위 {hit.get('pepct') if hit.get('pepct') is not None else '-'})")
        else:
            print(f"[확인] {chk} → 결과에 없음")

    items.sort(key=lambda x: -x["pct"])
    os.makedirs("data", exist_ok=True)
    kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    payload = {
        "updated": kst.strftime("%Y-%m-%d %H:%M KST"),
        "universe": len(uni),
        "count": len(items),
        "peCount": n_pe,
        "items": items,
    }
    with open("data/screener_us.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[완료] {len(items)}종목 저장")

if __name__ == "__main__":
    main()
