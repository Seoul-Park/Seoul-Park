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
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "residential"
KST = timezone(timedelta(hours=9))

# 구별 atchFileId (확장 시 여기 추가)
DISTRICT_CONFIG = {
    "guro": {
        "name": "구로구",
        "atchFileId": "FILE_000000003572148",
        "fileDetailSn": "1",
        "publicDataPk": "15021105",
    },
}


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


def fetch_csv(cfg: dict) -> str:
    url = (f"https://www.data.go.kr/cmm/cmm/fileDownload.do?"
           f"atchFileId={cfg['atchFileId']}&fileDetailSn={cfg['fileDetailSn']}")
    headers = {"Referer": f"https://www.data.go.kr/data/{cfg['publicDataPk']}/standard.do"}
    res = requests.get(url, headers=headers, timeout=60)
    res.raise_for_status()
    return res.content.decode("utf-8-sig")


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


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    code = argv[1].strip().lower()
    cfg = DISTRICT_CONFIG.get(code)
    if not cfg:
        print(f"[{code}] 미등록 구 코드", file=sys.stderr)
        return 1

    print(f"[{code}] downloading CSV ({cfg['atchFileId']})")
    text = fetch_csv(cfg)
    lots = convert(text, cfg["name"])
    print(f"[{code}] parsed {len(lots)} parking spots")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "district": cfg["name"],
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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
