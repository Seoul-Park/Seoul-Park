"""
서울 25개 구 시설관리공단 공영주차장 데이터 스크래퍼

사용:
    python scripts/scrape.py guro          # 구로구만
    python scripts/scrape.py all           # 활성화된 모든 구
"""
from __future__ import annotations

import json
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


# ─────────────────────────── 구로구 파서 ───────────────────────────

def parse_guro(html: str) -> list[dict]:
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
        })

    return lots


# ─────────────────────────── 파서 레지스트리 ───────────────────────────

PARSERS = {
    "guro": parse_guro,
    # 추가 구는 여기에:
    # "gangnam": parse_gangnam,
}


# ─────────────────────────── 실행 로직 ───────────────────────────

def load_districts() -> dict:
    return json.loads(DISTRICTS_PATH.read_text(encoding="utf-8"))


def find_district(districts: dict, code: str) -> dict | None:
    return next((d for d in districts["districts"] if d["code"] == code), None)


def scrape_one(code: str, districts: dict) -> int:
    district = find_district(districts, code)
    if not district:
        print(f"[{code}] ERROR: 알 수 없는 구 코드", file=sys.stderr)
        return 1
    if not district.get("active"):
        print(f"[{code}] 비활성 상태 - 스킵", file=sys.stderr)
        return 0
    if code not in PARSERS:
        print(f"[{code}] 파서 미구현 - 스킵", file=sys.stderr)
        return 0

    source_url = district["sourceUrl"]
    print(f"[{code}] fetching {source_url}")
    res = requests.get(source_url, timeout=30)
    res.raise_for_status()

    lots = PARSERS[code](res.text)
    if not lots:
        print(f"[{code}] ERROR: 파싱 결과 없음", file=sys.stderr)
        return 1
    print(f"[{code}] parsed {len(lots)} lots")

    payload = {
        "source": source_url,
        "district": district["name"],
        "districtCode": code,
        "operator": district.get("operator"),
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
    print(f"[{code}] wrote {out_path.relative_to(ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    districts = load_districts()
    target = argv[1].strip().lower()

    if target == "all":
        codes = [d["code"] for d in districts["districts"] if d.get("active")]
        if not codes:
            print("활성화된 구가 없습니다.", file=sys.stderr)
            return 0
        return max(scrape_one(c, districts) for c in codes)

    return scrape_one(target, districts)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
