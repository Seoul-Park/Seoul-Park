"""
서울 열린데이터 GetParkingInfo에서 실시간 잔여석 정보를 받아
data/realtime.json 으로 저장.

환경변수:
    SEOUL_OPEN_API_KEY    필수
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "realtime.json"
KST = timezone(timedelta(hours=9))


def main() -> int:
    api_key = os.environ.get("SEOUL_OPEN_API_KEY")
    if not api_key:
        print("ERROR: SEOUL_OPEN_API_KEY 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/GetParkingInfo/1/1000/"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    info = res.json().get("GetParkingInfo", {})

    result = info.get("RESULT", {})
    if result.get("CODE") != "INFO-000":
        print(f"ERROR: API {result.get('CODE')} {result.get('MESSAGE')}", file=sys.stderr)
        return 1

    rows = info.get("row", [])
    lots = {}
    for r in rows:
        code = str(r.get("PKLT_CD") or "").strip()
        if not code:
            continue
        try:
            total = int(r.get("TPKCT") or 0)
            current = int(r.get("NOW_PRK_VHCL_CNT") or 0)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        lots[code] = {
            "total": total,
            "available": max(0, total - current),
            "updatedAt": r.get("NOW_PRK_VHCL_UPDT_TM", ""),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "서울 열린데이터 GetParkingInfo",
        "lots": lots,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(lots)} lots)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
