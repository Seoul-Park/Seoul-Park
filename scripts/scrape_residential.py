"""
거주자우선주차구역 데이터 변환
- 데이터 소스: 공공데이터포털 "전국거주자우선주차정보표준데이터" (publicDataPk=15021105)
- 자치단체별 CSV 파일을 받아 우리 lots 포맷으로 변환

사용:
    python scripts/scrape_residential.py guro
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "residential"
KST = timezone(timedelta(hours=9))

# 표준데이터셋 15021105의 자치단체별 uddi 매핑
# atchFileId는 매 실행 시 selectFileDataDownload.do로 동적 조회 (변경 가능성 대응)
DISTRICT_UDDI = {
    "gangnam":     ("강남구",   "uddi:c8ee98e1-c2d9-418b-8b24-89d5a35f3167_201912301657"),
    "gangbuk":     ("강북구",   "uddi:702f43fb-7fa9-4f0f-865b-a5153cdee3e2_201909261629"),
    "gangseo":     ("강서구",   "uddi:1685c062-7a3b-4110-a50e-c2502c43f3a4"),
    "gwanak":      ("관악구",   "uddi:bdbd6da2-427a-418c-be83-810ae00f1fb0_201906281341"),
    "gwangjin":    ("광진구",   "uddi:640f303c-43c1-457c-9074-a9f9356475bb"),
    "guro":        ("구로구",   "uddi:d7c667b3-7bb6-432f-bc06-c198bb60c885_202003161043"),
    "geumcheon":   ("금천구",   "uddi:77a92859-2f57-4e09-b2b2-e3dda32d0f14_202003181610"),
    "nowon":       ("노원구",   "uddi:218c66dc-0b1d-4f88-aa5e-c88f3274dace"),
    "dongjak":     ("동작구",   "uddi:325630b6-fb15-457f-87d4-db9c9fbf63f2_202001061726"),
    "seocho":      ("서초구",   "uddi:ab4e56a4-7774-4069-929a-c581f462b6ad"),
    "seongbuk":    ("성북구",   "uddi:5e601031-d575-4e2a-b19e-9e9a63f74c76"),
    "songpa":      ("송파구",   "uddi:d6fb591c-a7e2-40ba-a4a8-873372574440_202003111406"),
    "yangcheon":   ("양천구",   "uddi:dad61a70-f667-48e8-b78d-c8474141b4ba_201911251120"),
    "yeongdeungpo":("영등포구", "uddi:ab0f63bf-d893-47be-8b3b-d0bdb0ac5b1e"),
    "jongno":      ("종로구",   "uddi:33b88e36-faef-4ec4-93fe-b60965487d73"),
    "jungnang":    ("중랑구",   "uddi:7f9c603a-6038-4896-9faf-e7cecaee3ad0"),
}


def fetch_atch_file_id(uddi, retries=4):
    url = (f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
           f"?recommendDataYn=Y&publicDataPk=15021105&publicDataDetailPk={uddi}")
    headers = {"Referer": "https://www.data.go.kr/data/15021105/standard.do",
               "X-Requested-With": "XMLHttpRequest",
               "User-Agent": "Mozilla/5.0"}
    for i in range(retries):
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code == 200:
                return res.json().get("fileDataRegistVO", {}).get("atchFileId")
        except Exception as e:
            print(f"  재시도 {i+1}/{retries}: {e}", file=sys.stderr)
        time.sleep(2 ** i)  # 1, 2, 4, 8초 백오프
    return None


def parse_monthly(fee_str: str) -> dict:
    """'주간:3만원+야간:2만원+전일:4만원' → {day, night, all}"""
    out = {"day": "-", "night": "-", "all": "-"}
    for part in (fee_str or "").split("+"):
        part = part.strip()
        if ":" not in part:
            continue
        k, v = [s.strip() for s in part.split(":", 1)]
        # '3만원' → '30,000원'
        m = re.match(r"(\d+)만원", v)
        if m:
            v = f"{int(m.group(1)) * 10000:,}원"
        if k == "주간":
            out["day"] = v
        elif k == "야간":
            out["night"] = v
        elif k == "전일":
            out["all"] = v
    return out


def fetch_csv(atch_file_id: str, retries=4) -> str:
    url = (f"https://www.data.go.kr/cmm/cmm/fileDownload.do?"
           f"atchFileId={atch_file_id}&fileDetailSn=1")
    headers = {"Referer": "https://www.data.go.kr/data/15021105/standard.do",
               "User-Agent": "Mozilla/5.0"}
    last_err = None
    for i in range(retries):
        try:
            res = requests.get(url, headers=headers, timeout=60)
            res.raise_for_status()
            return res.content.decode("utf-8-sig", errors="replace")
        except Exception as e:
            last_err = e
            print(f"  CSV 재시도 {i+1}/{retries}: {e}", file=sys.stderr)
            time.sleep(2 ** i)
    raise last_err


def convert(text: str, district_name: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    lots = []
    for r in reader:
        try:
            lat = float(r.get("거주자우선주차구획위도", "") or 0)
            lng = float(r.get("거주자우선주차구획경도", "") or 0)
        except ValueError:
            continue
        if not (lat and lng):
            continue
        lots.append({
            "name": r.get("거주자우선주차구역명", "").strip(),
            "address": r.get("소재지도로명주소", "").strip(),
            "addressJibun": r.get("소재지지번주소", "").strip(),
            "lat": lat, "lng": lng,
            "code": r.get("거주자우선주차구획번호", "").strip(),
            "operationType": r.get("운영형태", "").strip(),
            "hours": r.get("사용시간대정보", "").replace("+", " / ").strip(),
            "period": r.get("사용기간", "").strip(),
            # 거주자우선주차는 일반 '시간요금'이 없음 (방문주차 별도)
            "hourly": "방문주차 1시간 600원 (최대3시간)",
            "hourlyAvailable": True,
            "monthly": parse_monthly(r.get("이용요금", "")),
            "discount": r.get("이용요금할인정보", "").strip(),
            "payment": r.get("이용요금결제방법", "").strip(),
            "applyMethod": r.get("신청방법", "").replace("+", ", ").strip(),
            "tel": r.get("관리기관전화번호", "").strip() or None,
            "mgmt": r.get("관리기관명", "").strip(),
            "mapLink": None,
            "category": "residential",
            "source": "data.go.kr-15021105",
            "realtimeKey": None,
        })
    return lots


def scrape_one(code: str) -> int:
    info = DISTRICT_UDDI.get(code)
    if not info:
        print(f"[{code}] 미등록 구 코드", file=sys.stderr)
        return 1
    gu_name, uddi = info
    print(f"[{code}] {gu_name} atchFileId 조회…")
    atch_id = fetch_atch_file_id(uddi)
    if not atch_id:
        print(f"[{code}] atchFileId 조회 실패", file=sys.stderr)
        return 1
    print(f"[{code}] CSV 다운로드 ({atch_id})")
    text = fetch_csv(atch_id)
    lots = convert(text, gu_name)
    print(f"[{code}] {len(lots)}곳 변환")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "district": gu_name,
        "districtCode": code,
        "category": "residential",
        "source": "공공데이터포털 전국거주자우선주차정보표준데이터",
        "updatedAt": datetime.now(KST).date().isoformat(),
        "lots": lots,
    }
    out_path = OUT_DIR / f"{code}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{code}] wrote {out_path.relative_to(ROOT)}")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    target = argv[1].strip().lower()
    if target == "all":
        results = []
        for code in DISTRICT_UDDI:
            results.append(scrape_one(code))
            time.sleep(1.5)  # data.go.kr rate limit 회피
        return max(results) if results else 0
    return scrape_one(target)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
