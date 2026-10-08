#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3차시용 주가 자료 만들기 (선생님이 한 번만 실행)

공공데이터포털 「금융위원회_주식시세정보」 (V2) API에서
  1) 기준일(기본 2026-09-30)의 시가총액 상위 10개 회사
  2) 그 회사들 + tools/extra_companies.txt 에 적은 회사들의 2020-01 ~ 기준월 월말 종가
를 받아 data/stocks.json 과 js/stocks-data.js 로 저장합니다.

사용법
  python tools/build_stocks.py --key 일반_인증키
  (또는 환경변수 DATA_GO_KR_KEY 에 키를 넣어 두고  python tools/build_stocks.py )
  python tools/build_stocks.py --check      ← 자료는 만들지 않고 API 연결만 점검
  python tools/build_stocks.py --etf        ← 4차시용 ETF 자료 (tools/etf_list.txt 의 ETF) → data/etf.json, js/etf-data.js
  python tools/build_stocks.py --all        ← 코스피·코스닥 상장 회사 '전체'를 저장
                                              (extra_companies.txt 는 필요 없음, 호출 약 300~400건)

참고
  - 서비스 주소: https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2
  - 가격은 '월말 종가'이며, 액면분할·병합은 자동으로 보정합니다. 배당금은 포함하지 않습니다.
  - 이 API는 2020-01 무렵부터 자료가 있어서 시작일 기본값을 2020-01-01 로 둡니다.
  - --all 은 회사별로 받지 않고 '매달 마지막 거래일의 전 종목 시세'를 받아 만듭니다.
    액면분할·무상증자는 상장주식수 변화로 찾아 보정합니다. 스팩(기업인수목적회사)은 뺍니다.
  - 오류가 나면 API가 보낸 실제 오류 문구(인증키는 가린 채)를 그대로 보여 줍니다.
"""
import argparse, json, math, os, re, sys, time, datetime as dt
from urllib.parse import unquote

try:
    import requests
except ImportError:
    sys.exit("requests 라이브러리가 필요합니다.  pip install requests")

BASE = "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
# 4차시 ETF 자료 : 「금융위원회_증권상품시세정보」 (data.go.kr에서 따로 활용신청 필요, 같은 인증키 사용)
ETF_BASE = "https://apis.data.go.kr/1160100/service/GetSecuritiesProductInfoService/getETFPriceInfo"
PREF = re.compile(r"\d?우[A-C]?(\(전환\))?$")      # 우선주 이름 끝 (예: 삼성전자우, 현대차2우B)
SPLIT_THRESHOLD = 0.31                              # 하루 변동이 이 값보다 크면 액면분할/병합으로 보고 보정
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 다시 시도해도 소용없는 오류(인증키·신청 문제) → 바로 멈춤
FATAL_CODES = {"10", "11", "12", "20", "22", "30", "31", "32", "33"}
HELP = {
    "30": "인증키가 이 서비스에 등록되어 있지 않습니다. ① 시크릿에 넣은 키가 data.go.kr 「일반 인증키」와 같은지, "
          "② 앞뒤에 공백이 없는지 확인하세요.",
    "20": "서비스 접근이 거부되었습니다. data.go.kr에서 활용신청 상태가 '승인'인지 확인하세요.",
    "22": "하루 호출 한도(10,000건)를 넘었습니다. 내일 다시 실행하세요.",
    "31": "활용기간이 끝났습니다. data.go.kr에서 연장 신청을 하세요.",
    "32": "등록되지 않은 IP입니다.",
    "12": "서비스 주소가 없거나 폐기되었습니다. BASE 주소를 확인하세요.",
}

KEY_FOR_MASK = ""


def mask(text):
    text = str(text)
    if KEY_FOR_MASK:
        text = text.replace(KEY_FOR_MASK, "***인증키***")
    return re.sub(r"serviceKey=[^&\s\"']+", "serviceKey=***", text)


class ApiError(RuntimeError):
    def __init__(self, msg, code=None, fatal=False):
        RuntimeError.__init__(self, msg)
        self.code = code
        self.fatal = fatal


def explain(code, msg):
    s = "API 오류 (결과코드 %s): %s" % (code, msg)
    if str(code) in HELP:
        s += "\n  → " + HELP[str(code)]
    return s


def parse_xml_error(text):
    """인증키 오류 등은 JSON을 요청해도 XML로 돌아옴"""
    def tag(name):
        m = re.search(r"<%s>(.*?)</%s>" % (name, name), text, re.S)
        return m.group(1).strip() if m else None
    code = tag("returnReasonCode") or tag("resultCode")
    msg = tag("returnAuthMsg") or tag("errMsg") or tag("resultMsg")
    return code, msg


def field(r, *names, default=None):
    """V2에서 항목 이름이 바뀌어도 동작하도록 여러 이름을 차례로 확인"""
    for n in names:
        if n in r and r[n] not in (None, ""):
            return r[n]
    return default


def num(v, default=0.0):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


def call(params, key, retries=4, base=None):
    p = {"serviceKey": key, "resultType": "json"}
    p.update(params)
    last = None
    for t in range(retries):
        try:
            try:
                r = requests.get(base or BASE, params=p, timeout=60)
            except requests.exceptions.RequestException as e:
                raise ApiError("서버에 접속하지 못했습니다(네트워크/해외 접속 차단 가능성): %s" % mask(e))
            text = r.text
            try:
                js = r.json()
            except ValueError:
                code, msg = parse_xml_error(text)
                if code or msg:
                    raise ApiError(explain(code, msg), code, fatal=str(code) in FATAL_CODES)
                raise ApiError("JSON이 아닌 응답입니다 (HTTP %s): %s" % (r.status_code, mask(text[:300])),
                               fatal=r.status_code in (401, 403, 404))
            resp = js.get("response", js)
            header = resp.get("header", {}) or {}
            code = header.get("resultCode")
            if code not in (None, "00", "0"):
                raise ApiError(explain(code, header.get("resultMsg")), code, fatal=str(code) in FATAL_CODES)
            body = resp.get("body", {}) or {}
            total = int(num(body.get("totalCount", 0)))
            items = body.get("items") or {}
            items = items.get("item", []) if isinstance(items, dict) else (items if isinstance(items, list) else [])
            if isinstance(items, dict):
                items = [items]
            return items, total
        except ApiError as e:
            last = e
            if e.fatal:
                raise
            time.sleep(1.5 * (t + 1))                # 잠깐 실패하면 다시 시도
        except Exception as e:
            last = ApiError(mask(e))
            time.sleep(1.5 * (t + 1))
    raise last


def fetch_all(key, params, rows=1000, base=None):
    out, page = [], 1
    while True:
        items, total = call(dict(params, numOfRows=rows, pageNo=page), key, base=base)
        out += items
        if not items or len(out) >= total:
            break
        page += 1
        time.sleep(0.15)
    return out


def check(key, asof):
    """API 연결 점검: 실제 응답을 보여 줌 (기존 check_api.py 역할)"""
    print("== API 연결 점검 ==")
    print("주소:", BASE)
    print("인증키 길이: %d자 (앞 4자리 %s…)" % (len(key), key[:4]))
    for label, prm in [("기준일 " + asof, {"basDt": asof}), ("2020-01-31 (2020년 자료 확인)", {"basDt": "20200131"})]:
        try:
            items, total = call(dict(prm, numOfRows=3, pageNo=1), key, retries=1)
            print("[성공] %s: 전체 %d건" % (label, total))
            for it in items[:3]:
                print("   ", field(it, "basDt"), field(it, "srtnCd"), field(it, "itmsNm"),
                      "종가", field(it, "clpr"), "시총", field(it, "mrktTotAmt"))
            if items:
                print("    응답 항목 이름:", ", ".join(sorted(items[0].keys())))
        except ApiError as e:
            print("[실패] %s:\n  %s" % (label, e))
            return False
    return True


def find_asof(key, asof):
    d = dt.datetime.strptime(asof, "%Y%m%d").date()
    for _ in range(12):
        s = d.strftime("%Y%m%d")
        _, total = call({"basDt": s, "numOfRows": 1, "pageNo": 1}, key)   # 인증 오류면 여기서 바로 실제 문구로 멈춤
        if total > 0:
            return s
        d -= dt.timedelta(days=1)
    raise RuntimeError("API 연결은 정상인데 %s 이전 12일 동안 거래 자료가 없습니다. "
                       "--asof 날짜를 바꾸거나, 아직 자료가 올라오지 않았는지 확인하세요." % asof)


def norm_code(s):
    """단축코드 정리: 'A005930' → '005930'. 영문이 섞인 새 코드(예: 0126Z0)도 유지"""
    s = re.sub(r"[^0-9A-Za-z]", "", str(s or "")).upper()
    if len(s) == 7 and s[0] == "A":
        s = s[1:]
    return s


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


def collect(rows, code):
    seen = {}
    for r in rows:
        if norm_code(field(r, "srtnCd", "shotnIsin")) != code:
            continue
        c = num(field(r, "clpr", "clsPrc"), 0)
        d = re.sub(r"\D", "", str(field(r, "basDt", default="")))
        if c > 0 and len(d) == 8:
            seen[d] = c
    return seen


def fetch_history(key, code, start, end, isin=None):
    seen = collect(fetch_all(key, {"likeSrtnCd": code, "beginBasDt": start, "endBasDt": end}), code)
    if len(seen) < 24 and isin:                      # 단축코드 검색이 안 되면 ISIN 코드로 다시 시도
        seen.update(collect(fetch_all(key, {"isinCd": isin, "beginBasDt": start, "endBasDt": end}), code))
    daily = sorted(seen.items())
    if len(daily) < 24:
        raise RuntimeError("%s: 자료가 너무 적습니다(%d일)" % (code, len(daily)))
    adj, events = adjust_splits(daily)
    months, prices = month_ends(adj)
    return months, prices, events


# ---------------- --all : 상장 회사 전체 (월말 스냅숏 방식) ----------------
SPAC = re.compile(r"스팩")


def month_list(start, asof):
    y, m = int(start[:4]), int(start[4:6])
    ey, em = int(asof[:4]), int(asof[4:6])
    out = []
    while (y, m) <= (ey, em):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def last_trading_day(key, y, m, asof):
    """그 달의 마지막 거래일(자료가 있는 날)을 찾음"""
    if (y, m) == (int(asof[:4]), int(asof[4:6])):
        return asof
    d = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    for _ in range(12):
        s = d.strftime("%Y%m%d")
        _, total = call({"basDt": s, "numOfRows": 1, "pageNo": 1}, key)
        if total > 0:
            return s
        d -= dt.timedelta(days=1)
        if d.month != m:
            break
    return None


def shares_of(r):
    sh = num(field(r, "lstgStCnt", default=0))
    if sh <= 0:
        c = num(field(r, "clpr", "clsPrc"), 0)
        sh = num(field(r, "mrktTotAmt", default=0)) / c if c > 0 else 0
    return sh


def adjust_by_shares(closes, shares):
    """상장주식수가 크게 바뀌고 주가가 반대로 비슷하게 움직였으면 분할/병합/무상증자로 보고 보정"""
    n = len(closes)
    factors, events = [1.0] * n, []
    for i in range(1, n):
        if shares[i] <= 0 or shares[i - 1] <= 0:
            continue
        sr = shares[i] / shares[i - 1]
        pr = closes[i] / closes[i - 1]
        if (sr >= 1.3 or sr <= 1 / 1.3) and abs(math.log(pr) + math.log(sr)) < 0.5 * abs(math.log(sr)):
            events.append(i)
            for j in range(i):
                factors[j] /= sr
    return [c * f for c, f in zip(closes, factors)], events


def build_all(key, rows_asof, start, asof, include_preferred):
    universe = {}
    for r in rows_asof:
        nm = str(field(r, "itmsNm", default=""))
        if not include_preferred and PREF.search(nm):
            continue
        if SPAC.search(nm):
            continue
        universe[norm_code(field(r, "srtnCd"))] = (nm, str(field(r, "mrktCtg")).upper())
    print("전체 모드: 대상 회사 %d개 (우선주·스팩 제외)" % len(universe))

    months, snaps = [], []
    for y, m in month_list(start, asof):
        d = last_trading_day(key, y, m, asof)
        if not d:
            print("  %d-%02d: 거래일을 찾지 못해 건너뜀" % (y, m))
            continue
        snap = {}
        for r in fetch_all(key, {"basDt": d}):
            c = norm_code(field(r, "srtnCd", "shotnIsin"))
            if c in universe:
                p = num(field(r, "clpr", "clsPrc"), 0)
                if p > 0:
                    snap[c] = (p, shares_of(r))
        months.append("%d-%02d" % (y, m))
        snaps.append(snap)
        print("  %s (%s) 종목 %d개" % (months[-1], d, len(snap)))
        time.sleep(0.15)
    if not months:
        sys.exit("월말 자료를 하나도 받지 못했습니다.")

    companies, adjusted, short = {}, 0, 0
    for code, (name, market) in universe.items():
        idx = [i for i, s in enumerate(snaps) if code in s]
        if not idx:
            continue
        first, last = idx[0], idx[-1]
        closes, shares, prev = [], [], None
        for i in range(first, last + 1):            # 거래정지 등으로 빈 달은 직전 값으로 채움
            prev = snaps[i].get(code, prev)
            closes.append(prev[0])
            shares.append(prev[1])
        if len(closes) < 13:                          # 1년 이상 자료가 있어야 분석 가능
            short += 1
            continue
        adj, ev = adjust_by_shares(closes, shares)
        if ev:
            adjusted += 1
        companies[code] = {"name": name, "market": market, "s": first,
                           "p": [round(v) if v >= 1000 else round(v, 2) for v in adj]}
    print("저장할 회사 %d개 (자료 1년 미만 %d개 제외, 분할·무상증자 보정 %d개)" % (len(companies), short, adjusted))
    return companies, months


def build_etf(key, a, asof):
    names = read_extras(a.etf_list)
    if not names:
        sys.exit("ETF 목록이 비어 있습니다: %s" % a.etf_list)
    print("ETF 시세 주소:", a.etf_url)
    try:
        test = fetch_all(key, {"basDt": asof}, base=a.etf_url)
    except ApiError as e:
        print("\n[중단] ETF 시세를 받지 못했습니다.\n  " + mask(e))
        print("  → data.go.kr 에서 「금융위원회_증권상품시세정보」를 활용신청했는지 확인하세요. (주식 시세와 별도 신청)")
        sys.exit(1)
    by_name = {}
    for r in test:
        by_name.setdefault(str(field(r, "itmsNm", default="")).strip(), norm_code(field(r, "srtnCd", "shotnIsin")))
    want = {}
    for nm in names:
        if nm in by_name:
            want[by_name[nm]] = nm
        else:
            key_nm = nm.replace(" ", "")
            near = [k for k in by_name if key_nm.lower() in k.replace(" ", "").lower()][:5]
            print("  [건너뜀] '%s' 이름이 기준일 ETF 자료에 없습니다. 비슷한 이름: %s" % (nm, near))
    print("ETF %d개 자료 받는 중 (월말 자료)" % len(want))
    months, snaps = [], []
    for y, m in month_list(a.start, asof):
        d = last_trading_day(key, y, m, asof)
        if not d:
            continue
        snap = {}
        for r in fetch_all(key, {"basDt": d}, base=a.etf_url):
            c = norm_code(field(r, "srtnCd", "shotnIsin"))
            if c in want:
                p = num(field(r, "clpr", "clsPrc"), 0)
                sh = num(field(r, "stLstgCnt", "lstgStCnt", default=0))
                if sh <= 0 and p > 0:
                    sh = num(field(r, "mrktTotAmt", default=0)) / p
                if p > 0:
                    snap[c] = (p, sh)
        months.append("%d-%02d" % (y, m))
        snaps.append(snap)
        print("  %s (%s) ETF %d개" % (months[-1], d, len(snap)))
        time.sleep(0.15)
    etfs = {}
    for code, nm in want.items():
        idx = [i for i, s in enumerate(snaps) if code in s]
        if not idx:
            print("  [실패] %s: 월말 자료가 없습니다" % nm)
            continue
        closes, shares, prev = [], [], None
        for i in range(idx[0], idx[-1] + 1):
            prev = snaps[i].get(code, prev)
            closes.append(prev[0])
            shares.append(prev[1])
        if len(closes) < 13:
            print("  [건너뜀] %s: 자료가 1년 미만" % nm)
            continue
        adj, ev = adjust_by_shares(closes, shares)
        etfs[code] = {"name": nm, "s": idx[0], "p": [round(v) if v >= 1000 else round(v, 2) for v in adj]}
        print("  %s %-22s %s ~ %s (%d개월)%s" % (code, nm, months[idx[0]], months[idx[-1]], len(closes), "  분할 보정" if ev else ""))
    if not etfs:
        sys.exit("ETF 자료를 하나도 만들지 못했습니다. (기존 파일은 그대로 둡니다)")
    out = {"generatedAt": dt.date.today().isoformat(), "asof": asof,
           "source": "금융위원회_증권상품시세정보 (공공데이터포털)", "note": "월말 종가 기준, 분배금 미포함",
           "months": months, "etfs": etfs}
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    oj = os.path.join(ROOT, "data", "etf.json")
    ojs = os.path.join(ROOT, "js", "etf-data.js")
    os.makedirs(os.path.dirname(oj), exist_ok=True)
    os.makedirs(os.path.dirname(ojs), exist_ok=True)
    open(oj, "w", encoding="utf-8").write(text)
    open(ojs, "w", encoding="utf-8").write("window.ETF_DATA=" + text + ";\n")
    print("저장 완료:", oj, "/", ojs, "(ETF %d개)" % len(etfs))


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
    global KEY_FOR_MASK
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("DATA_GO_KR_KEY", ""))
    ap.add_argument("--asof", default="20260930", help="시가총액 순위 기준일 YYYYMMDD (기본 20260930)")
    ap.add_argument("--start", default="20200101", help="가격 시작일 YYYYMMDD")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--include-preferred", action="store_true", help="우선주도 순위에 포함")
    ap.add_argument("--check", action="store_true", help="자료는 만들지 않고 API 연결만 점검")
    ap.add_argument("--all", action="store_true", help="코스피·코스닥 상장 회사 전체를 월말 자료로 저장")
    ap.add_argument("--etf", action="store_true", help="4차시용 ETF 월말 자료 만들기 (tools/etf_list.txt)")
    ap.add_argument("--etf-url", default=ETF_BASE, help="ETF 시세 API 주소 (바뀌었을 때만)")
    ap.add_argument("--etf-list", default=os.path.join(ROOT, "tools", "etf_list.txt"))
    ap.add_argument("--extras", default=os.path.join(ROOT, "tools", "extra_companies.txt"))
    ap.add_argument("--out-json", default=os.path.join(ROOT, "data", "stocks.json"))
    ap.add_argument("--out-js", default=os.path.join(ROOT, "js", "stocks-data.js"))
    a = ap.parse_args()

    key = re.sub(r"\s", "", a.key or "")             # 복사할 때 섞인 공백·줄바꿈 제거
    if "%" in key:                                   # Encoding 키를 넣었으면 자동으로 Decoding
        key = unquote(key)
    if not key:
        sys.exit("서비스키가 없습니다. --key 로 넣거나 환경변수(GitHub 시크릿) DATA_GO_KR_KEY 를 설정하세요.")
    KEY_FOR_MASK = key

    if a.check:
        sys.exit(0 if check(key, a.asof) else 1)

    print("API 주소:", BASE)
    try:
        asof = find_asof(key, a.asof)
    except Exception as e:
        print("\n[중단] " + mask(e))
        print("  자세히 보려면:  python tools/build_stocks.py --check")
        sys.exit(1)
    print("기준일:", asof)

    if a.etf:
        build_etf(key, a, asof)
        return

    rows = fetch_all(key, {"basDt": asof})
    rows = [r for r in rows if str(field(r, "mrktCtg", default="")).upper() in ("KOSPI", "KOSDAQ")]
    print("상장 종목 수(코스피+코스닥):", len(rows))
    if not rows:
        sys.exit("기준일 자료에 코스피/코스닥 종목이 없습니다. 응답 항목 이름이 바뀌었을 수 있으니 --check 결과를 확인하세요.")
    cands = rows if a.include_preferred else [r for r in rows if not PREF.search(str(field(r, "itmsNm", default="")))]
    cap = lambda r: num(field(r, "mrktTotAmt", default=0))
    cands.sort(key=lambda r: -cap(r))
    top = cands[:a.top]

    ranking, codes = [], []
    for i, r in enumerate(top, 1):
        code = norm_code(field(r, "srtnCd"))
        name, market = field(r, "itmsNm"), str(field(r, "mrktCtg")).upper()
        ranking.append({"rank": i, "code": code, "name": name, "market": market,
                        "cap": int(cap(r)), "close": int(num(field(r, "clpr")))})
        codes.append((code, name, market, field(r, "isinCd")))
    print("시가총액 순위:")
    for x in ranking:
        print("  %2d. %-14s %s  %.1f조원" % (x["rank"], x["name"], x["code"], x["cap"] / 1e12))

    if a.all:
        companies, months_all = build_all(key, rows, a.start, asof, a.include_preferred)
        ranking = [r for r in ranking if r["code"] in companies] or ranking
        out = {
            "demo": False, "all": True,
            "generatedAt": dt.date.today().isoformat(),
            "asof": asof,
            "source": "금융위원회_주식시세정보 (공공데이터포털)",
            "note": "월말 종가 기준, 액면분할·무상증자 보정, 배당금 미포함",
            "ranking": ranking,
            "months": months_all,
            "companies": companies,
        }
        save(out, a)
        return

    by_name = {}
    for r in rows:
        by_name.setdefault(field(r, "itmsNm"), []).append(r)
    for nm in read_extras(a.extras):
        hit = by_name.get(nm)
        if not hit:
            near = [k for k in by_name if k and nm in k][:5]
            print("  [건너뜀] '%s' 이름이 기준일 자료에 없습니다. 비슷한 이름: %s" % (nm, near))
            continue
        r = max(hit, key=cap)
        c = norm_code(field(r, "srtnCd"))
        if c not in [x[0] for x in codes]:
            codes.append((c, field(r, "itmsNm"), str(field(r, "mrktCtg")).upper(), field(r, "isinCd")))

    end = asof
    companies = {}
    print("가격 자료 받는 중 (%d개 회사):" % len(codes))
    for code, name, market, isin in codes:
        try:
            months, prices, events = fetch_history(key, code, a.start, end, isin)
        except Exception as e:
            print("  [실패] %s %s: %s" % (code, name, mask(e)))
            continue
        companies[code] = {"name": name, "market": market, "months": months, "prices": prices}
        ev = ", ".join("%s(x%.4f)" % (d, r) for d, r in events) or "없음"
        print("  %s %-14s %s ~ %s (%d개월)  분할/병합 보정: %s" % (code, name, months[0], months[-1], len(months), ev))
        if events:
            companies[code]["adjusted"] = [[d, round(r, 6)] for d, r in events]
        time.sleep(0.2)

    if not companies:
        sys.exit("가격 자료를 하나도 받지 못했습니다. 위의 [실패] 문구를 확인하세요. (기존 파일은 그대로 둡니다)")
    first = min(c["months"][0] for c in companies.values())
    if first > a.start[:4] + "-" + a.start[4:6]:
        print("  [알림] API 자료가 %s 부터만 있습니다. 그 이전 기간은 저장되지 않았습니다." % first)

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
    save(out, a)


def save(out, a):
    os.makedirs(os.path.dirname(a.out_json), exist_ok=True)
    os.makedirs(os.path.dirname(a.out_js), exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    open(a.out_json, "w", encoding="utf-8").write(text)
    open(a.out_js, "w", encoding="utf-8").write("window.STOCK_DATA=" + text + ";\n")
    print("저장 완료:", a.out_json, "/", a.out_js,
          "(회사 %d개, %.1fMB)" % (len(out["companies"]), len(text.encode("utf-8")) / 1e6))


if __name__ == "__main__":
    main()
