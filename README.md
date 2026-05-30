# 🅿️ Seoul-Park

서울특별시 25개 자치구의 **공영 · 공유 · 거주자우선 주차장 6만여 곳**을 한 지도에서
검색·결제 연동·내비 안내까지 한 번에 처리할 수 있는 웹 앱입니다.

🌐 **공개 사이트**: https://seoul-park.github.io/Seoul-Park

---

## ✨ 주요 기능

### 지도 & 검색

- 카카오 지도 기반 한 화면에서 6만여 곳의 주차장 위치 표시
- **카테고리별 마커**: 파랑 P(공영) / 보라 P(공유) / 녹색 P(거주자우선)
- **화면 안/밖 자동 swap**: 화면 안엔 큰 P 핀, 밖은 작은 점으로 가독성 ↑
- **현재 위치 자동 인식**: GPS 동의 시 자치구 자동 전환 + 중심 이동
- 우하단 **"내 위치로 이동"** 동그란 버튼
- 우하단 **마커 범례** (파랑·보라·녹색 P)
- **즐겨찾기 ⭐** 기능 (localStorage 영구 저장, 상단 드롭다운에서 빠른 접근)

### 좌측 사이드바

- 출발지/도착지 자동완성 검색 (카카오 Places API)
- **현재 위치 → 도착지 거리순 정렬**
- 좌측 리스트 호버 시 지도가 부드럽게 panTo + 강조 P 핀 두 번 점프 효과
- 카카오내비 / 티맵 앱 딥링크 호출 (모바일)

### 안내 카드

- 마커 또는 리스트 클릭 → 카드 표시
- **시간주차 요금** + **운영시간 + 주차면수** + 카테고리별 결제 연동 버튼
- **카카오T 주차** + **자치구 공식 시설관리공단** 두 결제 버튼 (거주자우선)
- **공유누리에서 예약·결제** 버튼 (공유주차장)
- **거리뷰** 모달 (카카오 Roadview)
- **경로 검색** 클릭 시 도착지 자동 입력 + 좌측 사이드바 내비 활성화

### 실시간

- 서울시 OpenAPI 기준 **124곳 실시간 잔여석**, 10분마다 갱신
- 만차 시 마커에 노란색 강조

---

## 📊 데이터 현황

| 카테고리 | 수량 | 자치구 수 | 출처 |
|---|---|---|---|
| **공영주차장** | 1,110곳 | 25개 (서울시·자치구 운영 분리) | 서울 OpenAPI · 표준데이터 · 시설공단 |
| **공유주차장** | 111곳 | 13개 | 공유누리(행정안전부) |
| **거주자우선주차** | 59,168곳 | 16개 | 공공데이터포털 표준데이터 |
| **합계** | **60,389곳** | | |

### 데이터 출처

- [서울 열린데이터광장](https://data.seoul.go.kr) — GetParkingInfo (실시간) · GetParkInfo (정적)
- [공공데이터포털 표준데이터 15012896](https://www.data.go.kr/data/15012896/standard.do) — 전국주차장정보
- [공공데이터포털 표준데이터 15021105](https://www.data.go.kr/data/15021105/standard.do) — 전국거주자우선주차정보
- [공유누리 OPEN API](https://www.eshare.go.kr/OpenApi/Info/detail.do?svcNo=15) — 공유자원 주차장 목록
- [구로구시설관리공단](https://www.gurosisul.or.kr) 등 자치구 시설공단

---

## 🏛 자치구별 거주자우선주차 결제 시스템

거주자우선주차 방문차량 결제는 자치구마다 다른 시스템을 사용합니다. 앱은 카드에서 두 가지 옵션을 제공해요.

| 자치구 | 공식 시스템 |
|---|---|
| 구로 | [parkguro.or.kr](https://www.parkguro.or.kr/userNew/bangmoon/bangmoon_create.aspx) |
| 강남 | [gn.gncity.or.kr](https://gn.gncity.or.kr/) |
| 강서 | [parking.gssi.or.kr](https://parking.gssi.or.kr/) |
| 영등포 | [rparking.y-sisul.or.kr](https://rparking.y-sisul.or.kr/) |
| 금천 | [park.gfmc.kr](https://park.gfmc.kr/) |
| 동작 | [park.idongjak.or.kr](https://park.idongjak.or.kr/) |
| 양천 | [ycs.or.kr](https://www.ycs.or.kr/) |
| 성북 | [gongdan.go.kr/park](https://www.gongdan.go.kr/park/) |
| 광진 | [구청 공유주차 안내](https://www.gwangjin.go.kr/portal/main/contents.do?menuNo=200619) |
| 종로 · 중랑 · 송파 · 서초 · 노원 · 강북 | `{자치구}.park119.{co.kr/or.kr/com}` |
| 관악 | [gwanak.parkinghome.com](https://gwanak.parkinghome.com/) |

---

## 📂 저장소 구조

```
Seoul-Park/
├── index.html                 메인 단일 페이지 앱
├── data/
│   ├── districts.json         25개 자치구 메타
│   ├── realtime.json          실시간 잔여석 (10분 갱신)
│   ├── lots/                  공영·공유 주차장 (구별 + shared_seoul.json)
│   └── residential/           거주자우선주차 (16개 구)
├── scripts/                   Python 데이터 수집기
│   ├── requirements.txt
│   ├── scrape.py              시설공단 + 서울 GetParkingInfo
│   ├── scrape_standard.py     공공데이터 표준데이터
│   ├── scrape_parkinfo.py     서울 GetParkInfo (2,293곳)
│   ├── scrape_residential.py  거주자우선 (16개 자치구)
│   ├── scrape_seongdong.py    성동구도시관리공단 OpenAPI
│   ├── scrape_eshare.py       공유누리 (정식 API + 내부 fallback)
│   └── fetch_realtime.py      실시간 잔여석
└── .github/workflows/
    ├── sync.yml               매주 월요일 04시(KST) 정적 동기화
    └── realtime.yml           10분 주기 실시간 갱신
```

---

## 🔐 환경 변수 (GitHub Secrets)

저장소 **Settings → Secrets and variables → Actions** 에 등록 필요:

| Secret 이름 | 출처 | 용도 |
|---|---|---|
| `SEOUL_OPEN_API_KEY` | [서울 열린데이터광장](https://data.seoul.go.kr) | GetParkingInfo / GetParkInfo |
| `ESHARE_API_KEY` | [공유누리](https://www.eshare.go.kr/OpenApi/Info/detail.do?svcNo=15) | 공유주차장 정식 API (없으면 내부 fallback 자동 동작) |

---

## 🛠 기술 스택

- **Frontend**: Vanilla HTML / CSS / JavaScript (단일 파일, 빌드 도구 없음)
- **지도 SDK**: Kakao Maps JavaScript SDK (services, clusterer, autoload=false)
- **경로**: Kakao Mobility Directions API
- **검색**: Kakao Places API (keyword + address)
- **거리뷰**: Kakao Roadview / RoadviewClient
- **데이터 수집**: Python 3.12 (requests, beautifulsoup4)
- **CI/CD**: GitHub Actions (cron)
- **호스팅**: GitHub Pages (main 브랜치)

---

## 🚀 로컬 실행

```bash
# 1. 데이터 갱신 (선택)
cd scripts
pip install -r requirements.txt
SEOUL_OPEN_API_KEY=... python scrape.py all
ESHARE_API_KEY=...    python scrape_eshare.py

# 2. 정적 서버 띄우기
cd ..
npx serve -p 3335 .
# → http://localhost:3335 접속

# 단, Kakao Maps SDK는 등록된 도메인에서만 작동 → 카카오 개발자 콘솔에 localhost:3335 등록 필요
```

---

## 📜 라이선스

데이터는 각 기관(서울특별시, 행정안전부, 공공데이터포털 제공기관)의 라이선스(대부분 공공누리 1유형)를 따릅니다.
코드는 개인·비영리 학습 목적으로 자유 사용 가능.

---

## 🤝 기여

이슈 / PR 환영합니다. 자치구별 시설공단 운영시간이나 결제 시스템 정보를 알고 계시면 알려주세요.

---

🤖 _이 프로젝트는 [Claude Code](https://claude.com/claude-code) 와 함께 만들어졌습니다._
