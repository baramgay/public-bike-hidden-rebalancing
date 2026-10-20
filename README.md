# 기록 사이의 이동: 공공자전거 숨은 재배치 진단과 AI·형평 배치 제안

창원시 공영자전거 '누비자'의 공개 이용기록 1,307만 건(2023~2025)을 자전거 번호로 이어 기록 사이에 숨은 이동(재배치 차량·정비 등)을 찾고, 수요 예측과 취약 거점 최소 보장을 결합한 야간 재배치를 관측 대여 재생 실험으로 비교한 분석 코드다. 현재 코드는 누비자 파일 형식에 맞춰져 있다.

## 데이터
공개 공공데이터 15종(목록·출처는 [`docs/report/data_sources.json`](docs/report/data_sources.json)). 원자료는 저장소에 없으므로 각 URL에서 받아 `data/raw/` 아래 수집 코드가 기대하는 경로에 둔다(`scripts/collection/`).

## 실행 순서
```powershell
pip install -r requirements-analysis.txt
python scripts/analysis/build_event_panel.py                      # 0 시간 패널
python scripts/analysis/trace_bike_chains.py                      # 1 자전거 연쇄 추적
python scripts/analysis/build_accessibility_scenarios.py          # 2 접근성·취약 거점
python scripts/analysis/estimate_observed_truck_km.py             # 3 차량 경로 추정
python scripts/analysis/forecast_station_day_need.py              # 4 거점·일 필요 대수 예측
python scripts/analysis/run_rebalancing_experiments.py --tag v2   # 5 배치 실험
python scripts/analysis/stat_tests.py                             # 6 통계 검정
python scripts/ai/classify_council_llm.py                         # 7 시의회 회의록 분류
python scripts/ai/dispatch_brief.py --date 2025-04-15             # 8 배차 브리핑
python -m pytest tests
```
- 1단계는 `rasterio`(고도 타일), 7·8단계와 시험은 `anthropic`·`langgraph`·`pytest`가 필요하다
- 취약 거점 판정은 저장소의 `data/processed/accessibility_scenarios/vulnerability_lock.json`을 쓴다
- 보고서 그림·수치: `scripts/report/`

## 주요 산출물
`data/processed/` 아래 연도별 이동 요약(`bike_chains`), 예측 성능(`forecast`), 배치 실험 결과(`rebalancing_sim`), 통계 검정(`stats`). 방법과 결과 설명은 `data/metadata/*.md`.

## 검증과 한계
- 시간순 분리: 학습 2023.2~2024.9, 검증 2024.10~12, 시험 2025.1~6. 설정은 시험 전에 고정하고 코드·집단 파일은 SHA-256으로 잠근다
- 기록 없는 이동의 주체·시각은 기록에 없어 추정이다
- 실험은 관측된 대여만 재생하므로 자전거가 없어 포기한 수요는 담지 못한다
- 접근성 분류는 2024.12~2026.10 시점의 정적 분류다
- 2025년 7월 출발 기록은 원자료에 없어 0으로 채우지 않고 제외했다

API 키는 `.env.local`(저장소 제외)에만 둔다.
