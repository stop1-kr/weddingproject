#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3차시용 주가 자료 만들기 (선생님이 한 번만 실행)

공공데이터포털 「금융위원회_주식시세정보」 (V2) API에서
  1) 기준일(기본 2026-09-30)의 시가총액 상위 10개 회사
  2) 그 회사들 + tools/extra_companies.txt 에 적은 회사들의 2010-01 ~ 기준월 월말 종가
를 받아 data/stocks.json 과 js/stocks-data.js 로 저장합니다.

사용법
  python tools/build_stocks.py --key 일반_인증키
  (또는 환경변수 DATA_GO_KR_KEY 에 키를 넣어 두고  python tools/build_stocks.py )
  python tools/build_stocks.py --check      ← 자료는 만들지 않고 API 연결만 점검

참고
  - 서비스 주소: https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2
  - 가격은 '월말 종가'이며, 액면분할·병합은 자동으로 보정합니다. 배당금은 포함하지 않습니다.
  - API가 제공하는 자료의 시작 시점이 2010-01보다 늦으면, 있는 기간만 저장됩니다.
  - 오류가 나면 API가 보낸 실제 오류 문구(인증키는 가린 채)를 그대로 보여 줍니다.
"""
import argparse, json, os, re, sys, time, datetime as dt
from urllib.parse import unquote

try:
    import requests
except ImportError:
    sys.exit("requests 라이브러리가 필요합니다.  pip install requests")

BASE = "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
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


def call(params, key, retries=4):
    p = {"serviceKey": key, "resultType": "json"}
    p.update(params)
    last = None
    for t in range(retries):
        try:
            try:
                r = requests.get(BASE, params=p, timeout=60)
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


def check(key, asof):
    """API 연결 점검: 실제 응답을 보여 줌 (기존 check_api.py 역할)"""
    print("== API 연결 점검 ==")
    print("주소:", BASE)
    print("인증키 길이: %d자 (앞 4자리 %s…)" % (len(key), key[:4]))
    for label, prm in [("기준일 " + asof, {"basDt": asof}), ("2010-01-29 (2010년 자료 확인)", {"basDt": "20100129"})]:
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
    ap.add_argument("--start", default="20100101", help="가격 시작일 YYYYMMDD")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--include-preferred", action="store_true", help="우선주도 순위에 포함")
    ap.add_argument("--check", action="store_true", help="자료는 만들지 않고 API 연결만 점검")
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
    os.makedirs(os.path.dirname(a.out_json), exist_ok=True)
    os.makedirs(os.path.dirname(a.out_js), exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    open(a.out_json, "w", encoding="utf-8").write(text)
    open(a.out_js, "w", encoding="utf-8").write("window.STOCK_DATA=" + text + ";\n")
    print("저장 완료:", a.out_json, "/", a.out_js, "(회사 %d개)" % len(companies))


if __name__ == "__main__":
    main()
