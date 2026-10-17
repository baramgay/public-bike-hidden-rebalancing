// A4 세로 분석보고서 PPTX 생성기(표지 + 본문 5쪽 + 참고문헌). 숫자는 outputs/report/report_numbers.json(분석 출력)에서만 읽는다.
// 실행: NODE_PATH=tmp/pptxgenjs-runtime/node_modules node scripts/report/build_deck.js
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const N = JSON.parse(fs.readFileSync(path.join(ROOT, "outputs/report/report_numbers.json"), "utf8"));
const DS = JSON.parse(fs.readFileSync(path.join(ROOT, "docs/report/data_sources.json"), "utf8"));
const REFS = JSON.parse(fs.readFileSync(path.join(ROOT, "docs/report/references.json"), "utf8"));
const OUT = path.join(ROOT, "outputs/report/누비자_분석보고서.pptx");
const IMG = (p) => path.join(ROOT, p);
const FIG = (name) => `outputs/report_figures/${name}.png`;

// ---------- 제목·식별(사용자 확정 대기 항목은 여기만 고친다) ----------
const TITLE_MAIN = "기록 사이의 이동";
const TITLE_SUB = "공공자전거 숨은 재배치 진단과 AI·형평 배치 제안";
const CASE = "창원시 공영자전거 ‘누비자’ 이용기록 1,307만 건으로 본 전국 적용형 공개 분석";
const TEAM = "팀명 ○○○ (참가신청서와 동일하게 입력)";
const TOPIC = "공공자전거 이용기록을 자전거 번호로 이어 기록 없는 재배치 이동을 찾고, AI 수요 예측과 취약 거점 최소 보장으로 더 공정하고 덜 달리는 재배치를 설계·검증(창원 누비자 사례, 다른 도시에 그대로 적용 가능한 공개 방법)";
const CODE_URL = "https://github.com/(공개 저장소 주소 확정 후 입력)";
const RUN_HEAD = `${TITLE_MAIN} · ${TITLE_SUB}`;

const mm = (v) => v / 25.4;
const C = {
  forest: "183F35", accent: "00897B", teal: "137F7B", mint: "00B8B4", ink: "26342E", ink2: "4F5D57",
  muted: "7D8B85", bg: "F2F5F1", line: "D5DDD8", light: "BFDDD6", pale: "E6F2EF", white: "FFFFFF",
};
const F = { reg: "Pretendard", med: "Pretendard Medium", semi: "Pretendard SemiBold", xb: "Pretendard ExtraBold" };
const pct = (x, d = 1) => `${(x * 100).toFixed(d)}%`;
const int = (x) => Math.round(x).toLocaleString("en-US");
const fx = (x, d = 1) => Number(x).toFixed(d);

const pres = new pptxgen();
pres.defineLayout({ name: "A4P", width: mm(210), height: mm(297) });
pres.layout = "A4P";
pres.title = `${TITLE_MAIN} — ${CASE}`;
pres.subject = "AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전 분석보고서";

// ---------- 공통 도우미 ----------
function T(s, text, x, y, w, h, o = {}) {
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
function page(no) {
  const s = pres.addSlide();
  s.background = { color: C.white };
  T(s, RUN_HEAD, 12, 5.2, 150, 4, { fontSize: 7, color: C.muted });
  T(s, `${no} / 5`, 168, 5.2, 30, 4, { fontSize: 7, color: C.muted, align: "right" });
  s.addShape(pres.shapes.LINE, { x: mm(12), y: mm(9.6), w: mm(186), h: 0, line: { color: C.line, width: 0.5 } });
  return s;
}
function pill(s, text, x, y, w) {      // 공식 양식 항목명
  box(s, x, y, w, 6, { fill: C.forest, r: 3 });
  T(s, text, x, y + 1.05, w, 4.5, { fontFace: F.semi, fontSize: 8.5, color: C.white, align: "center" });
}
function head(s, text, y, size = 13) {
  T(s, text, 12, y, 186, 9, { fontFace: F.xb, fontSize: size, color: C.forest, lineSpacingMultiple: 1.05 });
}
function sub(s, text, x, y, w = 120) {
  T(s, text, x, y, w, 5, { fontFace: F.semi, fontSize: 9.5, color: C.forest });
}
function cap(s, text, x, y, w, h = 4) {
  T(s, text, x, y, w, h, { fontSize: 6.8, color: C.muted, lineSpacingMultiple: 1.15 });
}
function stat(s, x, y, w, h, big, unit, label, o = {}) {
  box(s, x, y, w, h, { fill: o.fill ?? C.bg });
  T(s, [{ text: big, options: { fontFace: F.xb, fontSize: o.size ?? 15, color: o.color ?? C.forest } },
        { text: unit, options: { fontFace: F.semi, fontSize: 9, color: o.color ?? C.forest } }],
    x + 3, y + 2.6, w - 6, 8.5);
  T(s, label, x + 3, y + 11.5, w - 6, h - 12.5, { fontSize: 7.5, color: C.ink2, lineSpacingMultiple: 1.15 });
}
function icon(s, name, x, y, size) { img(s, `design/sol/derived/06_icon_${name}_t.png`, x, y, size, size); }
function bullets(s, items, x, y, w, h, o = {}) {
  s.addText(items.map((t, i) => ({
    text: t, options: { bullet: { indent: 9 }, breakLine: i < items.length - 1, paraSpaceAfter: o.gap ?? 2 },
  })), { x: mm(x), y: mm(y), w: mm(w), h: mm(h), margin: 0, isTextBox: true, valign: "top",
    fontFace: F.reg, fontSize: o.size ?? 8.3, color: C.ink, lineSpacingMultiple: 1.17 });
}

// ---------- 수치 ----------
const dep = Object.fromEntries(N.dependency_rows.map((r) => [r.name, r]));
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

// =====================================================================
// 표지
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  img(s, "design/sol/01_cover_forest.png", 0, 0, 210, 297, { sizing: { type: "cover", w: mm(210), h: mm(297) } });
  T(s, "AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전 · 분석보고서", 16, 16, 178, 6,
    { fontFace: F.semi, fontSize: 10, color: C.forest });
  T(s, TITLE_MAIN, 16, 30, 178, 30, { fontFace: F.xb, fontSize: 30, color: C.forest, lineSpacingMultiple: 1.05 });
  T(s, TITLE_SUB, 16, 47, 150, 14, { fontFace: F.semi, fontSize: 12.5, color: C.ink, lineSpacingMultiple: 1.25 });
  T(s, CASE, 16, 63, 120, 6, { fontFace: F.semi, fontSize: 11, color: C.teal });
  box(s, 16, 252, 178, 27, { fill: C.white });
  T(s, TEAM, 21, 256, 168, 6, { fontFace: F.semi, fontSize: 11, color: C.forest });
  T(s, `공개 공공데이터 ${DS.rows.length}종 · 이용기록 ${int(N.valid_rows / 1e4)}만 건 · 2023~2025년`, 21, 263.5, 168, 5,
    { fontSize: 9, color: C.ink2 });
  cap(s, "표지·개념 그림: 생성형 AI(OpenAI Codex 이미지 생성)로 만든 개념도이며 데이터 수치를 담지 않음", 21, 271, 168);
}

// =====================================================================
// 1쪽 — 이름/팀명·주제, 분석 배경 및 목적
// =====================================================================
{
  const s = page(1);
  const lab = { fill: { color: C.bg }, fontFace: F.semi, fontSize: 8.5, color: C.forest, valign: "middle", align: "center" };
  const val = { fontSize: 8.3, color: C.ink, valign: "middle" };
  s.addTable([
    [{ text: "이름/팀명", options: lab }, { text: TEAM, options: val }],
    [{ text: "주제", options: lab }, { text: TOPIC, options: val }],
  ], { x: mm(12), y: mm(12.5), w: mm(186), colW: [mm(20), mm(166)], rowH: [mm(6), mm(10)],
    fontFace: F.reg, border: { type: "solid", pt: 0.5, color: C.line }, margin: [1.5, 4, 1.5, 4] });

  pill(s, "분석 배경 및 목적", 12, 31.5, 34);
  head(s, "반납한 곳과 다음에 빌려 간 곳이 다르다 — 이용기록 사이에 숨은 이동", 39.5, 14.5);
  T(s, "공공자전거 이용기록에는 빌린 곳과 반납한 곳만 남는다. 같은 자전거 번호를 시간순으로 이으면, 반납된 거점과 다음 대여 거점이 다른 경우가 보인다. " +
    "그 사이 자전거는 기록 없이 옮겨졌다 — 재배치 차량이 옮긴 이동이 중심이고 정비 수거·기록 누락도 섞인다. " +
    "창원시 공영자전거 ‘누비자’(터미널 454곳·자전거 5,745대, 2025년 운영사 공시)의 3년 기록으로 이 숨은 이동을 끝까지 추적했다.",
  12, 48.5, 186, 12, { fontSize: 8.8 });

  img(s, "design/sol/derived/02_hill_section_crop.png", 12, 63, 92, 44);
  img(s, FIG("bike_day_4503"), 110, 61.5, 88, 50);
  cap(s, "개념도(생성형 AI 그림) — 사람은 주로 언덕을 내려가고, 자전거는 기록 없이 다시 올라간다", 12, 108, 92);
  cap(s, `실제 기록: 자전거 ${ex.bike}번(2024.1.10~11). 레알주차장 옆(해발 23m)에 반납된 뒤 성주 유니온빌리지(105m)에서 다음 대여. ` +
    `같은 밤 같은 출발·도착 거점으로 ${N.example_bike.same_night_batch_25_to_159.length}대`, 110, 113, 88, 7);

  T(s, "사람이 탄 이동은 내려가고, 기록 없는 이동은 올라간다", 12, 115, 92, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
  img(s, FIG("elev_direction"), 12, 121.5, 89, 41);
  const sw = 28.67;
  stat(s, 110, 122, sw, 40, `${int(N.valid_rows / 1e4)}만`, "건", "3년 이용기록\n(2023~2025)");
  stat(s, 110 + sw + 1, 122, sw, 40, pct(N.moved_share_3y), "", "판정 가능한 연속 이용 중 기록 없는 이동", { color: C.accent });
  stat(s, 110 + 2 * (sw + 1), 122, sw, 40, int(N.moved_per_day_3y), "건", "하루 평균 기록 없는 이동(관측일)");

  sub(s, "왜 중요한가", 12, 169);
  const why = [
    ["co2", "탄소 계산의 빈칸", `운영사의 탄소 감축량은 ‘이용 횟수 × 4.75km × 192g’으로 계산되고 재배치 차량 배출은 빼지 않는다. 2024년 재배치 경로 추정만 하루 약 ${int(N.truck_km_per_day_2024_cap20)}km.`],
    ["hill", "언덕 위 거점일수록 의존", `고도 상위 25% 거점은 대여의 ${pct(depHigh.dependency)}가 기록 없는 이동 뒤에 일어났다(하위 25%는 ${pct(depLow.dependency)}). 차량을 줄이면 영향이 고르지 않다.`],
    ["bike", "전국 공통 과제", "전국 공영자전거 69,572대·연 대여 5,818만 건(2024, 행정안전통계연보). 자전거 번호가 담긴 이용기록은 창원·대전·김해가 공개 — 같은 방법을 바로 쓸 수 있다."],
  ];
  why.forEach(([ic, t, d], i) => {
    const x = 12 + i * 63;
    box(s, x, 175, 60, 37);
    icon(s, ic, x + 2.5, 177.5, 10);
    T(s, t, x + 14, 179.5, 44, 5, { fontFace: F.semi, fontSize: 9, color: C.forest });
    T(s, d, x + 3, 189, 54.5, 22, { fontSize: 7.6, color: C.ink2, lineSpacingMultiple: 1.17 });
  });

  box(s, 12, 215.5, 186, 18, { fill: C.white, line: C.light });
  T(s, "참여 동기", 16, 218.2, 20, 5, { fontFace: F.semi, fontSize: 9, color: C.teal });
  T(s, "공공자전거의 친환경 효과는 이용 횟수로만 셈해진다. 그런데 이용기록을 이어 보니 사람이 타지 않은 이동이 하루 1,600건을 넘었다. " +
    "보이지 않던 운영 부담이 어느 동네에 쏠리는지 데이터로 드러내고, AI로 그 부담을 줄이면서도 소외 지역을 지킬 수 있는지 확인하고 싶었다.",
  36, 218.2, 158, 14, { fontSize: 8.3 });

  sub(s, "분석 목적 — 세 가지 질문", 12, 237);
  const qs = [
    ["01", "숨은 이동은 얼마나, 언제, 어디로 일어나는가?", "분석 내용 및 결과 ① · 3쪽"],
    ["02", "AI 수요 예측은 같은 이동 예산으로 더 많은 대여를 살리는가?", "분석 내용 및 결과 ② · 4쪽"],
    ["03", "취약 거점 최소 보장은 형평을 얼마나 높이고, 비용은 얼마인가?", "결과 ②·정책제안 · 4~5쪽"],
  ];
  qs.forEach(([n, q, where], i) => {
    const x = 12 + i * 63;
    box(s, x, 243, 60, 28, { fill: C.pale });
    T(s, n, x + 3, 245.5, 12, 7, { fontFace: F.xb, fontSize: 14, color: C.accent });
    T(s, q, x + 14, 246, 43, 14, { fontFace: F.semi, fontSize: 8.8, color: C.forest, lineSpacingMultiple: 1.2 });
    T(s, `→ ${where}`, x + 14, 263.5, 44, 4, { fontSize: 7.3, color: C.teal });
  });
  T(s, "목표: 덜 달리고 더 공정한 재배치 — 다른 도시도 그대로 쓸 수 있는 공개 코드와 지표", 12, 275.5, 186, 5,
    { fontFace: F.semi, fontSize: 9, color: C.teal, align: "center" });
}

// =====================================================================
// 2쪽 — 활용 데이터, 분석과정 및 방법, AI 기술 활용
// =====================================================================
{
  const s = page(2);
  pill(s, "활용 데이터", 12, 12.5, 22);
  T(s, `공개 공공데이터 ${DS.rows.length}종만 사용 — 같은 자료로 누구나 재현할 수 있다`, 37, 12.6, 161, 6,
    { fontFace: F.xb, fontSize: 12.5, color: C.forest });
  // 머리글은 공식 양식과 같은 2단(출처 = 플랫폼·URL)으로 도형을 그리고, 본문만 표로 넣는다
  const cw = [6, 33, 25, 25, 61, 36], cx = cw.map((_, i) => 12 + cw.slice(0, i).reduce((a, b) => a + b, 0));
  const hcell = (text, x, y, w, h) => {
    s.addShape(pres.shapes.RECTANGLE, { x: mm(x), y: mm(y), w: mm(w), h: mm(h), fill: { color: C.forest }, line: { color: C.white, width: 0.5 } });
    T(s, text, x, y, w, h, { fontFace: F.semi, fontSize: 7.3, color: C.white, align: "center", valign: "middle" });
  };
  [[0, "No."], [1, "활용 데이터(명)"], [2, "제공기관(명)"], [5, "선정 이유(분석에서의 쓰임)"]].forEach(([i, t]) => hcell(t, cx[i], 21, cw[i], 8.6));
  hcell("출처", cx[3], 21, cw[3] + cw[4], 4.3);
  hcell("플랫폼(명)", cx[3], 25.3, cw[3], 4.3);
  hcell("URL", cx[4], 25.3, cw[4], 4.3);
  const cell = (t, o = {}) => ({ text: t, options: { fontSize: 6.9, color: C.ink, valign: "middle", ...o } });
  const rows = [
    ...DS.rows.map(([name, org, plat, url, why], i) => [
      cell(String(i + 1), { align: "center", color: C.teal, fontFace: F.semi }),
      cell(name, { fontFace: F.semi, color: C.forest }), cell(org), cell(plat),
      { text: [{ text: url, options: { hyperlink: { url } } }], options: { fontSize: 6.0, color: C.teal, valign: "middle" } },
      cell(why),
    ]),
  ];
  s.addTable(rows, {
    x: mm(12), y: mm(29.6), w: mm(186), colW: cw.map(mm),
    rowH: DS.rows.map(() => mm(5.2)), fontFace: F.reg,
    border: { type: "solid", pt: 0.4, color: C.line }, margin: [1, 2, 1, 2], fill: { color: C.white },
  });
  cap(s, `※ ${DS.footnote}`, 12, 110, 186, 4);

  pill(s, "분석과정 및 방법", 12, 120.5, 30);
  T(s, "다섯 단계, 모든 단계를 코드로 재현 — 괄호 숫자는 위 표의 자료 번호", 45, 121.6, 150, 5, { fontSize: 8, color: C.ink2 });
  const steps = [
    ["bike", "수집·정제", "3년 이용 1,307만 건을 DuckDB로 결합. 오류·중복 제거, 2025년 7월 결측은 0으로 채우지 않고 제외", "검사: 이용 − 자전거 수 = 연속쌍 수", "①②"],
    ["route", "자전거 연쇄 추적", "같은 번호의 반납 거점 ≠ 다음 대여 거점 → 기록 없는 이동. 간격·속도(시속 60km)·운영센터 규칙으로 8유형 분류", `핵심 이동 ${int(N.moved_3y)}건`, "①②⑭"],
    ["hill", "지형·생활 접근성", "30m 고도로 오르막 판정. 반경 300m 버스 운행, 의료·약국·시장 거리 하위 25%로 취약 거점 지정", `취약 ${N.vuln_count}곳(복합 ${N.vuln_both_count}곳)`, "③~⑧"],
    ["ai", "AI 수요 예측", "거점·날짜별 아침 필요 대수 예측. 경사 부스팅(포아송 손실), 과거 이력·요일·공휴일·전날 날씨·고도 입력", "학습→검증→시험 시간순 분리", "①⑨⑩"],
    ["truck", "배치 실험·탄소", "2025년 상반기 실제 대여를 순서대로 재생, 재고 0이면 실패. 같은 밤당 이동 예산으로 전략 비교, km→탄소 환산", "시험 전 설계·코드 고정", "①⑫⑬"],
  ];
  steps.forEach(([ic, t, d, outp, data], i) => {
    const x = 12 + i * 37.6, w = 35.6;
    box(s, x, 128, w, 46);
    T(s, `${i + 1}`, x + 2.5, 129.5, 6, 6, { fontFace: F.xb, fontSize: 11, color: C.accent });
    icon(s, ic, x + w - 10.5, 129, 8.5);
    T(s, t, x + 2.5, 136.5, w - 5, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
    T(s, d, x + 2.5, 142, w - 5, 20, { fontSize: 6.9, color: C.ink2, lineSpacingMultiple: 1.17 });
    T(s, outp, x + 2.5, 162.5, w - 5, 6, { fontFace: F.semi, fontSize: 7, color: C.teal, lineSpacingMultiple: 1.1 });
    T(s, `자료 ${data}`, x + 2.5, 169.2, w - 5, 4, { fontSize: 6.6, color: C.muted });
  });

  pill(s, "AI 기술 활용", 12, 177.5, 22);
  T(s, "AI는 분석·검증·전달의 도구로 쓰고, AI가 만든 결과는 원자료와 코드로 다시 확인했다", 37, 178.6, 160, 5, { fontSize: 8, color: C.ink2 });
  const AH = { fill: { color: C.forest }, color: C.white, fontFace: F.semi, fontSize: 7.4, valign: "middle", align: "center" };
  const ac = (t, o = {}) => ({ text: t, options: { fontSize: 6.9, color: C.ink, valign: "middle", ...o } });
  const svc = (t) => ac(t, { fontFace: F.semi, color: C.forest });
  const ai = [
    [svc("Claude Code\n(Anthropic Claude Opus 5.5)"), ac("분석 코드 작성·실행, 오류 재현·수정, 보존 법칙·수치 교차 검증, 보고서 생성기 작성"),
     ac("“같은 자전거 번호의 반납 거점과 다음 대여 거점이 다르면 기록 없는 이동으로 보고, 간격·속도 규칙으로 분류하는 코드를 쓰고 보존 법칙으로 검증하라”")],
    [svc("Claude Haiku·Sonnet\n(LLM, 헤드리스 호출)"), ac(`시의회 회의록 누비자 발언 ${CO.utterances}건 쟁점 분류: Haiku 전수, Sonnet이 무작위 ${CO.second_coder_n}건 독립 재분류해 일치도 측정(주제 일치 ${pct(CO.primary_code_agreement, 0)})`),
     ac("“각 발언을 코드북 11개 쟁점(재배치·정비·형평·환경 등) 중 최대 2개로 분류하고 입장을 고르라. JSON 배열만 출력”")],
    [svc("LangGraph + Claude Sonnet\n(에이전트 흐름)"), ac("밤사이 재배치 계획표 → 운영자용 브리핑 초안 → 숫자·거점명 자동 대조 → 최대 2회 수정 → 사람 승인"),
     ac("“아래 배치 계획표만 근거로 내일 아침 운영자 브리핑을 5줄로 쓰라. 표에 없는 숫자·거점명은 쓰지 말라”")],
    [svc("scikit-learn\n경사 부스팅(머신러닝)"), ac("거점·날짜별 아침 필요 대수 예측(AI 예측). 설정은 학습 전 고정, 검증기간으로만 보정값 선택"),
     ac("프롬프트 없음 — 입력 특징·하이퍼파라미터·평가기간을 코드로 고정(재현 가능)")],
    [svc("OpenAI Codex\n(이미지 생성·검토 보조)"), ac("표지·개념 일러스트·아이콘 생성(데이터 수치 미포함), 자료 대장·문구 교차 검토 보조"),
     ac("“문자 없는 3D 개념 그림: 언덕을 내려가는 공공자전거와 오르는 재배치 차량, 숲색·청록, 수치·라벨 넣지 않음”")],
  ];
  s.addTable([[{ text: "사용 서비스", options: AH }, { text: "활용 범위", options: AH }, { text: "주요 프롬프트(요약)", options: AH }], ...ai], {
    x: mm(12), y: mm(185), w: mm(186), colW: [mm(36), mm(70), mm(80)],
    rowH: [mm(5), ...ai.map(() => mm(10.2))], fontFace: F.reg,
    border: { type: "solid", pt: 0.4, color: C.line }, margin: [1, 2.5, 1, 2.5],
  });

  sub(s, "결과를 믿을 수 있게 한 장치", 12, 245.5);
  const guards = [
    ["보존 검사", "이용 − 자전거 수 = 연속쌍 수를 매 실행 확인"],
    ["시간순 분리", "2023.2~2024.9 학습 · 2024 4분기 검증 · 2025 상반기 시험"],
    ["사전 고정", "시험 전 전략·지표·코드 해시 고정, 수정 시 새 잠금으로 기록"],
    ["두 AI 교차 분류", "다른 모델이 표본을 독립 재분류해 일치도 측정"],
    ["통계 검정", "날짜·거점 부트스트랩 95% 신뢰구간, Wilcoxon 부호순위, 가중 회귀(HC1)"],
  ];
  guards.forEach(([t, d], i) => {
    const x = 12 + i * 37.6;
    box(s, x, 251, 35.6, 21, { fill: C.pale });
    T(s, t, x + 2.5, 253, 31, 4.5, { fontFace: F.semi, fontSize: 8.3, color: C.forest });
    T(s, d, x + 2.5, 258.5, 31, 13, { fontSize: 7, color: C.ink2, lineSpacingMultiple: 1.15 });
  });
  cap(s, "※ 기록 없는 이동의 실제 주체·차종은 기록에 없다. 묶음·야간·오르막 패턴으로 재배치 차량 이동이 중심임을 추정했으며, 수치는 모두 ‘추정 이동’ 기준이며, 본문 수치는 분석 출력 파일에서 자동으로 불러왔다.", 12, 275, 186, 4);
}

// =====================================================================
// 3쪽 — 분석 내용 및 결과 ①
// =====================================================================
{
  const s = page(3);
  pill(s, "분석 내용 및 결과 ①", 12, 12.5, 34);
  T(s, "분석결과 이미지", 48, 13.6, 30, 4, { fontSize: 7.5, color: C.teal });
  head(s, `숨은 이동은 언덕 위로 — 고지대 거점 대여의 ${pct(depHigh.dependency, 0)}는 ‘옮겨진 자전거’`, 20.5, 14);

  img(s, FIG("map_truck_dependency_2024"), 12, 31, 100, 103.7);
  cap(s, "거점별 의존도 = 기록 없이 옮겨져 온 자전거 ÷ 대여(2024년, 대여 365건 이상 거점) · 지형 음영: Copernicus 30m", 12, 135.3, 100, 7);
  img(s, "docs/codex_support/report_release_review_20261017/dependency_bars_60x74_review_v2.png", 116, 31, 60, 74);
  T(s, [{ text: fx(depHigh.dependency / depLow.dependency, 1), options: { fontFace: F.xb, fontSize: 17, color: C.accent } },
        { text: "배", options: { fontFace: F.semi, fontSize: 9, color: C.accent } }], 178, 52, 20, 8, { align: "center" });
  T(s, "고지대 ÷\n저지대", 178, 60.5, 20, 8, { fontSize: 7, color: C.ink2, align: "center" });
  T(s, [{ text: fx(depBoth.dependency / depOther.dependency, 1), options: { fontFace: F.xb, fontSize: 17, color: C.accent } },
        { text: "배", options: { fontFace: F.semi, fontSize: 9, color: C.accent } }], 178, 89, 20, 8, { align: "center" });
  T(s, "복합 취약 ÷\n그 외", 178, 97.5, 20, 8, { fontSize: 7, color: C.ink2, align: "center" });
  bullets(s, [
    `고도 상위 25%(약 35m↑): 대여의 ${pct(depHigh.dependency)} — 하위 25%(${pct(depLow.dependency)})의 ${fx(depHigh.dependency / depLow.dependency, 1)}배`,
    `버스·생활시설이 함께 취약(분석 ${depBoth.stations}곳): ${pct(depBoth.dependency)}, 그 외 ${pct(depOther.dependency)}`,
    `성주 유니온빌리지(105m): 2024년 대여의 ${pct(N.stations["성주 유니온빌리지"].dependency)}`,
    `회귀(고도·취약·대여량·구를 함께, 대여 가중, n=${ST.dependency_regression.main.n}): 고도 10m당 +${fx(REG.elev10.coef * 100, 1)}%p, 복합 취약 +${fx(CVN.coef * 100, 1)}%p(95% 신뢰구간 ${fx(CVN.ci95[0] * 100, 1)}~${fx(CVN.ci95[1] * 100, 1)})`,
  ], 116, 107, 82, 32, { size: 7.6, gap: 1.6 });

  img(s, FIG("hourly_moved_share"), 12, 143, 101.3, 40.3);
  cap(s, "시간대별 대여 중 기록 없는 이동 뒤 대여 비율(2023~2025 합계, 다음 대여 시각 기준)", 12, 183.8, 101);
  T(s, [{ text: `오전 8시 대여의 ${pct(N.moved_share_8am)}`, options: { fontFace: F.semi, color: C.forest } },
        { text: "가 밤사이 옮겨진 자전거로 시작된다. 아침 수요를 재배치가 받치고 있다." }], 12, 188.5, 101, 9, { fontSize: 8.3 });
  T(s, "기록 없는 이동, 어느 구에서 어느 구로?", 120, 141, 78, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
  img(s, FIG("district_matrix"), 120, 146.5, 63, 57);
  cap(s, "색 농도는 제곱근 척도", 184, 196, 14, 7);

  sub(s, "운영의 흔적과 규모", 12, 207);
  const cards = [
    [pct(N.batch5plus_share_2024, 0), "", "같은 운영일·같은 출발→도착으로 5건 이상 묶인 이동(2024) — 차량 재배치와 부합"],
    [`약 ${int(N.truck_km_per_day_2024_cap20)}`, "km", `하루 재배치 경로 추정(2024, 적재 20대·직선·차고지 왕복 가정), 연 ${fx(N.truck_km_year_2024_cap20 / 1e4, 1)}만 km`],
    ["29", "대", "배송·시스템정비 차량(운영사 공시, 2025). 재배치 전담 대수·연료는 비공개"],
    [pct(N.moved_share_3y), "", `3년 평균 비율. 연도별 ${yearlyShares.join(" · ")}(2023·2024·2025) — 일시 현상이 아닌 구조`],
  ];
  cards.forEach(([big, unit, label], i) => {
    const x = 12 + i * 47;
    stat(s, x, 213, 45, 31, big, unit, label);
  });
  box(s, 12, 248, 186, 34, { fill: C.white, line: C.light });
  T(s, "해석", 16, 250.5, 20, 5, { fontFace: F.semi, fontSize: 9, color: C.teal });
  bullets(s, [
    "기록 없는 이동은 묶음·야간·오르막 패턴이 뚜렷해 차량 재배치와 부합한다(정비 수거·기록 누락 일부 포함).",
    "부담은 언덕 위·외곽 거점과 출근 시간대 대여에 쏠린다 → 재배치를 줄이면 이 거점들이 먼저 영향을 받을 수 있다(4쪽 실험으로 확인).",
    `이동의 ${fx(N.fig.district_matrix.diagonal_pct, 0)}%가 같은 구 안에서 일어나 권역 단위 배치 계획이 가능하다.`,
    "이 지표는 자전거 번호가 담긴 이용기록만 있으면 어느 도시든 계산된다 → 5쪽 정책 ①(숨은 이동 지표 공개)로 연결.",
  ], 30, 250.5, 164, 30, { size: 8.2, gap: 2.2 });
}

// =====================================================================
// 4쪽 — 분석 내용 및 결과 ②: AI 예측 배치 실험
// =====================================================================
{
  const s = page(4);
  pill(s, "분석 내용 및 결과 ②", 12, 12.5, 34);
  T(s, "분석결과 이미지", 48, 13.6, 30, 4, { fontSize: 7.5, color: C.teal });
  head(s, "같은 이동 예산이면 AI 예측이 더 많은 대여를, 취약 거점 보장이 더 짧은 ‘빈 거치대’를", 20.5, 13.5);

  cover(s, "design/sol/04_digital_twin_forest.png", 12, 31, 56, 37.3);
  box(s, 71, 31, 61, 46, { fill: C.bg });
  T(s, "실험 방법 — 기록을 다시 재생하는 가상 운영", 74, 33, 56, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
  bullets(s, [
    `2025년 1~6월 실제 대여 ${int(testDemand)}건을 시간순으로 다시 재생`,
    "거치대가 비어 있으면 그 대여는 ‘실패’로 기록",
    "매일 02시, 전략마다 같은 ‘밤당 이동 예산’ 안에서 자전거를 옮김",
    "설정은 2024년 4분기(검증)로만 고르고, 시험 결과는 사전 고정 뒤 공개",
  ], 74, 39.5, 56, 37, { size: 7.5, gap: 1.5 });
  cap(s, "가상 운영 개념도(생성형 AI 그림)", 12, 69, 56);
  img(s, FIG("forecast_mae"), 136, 31, 62, 45.8);
  cap(s, `필요 대수 예측 오차(시험기간, 대). AI는 규칙 대비 ${fx(MAE.groups["전체"].reduction_vs_rule_pct.ai, 1)}%, 날씨까지 알면 ${fx(MAE.groups["전체"].reduction_vs_rule_pct.ai_weather, 1)}% 감소`, 136, 77.5, 62, 7);

  img(s, FIG("policy_frontier"), 12, 86, 101.3, 63.2);
  cap(s, "밤당 이동 대수별 대여 성공률(시험기간). 상한선은 실제 운영에서 알 수 없는 정보를 쓴 비교선", 12, 150, 101);
  img(s, FIG("notruck"), 120, 86, 62, 45.5);
  T(s, "재배치를 멈추면", 120, 132.5, 78, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
  T(s, `대여 성공률이 ${pct(sim("none", 0).served_rate, 0)}로 떨어지고, 고지대 거점은 ${fx(NT.groups["고지대 (상위 25%)"].none_served_rate_pct, 0)}%까지 내려간다. 재배치는 언덕 위 거점의 생명선이다.`,
    120, 138, 78, 14, { fontSize: 7.9 });

  img(s, FIG("equity"), 12, 157, 84.6, 51.6);
  cap(s, `예산 1,500대/밤 · 취약 거점 ${EQ.group_stations}곳 · 빈 시간 = 05~24시 중 재고 0인 시간(거점·일 평균)`, 12, 209, 85, 7);
  const k = [
    [`${int(saveAI)}`, "대↓", `같은 성공률(${pct(ES.target_served_rate)})에 필요한 밤당 이동, AI 예측 vs 경험 규칙(−${pct(saveAI / ES.rule4w.moves_per_night)})`],
    [`+${fx(PF.gain_at_budget_1500_pp.ai, 2)}`, "%p", `같은 예산(1,500대/밤)의 대여 성공률, AI 예측 vs 경험 규칙`],
    [`${fx(EQ.vulnerable_gain_ai_fair_vs_ai.zero_hours_pct, 0)}`, "%", "취약 거점 빈 시간, AI+취약 보장 vs AI 예측"],
    [`${fx(EQ.overall_cost_ai_fair_minus_ai_pp, 2)}`, "%p", "보장의 대가: 전체 대여 성공률 변화(같은 예산)"],
  ];
  k.forEach(([big, unit, label], i) => {
    const x = 102 + (i % 2) * 48, y = 157 + Math.floor(i / 2) * 29;
    stat(s, x, y, 46, 27, big, unit, label, { color: i < 2 ? C.forest : C.accent });
  });

  box(s, 12, 218, 186, 64, { fill: C.white, line: C.light });
  T(s, "탄소로 환산하면", 16, 220.5, 60, 5, { fontFace: F.semi, fontSize: 9.5, color: C.forest });
  const yr = (km, f) => (km * 365 * f) / 1000;
  bullets(s, [
    `AI 예측은 같은 서비스에 밤당 차량 주행을 약 ${fx(kmSaveAI, 0)}km 줄인다 → 연 ${fx(yr(kmSaveAI, co2.diesel_low), 1)}~${fx(yr(kmSaveAI, co2.diesel_high), 1)}t CO2(1톤 경유 화물차 기준). 예측만으로 줄어드는 탄소는 크지 않다.`,
    `큰 차이는 차량에서 나온다: 2024년 경로 추정 연 ${fx(N.truck_km_year_2024_cap20 / 1e4, 1)}만 km는 경유 ${fx(N.observed_co2_t_2024.diesel_low, 0)}~${fx(N.observed_co2_t_2024.diesel_high, 0)}t, 전기 화물차면 ${fx(N.observed_co2_t_2024.ev, 0)}t(약 절반).`,
    "운영사 감축량 산식은 승용차 대체 100%를 가정하고 재배치 배출을 빼지 않는다. 대체율이 해외 사례처럼 낮으면(2~21%) 재배치 배출 비중이 커진다 → ‘순감축’ 회계가 필요하다.",
    `AI의 진짜 효과는 서비스와 형평: 같은 예산으로 반년 대여 약 ${int(testDemand * PF.gain_at_budget_1500_pp.ai / 100)}건을 더 살리고, 보장을 더하면 취약 거점 빈 시간이 ${fx(-EQ.vulnerable_gain_ai_fair_vs_ai.zero_hours_pct, 0)}% 줄어든다.`,
  ], 16, 227, 122, 34, { size: 7.7, gap: 1.6 });
  // 통계적 확인(95% 신뢰구간, scripts/analysis/stat_tests.py)
  const fc = ST.forecast.ai_vs_rule4w, ar = ST.ai_vs_rule_station.all.success_rate.pooled;
  const vz = ST.equity_station.vulnerable.empty_hours_per_station_day, nv = ST.equity_station.non_vulnerable.success_rate.pooled;
  box(s, 15, 262, 124, 18.5, { fill: C.pale, r: 1.5 });
  T(s, "통계적 확인(95% 신뢰구간)", 17.5, 263.3, 60, 4, { fontFace: F.semi, fontSize: 7.6, color: C.forest });
  bullets(s, [
    `예측 오차 감소 ${fx(fc.reduction_pct, 1)}%(${fx(fc.reduction_pct_ci95[0], 1)}~${fx(fc.reduction_pct_ci95[1], 1)}%), AI가 더 정확한 날 ${pct(fc.daily.share_days_better, 0)} — 날짜 단위 부트스트랩`,
    `대여 성공률 AI−규칙 +${fx(ar.diff * 100, 2)}%p(${ci(ar.ci95_diff, 100, 2)}) · 보장 시 취약 거점 빈 시간 ${fx(vz.mean_diff, 2)}시간(${ci(vz.ci95_mean_diff, 1, 2)}), 개선 ${pct(vz.share_improved, 0)}·악화 ${pct(vz.share_worse, 0)}로 효과는 일부 거점에 집중`,
  ], 17.5, 267.6, 120, 13, { size: 6.9, gap: 0.8 });
  // 재배치 차량 연간 배출 미니 막대(2024 경로 추정 km × 배출계수)
  T(s, "재배치 차량 연간 배출(2024 경로 추정, tCO2)", 142, 221, 54, 8, { fontFace: F.semi, fontSize: 7.6, color: C.forest });
  const bars = [["경유 화물차(연비 낮음)", N.observed_co2_t_2024.diesel_high, C.muted], ["경유 화물차(연비 높음)", N.observed_co2_t_2024.diesel_low, C.muted],
    ["전기 화물차", N.observed_co2_t_2024.ev, C.accent], ["AI 예측 절감분(경유)", yr(kmSaveAI, co2.diesel_high), C.mint]];
  const vmax = bars[0][1];
  bars.forEach(([lab, v, col], i) => {
    const y = 231 + i * 11.5;
    T(s, lab, 142, y, 54, 4, { fontSize: 6.8, color: C.ink2 });
    box(s, 142, y + 4.2, Math.max(0.8, 40 * v / vmax), 4.2, { fill: col, r: 0 });
    T(s, `${fx(v, 0)}t`, 142 + Math.max(0.8, 40 * v / vmax) + 1.2, y + 4, 14, 4.5, { fontFace: F.semi, fontSize: 7.4, color: C.forest });
  });
  cap(s, "배출계수: 경유 2.60kg/L·연비 8.6~9.9km/L, 전기 3.1km/kWh·0.4149kg/kWh", 142, 277, 54, 5);
}

// =====================================================================
// 5쪽 — 정책제안 및 기대효과
// =====================================================================
{
  const s = page(5);
  pill(s, "정책제안 및 기대효과", 12, 12.5, 34);
  head(s, "숨은 이동을 보이게, 배치는 예측으로, 언덕 위 거점엔 아침 2대를", 20.5, 14);
  const pol = [
    ["truck", "① 숨은 이동 지표 공개", "기록 없는 이동 비율·거점별 의존도·재배치 km를 운영 성과 지표로 매월 공개", "전국 공공자전거 운영기관",
      `재배치 부담이 쏠린 동네를 정기 점검, 탄소 ‘순감축’ 산정의 기초`],
    ["ai", "② AI 예측 야간 배치", "거점별 내일 아침 필요 대수를 예측하고 기상 예보와 연동, 운영자 승인 후 배차", "운영기관 배차 담당",
      `같은 서비스에 밤당 이동 ${int(saveAI)}대(${pct(saveAI / ES.rule4w.moves_per_night)})↓, 예보 연동 시 최대 ${int(saveAIw)}대↓`],
    ["clinic", "③ 취약 거점 아침 2대", `버스·생활시설 접근이 약한 ${N.vuln_count}곳에 매일 아침 최소 2대 보장`, "지자체(형평 목표)·운영기관",
      `취약 거점 빈 시간 ${fx(-EQ.vulnerable_gain_ai_fair_vs_ai.zero_hours_pct, 0)}%↓, 전체 성공률 비용 ${fx(Math.abs(EQ.overall_cost_ai_fair_minus_ai_pp), 2)}%p`],
    ["co2", "④ 재배치 차량 전기화", "1톤 경유 화물차를 전기 화물차로 바꾸고 감축량에서 운영 배출을 뺀다", "지자체 탄소중립 계획",
      `재배치 배출 연 ${fx(N.observed_co2_t_2024.diesel_low, 0)}~${fx(N.observed_co2_t_2024.diesel_high, 0)}t → ${fx(N.observed_co2_t_2024.ev, 0)}t`],
  ];
  pol.forEach(([ic, t, what, who, eff], i) => {
    const x = 12 + i * 47, w = 45;
    box(s, x, 31, w, 72, { fill: C.bg });
    icon(s, ic, x + 2.5, 33, 11);
    T(s, t, x + 2.5, 45.5, w - 5, 9, { fontFace: F.semi, fontSize: 9.2, color: C.forest });
    T(s, what, x + 2.5, 52.5, w - 5, 20, { fontSize: 7.6, color: C.ink2, lineSpacingMultiple: 1.17 });
    T(s, [{ text: "대상 ", options: { fontFace: F.semi, color: C.teal } }, { text: who }], x + 2.5, 73, w - 5, 8, { fontSize: 7.3 });
    box(s, x + 2, 82, w - 4, 19, { fill: C.white });
    T(s, [{ text: "기대효과\n", options: { fontFace: F.semi, color: C.accent, fontSize: 7.3 } }, { text: eff, options: { fontSize: 7.6, color: C.forest } }],
      x + 4, 83.5, w - 8, 17, { lineSpacingMultiple: 1.15 });
  });

  // 운영자 브리핑(LLM) 휴대폰 화면
  const B = N.brief;
  box(s, 12, 109, 54, 104, { fill: C.forest, r: 6 });
  box(s, 14.5, 115, 49, 92, { fill: C.white, r: 2 });
  T(s, "내일 아침 배치 브리핑 · AI 초안", 16.5, 117, 45, 4, { fontFace: F.semi, fontSize: 7.4, color: C.forest });
  // 1)요약·2)우선 배치·4)확인 요청만 싣고 3)경로는 정차 수만 표기(화면 공간)
  const briefLines = B ? B.draft.replace(/[#*`]/g, "").split("\n").map((l) => l.trim()).filter(Boolean) : [];
  const sec3 = briefLines.findIndex((l) => l.startsWith("3)")), sec4 = briefLines.findIndex((l) => l.startsWith("4)"));
  const briefText = B ? [...briefLines.slice(1, sec3), `3) 1회차 경로: 정차 ${B.facts.first_runs[0].stops.length}곳`, ...briefLines.slice(sec4)].join("\n")
    : "(브리핑 생성 후 자동 입력)";
  T(s, B ? `${B.facts.date} 밤 · 시험기간 재현` : "", 16.5, 121.5, 45, 4, { fontSize: 6.6, color: C.muted });
  T(s, briefText, 16.5, 126, 45, 62, { fontSize: 6.4, color: C.ink, lineSpacingMultiple: 1.15 });
  box(s, 16.5, 189, 45, 16, { fill: C.pale, r: 1.5 });
  T(s, B ? `자동 검증: 배치표에 없는 숫자·거점명 ${B.final_errors.length}건\n수정 ${B.revisions}회 → 운영자 승인 ${B.approved ? "완료" : "대기"}` : "",
    18, 190.5, 42, 13, { fontSize: 6.4, color: C.forest, lineSpacingMultiple: 1.2 });
  cap(s, "LangGraph: 초안→숫자·거점명 자동 대조→수정→사람 승인. AI가 표에 없는 숫자를 쓰지 못하게 막는다", 12, 214, 54, 7);

  img(s, FIG("council_issues"), 72, 109, 84, 52);
  T(s, "시의회는 무엇을 말해 왔나", 158, 110, 40, 5, { fontFace: F.semi, fontSize: 8.6, color: C.forest });
  T(s, `2020~2026년 누비자 관련 발언 ${CO.relevant}건을 AI로 분류. 예산·이용 실적이 절반을 넘고, 재배치 ${pct(CO.share_of_relevant["재배치"], 0)}·형평 ${pct(CO.share_of_relevant["형평"], 0)}는 드물었다. ` +
    `보이지 않는 운영 부담은 논의에서도 보이지 않았다.`, 158, 116, 40, 40, { fontSize: 7.5, lineSpacingMultiple: 1.18 });
  cap(s, `관련 발언 대비 쟁점 비중(발언당 최대 2개) · 두 모델 일치: 관련성 ${pct(CO.relevant_agreement, 0)}, 주제 ${pct(CO.primary_code_agreement, 0)}`, 72, 161.5, 126, 4);

  sub(s, "기대효과와 파급효과", 72, 168);
  const effects = [
    ["운영", `같은 서비스를 더 적은 이동으로: 밤당 ${int(saveAI)}대·주행 약 ${fx(kmSaveAI, 0)}km 절감, 인력·연료비 절감 여지`],
    ["형평", `언덕 위·외곽 거점의 아침 빈 거치대 감소(취약 거점 빈 시간 ${fx(-EQ.vulnerable_gain_ai_fair_vs_ai.zero_hours_pct, 0)}%↓)`],
    ["환경", "재배치 배출을 포함한 ‘순감축’ 회계와 전기 화물차 전환으로 재배치 배출 절반"],
    ["전국 확산", "자전거 번호가 담긴 이용기록 공개만으로 다른 도시에 같은 코드 적용 — 공공데이터 개방 기준에 ‘자전거 번호’ 포함 권고"],
  ];
  effects.forEach(([t, d], i) => {
    const y = 174 + i * 10;
    box(s, 72, y, 126, 9, { fill: i % 2 ? C.white : C.bg, r: 1.2 });
    T(s, t, 74.5, y + 2.1, 18, 5, { fontFace: F.semi, fontSize: 8, color: C.accent });
    T(s, d, 93, y + 1.4, 103, 7, { fontSize: 7.6, color: C.ink, valign: "middle" });
  });

  box(s, 12, 223, 186, 30, { fill: C.white, line: C.light });
  T(s, "한계와 다음 단계", 16, 225.5, 40, 5, { fontFace: F.semi, fontSize: 8.8, color: C.teal });
  bullets(s, [
    "이동의 실제 주체·시각은 기록에 없어 ‘추정 이동’이다. 운영기관의 배차 기록과 맞춰 보면 정확도를 확인할 수 있다.",
    "실험은 관측된 대여를 재생하므로 자전거가 없어 포기한 수요는 담지 못한다. 초기 재고는 관측 기록으로 재구성한 공통 조건이다.",
    "생활 접근성은 2024.12~2026.10 시점 자료로 만든 정적 분류다. 실제 운영에서는 전날 발표 기상 예보로 날씨 입력을 바꿔야 한다.",
  ], 16, 231.5, 178, 21, { size: 7.6, gap: 1.5 });

  box(s, 12, 256, 186, 27, { fill: C.bg });
  T(s, "분석 도구 및 코드", 16, 258.5, 40, 5, { fontFace: F.semi, fontSize: 8.8, color: C.teal });
  T(s, "Python(pandas·DuckDB·NumPy·scikit-learn·matplotlib), LangGraph, Claude Code, pptxgenjs · 지형: Copernicus DEM · 문서: PowerPoint→PDF", 16, 264, 178, 5, { fontSize: 7.8 });
  T(s, [{ text: "전체 코드·재현 순서: ", options: { fontFace: F.semi, color: C.forest } },
        { text: CODE_URL, options: { color: C.teal } }], 16, 270, 178, 5, { fontSize: 8 });
  T(s, "참고문헌은 다음 쪽(본문 분량 제외). 데이터 출처는 2쪽 표.", 16, 276, 178, 4, { fontSize: 7, color: C.muted });
}

// =====================================================================
// 참고문헌(본문 분량 제외)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  T(s, RUN_HEAD, 12, 5.2, 150, 4, { fontSize: 7, color: C.muted });
  s.addShape(pres.shapes.LINE, { x: mm(12), y: mm(9.6), w: mm(186), h: 0, line: { color: C.line, width: 0.5 } });
  pill(s, "참고문헌", 12, 12.5, 20);
  const groups = [...new Set(REFS.map((r) => r.group))];
  const runs = [];
  groups.forEach((g, gi) => {
    runs.push({ text: g, options: { fontFace: F.semi, fontSize: 8.4, color: C.forest, breakLine: true, paraSpaceBefore: gi ? 5 : 0, paraSpaceAfter: 2 } });
    REFS.filter((r) => r.group === g).forEach((r) => {
      runs.push({ text: `${r.n}. ${r.text}`, options: { fontSize: 6.9, color: C.ink, breakLine: !r.url, paraSpaceAfter: r.url ? 0 : 2.2 } });
      if (r.url) runs.push({ text: ` ${r.url}`, options: { fontSize: 6.4, color: C.teal, hyperlink: { url: r.url }, breakLine: true, paraSpaceAfter: 2.2 } });
    });
  });
  const half = Math.ceil(runs.length / 2);
  let cut = runs.findIndex((r, i) => i >= half && r.options.fontFace === F.semi);
  if (cut < 0) cut = half;
  [[runs.slice(0, cut), 12], [runs.slice(cut), 107]].forEach(([part, x]) => {
    s.addText(part, { x: mm(x), y: mm(22), w: mm(91), h: mm(266), margin: 0, isTextBox: true, valign: "top",
      fontFace: F.reg, lineSpacingMultiple: 1.12 });
  });
}

pres.writeFile({ fileName: OUT }).then((f) => console.log("wrote", f));
