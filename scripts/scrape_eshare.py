"""
공유누리 (eshare.go.kr) 공공개방 주차장 — 서울특별시

엔드포인트 (인증키 불필요, 지도 페이지가 사용하는 내부 API):
    POST https://www.eshare.go.kr/UserPortal/Upc/UpcMapSrch/selectUpcParkingMap.do
    POST https://www.eshare.go.kr/UserPortal/Upc/UpcMapSrch/selectUpdParkingSvcMapTotalCount.do

서울 좌표 박스(swLat,swLng,neLat,neLng)로 한 번에 받아와서
data/lots/shared_seoul.json 으로 저장.

(필요시 300건 초과 대비 박스를 4분할하도록 fallback 포함)
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
OUT_PATH = LOTS_DIR / "shared_seoul.json"
KST = timezone(timedelta(hours=9))

BASE = "https://www.eshare.go.kr"
COUNT_URL = f"{BASE}/UserPortal/Upc/UpcMapSrch/selectUpdParkingSvcMapTotalCount.do"
LIST_URL = f"{BASE}/UserPortal/Upc/UpcMapSrch/selectUpcParkingMap.do"

HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": "Mozilla/5.0",
    "Referer": f"{BASE}/UserPortal/Upd/UpdParkingSvcMap/index.do",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# 주차장 분류 코드 (JS에서 확인: 010701/02/03/99 = 노상/노외/부설/기타)
RSRC_CD_LIST = [
    {"rsrcClsCd": "010701"},
    {"rsrcClsCd": "010702"},
    {"rsrcClsCd": "010703"},
    {"rsrcClsCd": "010799"},
]

# 서울 외곽 좌표 박스 (대략)
SEOUL_BBOX = {"swLat": 37.42, "swLng": 126.76, "neLat": 37.70, "neLng": 127.19}


def post_json(url: str, payload: dict) -> dict:
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_bbox(swLat, swLng, neLat, neLng):
    """주어진 BBox에서 주차장 목록 가져오기. 300건 이상이면 4분할 재귀."""
    payload = {
        "swLat": swLat, "swLng": swLng, "neLat": neLat, "neLng": neLng,
        "baseY": (swLng + neLng) / 2,
        "baseX": (swLat + neLat) / 2,
        "rsrcCdList": RSRC_CD_LIST,
        "freeYN": "all",
    }
    cnt = post_json(COUNT_URL, payload).get("totalCnt", 0)
    print(f"[eshare] bbox({swLat:.3f},{swLng:.3f})~({neLat:.3f},{neLng:.3f}) → {cnt}건")

    if cnt == 0:
        return []
    if cnt >= 300:
        # 4분할 후 재귀
        mid_lat = (swLat + neLat) / 2
        mid_lng = (swLng + neLng) / 2
        out = []
        for box in [
            (swLat, swLng, mid_lat, mid_lng),
            (swLat, mid_lng, mid_lat, neLng),
            (mid_lat, swLng, neLat, mid_lng),
            (mid_lat, mid_lng, neLat, neLng),
        ]:
            out.extend(fetch_bbox(*box))
        return out

    data = post_json(LIST_URL, payload)
    return data.get("srchList", []) or []


def parse_district(addr: str) -> tuple[str, str]:
    """주소에서 자치구 추출 → (district_kor, district_code)"""
    m = re.search(r"서울(?:특별시)?\s+([가-힣]+구)", addr or "")
    if not m:
        return ("", "")
    kor = m.group(1)
    code_map = {
        "강남구": "gangnam", "강동구": "gangdong", "강북구": "gangbuk", "강서구": "gangseo",
        "관악구": "gwanak", "광진구": "gwangjin", "구로구": "guro", "금천구": "geumcheon",
        "노원구": "nowon", "도봉구": "dobong", "동대문구": "dongdaemun", "동작구": "dongjak",
        "마포구": "mapo", "서대문구": "seodaemun", "서초구": "seocho", "성동구": "seongdong",
        "성북구": "seongbuk", "송파구": "songpa", "양천구": "yangcheon", "영등포구": "yeongdeungpo",
        "용산구": "yongsan", "은평구": "eunpyeong", "종로구": "jongno", "중구": "junggu",
        "중랑구": "jungnang",
    }
    return (kor, code_map.get(kor, ""))


def fmt_fee(fee_raw) -> str:
    try:
        fee = int(float(fee_raw or 0))
        return f"{fee:,}원" if fee > 0 else "-"
    except (ValueError, TypeError):
        return "-"


def to_lot(r: dict) -> dict | None:
    try:
        lat = float(r.get("laVal") or 0)
        lng = float(r.get("loVal") or 0)
    except (ValueError, TypeError):
        return None
    if lat < 33 or lng < 124:
        return None

    addr_main = (r.get("addr") or "").strip()
    addr_dtl = (r.get("dtlAddr") or "").strip()
    addr = re.sub(r"\s+", " ", f"{addr_main} {addr_dtl}").strip()
    name = (r.get("rsrcNm") or "").strip()

    is_free = (r.get("freeYnNm") or "").upper() == "Y"
    base_fee = r.get("basFee") or 0
    hourly_str = "무료" if is_free else (fmt_fee(base_fee) if base_fee else "요금 정보 없음")

    district_kor, district_code = parse_district(addr_main)

    return {
        "name": name or "이름없음",
        "address": addr,
        "lat": lat,
        "lng": lng,
        "code": (r.get("rsrcNo") or "").strip(),
        "operationType": "공유",
        "applyMethod": (r.get("rsrcClsNm") or "").strip(),  # 노상/노외/부설
        "spaces": None,
        "grade": "-",
        "hourly": hourly_str,
        "hourlyAvailable": True,
        "monthly": {"day": "-", "night": "-", "all": "-"},
        "hours": "운영시간은 공유누리 상세 페이지 참고",
        "tel": (r.get("chrgrTel") or "").strip() or None,
        "mapLink": f"{BASE}/UserPortal/Upv/UprParking/index.do?rsrc_no={r.get('rsrcNo','')}",
        "category": "shared",
        "source": "eshare-go-kr",
        "districtKor": district_kor,
        "districtCode": district_code,
        "rsrcDcd": (r.get("rsrcDcd") or "").strip(),
        "realtimeKey": None,
    }


def main():
    print(f"[eshare] fetching Seoul shared parking from {LIST_URL}")
    raw_list = fetch_bbox(**SEOUL_BBOX)
    print(f"[eshare] raw fetched: {len(raw_list)} 건")

    # rsrcNo 기준 중복 제거 (4분할 박스에서 겹칠 수 있음)
    seen = set()
    uniq = []
    for r in raw_list:
        no = r.get("rsrcNo")
        if no and no not in seen:
            seen.add(no)
            uniq.append(r)
    print(f"[eshare] dedup: {len(uniq)} 건")

    # 서울 자치구가 포함된 주소만 (BBox에 인천/경기 일부 들어올 수 있음)
    lots = []
    for r in uniq:
        addr = r.get("addr") or ""
        if "서울" not in addr:
            continue
        lot = to_lot(r)
        if lot:
            lots.append(lot)
    print(f"[eshare] filtered 서울만: {len(lots)} 건")

    out = {
        "district": "서울특별시",
        "districtCode": "shared_seoul",
        "operator": "공유누리(행정안전부)",
        "source": "https://www.eshare.go.kr",
        "updatedAt": datetime.now(KST).date().isoformat(),
        "lots": lots,
    }

    LOTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[eshare] saved {len(lots)} lots → {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
