"""
서울 25개 구 공영주차장 데이터 스크래퍼
- 구별 시설관리공단 사이트 (지역별 파서)
- 서울 열린데이터 API GetParkingInfo (서울시 직영 공영주차장)

사용:
    python scripts/scrape.py guro          # 구로구만
    python scripts/scrape.py all           # 활성화된 모든 구

환경변수:
    SEOUL_OPEN_API_KEY    설정되면 서울 API에서 해당 구 주차장도 함께 포함
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOTS_DIR = DATA_DIR / "lots"
DISTRICTS_PATH = DATA_DIR / "districts.json"
KST = timezone(timedelta(hours=9))


# ───────────────────────────── 공통 유틸 ─────────────────────────────

def cell_text(td) -> str:
    parts: list[str] = []
    for el in td.children:
        if isinstance(el, NavigableString):
            parts.append(str(el))
        elif el.name == "br":
            parts.append(" ")
        elif el.name == "a" and "pos_map" in (el.get("class") or []):
            continue
        else:
            parts.append(el.get_text(" ", strip=True))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def normalize_hourly(raw: str) -> str:
    def add_commas(m):
        return f"{int(m.group(1)):,}원"
    return re.sub(r"(\d{4,})원", add_commas, raw)


def categorize(apply_method: str, hourly_available: bool) -> str:
    if "신청불가" in apply_method:
        return "special"
    if not hourly_available:
        return "monthly-only"
    return "normal"


# ─────────────────────── 구로구 시설관리공단 파서 ───────────────────────

def parse_guro_sisul(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="oops")
    if table is None:
        raise RuntimeError("구로구: 주차장 테이블을 찾지 못함 (사이트 구조 변경?)")

    lots: list[dict] = []
    current_op = ""

    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        if cells[0].name == "th":
            current_op = cell_text(cells[0])
            data_cells = cells[1:]
        else:
            data_cells = cells

        if len(data_cells) < 10:
            continue

        (name_td, apply_td, spaces_td, grade_td, hourly_td,
         m_day, m_night, m_all, hours_td, loc_td) = data_cells[:10]

        a = loc_td.find("a", class_="pos_map")
        map_link = a["href"].strip() if a and a.has_attr("href") else None

        addr_raw = cell_text(loc_td)
        address = addr_raw if addr_raw.startswith("서울 구로구") else f"서울 구로구 {addr_raw}"

        hourly_raw = cell_text(hourly_td)
        hourly_avail = "불가" not in hourly_raw
        apply_method = cell_text(apply_td)

        try:
            spaces = int(re.sub(r"\D", "", cell_text(spaces_td))) or None
        except ValueError:
            spaces = None

        lots.append({
            "name": cell_text(name_td),
            "address": address,
            "operationType": current_op,
            "applyMethod": apply_method,
            "spaces": spaces,
            "grade": cell_text(grade_td),
            "hourly": normalize_hourly(hourly_raw),
            "hourlyAvailable": hourly_avail,
            "monthly": {
                "day": cell_text(m_day),
                "night": cell_text(m_night),
                "all": cell_text(m_all),
            },
            "hours": cell_text(hours_td),
            "mapLink": map_link,
            "category": categorize(apply_method, hourly_avail),
            "source": "guro-sisul",
            "realtimeKey": None,
        })

    return lots


# ─────────────────────── 서울 열린데이터 API 파서 ───────────────────────

def parse_seoul_api_for_district(api_key: str, district_name: str) -> list[dict]:
    """
    서울 GetParkingInfo API 호출 후 해당 구 주차장만 우리 포맷으로 변환.
    district_name: '구로구' 같은 한글 구 이름 (ADDR 필드 매칭용)
    """
    url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/GetParkingInfo/1/1000/"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    payload = res.json()
    info = payload.get("GetParkingInfo", {})
    result = info.get("RESULT", {})
    if result.get("CODE") != "INFO-000":
        raise RuntimeError(f"서울 API 오류: {result.get('CODE')} {result.get('MESSAGE')}")

    rows = info.get("row", [])
    matched = [r for r in rows if district_name in r.get("ADDR", "")]

    lots = []
    for r in matched:
        try:
            spaces = int(r.get("TPKCT") or 0) or None
        except (ValueError, TypeError):
            spaces = None

        bsc_crg = r.get("BSC_PRK_CRG") or 0
        bsc_hr = r.get("BSC_PRK_HR") or 0
        try:
            crg = int(float(bsc_crg))
            hr = int(float(bsc_hr))
        except (ValueError, TypeError):
            crg, hr = 0, 0
        if hr > 0 and crg > 0:
            per_hour = int(crg * (60 / hr))
            hourly = f"{hr}분당 {crg:,}원 (1시간 {per_hour:,}원)"
        else:
            hourly = "요금 정보 없음"

        prd_amt = r.get("PRD_AMT") or "0"
        try:
            month_all = f"{int(prd_amt):,}원" if int(prd_amt) > 0 else "-"
        except ValueError:
            month_all = "-"

        # 운영시간 (평일/주말/공휴일 통합 간략화)
        wd_b = r.get("WD_OPER_BGNG_TM") or ""
        wd_e = r.get("WD_OPER_END_TM") or ""
        if wd_b == "0000" and wd_e == "2400":
            hours = "24시간"
        elif wd_b and wd_e:
            hours = f"평일 {wd_b[:2]}:{wd_b[2:]}~{wd_e[:2]}:{wd_e[2:]}"
        else:
            hours = "-"

        addr = r.get("ADDR", "")
        if not addr.startswith("서울"):
            addr = f"서울 {addr}"

        lots.append({
            "name": r.get("PKLT_NM", ""),
            "address": addr,
            "operationType": "서울시 직영",
            "applyMethod": r.get("OPER_SE_NM", ""),
            "spaces": spaces,
            "grade": "-",
            "hourly": hourly,
            "hourlyAvailable": True,
            "monthly": {"day": "-", "night": "-", "all": month_all},
            "hours": hours,
            "mapLink": None,
            "category": "normal",
            "source": "seoul-city",
            "realtimeKey": r.get("PKLT_CD"),
        })

    return lots


# ─────────────────────────── 파서 레지스트리 ───────────────────────────

LOCAL_PARSERS = {
    "guro": parse_guro_sisul,
    # 추가 구는 여기에:
    # "gangnam": parse_gangnam_sisul,
}


# ─────────────────────────── 실행 로직 ───────────────────────────

def load_districts() -> dict:
    return json.loads(DISTRICTS_PATH.read_text(encoding="utf-8"))


def find_district(districts: dict, code: str) -> dict | None:
    return next((d for d in districts["districts"] if d["code"] == code), None)


def scrape_one(code: str, districts: dict, seoul_api_key: str | None) -> int:
    district = find_district(districts, code)
    if not district:
        print(f"[{code}] ERROR: 알 수 없는 구 코드", file=sys.stderr)
        return 1
    if not district.get("active"):
        print(f"[{code}] 비활성 상태 - 스킵", file=sys.stderr)
        return 0

    lots: list[dict] = []

    # 1) 시설관리공단 파서
    if code in LOCAL_PARSERS:
        source_url = district["sourceUrl"]
        print(f"[{code}] fetching {source_url}")
        res = requests.get(source_url, timeout=30)
        res.raise_for_status()
        local_lots = LOCAL_PARSERS[code](res.text)
        print(f"[{code}] sisul: parsed {len(local_lots)} lots")
        lots.extend(local_lots)
    else:
        print(f"[{code}] 시설공단 파서 미구현 - 서울 API만 사용")

    # 2) 서울 열린데이터 API (선택)
    if seoul_api_key:
        try:
            api_lots = parse_seoul_api_for_district(seoul_api_key, district["name"])
            print(f"[{code}] seoul-city: parsed {len(api_lots)} lots")
            lots.extend(api_lots)
        except Exception as e:
            print(f"[{code}] 서울 API 호출 실패 (스킵): {e}", file=sys.stderr)
    else:
        print(f"[{code}] SEOUL_OPEN_API_KEY 미설정 - 서울 API 스킵")

    if not lots:
        print(f"[{code}] ERROR: 수집된 데이터 없음", file=sys.stderr)
        return 1

    payload = {
        "district": district["name"],
        "districtCode": code,
        "operator": district.get("operator"),
        "sources": [s for s in [district.get("sourceUrl"), "서울 열린데이터 GetParkingInfo" if seoul_api_key else None] if s],
        "updatedAt": datetime.now(KST).date().isoformat(),
        "lots": lots,
    }

    LOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LOTS_DIR / f"{code}.json"
    new_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if out_path.exists():
        old = json.loads(out_path.read_text(encoding="utf-8"))
        if old.get("lots", []) == lots:
            print(f"[{code}] no changes - skipping write")
            return 0

    out_path.write_text(new_text, encoding="utf-8")
    print(f"[{code}] wrote {out_path.relative_to(ROOT)} (총 {len(lots)}곳)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    districts = load_districts()
    seoul_api_key = os.environ.get("SEOUL_OPEN_API_KEY")
    target = argv[1].strip().lower()

    if target == "all":
        codes = [d["code"] for d in districts["districts"] if d.get("active")]
        if not codes:
            print("활성화된 구가 없습니다.", file=sys.stderr)
            return 0
        return max(scrape_one(c, districts, seoul_api_key) for c in codes)

    return scrape_one(target, districts, seoul_api_key)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
