"""
공공데이터포털 '전국주차장정보표준데이터' (publicDataPk=15012896)
- 자치단체별 CSV를 받아 우리 lots 포맷으로 변환
- 공영주차장만 추출 (민영 제외)

사용:
    python scripts/scrape_standard.py all      # 등록된 모든 구
    python scripts/scrape_standard.py gangnam  # 단일 구
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
LOTS_DIR = ROOT / "data" / "lots"
KST = timezone(timedelta(hours=9))

# 23개 구 표준데이터 atchFileId 매핑 (구로구 제외 — 시설공단 데이터 유지)
DISTRICT_FILES = {
    "gangnam":     ("강남구",   "FILE_000000003626145"),
    "gangdong":    ("강동구",   "FILE_000000003629801"),
    "gangseo":     ("강서구",   "FILE_000000003628207"),
    "gwanak":      ("관악구",   "FILE_000000003626974"),
    "gwangjin":    ("광진구",   "FILE_000000003628541"),
    "geumcheon":   ("금천구",   "FILE_000000003627737"),
    "nowon":       ("노원구",   "FILE_000000003629959"),
    "dobong":      ("도봉구",   "FILE_000000003641143"),
    "dongdaemun":  ("동대문구", "FILE_000000003626799"),
    "dongjak":     ("동작구",   "FILE_000000003629922"),
    "mapo":        ("마포구",   "FILE_000000003631784"),
    "seodaemun":   ("서대문구", "FILE_000000003636390"),
    "seocho":      ("서초구",   "FILE_000000003626902"),
    "seongbuk":    ("성북구",   "FILE_000000003627791"),
    "songpa":      ("송파구",   "FILE_000000003631076"),
    "yangcheon":   ("양천구",   "FILE_000000003628289"),
    "yeongdeungpo":("영등포구", "FILE_000000003629748"),
    "yongsan":     ("용산구",   "FILE_000000003639919"),
    "eunpyeong":   ("은평구",   "FILE_000000003630562"),
    "jongno":      ("종로구",   "FILE_000000003628510"),
    "junggu":      ("중구",     "FILE_000000003628034"),
    "jungnang":    ("중랑구",   "FILE_000000003629595"),
}
# 표준데이터 미제공: gangbuk, seongdong


def fmt_time(s):
    s = (s or "").strip()
    if not s or s == "0":
        return ""
    s = s.zfill(4)
    return f"{s[:2]}:{s[2:]}"


def make_hours(r):
    wd_b, wd_e = fmt_time(r.get("평일운영시작시각", "")), fmt_time(r.get("평일운영종료시각", ""))
    sat_b, sat_e = fmt_time(r.get("토요일운영시작시각", "")), fmt_time(r.get("토요일운영종료시각", ""))
    hol_b, hol_e = fmt_time(r.get("공휴일운영시작시각", "")), fmt_time(r.get("공휴일운영종료시각", ""))
    parts = []
    if wd_b == "00:00" and wd_e == "24:00":
        parts.append("평일 24시간")
    elif wd_b and wd_e:
        parts.append(f"평일 {wd_b}~{wd_e}")
    if sat_b and sat_e and (sat_b, sat_e) != (wd_b, wd_e):
        parts.append(f"토 {sat_b}~{sat_e}")
    if hol_b and hol_e and (hol_b, hol_e) != (wd_b, wd_e):
        parts.append(f"공휴일 {hol_b}~{hol_e}")
    return " / ".join(parts) or "-"


def make_hourly(r):
    """주차기본요금/시간 → '5분당 100원 (1시간 1,200원)' 형태"""
    if (r.get("요금정보") or "").strip() == "무료":
        return "무료"
    try:
        base_fee = int(float(r.get("주차기본요금") or 0))
        base_hr = int(float(r.get("주차기본시간") or 0))
        if base_fee and base_hr:
            per_hour = round(base_fee * (60 / base_hr))
            return f"{base_hr}분당 {base_fee:,}원 (1시간 {per_hour:,}원)"
    except (ValueError, TypeError):
        pass
    return "요금 정보 없음"


def parse_csv(text: str) -> list[dict]:
    lots = []
    reader = csv.DictReader(io.StringIO(text))
    for r in reader:
        # 공영만 필터링
        if (r.get("주차장구분") or "").strip() != "공영":
            continue
        try:
            lat = float(r.get("위도", "") or 0)
            lng = float(r.get("경도", "") or 0)
        except ValueError:
            continue
        if not (lat and lng):
            continue
        try:
            spaces = int(float(r.get("주차구획수") or 0)) or None
        except (ValueError, TypeError):
            spaces = None
        is_free = (r.get("요금정보") or "").strip() == "무료"
        monthly_raw = r.get("월정기권요금") or ""
        try:
            monthly_all = f"{int(float(monthly_raw)):,}원" if float(monthly_raw or 0) > 0 else "-"
        except (ValueError, TypeError):
            monthly_all = "-"
        lots.append({
            "name": (r.get("주차장명") or "").strip(),
            "address": (r.get("소재지도로명주소") or r.get("소재지지번주소") or "").strip(),
            "lat": lat, "lng": lng,
            "code": (r.get("주차장관리번호") or "").strip(),
            "operationType": "공영",
            "applyMethod": (r.get("운영요일") or "").strip(),
            "spaces": spaces,
            "grade": (r.get("급지구분") or "").strip() or "-",
            "hourly": make_hourly(r),
            "hourlyAvailable": True,  # 무료 포함 모두 시간주차 가능으로 표시
            "monthly": {"day": "-", "night": "-", "all": monthly_all},
            "hours": make_hours(r),
            "tel": (r.get("전화번호") or "").strip() or None,
            "mapLink": None,
            "category": "normal",
            "source": "data.go.kr-15012896",
            "realtimeKey": None,
        })
    return lots


def fetch_csv(file_id: str) -> str:
    url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={file_id}&fileDetailSn=1"
    res = requests.get(url, headers={"Referer": "https://www.data.go.kr/data/15012896/standard.do"}, timeout=60)
    res.raise_for_status()
    return res.content.decode("utf-8-sig")


def scrape_one(code: str) -> int:
    if code not in DISTRICT_FILES:
        print(f"[{code}] 미등록 구 코드 (표준데이터 없음)", file=sys.stderr)
        return 1
    gu_name, file_id = DISTRICT_FILES[code]
    print(f"[{code}] {gu_name} 다운로드 ({file_id})")
    text = fetch_csv(file_id)
    lots = parse_csv(text)
    print(f"[{code}] 공영 {len(lots)}곳 변환")

    LOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LOTS_DIR / f"{code}.json"
    payload = {
        "district": gu_name,
        "districtCode": code,
        "operator": f"{gu_name} (표준데이터)",
        "source": "공공데이터포털 전국주차장정보표준데이터",
        "updatedAt": datetime.now(KST).date().isoformat(),
        "lots": lots,
    }
    new_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            if old.get("lots", []) == lots:
                print(f"[{code}] no changes")
                return 0
        except Exception:
            pass
    out_path.write_text(new_text, encoding="utf-8")
    print(f"[{code}] wrote {out_path.relative_to(ROOT)}")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    target = argv[1].strip().lower()
    if target == "all":
        codes = list(DISTRICT_FILES.keys())
        results = []
        for c in codes:
            results.append(scrape_one(c))
        return max(results) if results else 0
    return scrape_one(target)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
