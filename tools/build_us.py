#!/usr/bin/env python3
"""4차시용 미국 주식·환율 자료 만들기

야후 파이낸스(yfinance 라이브러리)에서
  1) 미국 대표 회사 후보들의 시가총액을 받아 TOP10을 정하고
  2) TOP10 + tools/us_list.txt 에 적은 종목(ETF, 코인, 금 포함)의 월말 종가(달러)와
  3) 월말 원/달러 환율
을 받아 data/us.json 과 js/us-data.js 로 저장합니다.

사용법
  pip install yfinance requests
  python tools/build_us.py                 (기준일 = 지난달 말)
  python tools/build_us.py --asof 20260930

참고
  - API 키가 필요 없습니다. 야후 파이낸스는 공식 API가 아니어서 가끔 '요청이 너무 많다'며 막힐 수 있습니다.
    이때는 몇 분 뒤 다시 실행하세요. (스크립트가 자동으로 3번까지 다시 시도합니다)
  - 가격은 액면분할이 반영된 종가(Close)이고 배당금은 넣지 않았습니다. (국내 주식 자료와 같은 기준)
  - 환율은 야후의 KRW=X(원/달러)를 쓰고, 실패하면 미국 연방준비제도(FRED)의 DEXKOUS 자료를 씁니다.
"""
import argparse, datetime as dt, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 시가총액 TOP10을 고를 후보 (미국 상장 미국 회사). 빠진 회사가 있으면 여기에 추가하세요.
CANDIDATES = [
    ("AAPL", "애플"), ("MSFT", "마이크로소프트"), ("NVDA", "엔비디아"), ("AMZN", "아마존"),
    ("GOOGL", "알파벳(구글)"), ("META", "메타(페이스북)"), ("AVGO", "브로드컴"), ("TSLA", "테슬라"),
    ("BRK-B", "버크셔 해서웨이"), ("LLY", "일라이 릴리"), ("JPM", "JP모건"), ("V", "비자"),
    ("WMT", "월마트"), ("ORCL", "오라클"), ("MA", "마스터카드"), ("XOM", "엑슨모빌"),
    ("NFLX", "넷플릭스"), ("COST", "코스트코"), ("UNH", "유나이티드헬스"), ("JNJ", "존슨앤드존슨"),
    ("PLTR", "팔란티어"), ("AMD", "AMD"), ("HD", "홈디포"), ("PG", "P&G"), ("BAC", "뱅크오브아메리카"),
]


def read_list(path):
    """us_list.txt : '티커 이름 [종류]'  (종류: 주식/ETF/코인/금, 생략하면 주식)"""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tk = parts[0].upper()
        kind = "주식"
        if parts[-1] in ("주식", "ETF", "코인", "금") and len(parts) > 2:
            kind = parts[-1]
            parts = parts[:-1]
        name = " ".join(parts[1:]) or tk
        out.append((tk, name, kind))
    return out


def month_end(asof):
    return asof.strftime("%Y-%m")


def with_retry(fn, what, tries=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # yfinance는 여러 종류의 오류를 냄
            msg = str(e)
            print("  [재시도 %d/%d] %s : %s" % (i + 1, tries, what, msg[:160]))
            if i == tries - 1:
                raise
            time.sleep(30 * (i + 1))


def monthly_close(yf, pd, tickers, start, end):
    """일별 종가를 받아 매달 마지막 값으로 바꿈 → {티커: pandas.Series(YYYY-MM → 값)}"""
    df = with_retry(lambda: yf.download(tickers, start=start, end=end, interval="1d",
                                        auto_adjust=False, progress=False, threads=True),
                    "가격 받기")
    if df is None or len(df) == 0:
        return {}
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"]
    else:
        close = df[["Close"]].rename(columns={"Close": tickers[0]})
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    out = {}
    for tk in close.columns:
        s = close[tk].dropna()
        if s.empty:
            continue
        try:
            m = s.resample("ME").last()
        except ValueError:
            m = s.resample("M").last()
        m = m.dropna()
        m.index = [d.strftime("%Y-%m") for d in m.index]
        out[str(tk)] = m
    return out


def market_caps(yf, tickers):
    caps = {}
    for tk in tickers:
        cap = None
        try:
            fi = yf.Ticker(tk).fast_info
            for k in ("market_cap", "marketCap"):
                try:
                    cap = getattr(fi, k) if hasattr(fi, k) else fi[k]
                except Exception:
                    cap = None
                if cap:
                    break
        except Exception:
            cap = None
        if not cap:
            try:
                cap = yf.Ticker(tk).info.get("marketCap")
            except Exception:
                cap = None
        if cap:
            caps[tk] = float(cap)
        else:
            print("  [시가총액 없음] %s" % tk)
        time.sleep(0.3)
    return caps


def fx_from_fred(start, end):
    import requests
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    last = {}
    for line in r.text.splitlines()[1:]:
        d, _, v = line.partition(",")
        if not re.match(r"\d{4}-\d{2}-\d{2}", d) or v.strip() in ("", "."):
            continue
        if not (start <= d < end):
            continue
        last[d[:7]] = float(v)   # 날짜 순서대로 덮어써서 그 달 마지막 값이 남음
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=None, help="기준일 YYYYMMDD (기본: 지난달 말일)")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--list", default=os.path.join(ROOT, "tools", "us_list.txt"))
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        sys.exit("yfinance 가 없습니다.  pip install yfinance requests  후 다시 실행하세요.")

    if a.asof:
        asof = dt.datetime.strptime(a.asof, "%Y%m%d").date()
    else:
        asof = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    end = (asof + dt.timedelta(days=1)).isoformat()
    last_m = month_end(asof)
    print("기준일:", asof, "/ 기간:", a.start, "~", asof)

    print("1) 시가총액 받는 중 (후보 %d개)" % len(CANDIDATES))
    caps = market_caps(yf, [t for t, _ in CANDIDATES])
    names = dict(CANDIDATES)
    top = sorted(caps, key=lambda t: -caps[t])[:a.top]
    ranking = [{"rank": i + 1, "code": t, "name": names[t], "mcap": round(caps[t] / 1e9, 1)} for i, t in enumerate(top)]
    for r in ranking:
        print("   %2d. %-6s %-12s 약 %s억 달러" % (r["rank"], r["code"], r["name"], format(round(r["mcap"] * 10), ",")))
    if len(ranking) < 5:
        print("  [주의] 시가총액을 거의 받지 못했습니다. 순위 없이 목록만 저장합니다.")

    items = [(t, names[t], "주식") for t in top]
    for tk, nm, kind in read_list(a.list):
        if tk not in [x[0] for x in items]:
            items.append((tk, nm, kind))
    tickers = [x[0] for x in items]
    print("2) 월말 종가 받는 중 (%d개): %s" % (len(tickers), " ".join(tickers)))
    closes = monthly_close(yf, pd, tickers, a.start, end)

    print("3) 원/달러 환율 받는 중")
    fx = {}
    try:
        m = monthly_close(yf, pd, ["KRW=X"], a.start, end).get("KRW=X")
        if m is not None:
            fx = {k: float(v) for k, v in m.items()}
        fx_src = "Yahoo Finance KRW=X (월말)"
    except Exception as e:
        print("  야후 환율 실패:", str(e)[:120])
    if len(fx) < 12:
        print("  → FRED(미국 연방준비제도) DEXKOUS 로 다시 받습니다.")
        fx = fx_from_fred(a.start, end)
        fx_src = "FRED DEXKOUS (월말)"
    if len(fx) < 12:
        sys.exit("환율 자료를 받지 못했습니다. 잠시 뒤 다시 실행하세요. (기존 파일은 그대로 둡니다)")

    months = sorted(set(k for s in closes.values() for k in s.index) | set(fx))
    months = [m for m in months if m <= last_m]
    fx_list, prev = [], None
    for m in months:
        prev = fx.get(m, prev)
        fx_list.append(round(prev, 2) if prev else None)

    companies = {}
    for tk, nm, kind in items:
        s = closes.get(tk)
        if s is None or len(s) == 0:
            print("  [실패] %s %s : 가격 자료 없음 (티커 확인)" % (tk, nm))
            continue
        s = s[[m for m in s.index if m <= last_m]]
        first = months.index(s.index[0])
        vals, prev = [], None
        for m in months[first:months.index(s.index[-1]) + 1]:
            prev = float(s[m]) if m in s.index else prev
            vals.append(round(prev, 4 if prev < 10 else 2))
        if len(vals) < 13:
            print("  [건너뜀] %s : 자료가 1년 미만" % tk)
            continue
        companies[tk] = {"name": nm, "kind": kind, "s": first, "p": vals}
        print("   %-8s %-16s %s ~ %s (%d개월) %s" % (tk, nm, months[first], months[first + len(vals) - 1], len(vals), kind))

    out = {"generatedAt": dt.date.today().isoformat(), "asof": asof.strftime("%Y%m%d"),
           "source": "Yahoo Finance (yfinance)", "fxSource": fx_src,
           "note": "월말 종가(달러), 액면분할 반영, 배당 미포함. 환율은 월말 원/달러",
           "months": months, "fx": fx_list, "ranking": [r for r in ranking if r["code"] in companies],
           "companies": companies}
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    oj, ojs = os.path.join(ROOT, "data", "us.json"), os.path.join(ROOT, "js", "us-data.js")
    os.makedirs(os.path.dirname(oj), exist_ok=True)
    os.makedirs(os.path.dirname(ojs), exist_ok=True)
    open(oj, "w", encoding="utf-8").write(text)
    open(ojs, "w", encoding="utf-8").write("window.US_DATA=" + text + ";\n")
    print("저장 완료: %s / %s (종목 %d개, 환율 %d개월, %s)" % (oj, ojs, len(companies), len(fx), fx_src))


if __name__ == "__main__":
    main()
