# 기록 사이의 이동 — 공공자전거 숨은 재배치 진단과 AI·형평 배치 제안

창원시 공영자전거 '누비자'의 공개 이용기록 1,307만 건(2023~2025)을 자전거 번호로 이어, 이용기록 사이에 숨은 이동(재배치 차량·정비 등)을 찾고, AI 수요 예측과 취약 거점 최소 보장을 결합한 야간 재배치를 관측 대여 재생 실험으로 비교한 분석 코드다. 자전거 번호·대여반납 시각·거점이 담긴 다른 도시의 이력(예: 대전 타슈, 김해)도 열 이름·운영센터 정의를 도시별로 변환하면 같은 진단 절차를 적용할 수 있다(현재 코드는 누비자 파일 형식에 맞춰져 있고, 다른 도시 실행 결과는 없다).

## 사용한 공개 데이터
공개 공공데이터 15종만 사용(민간 데이터 없음). 목록·제공기관·플랫폼·URL·쓰임은 [`docs/report/data_sources.json`](docs/report/data_sources.json). 원자료는 저장소에 넣지 않았으니 각 URL에서 내려받아 `data/raw/` 아래 수집 코드가 기대하는 경로에 둔다(`scripts/collection/` 참조).

## 분석 흐름과 재현 순서
```powershell
pip install -r requirements-analysis.txt
python scripts/analysis/build_event_panel.py                # 0 시간 패널(event_panel/hourly_panel_*.parquet, 2단계 입력)
python scripts/analysis/trace_bike_chains.py               # 1 자전거 연쇄 추적: 기록 없는 이동·고도·의존도
python scripts/analysis/build_accessibility_scenarios.py   # 2 버스·의료·약국·시장 접근성 → 취약 거점(저장소의 잠금 규칙과 대조)
python scripts/analysis/estimate_observed_truck_km.py      # 3 관측 이동의 차량 경로 추정
python scripts/analysis/forecast_station_day_need.py       # 4 거점·일 필요 대수 AI 예측(시간순 학습·검증·시험)
python scripts/analysis/run_rebalancing_experiments.py --tag v2   # 5 배치 실험(검증기간 설정 선택 → 시험기간 1회)
python scripts/analysis/stat_tests.py                      # 6 부트스트랩 신뢰구간·Wilcoxon·가중 회귀
python scripts/ai/classify_council_llm.py                  # 7 시의회 회의록 LLM 분류·교차 검증(claude CLI 또는 ANTHROPIC_API_KEY)
python scripts/ai/dispatch_brief.py --date 2025-04-15      # 8 LangGraph 배차 브리핑(초안→자동 검증→사람 승인)
python -m pytest tests/test_simulate_rebalancing.py        # 시뮬레이터 단위 테스트
```
준비 사항
- 원자료: `data/raw/` 아래 수집 코드가 기대하는 경로. 의원·약국 좌표는 `scripts/grok/grok_hira_extract_changwon5.py`로 추출
- 취약 거점 판정 잠금: 저장소의 `data/processed/accessibility_scenarios/vulnerability_lock.json`(2026-10 고정본)을 그대로 쓴다. 지우고 `--write-lock`으로 새로 만들면 사전 고정이 아니라 재현용 잠금이다
- 1단계는 `rasterio`(고도 타일)가 필요하다. 7·8단계와 시험은 `anthropic`·`langgraph`·`pytest`(requirements 선택 항목)

보고서 그림·수치: `scripts/report/fig_*.py` → `scripts/report/build_numbers.py` → `scripts/report/build_deck.js`(pptxgenjs) → `scripts/report/render.py`(PowerPoint PDF 내보내기).

## 주요 산출물(저장소 포함분)
- 연도별 기록 없는 이동: `data/processed/bike_chains/yearly_summary.csv`, 원자료 감사 `audit.json`
- 예측 성능: `data/processed/forecast/q_metrics*.csv`, 잠금 `q_model_lock.json`
- 배치 실험 결과(v2): `data/processed/rebalancing_sim/results_v2.csv`, `meta_v2.json`, 사전 고정 `policy_lock_v1.json`·`policy_lock_v2.json`(오류 수정 이력 포함)
- 통계 검정: `data/processed/stats/stat_tests.json`
- 방법·결과 설명: `data/metadata/*.md`

## 검증 장치
- 보존 검사: 이용 수 − 자전거 수 = 연속 이용쌍 수
- 시간순 분리: 학습 2023.2~2024.9 · 검증 2024.10~12 · 시험 2025.1~6, 시험 결과는 설정 고정 뒤 확인
- 실험 코드·집단 파일 SHA-256 잠금, 코드 수정 시 새 잠금 추가(이전 결과 보존)
- LLM 분류는 다른 모델이 무작위 표본을 독립 재분류해 일치도(κ) 보고, 브리핑은 표에 없는 숫자·거점명을 자동 차단

## 한계
- 기록 없는 이동의 실제 주체·시각은 기록에 없어 '추정 이동'이다
- 실험은 관측된 대여를 재생하므로 자전거가 없어 포기한 수요는 담지 못한다
- 접근성 분류는 2024.12~2026.10 시점 자료로 만든 정적 분류다
- 2025년 7월 출발 기록은 원자료에 없어 0으로 채우지 않고 제외했다

## 비밀키
API 키는 `.env.local`(저장소 제외)에만 둔다. 저장소에는 키·원자료·자전거 번호가 담긴 가공 파일을 넣지 않는다.
