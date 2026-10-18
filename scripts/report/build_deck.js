// A4 세로 분석보고서 PPTX 생성기(표지 + 본문 5쪽 + 참고문헌). 숫자는 outputs/report/report_numbers.json(분석 출력)에서만 읽는다.
// 실행: NODE_PATH=tmp/pptxgenjs-runtime/node_modules node scripts/report/build_deck.js
// 문체: 개조식(명사형 종결), 줄표 대신 쌍점·괄호. 글자 크기 하한 7.5pt(표 속 URL 7.0pt). 점검: scripts/report/qa_layout.py
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const N = JSON.parse(fs.readFileSync(path.join(ROOT, "outputs/report/report_numbers.json"), "utf8"));
const DS = JSON.parse(fs.readFileSync(path.join(ROOT, "docs/report/data_sources.json"), "utf8"));
const REFS = JSON.parse(fs.readFileSync(path.join(ROOT, "docs/report/references.json"), "utf8"));
const TEAM = "길이음";                             // 공식 양식 '이름/팀명'(팀 참가)
const OUT = path.join(ROOT, `outputs/report/${TEAM}_분석보고서.pptx`);
const IMG = (p) => path.join(ROOT, p);
const FIG = (name) => `outputs/report_figures/${name}.png`;

// ---------- 제목·식별 ----------
const TITLE_MAIN = "기록 사이의 이동";
const TITLE_SUB = "공공자전거 숨은 재배치 진단과 AI·형평 배치 제안";
const CASE = "창원시 공영자전거 ‘누비자’ 이용기록 1,307만 건으로 본 전국 적용형 공개 분석";
const TOPIC = "공공자전거 이용기록을 자전거 번호로 연결해 기록 없는 재배치 이동을 진단하고, AI 수요 예측과 취약 거점 최소 보장을 결합한 야간 재배치 방안 제안(창원 누비자 사례, 다른 도시 이력에도 적용할 수 있는 공개 진단 절차)";
const CODE_URL = "https://github.com/baramgay/public-bike-hidden-rebalancing";
const RUN_HEAD = `${TITLE_MAIN} · ${TITLE_SUB}`;

const mm = (v) => v / 25.4;
const C = {
  // 보조 글자 회색은 흰 바탕 대비 7:1 이상(사용자 지시: 회색 글자는 짙게)
  forest: "183F35", accent: "00897B", teal: "137F7B", mint: "00B8B4", ink: "26342E", ink2: "3A4640",
  muted: "4D5953", bg: "F2F5F1", line: "D5DDD8", light: "BFDDD6", pale: "E6F2EF", white: "FFFFFF", gray: "9AA5AD",
  map: "EEF5F2",
};
const F = { reg: "Pretendard", semi: "Pretendard SemiBold", xb: "Pretendard ExtraBold" };
const pct = (x, d = 1) => `${(x * 100).toFixed(d)}%`;
const int = (x) => Math.round(x).toLocaleString("en-US");
const fx = (x, d = 1) => Number(x).toFixed(d).replace(/^-/, "−");
const sgn = (x, d = 1) => `${x < 0 ? "−" : "+"}${Math.abs(x).toFixed(d)}`;
// 수상작 관행(그림 번호 없이 내용·조건·출처 캡션, docs/research/award_report_style_grok_20261018.md)
const fig = (t) => t;

const pres = new pptxgen();
pres.defineLayout({ name: "A4P", width: mm(210), height: mm(297) });
pres.layout = "A4P";
pres.title = `${TITLE_MAIN}: ${TITLE_SUB}`;
pres.subject = "AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전 분석보고서";

// ---------- 공통 도우미 ----------
// 문자열 속 **핵심어**는 SemiBold·숲색으로 강조
const EM = { fontFace: F.semi, color: C.forest };
const rich = (t, base = {}) => t.split("**").map((p, i) => ({ text: p, options: i % 2 ? { ...base, ...EM } : { ...base } })).filter((r) => r.text);
function T(s, text, x, y, w, h, o = {}) {
  if (typeof text === "string" && text.includes("**")) text = rich(text);
  s.addText(text, {
    x: mm(x), y: mm(y), w: mm(w), h: mm(h), margin: 0, isTextBox: true, valign: "top",
    fontFace: F.reg, fontSize: 9, color: C.ink, lineSpacingMultiple: 1.2, ...o,
  });
}
function box(s, x, y, w, h, o = {}) {
  s.addShape(o.r === 0 ? pres.shapes.RECTANGLE : pres.shapes.ROUNDED_RECTANGLE, {
    x: mm(x), y: mm(y), w: mm(w), h: mm(h), rectRadius: mm(o.r ?? 2),
    fill: { color: o.fill ?? C.bg }, line: o.line ? { color: o.line, width: o.lw ?? 0.6 } : { type: "none" },
  });
}
function img(s, file, x, y, w, h, o = {}) {
  s.addImage({ path: IMG(file), x: mm(x), y: mm(y), w: mm(w), h: mm(h), ...o });
}
function cover(s, file, x, y, w, h) {
  img(s, file, x, y, w, h, { sizing: { type: "cover", w: mm(w), h: mm(h) } });
}
function runHead(s, no) {
  T(s, RUN_HEAD, 12, 5, 150, 4, { fontSize: 7.5, color: C.muted });
  if (no) T(s, `${no} / 5`, 168, 5, 30, 4, { fontSize: 7.5, color: C.muted, align: "right" });
  s.addShape(pres.shapes.LINE, { x: mm(12), y: mm(9.6), w: mm(186), h: 0, line: { color: C.line, width: 0.5 } });
}
function page(no) {
  const s = pres.addSlide();
  s.background = { color: C.white };
  runHead(s, no);
  return s;
}
function pill(s, text, x, y, w) {      // 공식 양식 항목명
  box(s, x, y, w, 6, { fill: C.forest, r: 3 });
  T(s, text, x, y + 0.9, w, 4.5, { fontFace: F.semi, fontSize: 9, color: C.white, align: "center" });
}
function head(s, text, y, size = 14) {
  T(s, text, 12, y, 186, 7, { fontFace: F.xb, fontSize: size, color: C.forest, lineSpacingMultiple: 1.05 });
}
function sub(s, text, x, y, w = 120) {
  T(s, text, x, y, w, 5, { fontFace: F.semi, fontSize: 9.5, color: C.forest });
}
// 그림 소제목
function figHead(s, title, x, y, w) {
  T(s, title, x, y, w, 5, { fontFace: F.semi, fontSize: 9, color: C.forest });
}
function cap(s, text, x, y, w, h = 4) {
  T(s, text, x, y, w, h, { fontSize: 7.5, color: C.muted, lineSpacingMultiple: 1.12 });
}
function stat(s, x, y, w, h, big, unit, label, o = {}) {
  box(s, x, y, w, h, { fill: o.fill ?? C.bg });
  T(s, [{ text: big, options: { fontFace: F.xb, fontSize: o.size ?? 15, color: o.color ?? C.forest } },
        { text: unit, options: { fontFace: F.semi, fontSize: 9, color: o.color ?? C.forest } }],
    x + 3, y + 2.4, w - 6, 8.5);
  T(s, label, x + 3, y + 11, w - 6, h - 12, { fontSize: 8, color: C.ink2, lineSpacingMultiple: 1.15 });
}
function icon(s, name, x, y, size) { img(s, `design/sol/derived/06_icon_${name}.png`, x, y, size, size); }
// 본체만 남긴 아이콘(_tc)을 상자(w×h) 안에 비율 유지로 맞춤: 가로로 긴 그림과 세로로 긴 그림의 크기를 고르게
function fitImg(s, file, x, y, w, h, align = "left") {      // PNG 머리(IHDR)의 가로·세로로 비율 계산
  const b = fs.readFileSync(IMG(file)), r = b.readUInt32BE(16) / b.readUInt32BE(20), iw = Math.min(w, h * r), ih = iw / r;
  const ix = align === "right" ? x + w - iw : align === "center" ? x + (w - iw) / 2 : x;
  img(s, file, ix, y + (h - ih) / 2, iw, ih);
}
const iconFit = (s, name, ...a) => fitImg(s, `design/sol/derived/06_icon_${name.replace(/_t$/, "")}_tc.png`, ...a);
// 글머리표는 항목의 첫 run에만(pptxgenjs는 bullet 있는 run마다 새 문단을 연다), 줄바꿈은 마지막 run에서
function bullets(s, items, x, y, w, h, o = {}) {
  s.addText(items.flatMap((t, i) => {
    const runs = rich(t);
    Object.assign(runs[0].options, { bullet: { indent: 9 }, paraSpaceAfter: o.gap ?? 2 });
    runs[runs.length - 1].options.breakLine = i < items.length - 1;
    return runs;
  }), { x: mm(x), y: mm(y), w: mm(w), h: mm(h), margin: 0, isTextBox: true, valign: "top",
    fontFace: F.reg, fontSize: o.size ?? 8.4, color: o.color ?? C.ink, lineSpacingMultiple: 1.15 });
}

// ---------- 수치 ----------
const depHigh = N.dependency_rows.find((r) => r.name.startsWith("고지대"));
const depLow = N.dependency_rows.find((r) => r.name.startsWith("저지대"));
const depBoth = N.dependency_rows.find((r) => r.group !== "고도" && r.name !== "그 외");
const depOther = N.dependency_rows.find((r) => r.name === "그 외");
const ex = N.fig.bike_day_4503;
const sim = (strategy, budget, split = "test") => N.simulation.find((r) => r.split === split && r.strategy === strategy && r.budget === budget);
const ES = N.equal_service;
const PF = N.fig.policy_frontier, EQ = N.fig.equity, NT = N.fig.notruck, MAE = N.fig.forecast_mae, CO = N.fig.council_issues;
const saveAI = ES.rule4w.moves_per_night - ES.ai.moves_per_night;
const saveAIw = ES.rule4w.moves_per_night - ES.ai_weather.moves_per_night;
const kmSaveAI = ES.rule4w.truck_km_per_night - ES.ai.truck_km_per_night;
const co2 = N.co2_kg_per_km;
const yearlyShares = Object.values(N.moved_share_by_year).map((v) => pct(v, 1));
const testDemand = sim("none", 0).demand;
const ST = N.stats, REG = ST.dependency_regression.main.coef, CVN = ST.dependency_regression.main.composite_vs_nonvulnerable;
const ci = (a, k = 100, d = 1) => `${fx(a[0] * k, d)}~${fx(a[1] * k, d)}`;
const vulnGain = -EQ.vulnerable_gain_ai_fair_vs_ai.zero_hours_pct;           // 취약 거점 빈 시간 감소율(%)
const yr = (km, f) => (km * 365 * f) / 1000;

// =====================================================================
// 표지
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  img(s, "design/sol/01_cover_forest_road_a.png", 0, 0, 210, 297, { sizing: { type: "cover", w: mm(210), h: mm(297) } });
  T(s, "AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전 · 분석보고서", 16, 15, 178, 7,
    { fontFace: F.semi, fontSize: 12, color: C.forest });
  T(s, TITLE_MAIN, 16, 27, 178, 20, { fontFace: F.xb, fontSize: 46, color: C.forest, lineSpacingMultiple: 1.0 });
  T(s, TITLE_SUB, 16, 49, 178, 10, { fontFace: F.semi, fontSize: 19, color: C.ink, lineSpacingMultiple: 1.1 });
  T(s, CASE, 16, 61, 178, 7, { fontFace: F.semi, fontSize: 13.5, color: C.teal });
  box(s, -1, 278, 212, 20, { fill: C.white, r: 0 });    // 그림 속 자전거 바퀴(약 277mm) 아래로, 쪽 가장자리에 그림이 비치지 않게 바깥까지
  fitImg(s, "design/sol/derived/10_team_gilieum_mark_tc.png", 16, 281.5, 20, 5.3);   // 팀 심볼, 본체 높이 약 5mm
  T(s, `팀 ${TEAM}`, 26.4, 281.2, 100, 6, { fontFace: F.semi, fontSize: 13, color: C.forest, valign: "middle" });
  T(s, `공개 공공데이터 ${DS.rows.length}종 · 이용기록 ${int(N.valid_rows / 1e4)}만 건 · 2023~2025년`, 16, 289, 110, 5,
    { fontSize: 10.5, color: C.ink2 });
  // 공식 양식 1쪽 머리의 두 CI(원본 추출, design/form_ci/README.md). 하늘 배경에서는 숲과나눔 로고가 흐려 흰 띠 안에 둠
  fitImg(s, "design/form_ci/hankyoreh.png", 135, 285.5, 22, 6, "right");
  fitImg(s, "design/form_ci/supgwananum.png", 161, 284.5, 33, 8, "right");
}

// =====================================================================
// 1쪽: 이름/팀명·주제, 분석 배경 및 목적
// =====================================================================
{
  const s = page(1);
  const lab = { fill: { color: C.bg }, fontFace: F.semi, fontSize: 8.5, color: C.forest, valign: "middle", align: "center" };
  const val = { fontSize: 8.5, color: C.ink, valign: "middle" };
  s.addTable([
    [{ text: "이름/팀명", options: lab }, { text: TEAM, options: val }],
    [{ text: "주제", options: lab }, { text: TOPIC, options: val }],
  ], { x: mm(12), y: mm(12.5), w: mm(186), colW: [mm(20), mm(166)], rowH: [mm(6), mm(10)],
    fontFace: F.reg, border: { type: "solid", pt: 0.5, color: C.line }, margin: [1.5, 4, 1.5, 4] });

  pill(s, "분석 배경 및 목적", 12, 31, 34);
  head(s, "이용기록 사이에 숨은 이동: 반납 거점과 다음 대여 거점의 불일치", 39.2);
  bullets(s, [
    "공공자전거 이용기록에는 대여·반납 거점과 시각만 남음. 같은 자전거의 **반납 거점과 다음 대여 거점이 다른 경우**를 ‘**기록 없는 이동**’으로 집계함. 재배치·정비·기록 누락 등이 포함될 수 있는 **자전거별 이동 정황**으로, 차량 운행 횟수와는 구분함",
    "창원시 공영자전거 ‘누비자’(터미널 454곳·자전거 5,745대, 2025년 운영사 공시)의 3년 이용기록으로 숨은 이동의 **규모·시간·장소**를 추적하고, **AI 예측·형평 기준**을 더한 재배치 방안을 실험으로 검증",
  ], 12, 47, 186, 17, { size: 8.6, gap: 1.5 });

  // 핵심 수치 띠
  const kpi = [
    [`${int(N.valid_rows / 1e4)}만`, "건", "3년 이용기록\n(2023~2025)"],
    [pct(N.moved_share_3y), "", "연속 이용쌍 중\n기록 없는 이동"],
    [int(N.moved_per_day_3y), "건", "하루 평균\n기록 없는 이동"],
    [`${int(N.moved_3y / 1e4)}만`, "건", "3년 핵심\n기록 없는 이동"],
  ];
  kpi.forEach(([v, u, l], i) => {
    const x = 12 + i * 47, col = i === 1 ? C.accent : C.forest;
    box(s, x, 65.3, 45, 13, { fill: C.pale });
    T(s, [{ text: v, options: { fontFace: F.xb, fontSize: 13.5, color: col } }, { text: u, options: { fontFace: F.semi, fontSize: 8.5, color: col } }],
      x + 2.5, 65.3, 22, 13, { valign: "middle" });
    T(s, l, x + 24, 65.3, 20.5, 13, { fontSize: 7.6, color: C.ink2, valign: "middle", lineSpacingMultiple: 1.1 });
  });

  img(s, "design/sol/derived/02_hill_section_crop.png", 12, 81, 92, 44);
  img(s, FIG("bike_day_4503"), 110, 80, 88, 49.2);
  cap(s, "개념도: 사람은 언덕을 내려가고, 자전거는 기록 없이 다시 올라감", 12, 126, 92, 7);
  cap(s, `실제 기록: 자전거 ${ex.bike}번의 하루(2024.1.10~11). 레알주차장 옆(해발 23m) 반납 후 성주 유니온빌리지(105m)에서 다음 대여, ` +
    `같은 밤 같은 구간 이동 ${N.example_bike.same_night_batch_25_to_159.length}대`, 110, 130.5, 88, 8);

  figHead(s, "이동 유형별 고도 방향(2024)", 12, 135, 96);
  img(s, FIG("elev_direction"), 12, 140.5, 89, 41);
  const NB = N.fig.national_bikes;
  figHead(s, "전국 시도별 공영자전거 대여 실적(2024)", 110, 139.5, 88);
  img(s, FIG("national_bikes"), 110, 145, 88, 37.2);
  cap(s, "자료: 2025 행정안전통계연보 표 4-2-7-2(2024.12.31 기준)",
    110, 182.6, 88, 8);
  const ED = N.ride_up_2024, EU = N.move_up_2024;
  T(s, [{ text: `오르막 비율: 사람이 탄 이동 ${pct(ED)}, 기록 없는 이동 ${pct(EU)}`, options: { fontFace: F.semi, color: C.forest } },
        { text: ". 기록 없는 이동 5건 중 4건은 언덕을 오르는 방향" }], 12, 182.6, 92, 8, { fontSize: 8, lineSpacingMultiple: 1.15 });

  sub(s, "분석 필요성", 12, 191.5);
  const why = [
    ["co2_t", "탄소 산정에서 빠진 배출", `운영사 탄소 감축량은 ‘이용 횟수 × 4.75km × 192g’으로 산정되며 **재배치 차량 배출은 미차감**. 2024년 재배치 경로 추정은 하루 약 ${int(N.truck_km_per_day_2024_cap20)}km`],
    ["hill_t", "고지대일수록 높은 의존도", `고도 상위 25% 거점은 대여의 **${pct(depHigh.dependency)}**가 기록 없는 이동 뒤 발생(하위 25%는 ${pct(depLow.dependency)}). 재배치 축소 시 **영향이 지역별로 불균등**`],
    ["bike_t", "전국 공통 과제", "전국 공영자전거 69,572대·연 대여 5,818만 건(2024). 자전거 번호가 담긴 이력(창원·대전·김해 등)은 **도시별 형식 변환 후 같은 진단 절차 적용 가능**"],
  ];
  why.forEach(([ic, t, d], i) => {
    const x = 12 + i * 63;
    box(s, x, 197.5, 60, 31);
    icon(s, ic, x + 2.5, 199.3, 9.5);
    T(s, t, x + 14, 201.5, 44, 5, { fontFace: F.semi, fontSize: 9, color: C.forest });
    T(s, d, x + 3, 210.5, 54.5, 17.5, { fontSize: 8, color: C.ink2, lineSpacingMultiple: 1.15 });
  });

  box(s, 12, 231.5, 186, 16, { fill: C.white, line: C.light });
  T(s, "참여 동기", 16, 234.2, 20, 5, { fontFace: F.semi, fontSize: 9, color: C.teal });
  T(s, "누비자 이용기록을 자전거 번호로 이어 보다가 사람이 타지 않은 이동이 **하루 1,600건 이상**임을 발견함. 운영사 탄소 감축량에는 이 이동의 차량 배출이 빠져 있음. " +
    "부담이 **어느 거점에 몰리는지** 확인하고, AI로 이동을 줄이면서 **접근이 불리한 거점의 대여를 지킬 수 있는지** 시험하고자 함",
  36, 234.2, 158, 12, { fontSize: 8.4, lineSpacingMultiple: 1.17 });

  sub(s, "분석 목적", 12, 250.5);
  T(s, "목표: 재배치 주행 감축과 취약 거점 형평 개선, 다른 도시에서도 쓰는 공개 코드·지표", 80, 250.7, 118, 5,
    { fontFace: F.semi, fontSize: 8.6, color: C.teal, align: "right" });
  const qs = [
    ["01", "숨은 이동은 얼마나, 언제, 어디서 일어나는가?", "분석 내용 및 결과 ① · 3쪽"],
    ["02", "AI 수요 예측은 같은 이동 예산으로 더 많은 대여를 살리는가?", "분석 내용 및 결과 ② · 4쪽"],
    ["03", "취약 거점 최소 보장은 형평을 얼마나 높이고, 대가는 얼마인가?", "결과 ② · 정책제안 · 4~5쪽"],
  ];
  qs.forEach(([n, q, where], i) => {
    const x = 12 + i * 63;
    box(s, x, 256.5, 60, 24, { fill: C.pale });
    T(s, n, x + 3, 258.5, 12, 7, { fontFace: F.xb, fontSize: 14, color: C.accent });
    T(s, q, x + 14, 259, 43, 12, { fontFace: F.semi, fontSize: 8.8, color: C.forest, lineSpacingMultiple: 1.2 });
    T(s, `→ ${where}`, x + 14, 273.8, 44, 4.5, { fontSize: 7.6, color: C.teal });
  });

}

// =====================================================================
// 2쪽: 활용 데이터, 분석과정 및 방법, AI 기술 활용
// =====================================================================
{
  const s = page(2);
  pill(s, "활용 데이터", 12, 12.5, 23);
  T(s, `공개 공공데이터 ${DS.rows.length}종만 사용`, 38, 12.7, 100, 6, { fontFace: F.xb, fontSize: 12.5, color: C.forest });
  T(s, "이용기록은 **자전거 번호**로 잇고, 지형·버스·생활시설·기상 자료를 **거점 단위**로 결합. 누구나 재현 가능",
    12, 20.3, 128, 8, { fontSize: 8.4, color: C.ink2, lineSpacingMultiple: 1.15 });
  fitImg(s, "design/sol/derived/08_data_layers_forest_w.png", 142, 10.8, 56, 18.3, "right");      // 데이터 결합 개념도(실제 지도 아님)
  // 머리글은 공식 양식과 같은 2단(출처 = 플랫폼·URL)으로 도형을 그리고, 본문만 표로 넣는다
  const cw = [5.5, 31, 23, 27, 64, 35.5], cx = cw.map((_, i) => 12 + cw.slice(0, i).reduce((a, b) => a + b, 0));
  const hcell = (text, x, y, w, h) => {
    s.addShape(pres.shapes.RECTANGLE, { x: mm(x), y: mm(y), w: mm(w), h: mm(h), fill: { color: C.forest }, line: { color: C.white, width: 0.5 } });
    T(s, text, x, y, w, h, { fontFace: F.semi, fontSize: 7.6, color: C.white, align: "center", valign: "middle" });
  };
  [[0, "No."], [1, "활용 데이터(명)"], [2, "제공기관(명)"], [5, "선정 이유(분석에서의 쓰임)"]].forEach(([i, t]) => hcell(t, cx[i], 29, cw[i], 9));
  hcell("출처", cx[3], 29, cw[3] + cw[4], 4.5);
  hcell("플랫폼(명)", cx[3], 33.5, cw[3], 4.5);
  hcell("URL", cx[4], 33.5, cw[4], 4.5);
  const cell = (t, o = {}) => ({ text: t, options: { fontSize: 7.5, color: C.ink, valign: "middle", ...o } });
  // 칸보다 긴 낱말은 PowerPoint가 글자 중간에서 끊으므로 줄바꿈 위치를 직접 지정(글자 폭은 Pretendard 실측)
  const BR = { "Copernicus DEM GLO-30": "Copernicus DEM\nGLO-30", "소상공인시장진흥공단": "소상공인\n시장진흥공단",
    "보건의료빅데이터개방시스템": "보건의료빅데이터\n개방시스템", "AWS 오픈데이터 레지스트리": "AWS 오픈데이터\n레지스트리",
    "종관기상관측(ASOS) 일자료": "종관기상관측(ASOS)\n일자료", "EG-TIPS(에너지온실가스 종합정보)": "EG-TIPS(에너지\n온실가스 종합정보)",
    "행정안전통계연보 2025(표 4-2-7-2)": "행정안전통계연보 2025\n(표 4-2-7-2)",
    "공영자전거 운영 현황(시도별)": "공영자전거 운영 현황\n(시도별)" };
  const br = (t) => BR[t] ?? t;
  const rowH = DS.rows.map((r) => (r[3].length > 100 ? 8.6 : r.some((t) => br(t).includes("\n")) || r[3].length > 60 ? 7.0 : 5.4));   // 두 줄 행 실측 약 7mm(Pretendard 줄 높이 1.19em), URL 세 줄 행 8.6mm
  const tableEnd = 38 + rowH.reduce((a, b) => a + b, 0);
  const rows = DS.rows.map(([name, org, plat, url, why], i) => [
    cell(String(i + 1), { align: "center", color: C.teal, fontFace: F.semi }),
    cell(br(name), { fontFace: F.semi, color: C.forest }), cell(br(org)), cell(br(plat)),
    { text: [{ text: url, options: { hyperlink: { url } } }], options: { fontSize: 7.0, color: C.teal, valign: "middle" } },
    cell(why),
  ]);
  s.addTable(rows, {
    x: mm(12), y: mm(38), w: mm(186), colW: cw.map(mm),
    rowH: rowH.map(mm), fontFace: F.reg, lineSpacingMultiple: 1.05,
    border: { type: "solid", pt: 0.4, color: C.line }, margin: [1, 1.6, 1, 1.6], fill: { color: C.white },
  });
  cap(s, `※ ${DS.footnote}`, 12, tableEnd + 1.2, 186, 4);
  const Y = tableEnd + 6.3;                       // 아래 절의 기준(표 높이에 따라 이동)

  pill(s, "분석과정 및 방법", 12, Y, 31);
  T(s, "5단계 전 과정을 코드로 재현(‘자료’ 번호는 위 표의 No.)", 46, Y + 0.9, 150, 5, { fontSize: 8.4, color: C.ink2 });
  const steps = [
    ["data_t", "수집·정제", "3년 이용 1,307만 건 DuckDB 결합. 오류 정제·중복 점검, 2025년 7월 결측은 0으로 채우지 않고 제외", "검사: 이용 − 자전거 수 = 연속쌍 수", "①②"],
    ["trace_t", "자전거 연쇄 추적", "같은 번호의 반납 거점 ≠ 다음 대여 거점이면 기록 없는 이동. 운영센터 경유·5분 미만·시속 60km 초과·좌표 없는 거점(0.4%)은 핵심에서 제외", `핵심 이동 ${int(N.moved_3y)}건\n하루 평균 ${int(N.moved_per_day_3y)}건(${int(N.moved_days_3y)}일)`, "①②⑭"],
    ["hill_t", "지형·생활 접근성", "30m 고도로 오르막 판정. 반경 300m 버스 운행 하위 25%, 또는 의료·약국·시장 중 2종 이상 거리 상위 25%면 취약 거점", `취약 ${N.vuln_count}곳(복합 ${N.vuln_both_count}곳)`, "③~⑧"],
    ["weather_t", "AI 수요 예측", "거점·날짜별 필요 대수(시간별 대여·반납으로 산정한 02시 시작 재고, 4쪽)를 경사 부스팅으로 예측. 이력·요일·날씨·고도 등 입력", "학습→검증→시험 시간순 분리", "①⑨⑩"],
    ["truck_t", "배치 실험·탄소", "2025년 상반기 실제 대여를 순서대로 재생, 재고 0이면 실패 처리. 같은 밤당 이동 예산으로 전략 비교, 주행 km를 탄소로 환산", "전략·지표는 시험 전 고정", "①⑫⑬"],
  ];
  steps.forEach(([ic, t, d, outp, data], i) => {
    const x = 12 + i * 37.6, w = 35.6;
    box(s, x, Y + 7.5, w, 47);
    T(s, `${i + 1}`, x + 2.5, Y + 9, 6, 6, { fontFace: F.xb, fontSize: 11, color: C.accent });
    iconFit(s, ic, x + w - 16.5, Y + 8.6, 14, 8.4, "right");
    T(s, t, x + 2.5, Y + 16.5, w - 5, 5, { fontFace: F.semi, fontSize: 8.8, color: C.forest });
    T(s, d, x + 2.5, Y + 22, w - 4.5, 19.5, { fontSize: 7.6, color: C.ink2, lineSpacingMultiple: 1.13 });
    T(s, outp, x + 2.5, Y + 42.5, w - 4.5, 7, { fontFace: F.semi, fontSize: 7.6, color: C.teal, lineSpacingMultiple: 1.1 });
    T(s, `자료 ${data}`, x + 2.5, Y + 49.5, w - 5, 4, { fontSize: 7.5, color: C.muted });
  });

  pill(s, "AI 기술 활용", 12, Y + 59, 23);
  T(s, "AI는 분석·검증·전달의 도구로 사용, AI 산출물은 원자료·코드로 재확인", 38, Y + 59.9, 160, 5, { fontSize: 8.4, color: C.ink2 });
  const AH = { fill: { color: C.forest }, color: C.white, fontFace: F.semi, fontSize: 7.6, valign: "middle", align: "center" };
  const ac = (t, o = {}) => ({ text: t, options: { fontSize: 7.5, color: C.ink, valign: "middle", ...o } });
  const svc = (t) => ac(t, { fontFace: F.semi, color: C.forest });
  const ai = [
    [svc("Claude Code\n(Anthropic Claude Opus 5.5)"), ac("분석 코드 작성·실행, 오류 재현·수정, 보존 법칙·수치 교차 검증, 보고서 생성기 작성"),
     ac("“같은 자전거 번호의 반납 거점과 다음 대여 거점이 다르면 기록 없는 이동으로 보고 간격·속도 규칙으로 분류하는 코드를 작성하고 보존 법칙으로 검증하라”")],
    [svc("Claude Haiku·Sonnet\n(LLM, 일괄 호출)"), ac(`시의회 회의록 누비자 발언 ${CO.utterances}건 쟁점 분류: Haiku 전수, Sonnet이 무작위 ${CO.second_coder_n}건 독립 재분류(주제 일치 ${pct(CO.primary_code_agreement, 0)})`),
     ac("“각 발언을 코드북 11개 쟁점(재배치·정비·형평·환경 등) 중 최대 2개로 분류하고 입장을 고르라. JSON 배열만 출력”")],
    [svc("LangGraph + Claude Sonnet\n(에이전트 흐름)"), ac("야간 재배치 계획표 → 운영자 브리핑 초안 → 숫자·거점명 자동 대조 → 최대 2회 수정 → 사람 승인"),
     ac("“아래 배치 계획표만 근거로 내일 아침 운영자 브리핑을 5줄로 작성하라. 표에 없는 숫자·거점명 사용 금지”")],
    [svc("scikit-learn\n경사 부스팅(머신러닝)"), ac("거점·날짜별 필요 대수 예측(경사 부스팅·포아송 손실). 설정은 학습 전 고정, 검증기간으로만 보정값 선택"),
     ac("프롬프트 없음(입력 변수·하이퍼파라미터·평가기간을 코드로 고정)")],
    [svc("OpenAI Codex\n(GPT Sol 6.1)"), ac("표지·개념 그림·아이콘 생성(데이터 수치 미포함), 자료 대장·문구 교차 검토 보조"),
     ac("“문자 없는 3D 개념 그림: 언덕을 내려가는 공공자전거와 오르는 재배치 차량, 숲색·청록, 수치·라벨 제외”")],
  ];
  s.addTable([[{ text: "사용 서비스", options: AH }, { text: "활용 범위", options: AH }, { text: "주요 프롬프트(요약)", options: AH }], ...ai], {
    x: mm(12), y: mm(Y + 66), w: mm(186), colW: [mm(39), mm(66), mm(81)],
    rowH: [mm(5), ...ai.map(() => mm(8.4))], fontFace: F.reg, lineSpacingMultiple: 1.08,
    border: { type: "solid", pt: 0.4, color: C.line }, margin: [1, 2, 1, 2],
  });

  sub(s, "결과 신뢰성 확보 장치", 12, Y + 118.5);
  const guards = [
    ["보존 검사", "이용 − 자전거 수 = 연속쌍 수, 매 실행 확인"],
    ["시간순 분리", "2023.2~2024.9 학습, 2024년 4분기 검증, 2025년 상반기 시험"],
    ["사전 고정", "전략·지표 시험 전 고정. 이후 찾은 엔진 오류 2건은 수정 뒤 같은 절차로 재평가"],
    ["두 AI 교차 분류", "다른 모델이 표본을 독립 재분류해 일치도(κ) 측정"],
    ["통계 검정", "날짜·거점 부트스트랩 95% 신뢰구간, Wilcoxon 부호순위, 가중 회귀(HC1)"],
  ];
  guards.forEach(([t, d], i) => {
    const x = 12 + i * 37.6;
    box(s, x, Y + 124, 35.6, 17, { fill: C.pale });
    T(s, t, x + 2.5, Y + 125.6, 31, 4.5, { fontFace: F.semi, fontSize: 8.4, color: C.forest });
    T(s, d, x + 2.5, Y + 130.4, 31.5, 10, { fontSize: 7.6, color: C.ink2, lineSpacingMultiple: 1.12 });
  });
  cap(s, "※ 기록 없는 이동의 실제 주체·차종은 기록에 없음. 묶음·야간·오르막 양상으로 재배치 차량 이동이 중심임을 추정했으며 모든 수치는 ‘추정 이동’ 기준",
    12, Y + 142.5, 186, 4);
}

// =====================================================================
// 3쪽: 분석 내용 및 결과 ①
// =====================================================================
{
  const s = page(3);
  pill(s, "분석 내용 및 결과 ①", 12, 12.5, 35);
  T(s, "분석결과 이미지", 49.5, 13.5, 30, 4, { fontSize: 7.6, color: C.teal });
  head(s, `숨은 이동은 언덕 위로: 고지대 거점 대여의 ${pct(depHigh.dependency, 0)}는 ‘옮겨진 자전거’`, 20.5);

  img(s, FIG("map_truck_dependency_2024"), 12, 30, 100, 103.7);
  cap(s, fig("거점별 의존도 = 기록 없이 옮겨져 온 자전거 ÷ 대여(2024년, 대여 365건 이상 거점). 지형 음영: Copernicus WorldDEM-30 가공(고지문 참고문헌 32)"), 12, 134.5, 100, 7);
  img(s, "docs/codex_support/report_release_review_20261017/dependency_bars_60x74_review_v2.png", 116, 30, 60, 74);
  T(s, [{ text: fx(depHigh.dependency / depLow.dependency, 1), options: { fontFace: F.xb, fontSize: 17, color: C.accent } },
        { text: "배", options: { fontFace: F.semi, fontSize: 9, color: C.accent } }], 177, 51, 21, 8, { align: "center" });
  T(s, "고지대 ÷\n저지대", 177, 59.5, 21, 8, { fontSize: 7.6, color: C.ink2, align: "center" });
  T(s, [{ text: fx(depBoth.dependency / depOther.dependency, 1), options: { fontFace: F.xb, fontSize: 17, color: C.accent } },
        { text: "배", options: { fontFace: F.semi, fontSize: 9, color: C.accent } }], 177, 88, 21, 8, { align: "center" });
  T(s, "복합 취약 ÷\n그 외", 177, 96.5, 21, 8, { fontSize: 7.6, color: C.ink2, align: "center" });
  cap(s, fig("집단별 의존도(2024)"), 116, 104.5, 82);
  bullets(s, [
    `고도 상위 25%(약 35m 이상): 대여의 **${pct(depHigh.dependency)}**, 하위 25%(${pct(depLow.dependency)})의 **${fx(depHigh.dependency / depLow.dependency, 1)}배**`,
    `버스·생활시설 복합 취약(분석 ${depBoth.stations}곳): **${pct(depBoth.dependency)}**, 그 외 ${pct(depOther.dependency)}`,
    `성주 유니온빌리지(해발 105m): 2024년 대여의 ${pct(N.stations["성주 유니온빌리지"].dependency)}`,
    `회귀(고도·취약·대여량·구 통제, 대여 가중, n=${ST.dependency_regression.main.n}): **고도 10m당 +${fx(REG.elev10.coef * 100, 1)}%p**, 복합 취약 +${fx(CVN.coef * 100, 1)}%p(95% 신뢰구간 ${fx(CVN.ci95[0] * 100, 1)}~${fx(CVN.ci95[1] * 100, 1)})`,
  ], 116, 109.5, 82, 33, { size: 8, gap: 1.4 });

  figHead(s, "시간대별 기록 없는 이동 뒤 대여 비율", 12, 144.5, 100);
  img(s, FIG("hourly_moved_share"), 12, 150, 101.3, 40.3);
  box(s, 12, 192, 101, 13, { fill: C.pale, r: 1.5 });
  T(s, [{ text: `오전 8시 대여의 ${pct(N.moved_share_8am)}`, options: { fontFace: F.semi, color: C.forest } },
        { text: "가 기록 없이 옮겨진 자전거로 시작됨. 아침 시간대 수요를 재배치가 뒷받침(2023~2025 합계, 다음 대여 시각 기준)" }],
  15, 192, 96, 13, { fontSize: 8.4, valign: "middle", lineSpacingMultiple: 1.15 });
  figHead(s, "구 간 기록 없는 이동(출발 → 도착)", 120, 144.5, 78);
  img(s, FIG("district_matrix"), 120, 150, 69, 62.4);

  sub(s, "운영의 흔적과 규모", 12, 215.5);
  const cards = [
    [pct(N.batch5plus_share_2024, 0), "", "같은 운영일·같은 출발→도착 구간으로 5건 이상 묶인 이동 비율(2024), 차량 재배치 양상과 부합"],
    [`약 ${int(N.truck_km_per_day_2024_cap20)}`, "km", `하루 재배치 경로 추정(2024, 적재 20대·직선 거리·차고지 왕복 가정), 연 ${fx(N.truck_km_year_2024_cap20 / 1e4, 1)}만 km`],
    ["29", "대", "배송·시스템정비 차량(운영사 공시, 2025). 재배치 전담 대수·연료는 비공개"],
    [pct(N.moved_share_3y), "", `3년 평균. 2023년 ${yearlyShares[0]}, 2024년 ${yearlyShares[1]}, 2025년 ${yearlyShares[2]}로 매년 비슷한 수준 유지`],
  ];
  cards.forEach(([big, unit, label], i) => stat(s, 12 + i * 47, 221.5, 45, 29, big, unit, label));
  box(s, 12, 253.5, 186, 25, { fill: C.white, line: C.light });
  T(s, "해석", 16, 256.3, 20, 5, { fontFace: F.semi, fontSize: 9.5, color: C.teal });
  bullets(s, [
    "기록 없는 이동은 **묶음·야간·오르막** 양상이 뚜렷해 **차량 재배치와 부합**(정비 수거·기록 누락 일부 포함)",
    "부담은 **언덕 위·외곽 거점과 아침 시간대 대여**에 집중 → 재배치를 멈춘 가상 운영에서 **고지대 거점 성공률이 더 낮음**(4쪽)",
    `이동의 **${fx(N.fig.district_matrix.diagonal_pct, 0)}%가 같은 구 안**에서 발생 → **구 단위 권역 배치 계획** 가능`,
    "자전거 번호가 담긴 이력이면 **다른 도시도 형식 변환 후 산출 가능한 지표** → 5쪽 정책 ①(숨은 이동 지표 공개)로 연결",
  ], 30, 256.3, 164, 21, { size: 8.4, gap: 1.8 });
}

// =====================================================================
// 4쪽: 분석 내용 및 결과 ②(AI 예측 배치 실험)
// =====================================================================
{
  const s = page(4);
  pill(s, "분석 내용 및 결과 ②", 12, 12.5, 35);
  T(s, "분석결과 이미지", 49.5, 13.5, 30, 4, { fontSize: 7.6, color: C.teal });
  head(s, "같은 이동 예산에서 AI 예측은 대여 성공을, 취약 거점 보장은 형평을 높임", 20.5);

  cover(s, "design/sol/04_digital_twin_forest.png", 12, 30, 56, 37.3);
  cap(s, fig("가상 운영 개념도"), 12, 68, 56);
  box(s, 71, 30, 61, 54, { fill: C.bg });
  T(s, "실험 방법: 기록을 다시 재생하는 가상 운영", 74, 32.3, 57, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
  bullets(s, [
    `2025년 1~6월 실제 대여 ${int(testDemand)}건 시간순 재생`,
    "거치대가 비면 해당 대여는 ‘실패’로 기록",
    "매일 02시, 같은 ‘밤당 이동 예산’ 안에서 거점별 **필요 대수** 추정치에 맞춰 재배치. 필요 대수는 02~24시 대여·반납을 시간별로 집계하고 같은 시간대는 대여를 먼저 처리해 산정한 시작 재고",
    "추정: **경험 규칙**은 최근 4주 같은 요일 기록 평균, **AI**는 전날까지 자료로 예측",
    "설정은 2024년 4분기(검증)로만 선택, 시험 뒤 고친 엔진 오류 2건도 같은 절차로 재평가",
  ], 74, 38.5, 56, 45, { size: 8, gap: 1.4 });
  img(s, FIG("forecast_mae"), 136, 30, 62, 45.5);
  cap(s, fig(`필요 대수 예측 오차(시험기간). AI는 규칙 대비 ${fx(MAE.groups["전체"].reduction_vs_rule_pct.ai, 1)}%, 날씨까지 알면 ${fx(MAE.groups["전체"].reduction_vs_rule_pct.ai_weather, 1)}% 감소`), 136, 76.3, 62, 10);

  img(s, FIG("policy_frontier"), 12, 87.5, 101.3, 63.2);
  cap(s, fig("밤당 이동 대수별 대여 성공률(시험기간). 상한선은 실제 운영에서 알 수 없는 정보를 쓴 비교선"), 12, 151.2, 101, 7);
  img(s, FIG("notruck"), 120, 87.5, 62, 45.5);
  figHead(s, "가상 운영에서 재배치를 멈추면", 120, 134, 78);
  T(s, `대여 성공률이 **${pct(sim("none", 0).served_rate, 0)}**로 하락하고 고지대 거점은 **${fx(NT.groups["고지대 (상위 25%)"].none_served_rate_pct, 0)}%**까지 떨어짐. **언덕 위 거점일수록 재배치 의존이 큼**`,
    120, 139.5, 78, 12, { fontSize: 8.2, lineSpacingMultiple: 1.17 });

  img(s, FIG("equity"), 12, 160, 84.6, 51.6);
  cap(s, fig(`취약 거점 형평 비교(1,500대/밤). 성공률은 취약 분류 ${EQ.group_stations}곳, 빈 시간(05~24시 재고 0인 시간)은 기간 내내 운영된 ${ST.equity_station.vulnerable.empty_hours_per_station_day.n}곳 평균`), 12, 212, 85, 7);
  const k = [
    [`${int(saveAI)}`, "대 감축", `같은 성공률(${pct(ES.target_served_rate)})에 필요한 밤당 이동: AI 예측 vs 경험 규칙(−${pct(saveAI / ES.rule4w.moves_per_night)})`],
    [int(sim("ai", 1500).served - sim("rule4w", 1500).served), "건 추가 성공", `대여 성공률 ${sgn(PF.gain_at_budget_1500_pp.ai, 2)}%p. AI 예측 vs 경험 규칙, 2025년 상반기 가상 운영·같은 예산 1,500대/밤`],
    [fx(EQ.vulnerable_gain_ai_fair_vs_ai.zero_hours_pct, 0), "%", "취약 거점 빈 시간: AI+취약 보장 vs AI 예측"],
    [fx(EQ.overall_cost_ai_fair_minus_ai_pp, 3), "%p", "보장의 대가: 전체 대여 성공률 변화(같은 예산)"],
  ];
  k.forEach(([big, unit, label], i) => {
    const x = 102 + (i % 2) * 48, y = 160 + Math.floor(i / 2) * 29.5;
    stat(s, x, y, 46, 27.5, big, unit, label, { color: i < 2 ? C.forest : C.accent });
  });

  box(s, 12, 221, 186, 64, { fill: C.white, line: C.light });
  T(s, "탄소로 환산하면", 16, 223.3, 60, 5, { fontFace: F.semi, fontSize: 9.5, color: C.forest });
  bullets(s, [
    `AI 예측은 같은 서비스 수준에서 밤당 주행 약 ${fx(kmSaveAI, 0)}km 감축(예산 곡선 보간·직선 경로 모형) → 연 ${fx(yr(kmSaveAI, co2.diesel_low), 1)}~${fx(yr(kmSaveAI, co2.diesel_high), 1)}t CO2(같은 효과 365일, 1톤 경유 화물차). **예측만으로 줄어드는 탄소는 제한적**`,
    `**차종 차이가 더 큼**: 2024년 경로 추정 연 ${fx(N.truck_km_year_2024_cap20 / 1e4, 1)}만 km를 전량 경유로 달리면 ${fx(N.observed_co2_t_2024.diesel_low, 0)}~${fx(N.observed_co2_t_2024.diesel_high, 0)}t, 전량 전기면 **${fx(N.observed_co2_t_2024.ev, 0)}t(약 절반)**. 실제 감축량은 차량별 연료·주행 확인 후 산정`,
    "운영사 감축량 산식은 승용차 대체 100%를 가정하고 재배치 배출을 미차감. 대체율이 해외 사례처럼 낮으면(2~21%, 참고문헌 2·3) 재배치 배출 비중 확대 → **‘순감축’ 회계 필요**",
    "**AI 예측의 효과는 탄소보다 대여 성공에서, 최소 보장의 효과는 취약 거점 빈 시간에서 뚜렷함**(위 성과 카드)",
  ], 16, 229.5, 121, 33, { size: 8, gap: 1.3 });
  // 통계적 확인(95% 신뢰구간, scripts/analysis/stat_tests.py)
  const fc = ST.forecast.ai_vs_rule4w, ar = ST.ai_vs_rule_station.all.success_rate.pooled;
  const vz = ST.equity_station.vulnerable.empty_hours_per_station_day;
  box(s, 15, 263.5, 123, 19.5, { fill: C.pale, r: 1.5 });
  T(s, "통계적 확인(95% 신뢰구간)", 17.5, 264.8, 60, 4, { fontFace: F.semi, fontSize: 8, color: C.forest });
  bullets(s, [
    `예측 오차 감소 ${fx(fc.reduction_pct, 1)}%(${fx(fc.reduction_pct_ci95[0], 1)}~${fx(fc.reduction_pct_ci95[1], 1)}%), AI가 더 정확한 날 ${pct(fc.daily.share_days_better, 0)}(날짜 단위 부트스트랩)`,
    `대여 성공률 AI−규칙 ${sgn(ar.diff * 100, 2)}%p(${ci(ar.ci95_diff, 100, 2)}), 보장 시 취약 거점 빈 시간 ${fx(vz.mean_diff, 2)}시간(${ci(vz.ci95_mean_diff, 1, 2)}). 개선 ${pct(vz.share_improved, 0)}·악화 ${pct(vz.share_worse, 0)}로 **효과는 일부 거점에 집중**`,
  ], 17.5, 269.3, 119, 13.5, { size: 7.6, gap: 0.8 });
  // 재배치 차량 연간 배출 미니 막대(2024 경로 추정 km × 배출계수)
  figHead(s, "차종별 연간 배출(같은 거리)", 142, 223.3, 54);
  T(s, "2024년 경로 추정, tCO2", 142, 228.3, 54, 4, { fontSize: 7.6, color: C.ink2 });
  const bars = [["경유 화물차(연비 낮음)", N.observed_co2_t_2024.diesel_high, C.gray], ["경유 화물차(연비 높음)", N.observed_co2_t_2024.diesel_low, C.gray],
    ["전기 화물차", N.observed_co2_t_2024.ev, C.accent], ["AI 예측 절감분(경유)", yr(kmSaveAI, co2.diesel_high), C.mint]];
  const vmax = bars[0][1];
  bars.forEach(([lab, v, col], i) => {
    const y = 233.5 + i * 10;
    T(s, lab, 142, y, 54, 4, { fontSize: 7.6, color: C.ink2 });
    const bw = Math.max(0.8, 38 * v / vmax);
    box(s, 142, y + 4.1, bw, 3.8, { fill: col, r: 0 });
    T(s, `${fx(v, 0)}t`, 142 + bw + 1.2, y + 3.9, 14, 4.5, { fontFace: F.semi, fontSize: 7.8, color: C.forest });
  });
  cap(s, "배출계수: 경유 2.60kgCO2/L(1톤 화물차 연비 8.6~9.9km/L), 전기 0.4149kgCO2/kWh(전비 3.1km/kWh)", 142, 274, 54, 10);
}

// =====================================================================
// 5쪽: 정책제안 및 기대효과
// =====================================================================
{
  const s = page(5);
  pill(s, "정책제안 및 기대효과", 12, 12.5, 35);
  head(s, "숨은 이동 지표 공개, 예측 기반 야간 배치, 취약 거점 최소 2대 보장", 20.5);
  const pol = [
    ["trace_t", "① 숨은 이동 지표 공개", "기록 없는 이동 비율·거점별 의존도·재배치 km를 운영 성과 지표로 매월 공개", "전국 공공자전거 운영기관",
      "재배치 부담이 큰 지역을 매월 점검, 탄소 ‘순감축’ 산정 자료로 사용"],
    ["ai_t", "② AI 예측 야간 배치", "거점별 내일 필요 대수를 예측해 기상 예보와 연동, 운영자 승인 후 배차", "운영기관 배차 담당",
      `같은 대여 성공률에서 밤당 이동 ${int(saveAI)}대(${pct(saveAI / ES.rule4w.moves_per_night)}) 감축. 당일 날씨를 안다고 가정한 상한은 ${int(saveAIw)}대`],
    ["equity_t", "③ 취약 거점 최소 2대", "최근 28일 이용이 있는 취약 거점(버스·생활시설 접근 약함)에 야간 배치 때 최소 2대 우선 확보", "지자체(형평 목표)·운영기관",
      `취약 거점 빈 시간 ${fx(vulnGain, 0)}% 감소, 전체 대여 성공률은 ${fx(Math.abs(EQ.overall_cost_ai_fair_minus_ai_pp), 3)}%p 하락에 그침`],
    ["evtruck_t", "④ 재배치 차량 전기화", "2025년 도입한 전기 화물트럭 1대에 이어 남은 경유 배송차를 단계적 전환, 감축량에서 운영 배출 차감", "지자체 탄소중립 계획",
      `같은 거리 기준 전량 경유 연 ${fx(N.observed_co2_t_2024.diesel_low, 0)}~${fx(N.observed_co2_t_2024.diesel_high, 0)}t, 전량 전기 ${fx(N.observed_co2_t_2024.ev, 0)}t(시나리오)`],
  ];
  pol.forEach(([ic, t, what, who, eff], i) => {
    const x = 12 + i * 47, w = 45;
    box(s, x, 30, w, 66, { fill: C.bg });
    iconFit(s, ic, x + 2.5, 32, 17, 10);
    T(s, t, x + 2.5, 43.5, w - 5, 5, { fontFace: F.semi, fontSize: 9.2, color: C.forest });
    T(s, what, x + 2.5, 49.5, w - 4.5, 15, { fontSize: 8, color: C.ink2, lineSpacingMultiple: 1.15 });
    T(s, [{ text: "대상 ", options: { fontFace: F.semi, color: C.teal } }, { text: who }], x + 2.5, 65.5, w - 5, 8, { fontSize: 7.8 });
    box(s, x + 2, 74, w - 4, 20, { fill: C.white });
    T(s, [{ text: "기대효과\n", options: { fontFace: F.semi, color: C.accent, fontSize: 7.8 } }, { text: eff, options: { fontSize: 8, color: C.forest } }],
      x + 4, 75.5, w - 7.5, 17.5, { lineSpacingMultiple: 1.15 });
  });

  // 운영자 브리핑 화면(LangGraph 기록의 사실값으로 구성, 경로 지도는 첫 구간 계산 경로)
  const B = N.brief, BF = B.facts;
  // 휴대폰 틀(Sol 07, 1200×2600px, 틀 46~1155 × 101~2496px, 화면 구멍 104~1097 × 175~2424px): 흰 화면판을 깔고 틀을 올린다
  const PS = 56 / 1109, PX = 12 - 46 * PS, PY = 100 - 101 * PS;
  box(s, PX + 100 * PS, PY + 171 * PS, 1001 * PS, 2257 * PS, { fill: C.white, r: 4 });
  img(s, "design/sol/07_phone_frame_forest.png", PX, PY, 1200 * PS, 2600 * PS);
  box(s, 16.5, 106, 47, 12, { fill: C.pale, r: 2 });
  T(s, "내일 아침 배치 브리핑", 18.5, 107.3, 32, 4.5, { fontFace: F.semi, fontSize: 8.4, color: C.forest });
  box(s, 51.5, 107.1, 10.5, 4.4, { fill: C.accent, r: 2.2 });
  T(s, "AI 초안", 51.5, 107.1, 10.5, 4.4, { fontFace: F.semi, fontSize: 7.5, color: C.white, align: "center", valign: "middle" });
  const [yy, mo, dd] = BF.date.split("-").map(Number);
  T(s, `${yy}.${mo}.${dd} 02시 배치안 · 예산 ${int(BF.budget_per_night)}대`, 18.5, 112.9, 44, 4, { fontSize: 7.5, color: C.ink2 });
  const tiles = [[`${int(BF.moved_bikes)}`, "대", "옮길 자전거"], [`${BF.pickup_stations + BF.drop_stations}`, "곳", `수거 ${BF.pickup_stations}\n배치 ${BF.drop_stations}`],
    [`${int(BF.route_km)}`, "km", `경로 구간\n${BF.route_segments}개`]];
  tiles.forEach(([v, u, l], i) => {
    const x = 16.5 + i * 16;
    box(s, x, 120, 15, 14.5, { fill: C.bg, r: 1.5 });
    T(s, [{ text: v, options: { fontFace: F.xb, fontSize: 9, color: C.forest } }, { text: u, options: { fontFace: F.semi, fontSize: 7.5, color: C.forest } }],
      x, 121.1, 15, 4.5, { align: "center" });
    T(s, l, x, 126.1, 15, 8, { fontSize: 7.5, color: C.ink2, align: "center", lineSpacingMultiple: 1.05 });
  });
  const run1 = BF.first_segments[0];
  T(s, `첫 구간 경로 ${fx(run1.km, 1)}km · 정차 ${run1.stops.length}곳`, 16.5, 136.5, 47, 4.5, { fontFace: F.semi, fontSize: 7.8, color: C.forest });
  box(s, 16.5, 141, 47, 28.6, { fill: C.map, r: 1.5 });
  img(s, FIG("brief_route"), 18.5, 142.25, 43, 26.1);
  T(s, [{ text: "○", options: { color: C.gray, fontFace: F.semi } }, { text: " 수거   " }, { text: "●", options: { color: C.accent } },
        { text: " 배치   원 크기 = 대수" }], 16.5, 170.1, 47, 4, { fontSize: 7.5, color: C.ink2 });
  T(s, "우선 배치 거점", 16.5, 175.5, 22, 4.5, { fontFace: F.semi, fontSize: 7.8, color: C.forest });
  box(s, 41.3, 176.8, 2.2, 2.2, { fill: C.accent, r: 0 });
  T(s, "최소 보장 거점", 44, 175.7, 19.5, 4.3, { fontSize: 7.5, color: C.ink2 });
  const top = BF.top_drops.slice(0, 5), bmax = top[0].bikes;
  top.forEach((d, i) => {
    const y = 180.5 + i * 5.9;
    T(s, `${i + 1}`, 16.5, y, 3, 3.5, { fontFace: F.xb, fontSize: 7.5, color: C.accent });
    T(s, d.station, 20, y, 33.5, 3.5, { fontFace: F.semi, fontSize: 7.5, color: C.ink });
    T(s, `${d.bikes}대`, 53.5, y, 10, 3.5, { fontFace: F.semi, fontSize: 7.5, color: C.forest, align: "right" });
    box(s, 20, y + 3.7, 43.5 * d.bikes / bmax, 1.2, { fill: d.vulnerable ? C.accent : C.gray, r: 0 });
  });
  box(s, 16.5, 210.5, 47, 5, { fill: C.pale, r: 1.5 });
  T(s, `자동 검사 오류 ${B.final_errors.length}건 · 수정 ${B.revisions}회 · ${B.approved ? "시연 승인" : "승인 대기"}`, 16.5, 210.5, 47, 5,
    { fontFace: F.semi, fontSize: 7.5, color: C.forest, align: "center", valign: "middle" });
  cap(s, fig("운영자 브리핑 화면 예시\n(2025.4.15 배치안, 시험기간 재현)"), 12, 222.3, 56, 7);

  img(s, FIG("council_issues"), 72, 100, 84, 46.2);
  iconFit(s, "council_t", 158, 100, 12, 11);
  T(s, "시의회는 무엇을 말해 왔나", 158, 112, 40, 5, { fontFace: F.semi, fontSize: 8.8, color: C.forest });
  T(s, `2020~2026년 누비자 언급 후보 ${CO.utterances}건 중 관련 발언 ${CO.relevant}건 AI 분류. 재정(${pct(CO.share_of_relevant["재정"], 0)})·이용(${pct(CO.share_of_relevant["이용"], 0)}) 쟁점이 중심이고 ` +
    `**재배치 ${pct(CO.share_of_relevant["재배치"], 0)}·형평 ${pct(CO.share_of_relevant["형평"], 0)}로 소수**. 재배치 같은 운영 부담은 **의회 논의에서도 비중이 작음**`,
  158, 118, 40, 28, { fontSize: 8, lineSpacingMultiple: 1.17 });
  cap(s, fig(`시의회 쟁점 비중(관련 발언 대비, 발언당 최대 2개). 두 모델 일치: 관련성 ${pct(CO.relevant_agreement, 0)}, 주제 ${pct(CO.primary_code_agreement, 0)}`), 72, 147, 126);

  sub(s, "추진 순서(향후 추진안)와 파급효과", 72, 153);
  const road = [
    ["① 진단·지표 정비", "집계 기준 정비, 운영기관 배차·정비 기록과 추정 이동 대조. 공개 시 추정치·산정 조건 명시"],
    ["② 효율·형평 공동 시범", "실제 재고·차량·거치대 용량·운행·상하차 시간을 반영할 권역 선정, AI 예측과 최소 2대 보장 함께 적용"],
    ["③ 성과 확인 후 확대", "전체 대여 성공률, 취약 거점 빈 시간·악화 거점, 실제 주행거리·작업시간 확인 후 확대 판단"],
  ];
  road.forEach(([t, d], i) => {
    const x = 72 + i * 34, w = 30.5;
    box(s, x, 159, w, 24, { fill: C.bg, r: 1.2 });
    T(s, t, x + 1.8, 160, w - 3, 4.5, { fontFace: F.semi, fontSize: 7.9, color: C.accent });
    T(s, d, x + 1.8, 164.6, w - 3, 18, { fontSize: 7.6, color: C.ink, lineSpacingMultiple: 1.1 });
    if (i < 2) T(s, "→", x + w, 159, 3.5, 24, { fontSize: 9, color: C.teal, align: "center", valign: "middle" });
  });
  const tail = [
    ["병행", "차량 전기화는 시범 이후로 미루지 않고 차량별 연료·주행과 교체 여건에 따라 별도 추진"],
    ["전국 확산", "자전거 번호·시각·거점이 담긴 이력을 도시별로 변환하면 같은 진단 절차 적용 가능. 공공데이터 개방 기준에 ‘자전거 번호’ 포함 권고"],
  ];
  tail.forEach(([t, d], i) => {
    const y = 184.5 + i * 9.6;
    box(s, 72, y, 98.5, 8.8, { fill: i ? C.bg : C.white, r: 1.2 });
    T(s, t, 74, y, 15, 8.8, { fontFace: F.semi, fontSize: 8.2, color: C.accent, valign: "middle" });
    T(s, d, 89, y, 79.5, 8.8, { fontSize: 8, color: C.ink, valign: "middle", lineSpacingMultiple: 1.1 });
  });
  fitImg(s, "design/sol/derived/09_korea_network_forest_w.png", 172.5, 158.5, 25.5, 25.5, "center");   // 개념도(실제 확산 실적·행정경계 아님)
  cap(s, "개념도: 같은 절차를\n다른 도시로", 172.5, 184.5, 25.5, 8);

  sub(s, "브리핑 생성 흐름(LangGraph, 사람 승인 포함)", 72, 204.5, 126);
  const flow = ["초안 작성(LLM)", "숫자·거점명 자동 대조", "오류 시 재작성(최대 2회)", "운영자 승인 후 배차"];
  flow.forEach((t, i) => {
    const x = 72 + i * 32.5;
    box(s, x, 210.5, 28, 8.5, { fill: i === 3 ? C.forest : C.pale, r: 1.5 });
    T(s, t, x + 1, 210.5, 26, 8.5, { fontFace: F.semi, fontSize: 7.6, color: i === 3 ? C.white : C.forest, align: "center", valign: "middle", lineSpacingMultiple: 1.05 });
    if (i < 3) T(s, "→", x + 28, 210.5, 4.5, 8.5, { fontSize: 9, color: C.teal, align: "center", valign: "middle" });
  });
  T(s, "배치표에 없는 숫자, 계획 밖 거점명, 계획과 다른 거점별 대수가 나오면 자동 차단 후 재작성. 최종 배차는 운영자 승인 후 실행(이 사례는 분석자 시연 승인)", 72, 220.6, 126, 8, { fontSize: 7.8, color: C.ink2, lineSpacingMultiple: 1.12 });

  box(s, 12, 234, 186, 29.5, { fill: C.white, line: C.light });
  T(s, "한계와 다음 단계", 16, 236.6, 40, 5, { fontFace: F.semi, fontSize: 9, color: C.teal });
  bullets(s, [
    "이동의 실제 주체·시각은 기록에 없어 **‘추정 이동’으로 한정**. 운영기관 배차 기록과 대조 시 정확도 확인 가능",
    "실험은 관측된 대여를 재생하므로 **자전거가 없어 포기한 수요는 미반영**. 초기 재고는 관측 기록으로 재구성한 공통 조건",
    "실험은 거치대 용량·차량 대수·운행 및 상하차 시간을 반영하지 않고 매일 02시에 재배치가 끝나는 것으로 처리한 **전략 간 비교**",
    "생활 접근성은 2024.12~2026.10 시점 자료 기반 **정적 분류**. 실제 운영 시 날씨 입력은 **전날 발표 기상 예보로 대체** 필요",
  ], 16, 242.5, 178, 20, { size: 8, gap: 1.4 });

  box(s, 12, 267.5, 186, 19.5, { fill: C.bg });
  T(s, "분석 도구 및 코드", 16, 269.8, 40, 5, { fontFace: F.semi, fontSize: 9, color: C.teal });
  T(s, "Python(pandas·DuckDB·NumPy·scikit-learn·matplotlib), LangGraph, Claude Code, PptxGenJS", 16, 275.5, 178, 4.5, { fontSize: 8 });
  T(s, [{ text: "전체 코드·재현 순서: ", options: { fontFace: F.semi, color: C.forest } },
        { text: CODE_URL, options: { color: C.teal, hyperlink: { url: CODE_URL } } }], 16, 280.8, 178, 4.5, { fontSize: 8.2 });
}

// =====================================================================
// 참고문헌(본문 분량 제외). 글줄 높이를 추정해 두 단에 나누고, 넘치면 다음 쪽으로 잇는다
// =====================================================================
{
  const REF_SIZE = 7.8, URL_SIZE = 7.2, LS = 1.12, COL_W = 91, TOP = 22, BOTTOM = 287;
  const em = (ch) => (/[ㄱ-힣]/.test(ch) ? 0.93 : /[A-Z0-9]/.test(ch) ? 0.6 : /[a-z]/.test(ch) ? 0.52 : /\s/.test(ch) ? 0.27 : 0.36);
  const widthMM = (t, pt) => [...t].reduce((a, ch) => a + em(ch), 0) * pt * 0.3528;
  const lineMM = REF_SIZE * LS * 0.3528;
  const items = [];
  [...new Set(REFS.map((r) => r.group))].forEach((g, gi) => {
    items.push({ h: 9.5 * 1.2 * 0.3528 + (gi ? 1.8 : 0) + 0.7, runs: [{ text: g, options: { fontFace: F.semi, fontSize: 9, color: C.forest, breakLine: true, paraSpaceBefore: gi ? 5 : 0, paraSpaceAfter: 2 } }], head: true });
    REFS.filter((r) => r.group === g).forEach((r) => {
      const w = widthMM(`${r.n}. ${r.text}`, REF_SIZE) + (r.url ? widthMM(` ${r.url}`, URL_SIZE) : 0);
      const runs = [{ text: `${r.n}. ${r.text}`, options: { fontSize: REF_SIZE, color: C.ink, breakLine: !r.url, paraSpaceAfter: r.url ? 0 : 2 } }];
      if (r.url) runs.push({ text: ` ${r.url}`, options: { fontSize: URL_SIZE, color: C.teal, hyperlink: { url: r.url }, breakLine: true, paraSpaceAfter: 2 } });
      items.push({ h: Math.ceil(w / (COL_W * 0.97)) * lineMM + 0.7, runs });
    });
  });
  const total = items.reduce((a, it) => a + it.h, 0), capH = BOTTOM - TOP;
  let cols = [[]];
  if (total <= 2 * capH) {
    let best = 1, bestDiff = Infinity, acc = 0;
    items.forEach((it, i) => {
      acc += it.h;
      if (!items[i + 1] || it.head) return;                  // 묶음 제목 바로 뒤에서는 자르지 않음
      const d = Math.abs(acc - total / 2);
      if (acc <= capH && total - acc <= capH && d < bestDiff) { bestDiff = d; best = i + 1; }
    });
    cols = [items.slice(0, best), items.slice(best)];
  }
  let used = 0;
  if (total > 2 * capH) items.forEach((it, i) => {
    const next = items[i + 1];
    const need = it.h + (it.head && next ? next.h : 0);      // 묶음 제목이 단 끝에 홀로 남지 않게
    if (used + need > BOTTOM - TOP && cols[cols.length - 1].length) { cols.push([]); used = 0; }
    cols[cols.length - 1].push(it);
    used += it.h;
  });
  for (let p = 0; p < cols.length; p += 2) {
    const s = pres.addSlide();
    s.background = { color: C.white };
    runHead(s, null);
    pill(s, p ? "참고문헌(계속)" : "참고문헌", 12, 12.5, p ? 28 : 21);
    [[cols[p], 12], [cols[p + 1], 107]].forEach(([col, x]) => {
      if (!col) return;
      const runs = col.flatMap((it) => it.runs);
      if (runs[0]?.options?.paraSpaceBefore) runs[0] = { ...runs[0], options: { ...runs[0].options, paraSpaceBefore: 0 } };
      s.addText(runs, { x: mm(x), y: mm(TOP), w: mm(COL_W), h: mm(BOTTOM - TOP), margin: 0, isTextBox: true, valign: "top",
        fontFace: F.reg, lineSpacingMultiple: LS });
    });
  }
}

// 한글 낱말 중간 줄바꿈 금지(PowerPoint '한글 단어 잘림 허용' 해제 = a:pPr eaLnBrk="0"). pptxgenjs가 노출하지 않아 저장 후 XML에 넣는다
async function noKoreanWordBreak(file) {
  const JSZip = require("jszip");
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  for (const name of Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const xml = (await zip.file(name).async("string"))
      .replace(/(<\/a:r>)<a:pPr\b[^>]*?(?:\/>|>.*?<\/a:pPr>)/g, "$1")   // pptxgenjs가 run마다 넣는 문단 중간 a:pPr 제거(문단당 하나만 유효)
      .replace(/<a:pPr(?![^>]*eaLnBrk)/g, '<a:pPr eaLnBrk="0"')
      .replace(/<a:p>(?!<a:pPr)/g, '<a:p><a:pPr eaLnBrk="0"/>')
      .replace(/lang="en-US"/g, 'lang="ko-KR" altLang="en-US"');   // 한국어 문단으로 표시해야 낱말 단위 줄바꿈이 적용됨
    zip.file(name, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}
pres.writeFile({ fileName: OUT }).then(async (f) => { await noKoreanWordBreak(f); console.log("wrote", f); });
