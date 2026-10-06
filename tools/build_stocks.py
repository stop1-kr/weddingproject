#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3차시용 주가 자료 만들기 (선생님이 한 번만 실행)

공공데이터포털 「금융위원회_주식시세정보」 API에서
  1) 기준일(기본 2026-09-30)의 시가총액 상위 10개 회사
  2) 그 회사들 + tools/extra_companies.txt 에 적은 회사들의 2010-01 ~ 기준월 월말 종가
를 받아 data/stocks.json 과 js/stocks-data.js 로 저장합니다.

사용법
  python tools/build_stocks.py --key 발급받은_서비스키
  (또는 환경변수 DATA_GO_KR_KEY 에 키를 넣어 두고  python tools/build_stocks.py )

참고
  - 가격은 '월말 종가'이며, 액면분할·병합은 자동으로 보정합니다. 배당금은 포함하지 않습니다.
  - API가 제공하는 자료의 시작 시점이 2010-01보다 늦으면, 있는 기간만 저장됩니다.
"""
import argparse, json, os, re, sys, time, datetime as dt
from urllib.parse import unquote

try:
    import requests
except ImportError:
    sys.exit("requests 라이브러리가 필요합니다.  pip install requests")

BASE = "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo"
PREF = re.compile(r"\d?우[A-C]?(\(전환\))?$")      # 우선주 이름 끝 (예: 삼성전자우, 현대차2우B)
SPLIT_THRESHOLD = 0.31                              # 하루 변동이 이 값보다 크면 액면분할/병합으로 보고 보정
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def call(params, key, retries=4):
    p = {"serviceKey": key, "resultType": "json"}
    p.update(params)
    last = None
    for t in range(retries):
        try:
            r = requests.get(BASE, params=p, timeout=60)
            try:
                js = r.json()
            except ValueError:
                raise RuntimeError("JSON이 아닌 응답입니다(서비스키 오류일 수 있음): " + r.text[:300])
            resp = js.get("response", js)
            header = resp.get("header", {})
            if header.get("resultCode") not in (None, "00"):
                raise RuntimeError("API 오류: %s %s" % (header.get("resultCode"), header.get("resultMsg")))
            body = resp.get("body", {})
            total = int(body.get("totalCount", 0) or 0)
            items = (body.get("items") or {})
            items = items.get("item", []) if isinstance(items, dict) else []
            if isinstance(items, dict):
                items = [items]
            return items, total
        except Exception as e:                      # 잠깐 실패하면 다시 시도
            last = e
            time.sleep(1.5 * (t + 1))
    raise RuntimeError(str(last))


def fetch_all(key, params, rows=1000):
    out, page = [], 1
    while True:
        items, total = call(dict(params, numOfRows=rows, pageNo=page), key)
        out += items
        if not items or len(out) >= total:
            break
        page += 1
        time.sleep(0.15)
    return out


def find_asof(key, asof):
    d = dt.datetime.strptime(asof, "%Y%m%d").date()
    for _ in range(12):
        s = d.strftime("%Y%m%d")
        _, total = call({"basDt": s, "numOfRows": 1, "pageNo": 1}, key)
        if total > 0:
            return s
        d -= dt.timedelta(days=1)
    raise RuntimeError("기준일 근처에 거래 자료가 없습니다: " + asof)


def norm_code(s):
    s = re.sub(r"\D", "", str(s or ""))
    return s[-6:] if len(s) >= 6 else s


def adjust_splits(daily):
    """daily: [(YYYYMMDD, close)] 오름차순 -> (보정된 daily, 보정 이벤트 목록)"""
    n = len(daily)
    factors = [1.0] * n
    events = []
    for i in range(1, n):
        r = daily[i][1] / daily[i - 1][1]
        if abs(r - 1) > SPLIT_THRESHOLD:
            events.append((daily[i][0], r))
            for j in range(i):
                factors[j] *= r
    return [(d, c * f) for (d, c), f in zip(daily, factors)], events


def month_ends(daily):
    m = {}
    for d, c in daily:
        m[d[:6]] = c                                 # 오름차순이므로 그 달의 마지막 거래일이 남음
    keys = sorted(m)
    return [k[:4] + "-" + k[4:] for k in keys], [round(m[k], 4) for k in keys]


def fetch_history(key, code, start, end):
    rows = fetch_all(key, {"likeSrtnCd": code, "beginBasDt": start, "endBasDt": end})
    seen = {}
    for r in rows:
        if norm_code(r.get("srtnCd")) != code:
            continue
        try:
            c = float(r["clpr"])
        except (KeyError, ValueError, TypeError):
            continue
        if c > 0:
            seen[str(r["basDt"])] = c
    daily = sorted(seen.items())
    if len(daily) < 24:
        raise RuntimeError("%s: 자료가 너무 적습니다(%d일)" % (code, len(daily)))
    adj, events = adjust_splits(daily)
    months, prices = month_ends(adj)
    return months, prices, events


def read_extras(path):
    if not os.path.exists(path):
        return []
    names = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("DATA_GO_KR_KEY", ""))
    ap.add_argument("--asof", default="20260930", help="시가총액 순위 기준일 YYYYMMDD (기본 20260930)")
    ap.add_argument("--start", default="20100101", help="가격 시작일 YYYYMMDD")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--include-preferred", action="store_true", help="우선주도 순위에 포함")
    ap.add_argument("--extras", default=os.path.join(ROOT, "tools", "extra_companies.txt"))
    ap.add_argument("--out-json", default=os.path.join(ROOT, "data", "stocks.json"))
    ap.add_argument("--out-js", default=os.path.join(ROOT, "js", "stocks-data.js"))
    a = ap.parse_args()
    key = unquote(a.key.strip())
    if not key:
        sys.exit("서비스키가 없습니다. --key 로 넣거나 환경변수 DATA_GO_KR_KEY 를 설정하세요.")

    asof = find_asof(key, a.asof)
    print("기준일:", asof)
    rows = fetch_all(key, {"basDt": asof})
    rows = [r for r in rows if r.get("mrktCtg") in ("KOSPI", "KOSDAQ")]
    print("상장 종목 수:", len(rows))
    cands = rows if a.include_preferred else [r for r in rows if not PREF.search(r.get("itmsNm", ""))]
    cands.sort(key=lambda r: -int(float(r.get("mrktTotAmt", 0) or 0)))
    top = cands[:a.top]

    ranking, codes = [], []
    for i, r in enumerate(top, 1):
        code = norm_code(r["srtnCd"])
        ranking.append({"rank": i, "code": code, "name": r["itmsNm"], "market": r["mrktCtg"],
                        "cap": int(float(r["mrktTotAmt"])), "close": int(float(r["clpr"]))})
        codes.append((code, r["itmsNm"], r["mrktCtg"]))

    by_name = {}
    for r in rows:
        by_name.setdefault(r["itmsNm"], []).append(r)
    for nm in read_extras(a.extras):
        hit = by_name.get(nm)
        if not hit:
            near = [k for k in by_name if nm in k][:5]
            print("  [건너뜀] '%s' 이름이 기준일 자료에 없습니다. 비슷한 이름: %s" % (nm, near))
            continue
        r = max(hit, key=lambda x: int(float(x.get("mrktTotAmt", 0) or 0)))
        c = norm_code(r["srtnCd"])
        if c not in [x[0] for x in codes]:
            codes.append((c, r["itmsNm"], r["mrktCtg"]))

    end = asof
    companies = {}
    for code, name, market in codes:
        try:
            months, prices, events = fetch_history(key, code, a.start, end)
        except Exception as e:
            print("  [실패] %s %s: %s" % (code, name, e))
            continue
        companies[code] = {"name": name, "market": market, "months": months, "prices": prices}
        ev = ", ".join("%s(x%.4f)" % (d, r) for d, r in events) or "없음"
        print("  %s %-14s %s ~ %s (%d개월)  분할/병합 보정: %s" % (code, name, months[0], months[-1], len(months), ev))
        if events:
            companies[code]["adjusted"] = [[d, round(r, 6)] for d, r in events]
        time.sleep(0.2)

    ranking = [r for r in ranking if r["code"] in companies] or ranking
    out = {
        "demo": False,
        "generatedAt": dt.date.today().isoformat(),
        "asof": asof,
        "source": "금융위원회_주식시세정보 (공공데이터포털)",
        "note": "월말 종가 기준, 액면분할·병합 보정, 배당금 미포함",
        "ranking": ranking,
        "companies": companies,
    }
    os.makedirs(os.path.dirname(a.out_json), exist_ok=True)
    os.makedirs(os.path.dirname(a.out_js), exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    open(a.out_json, "w", encoding="utf-8").write(text)
    open(a.out_js, "w", encoding="utf-8").write("window.STOCK_DATA=" + text + ";\n")
    print("저장 완료:", a.out_json, "/", a.out_js, "(회사 %d개)" % len(companies))


if __name__ == "__main__":
    main()
