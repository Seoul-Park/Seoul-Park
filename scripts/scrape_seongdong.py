"""
성동구도시관리공단 공영주차장 OpenAPI

엔드포인트:
    https://parking.happysd.or.kr/OpenApi/sdPublicParkingList (인증키 불필요)

기존 lots/seongdong.json에 중복 제거 후 신규만 추가.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
LOTS_DIR = ROOT / "data" / "lots"
OUT_PATH = LOTS_DIR / "seongdong.json"
KST = timezone(timedelta(hours=9))
MATCH_RADIUS_M = 100
URL = "https://parking.happysd.or.kr/OpenApi/sdPublicParkingList"


def haversine_m(a_lat, a_lng, b_lat, b_lng):
    R = 6371000
    rl = lambda d: d * math.pi / 180
    dlat = rl(b_lat - a_lat); dlng = rl(b_lng - a_lng)
    x = math.sin(dlat/2)**2 + math.sin(dlng/2)**2 * math.cos(rl(a_lat)) * math.cos(rl(b_lat))
    return 2 * R * math.asin(math.sqrt(x))


def fmt_time(s):
    s = (s or "").strip()
    if not s or s == "0": return ""
    s = s.zfill(4)
    return f"{s[:2]}:{s[2:]}"


def make_hours(r):
    wd_b, wd_e = fmt_time(r.get("평일운영시작시간")), fmt_time(r.get("평일운영종료시간"))
    sat_b, sat_e = fmt_time(r.get("토요일운영시작시간")), fmt_time(r.get("토요일운영종료시간"))
    hol_b, hol_e = fmt_time(r.get("공휴일운영시작시간")), fmt_time(r.get("공휴일운영종료시간"))
    parts = []
    if wd_b == "00:00" and wd_e == "24:00": parts.append("평일 24시간")
    elif wd_b and wd_e: parts.append(f"평일 {wd_b}~{wd_e}")
    if sat_b and sat_e and (sat_b, sat_e) != (wd_b, wd_e): parts.append(f"토 {sat_b}~{sat_e}")
    if hol_b and hol_e and (hol_b, hol_e) != (wd_b, wd_e): parts.append(f"공휴일 {hol_b}~{hol_e}")
    return " / ".join(parts) or "-"


def make_hourly(r):
    if (r.get("요금정보") or "").strip() == "무료":
        return "무료"
    try:
        crg = int(float(r.get("주차기본요금") or 0))
        hr = int(float(r.get("주차기본시간") or 0))
        if crg and hr:
            per_hour = round(crg * (60 / hr))
            return f"{hr}분당 {crg:,}원 (1시간 {per_hour:,}원)"
    except (ValueError, TypeError):
        pass
    return "요금 정보 없음"


def to_lot(r):
    try:
        lat = float(r.get("위도_WGS84좌표", "") or 0)
        lng = float(r.get("경도_WGS84좌표", "") or 0)
    except ValueError:
        return None
    if lat < 33 or lng < 124:
        return None
    try:
        spaces = int(float(r.get("주차구획수") or 0)) or None
    except (ValueError, TypeError):
        spaces = None
    monthly_raw = r.get("월정기권요금") or "0"
    try:
        month_all = f"{int(float(monthly_raw)):,}원" if float(monthly_raw or 0) > 0 else "-"
    except (ValueError, TypeError):
        month_all = "-"
    addr = (r.get("소재지도로명주소") or r.get("소재지지번주소") or "").strip()
    addr = re.sub(r"\s+", " ", addr)

    return {
        "name": (r.get("주차장명") or "").strip(),
        "address": addr,
        "lat": lat, "lng": lng,
        "code": (r.get("주차장관리번호") or "").strip(),
        "operationType": "공영",
        "applyMethod": (r.get("주차장유형") or "").strip(),  # 노상/노외
        "spaces": spaces,
        "grade": (r.get("급지구분") or "").strip() or "-",
        "hourly": make_hourly(r),
        "hourlyAvailable": True,
        "monthly": {"day": "-", "night": "-", "all": month_all},
        "hours": make_hours(r),
        "tel": (r.get("관리기관연락처") or "").strip() or None,
        "mapLink": None,
        "category": "normal",
        "source": "seongdong-sisul",
        "pkltKind": (r.get("주차장유형") or "").strip(),
        "realtimeKey": None,
    }


def main():
    print(f"[seongdong] downloading {URL}")
    res = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    res.raise_for_status()
    raw = res.json()
    new_lots = [l for l in (to_lot(r) for r in raw) if l]
    print(f"[seongdong] parsed {len(new_lots)} 곳 (좌표 유효)")

    # 기존 lots와 100m 중복 제거
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    else:
        existing = {
            "district": "성동구", "districtCode": "seongdong",
            "operator": "성동구도시관리공단",
            "source": "성동구 OpenAPI", "updatedAt": "",
            "lots": [],
        }
    existing_lots = existing.get("lots", [])
    existing_coords = [(l["lat"], l["lng"]) for l in existing_lots if l.get("lat") and l.get("lng")]

    added = 0
    for nl in new_lots:
        dup = any(haversine_m(nl["lat"], nl["lng"], elat, elng) < MATCH_RADIUS_M
                  for elat, elng in existing_coords)
        if dup: continue
        existing_lots.append(nl)
        existing_coords.append((nl["lat"], nl["lng"]))
        added += 1

    existing["lots"] = existing_lots
    existing["updatedAt"] = datetime.now(KST).date().isoformat()
    srcs = existing.get("sources") or []
    if "성동구 OpenAPI" not in srcs: srcs.append("성동구 OpenAPI")
    existing["sources"] = srcs

    LOTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[seongdong] +{added} 신규 (총 {len(existing_lots)}곳) → {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
