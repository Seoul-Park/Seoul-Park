"""
서울 열린데이터 GetParkInfo (2,293곳, 시·구 공영 통합)을
기존 lots/{code}.json 에 합치는 스크래퍼.

기존 데이터(표준데이터 + 시설공단 + 서울API GetParkingInfo)와
좌표 100m 이내 중복은 제외하고 신규만 추가.

환경변수:
    SEOUL_OPEN_API_KEY    필수
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

KAKAO_REST_KEY = os.environ.get("KAKAO_REST_KEY", "e369007f7234d41ce977746bcd1fb224")

ROOT = Path(__file__).resolve().parents[1]
LOTS_DIR = ROOT / "data" / "lots"
DISTRICTS_PATH = ROOT / "data" / "districts.json"
KST = timezone(timedelta(hours=9))
MATCH_RADIUS_M = 100   # 같은 주차장으로 간주할 거리 임계값

# 서울 25개 구 한글 → 코드 매핑 (districts.json 참조해도 됨)
DISTRICT_KO_TO_CODE = {
    "강남구":"gangnam","강동구":"gangdong","강북구":"gangbuk","강서구":"gangseo",
    "관악구":"gwanak","광진구":"gwangjin","구로구":"guro","금천구":"geumcheon",
    "노원구":"nowon","도봉구":"dobong","동대문구":"dongdaemun","동작구":"dongjak",
    "마포구":"mapo","서대문구":"seodaemun","서초구":"seocho","성동구":"seongdong",
    "성북구":"seongbuk","송파구":"songpa","양천구":"yangcheon","영등포구":"yeongdeungpo",
    "용산구":"yongsan","은평구":"eunpyeong","종로구":"jongno","중구":"junggu","중랑구":"jungnang",
}


def haversine_m(a_lat, a_lng, b_lat, b_lng):
    R = 6371000
    rl = lambda d: d * math.pi / 180
    dlat = rl(b_lat - a_lat)
    dlng = rl(b_lng - a_lng)
    x = math.sin(dlat/2)**2 + math.sin(dlng/2)**2 * math.cos(rl(a_lat)) * math.cos(rl(b_lat))
    return 2 * R * math.asin(math.sqrt(x))


def fmt_time(s):
    s = (s or "").strip()
    if not s or s == "0":
        return ""
    s = s.zfill(4)
    return f"{s[:2]}:{s[2:]}"


def make_hours(r):
    wd_b, wd_e = fmt_time(r.get("WD_OPER_BGNG_TM")), fmt_time(r.get("WD_OPER_END_TM"))
    parts = []
    if wd_b == "00:00" and wd_e == "24:00":
        parts.append("평일 24시간")
    elif wd_b and wd_e:
        parts.append(f"평일 {wd_b}~{wd_e}")
    sat_b, sat_e = fmt_time(r.get("WE_OPER_BGNG_TM")), fmt_time(r.get("WE_OPER_END_TM"))
    if sat_b and sat_e and (sat_b, sat_e) != (wd_b, wd_e):
        parts.append(f"주말 {sat_b}~{sat_e}")
    return " / ".join(parts) or "-"


def make_hourly(r):
    if (r.get("CHGD_FREE_NM") or "").strip() == "무료":
        return "무료"
    try:
        crg = int(float(r.get("PRK_CRG") or 0))
        hr = int(float(r.get("PRK_HM") or 0))
        if crg and hr:
            per_hour = round(crg * (60 / hr))
            return f"{hr}분당 {crg:,}원 (1시간 {per_hour:,}원)"
    except (ValueError, TypeError):
        pass
    return "요금 정보 없음"


def fetch_all_park_info(api_key):
    """1000건 제한으로 batch 분할 호출"""
    all_rows = []
    for start in (1, 1001, 2001):
        end = start + 999
        url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/GetParkInfo/{start}/{end}/"
        res = requests.get(url, timeout=30)
        res.raise_for_status()
        info = res.json().get("GetParkInfo", {})
        if info.get("RESULT", {}).get("CODE") != "INFO-000":
            print(f"  배치 {start}: API 오류, 건너뜀")
            continue
        all_rows.extend(info.get("row", []))
    return all_rows


def _kakao_get(url, retries=4):
    """카카오 API 호출 + 429/5xx 시 지수 백오프 재시도"""
    delay = 1.0
    for attempt in range(retries):
        try:
            res = requests.get(url, headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}, timeout=10)
        except Exception:
            time.sleep(delay); delay *= 2
            continue
        if res.status_code == 200:
            return res
        if res.status_code in (429, 500, 502, 503, 504):
            time.sleep(delay); delay *= 2
            continue
        return None  # 401/403 등 영구 실패
    return None


def geocode_kakao(query):
    """카카오 주소 검색 → 실패 시 키워드 검색 fallback. 좌표 (lat, lng) 또는 None."""
    base = "https://dapi.kakao.com/v2/local/search"
    q = urllib.parse.quote(query)
    res = _kakao_get(f"{base}/address.json?query={q}")
    if res is not None:
        docs = res.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    res = _kakao_get(f"{base}/keyword.json?query={q}")
    if res is not None:
        docs = res.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    return None


def to_lot(r, district_name_ko):
    try:
        lat = float(r.get("LAT") or 0)
        lng = float(r.get("LOT") or 0)
    except ValueError:
        return None
    if lat < 33 or lng < 124:   # 한국 좌표 범위 (대략)
        return None
    try:
        spaces = int(float(r.get("TPKCT") or 0)) or None
    except (ValueError, TypeError):
        spaces = None

    monthly_raw = r.get("MNTL_CMUT_CRG") or "0"
    try:
        m_all = f"{int(float(monthly_raw)):,}원" if float(monthly_raw or 0) > 0 else "-"
    except (ValueError, TypeError):
        m_all = "-"

    pklt_kind = (r.get("PKLT_KND_NM") or "").strip()
    return {
        "name": (r.get("PKLT_NM") or "").strip(),
        "address": (r.get("ADDR") or "").strip(),
        "lat": lat, "lng": lng,
        "code": (r.get("PKLT_CD") or "").strip(),
        "operationType": (r.get("OPER_SE_NM") or "").strip(),
        "applyMethod": pklt_kind,
        "spaces": spaces,
        "grade": "-",
        "hourly": make_hourly(r),
        "hourlyAvailable": True,
        "monthly": {"day": "-", "night": "-", "all": m_all},
        "hours": make_hours(r),
        "tel": (r.get("TELNO") or "").strip() or None,
        "mapLink": None,
        "category": "normal",
        "source": "seoul-getparkinfo",
        "pkltKind": pklt_kind,   # 노상/노외 분류 보존
        "realtimeKey": None,
    }


def main():
    api_key = os.environ.get("SEOUL_OPEN_API_KEY")
    if not api_key:
        print("ERROR: SEOUL_OPEN_API_KEY 미설정", file=sys.stderr)
        return 2

    print("GetParkInfo 전체 다운로드 중…")
    rows = fetch_all_park_info(api_key)
    print(f"  {len(rows)}곳 받음")

    # 1차: 좌표 있는 것만 추출
    by_district: dict[str, list[dict]] = {}
    no_coord_rows: list[tuple[str, dict]] = []  # (gu_ko, raw_row)
    skipped_other = 0
    for r in rows:
        addr = r.get("ADDR") or ""
        m = re.search(r"(\S+구)", addr)
        if not m or m.group(1) not in DISTRICT_KO_TO_CODE:
            skipped_other += 1
            continue
        gu_ko = m.group(1)
        lot = to_lot(r, gu_ko)
        if lot:
            by_district.setdefault(DISTRICT_KO_TO_CODE[gu_ko], []).append(lot)
        else:
            no_coord_rows.append((gu_ko, r))
    print(f"  좌표 있음: {sum(len(v) for v in by_district.values())}곳, 좌표 누락: {len(no_coord_rows)}곳, 기타 제외: {skipped_other}곳")

    # 2차: 좌표 누락 → 카카오 지오코딩으로 보강
    if no_coord_rows:
        print(f"  좌표 누락 {len(no_coord_rows)}곳 카카오 지오코딩 시도…")
        geo_ok = 0; geo_fail = 0
        for i, (gu_ko, r) in enumerate(no_coord_rows):
            addr = r.get("ADDR") or ""
            # "성동구 마장동 463-2" → "서울특별시 성동구 마장동 463-2"
            query = addr if addr.startswith("서울") else f"서울특별시 {addr}"
            coords = geocode_kakao(query)
            if coords:
                lat, lng = coords
                r2 = dict(r); r2["LAT"] = str(lat); r2["LOT"] = str(lng)
                lot = to_lot(r2, gu_ko)
                if lot:
                    by_district.setdefault(DISTRICT_KO_TO_CODE[gu_ko], []).append(lot)
                    geo_ok += 1
                else:
                    geo_fail += 1
            else:
                geo_fail += 1
            if (i + 1) % 50 == 0:
                print(f"    진행 {i+1}/{len(no_coord_rows)} (성공 {geo_ok})")
            time.sleep(0.15)  # rate limit 안전 마진 (약 7 req/s)
        print(f"  지오코딩 성공: {geo_ok}곳, 실패: {geo_fail}곳")
    print(f"  최종 유효: {sum(len(v) for v in by_district.values())}곳, 구 수: {len(by_district)}")

    # 구별 기존 lots와 중복 제거 후 추가
    districts_data = json.loads(DISTRICTS_PATH.read_text(encoding="utf-8"))
    added_total = 0
    for code, new_lots in by_district.items():
        out_path = LOTS_DIR / f"{code}.json"
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            existing_lots = existing.get("lots", [])
        else:
            district = next((d for d in districts_data["districts"] if d["code"] == code), None)
            existing = {
                "district": district["name"] if district else code,
                "districtCode": code,
                "operator": district.get("operator") if district else None,
                "source": "서울 GetParkInfo (신규)",
                "updatedAt": datetime.now(KST).date().isoformat(),
                "lots": [],
            }
            existing_lots = []

        # 좌표 있는 기존 곳 캐시
        existing_coords = [(l["lat"], l["lng"]) for l in existing_lots if l.get("lat") and l.get("lng")]

        added_here = 0
        for nl in new_lots:
            is_dup = any(haversine_m(nl["lat"], nl["lng"], elat, elng) < MATCH_RADIUS_M
                         for elat, elng in existing_coords)
            if is_dup:
                continue
            existing_lots.append(nl)
            existing_coords.append((nl["lat"], nl["lng"]))
            added_here += 1
        if added_here == 0:
            continue

        existing["lots"] = existing_lots
        existing["updatedAt"] = datetime.now(KST).date().isoformat()
        # source 안내 보강
        srcs = existing.get("sources") or []
        if "서울 GetParkInfo" not in srcs:
            srcs.append("서울 GetParkInfo")
        existing["sources"] = srcs

        out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  [{code:13}] +{added_here} 신규 (총 {len(existing_lots)}곳)")
        added_total += added_here

    print(f"\n총 {added_total}곳 추가됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
