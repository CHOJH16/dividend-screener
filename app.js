const DATA_FILE = "data/screener_us.json";
const NCOL = 11;

const BAND = {
  "-2": { label: "매우 고평가", cls: "b--2" },
  "-1": { label: "고평가",     cls: "b--1" },
  "0":  { label: "중립",       cls: "b-0"  },
  "1":  { label: "저평가",     cls: "b-1"  },
  "2":  { label: "매우 저평가", cls: "b-2"  },
};

const MOAT = {
  Wide:   { label: "넓음", cls: "moat-wide",   rank: 3 },
  Narrow: { label: "좁음", cls: "moat-narrow", rank: 2 },
  None:   { label: "없음", cls: "moat-none",   rank: 1 },
};

const FULL_HISTORY = 9.5;

const DEFAULTS = {
  idx: ["SP500", "NDX100"], streak: 10, minY: 0,
  band: "all", moat: "all", q: "", trap: true,
  maxPE: 0, peBand: "all", hasPE: false,
  sort: "pct", dir: -1,
};

let ALL = [];
let S = { ...DEFAULTS, idx: new Set(DEFAULTS.idx) };

const $ = (s) => document.querySelector(s);
const fmtP = (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtY = (v) => Number(v).toFixed(2) + "%";
const has = (v) => v !== null && v !== undefined && v !== "";
const fmtE = (v) => (has(v) ? Number(v).toFixed(1) + "배" : "-");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------------------------------------------- 상태 → 화면 동기화 */
function syncControls() {
  $("#f-streak").value = String(S.streak);
  $("#f-miny").value   = String(S.minY);
  $("#f-band").value   = S.band;
  $("#f-pe").value     = String(S.maxPE);
  $("#f-peband").value = S.peBand;
  $("#f-moat").value   = S.moat;
  $("#f-q").value      = S.q;
  $("#f-trap").checked = S.trap;
  $("#f-hasspe").checked = S.hasPE;
  document.querySelectorAll("#f-idx .chip").forEach((x) =>
    x.classList.toggle("on", S.idx.has(x.dataset.v)));

  if ($("#f-streak").value === "") { S.streak = 0;     $("#f-streak").value = "0"; }
  if ($("#f-miny").value   === "") { S.minY   = 0;     $("#f-miny").value   = "0"; }
  if ($("#f-band").value   === "") { S.band   = "all"; $("#f-band").value   = "all"; }
  if ($("#f-pe").value     === "") { S.maxPE  = 0;     $("#f-pe").value     = "0"; }
  if ($("#f-peband").value === "") { S.peBand = "all"; $("#f-peband").value = "all"; }
  if ($("#f-moat").value   === "") { S.moat   = "all"; $("#f-moat").value   = "all"; }
}

/* ---------------------------------------------------- 데이터 주소 후보 */
function candidates() {
  const list = [];
  try { list.push(new URL(DATA_FILE, location.href).href); } catch (e) {}
  list.push("./" + DATA_FILE);
  const m = location.hostname.match(/^([^.]+)\.github\.io$/i);
  if (m) {
    const user = m[1];
    const seg = location.pathname.split("/").filter(Boolean);
    const repo = seg.length ? seg[0] : user + ".github.io";
    list.push(`https://raw.githubusercontent.com/${user}/${repo}/main/${DATA_FILE}`);
  }
  return list.filter((v, i) => list.indexOf(v) === i);
}

function getJSON(url) {
  if (typeof fetch === "function") {
    return fetch(url, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }
  return new Promise((res, rej) => {
    const x = new XMLHttpRequest();
    x.open("GET", url, true);
    x.timeout = 15000;
    x.onload = () => {
      if (x.status < 200 || x.status >= 300) return rej(new Error("HTTP " + x.status));
      try { res(JSON.parse(x.responseText)); } catch (e) { rej(new Error("JSON 오류")); }
    };
    x.onerror = () => rej(new Error("네트워크 오류"));
    x.ontimeout = () => rej(new Error("시간 초과"));
    x.send();
  });
}

function showError(title, detail) {
  $("#updated").textContent = title;
  $("#tbody").innerHTML =
    '<tr><td colspan="' + NCOL + '" class="empty">' + title +
    '<br><small style="opacity:.7">' + String(detail || "").slice(0, 200) + "</small><br><br>" +
    '<button type="button" id="btn-retry" class="ghost">다시 시도</button></td></tr>';
  const b = $("#btn-retry");
  if (b) b.onclick = () => {
    $("#tbody").innerHTML = '<tr><td colspan="' + NCOL + '" class="empty">다시 불러오는 중입니다…</td></tr>';
    load();
  };
}

/* ---------------------------------------------------- 데이터 로드 */
async function load() {
  $("#updated").textContent = "불러오는 중…";
  let json = null, lastErr = "";

  outer:
  for (const base of candidates()) {
    for (let n = 1; n <= 3; n++) {
      const url = base + (base.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
      try {
        json = await getJSON(url);
        if (json && json.items) break outer;
        throw new Error("내용 없음");
      } catch (e) {
        lastErr = (e && e.message) ? e.message : "알 수 없는 오류";
        json = null;
        await sleep(700 * n);
      }
    }
  }

  if (!json) {
    showError("데이터를 받지 못했습니다", "원인: " + lastErr + " · 잠시 후 다시 시도 버튼을 눌러 주세요.");
    return;
  }

  ALL = json.items || [];
  $("#updated").textContent = json.updated || "-";
  $("#cnt-all").textContent = ALL.length;

  try {
    render();
  } catch (e) {
    showError("화면 표시 중 오류", (e && e.message) || e);
  }
}

/* ---------------------------------------------------- 해자 표시
   애널리스트 등급만 사용합니다. 퀀트 모델 값(qmoat)은 재무지표만으로
   산출돼 정성적 판단이 빠져 있으므로 등급으로 쓰지 않습니다.          */
function moatRank(d) {
  if (d.moat && MOAT[d.moat]) return MOAT[d.moat].rank;
  return 0;
}

function isETF(d) {
  return d.etf === true || (d.idx || []).indexOf("DIVETF") >= 0;
}

function moatCell(d) {
  const m = MOAT[d.moat];
  if (m) return `<span class="badge ${m.cls}">${m.label}</span>`;
  if (isETF(d)) {
    return '<span class="moat-na" title="ETF는 개별 기업이 아니라 해자 등급 대상이 아닙니다">-</span>';
  }
  return '<span class="moat-unrated" title="모닝스타 애널리스트가 커버하지 않는 종목이라 해자 등급이 없습니다">미평가</span>';
}

/* ---------------------------------------------------- PER 표시 */
function hasPE(d) {
  return has(d.pe) && has(d.pepct);
}

function peCell(d) {
  if (!hasPE(d)) {
    const why = isETF(d) ? "ETF는 PER 대상이 아닙니다"
                         : "적자이거나 분기 EPS를 확보하지 못한 종목입니다";
    return `<span class="moat-na" title="${why}">-</span>`;
  }
  const b = BAND[String(d.peband)] || BAND["0"];
  return `<div class="cellbar">
      <span class="pnum" title="최근 ${d.peyrs}년 중 지금보다 PER이 낮았던 기간 비율">${Math.round(d.pepct)}%</span>
      <span class="badge ${b.cls}">${b.label}</span>
    </div>`;
}

/* ---------------------------------------------------- 필터 + 정렬 */
function view() {
  const q = S.q.trim().toLowerCase();
  const minStreak = Number(S.streak) || 0;
  const minY = Number(S.minY) || 0;
  const maxPE = Number(S.maxPE) || 0;
  const needPE = S.hasPE || maxPE > 0 || S.peBand !== "all";

  let rows = ALL.filter((d) => {
    const idx = d.idx || [];
    if (!idx.some((i) => S.idx.has(i))) return false;
    if (minStreak > 0 && Number(d.streak) < minStreak) return false;
    if (minY > 0 && Number(d.y) < minY) return false;
    if (S.trap && d.y > 15) return false;
    if (S.band === "cheap" && d.pct < 70) return false;
    if (S.band === "verycheap" && d.pct < 90) return false;
    if (S.band === "notrich" && d.pct < 30) return false;
    if (S.moat === "wide" && d.moat !== "Wide") return false;
    if (S.moat === "wn" && !(d.moat === "Wide" || d.moat === "Narrow")) return false;
    if (S.moat === "rated" && !d.moat) return false;

    if (needPE && !hasPE(d)) return false;
    if (maxPE > 0 && Number(d.pe) > maxPE) return false;
    if (S.peBand === "below" && !(has(d.pe50) && Number(d.pe) <= Number(d.pe50))) return false;
    if (S.peBand === "notrich" && d.pepct > 70) return false;
    if (S.peBand === "cheap" && d.pepct > 30) return false;
    if (S.peBand === "verycheap" && d.pepct > 10) return false;

    if (q && !((d.sym || "").toLowerCase().includes(q) ||
               (d.name || "").toLowerCase().includes(q) ||
               (d.sec || "").toLowerCase().includes(q))) return false;
    return true;
  });

  const k = S.sort;
  rows.sort((a, b) => {
    if (k === "moat") return (moatRank(a) - moatRank(b)) * S.dir;
    const x = a[k], y = b[k];
    const xn = !has(x), yn = !has(y);
    if (xn && yn) return 0;
    if (xn) return 1;            // 값이 없는 종목은 항상 뒤로
    if (yn) return -1;
    if (typeof x === "string") return String(x).localeCompare(String(y)) * S.dir;
    return ((x || 0) - (y || 0)) * S.dir;
  });
  return rows;
}

/* ---------------------------------------------------- 그리기 */
function render() {
  const rows = view();
  $("#cnt").textContent = rows.length;

  document.querySelectorAll("th.s").forEach((th) => {
    th.classList.toggle("on", th.dataset.key === S.sort);
    th.classList.toggle("asc", th.dataset.key === S.sort && S.dir === 1);
  });

  if (!rows.length) {
    $("#tbody").innerHTML =
      '<tr><td colspan="' + NCOL + '" class="empty">조건에 맞는 종목이 없습니다. 필터를 완화해 보세요.</td></tr>';
    return;
  }

  $("#tbody").innerHTML = rows.map((d) => {
    const b = BAND[String(d.band)] || BAND["0"];
    const idx = d.idx || [];
    const tags = [];
    if (idx.includes("DIVETF")) tags.push("ETF");
    else if (idx.includes("SP500") && idx.includes("NDX100")) tags.push("S&P·NDX");
    else if (idx.includes("NDX100")) tags.push("NDX");
    const warn = d.yrs < FULL_HISTORY
      ? `<span class="tag" title="배당수익률 밴드를 ${d.yrs}년치 데이터로만 계산했습니다">이력 ${d.yrs}년</span>`
      : "";
    return `<tr data-sym="${d.sym}">
      <td><span class="nm">${d.name}</span><span class="tk">${d.sym}</span>
          ${tags.map((t) => `<span class="tag">${t}</span>`).join("")}${warn}</td>
      <td class="r">${fmtP(d.px)}</td>
      <td class="r big">${fmtY(d.y)}</td>
      <td class="r">${fmtY(d.y50)}</td>
      <td class="c">
        <div class="cellbar">
          <span class="pnum">${Math.round(d.pct)}%</span>
          <span class="badge ${b.cls}">${b.label}</span>
        </div>
      </td>
      <td class="r big">${fmtE(d.pe)}</td>
      <td class="r">${fmtE(d.pe50)}</td>
      <td class="c">${peCell(d)}</td>
      <td class="r">${d.streak}년</td>
      <td class="c">${moatCell(d)}</td>
      <td>${d.sec}</td>
    </tr>`;
  }).join("");

  document.querySelectorAll("#tbody tr[data-sym]").forEach((tr) => {
    tr.onclick = () => openModal(tr.dataset.sym);
  });
}

/* ---------------------------------------------------- 상세 팝업 */
function openModal(sym) {
  const d = ALL.find((x) => x.sym === sym);
  if (!d) return;
  const b = BAND[String(d.band)] || BAND["0"];

  let moatTxt;
  if (d.moat && MOAT[d.moat]) moatTxt = "해자 " + MOAT[d.moat].label;
  else if (isETF(d)) moatTxt = "해자 등급 대상 아님";
  else moatTxt = "해자 미평가";

  $("#m-name").textContent = d.name;
  $("#m-sym").textContent =
    `${d.sym} · ${d.sec} · 배당 증가(유지) ${d.streak}년 · 밴드 계산 기간 ${d.yrs}년 · ${moatTxt}`;
  $("#m-badge").textContent = b.label;
  $("#m-badge").className = "badge " + b.cls;
  $("#m-px").textContent = fmtP(d.px);
  $("#m-ttm").textContent = "$" + Number(d.ttm).toFixed(2);
  $("#m-y").textContent = fmtY(d.y);
  $("#m-pct").textContent = Math.round(d.pct) + "백분위";
  $("#m-marker").style.left = d.pct + "%";
  $("#m-marker-t").textContent = Math.round(d.pct) + "백분위";
  $("#m-p10").textContent = fmtY(d.y10);
  $("#m-p25").textContent = fmtY(d.y25);
  $("#m-p50").textContent = fmtY(d.y50);
  $("#m-p75").textContent = fmtY(d.y75);
  $("#m-p90").textContent = fmtY(d.y90);
  $("#m-note").textContent =
    `현재 배당수익률이 최근 ${d.yrs}년 기준 상위 ${Math.round(100 - d.pct)}% 구간입니다. ` +
    (d.pct >= 70 ? "역사적으로 낮은 주가·높은 수익률 구간입니다."
                 : d.pct <= 30 ? "역사적으로 높은 주가·낮은 수익률 구간입니다."
                 : "평균적인 구간입니다.");

  /* PER 밴드 */
  if (hasPE(d)) {
    $("#m-pe-wrap").hidden = false;
    $("#m-pe-none").hidden = true;
    $("#m-pe").textContent    = fmtE(d.pe);
    $("#m-peps").textContent  = has(d.peps) ? "$" + Number(d.peps).toFixed(2) : "-";
    $("#m-pe50").textContent  = fmtE(d.pe50);
    $("#m-peavg").textContent = fmtE(d.peavg);
    $("#m-pemarker").style.left = d.pepct + "%";
    $("#m-pemarker-t").textContent = Math.round(d.pepct) + "백분위";
    $("#m-pe10").textContent  = fmtE(d.pe10);
    $("#m-pe25").textContent  = fmtE(d.pe25);
    $("#m-pe50b").textContent = fmtE(d.pe50);
    $("#m-pe75").textContent  = fmtE(d.pe75);
    $("#m-pe90").textContent  = fmtE(d.pe90);
    const gap = has(d.pe50) && Number(d.pe50) > 0
      ? Math.round((Number(d.pe) / Number(d.pe50) - 1) * 100) : null;
    $("#m-penote").textContent =
      `최근 ${d.peyrs}년 가운데 ${Math.round(d.pepct)}%의 기간이 지금보다 PER이 낮았습니다. ` +
      (gap === null ? "" :
        (gap > 0 ? `10년 중앙 PER보다 ${gap}% 비쌉니다. `
                 : `10년 중앙 PER보다 ${Math.abs(gap)}% 쌉니다. `)) +
      (d.pepct <= 30 ? "역사적으로 싼 구간입니다."
                     : d.pepct >= 70 ? "역사적으로 비싼 구간입니다."
                     : "평균적인 구간입니다.") +
      (d.pestale ? " (오늘 EPS 갱신에 실패해 직전 실적으로 계산했습니다)" : "");
  } else {
    $("#m-pe-wrap").hidden = true;
    $("#m-pe-none").hidden = false;
  }

  $("#m-yahoo").href = "https://finance.yahoo.com/quote/" + d.sym;
  $("#modal").hidden = false;
}

/* ---------------------------------------------------- 이벤트 */
document.querySelectorAll("#f-idx .chip").forEach((c) => {
  c.onclick = () => {
    const v = c.dataset.v;
    if (S.idx.has(v) && S.idx.size > 1) S.idx.delete(v);
    else S.idx.add(v);
    document.querySelectorAll("#f-idx .chip").forEach((x) =>
      x.classList.toggle("on", S.idx.has(x.dataset.v)));
    render();
  };
});

$("#f-streak").onchange = (e) => { S.streak = +e.target.value; render(); };
$("#f-miny").onchange   = (e) => { S.minY   = +e.target.value; render(); };
$("#f-band").onchange   = (e) => { S.band   = e.target.value;  render(); };
$("#f-pe").onchange     = (e) => { S.maxPE  = +e.target.value; render(); };
$("#f-peband").onchange = (e) => { S.peBand = e.target.value;  render(); };
$("#f-moat").onchange   = (e) => { S.moat   = e.target.value;  render(); };
$("#f-trap").onchange   = (e) => { S.trap   = e.target.checked; render(); };
$("#f-hasspe").onchange = (e) => { S.hasPE  = e.target.checked; render(); };

let t = null;
$("#f-q").oninput = (e) => {
  clearTimeout(t);
  t = setTimeout(() => { S.q = e.target.value; render(); }, 180);
};

const ASC_FIRST = ["name", "sec", "pe", "pe50", "pepct"];
document.querySelectorAll("th.s").forEach((th) => {
  th.onclick = () => {
    const k = th.dataset.key;
    S.dir = S.sort === k ? -S.dir : (ASC_FIRST.includes(k) ? 1 : -1);
    S.sort = k;
    render();
  };
});

$("#btn-reset").onclick = () => {
  S = { ...DEFAULTS, idx: new Set(DEFAULTS.idx) };
  syncControls();
  render();
};

$("#btn-csv").onclick = () => {
  const rows = view();
  const head = ["티커", "종목명", "주가", "현재배당수익률", "10년중앙수익률", "수익률백분위", "배당밴드",
                "현재PER", "10년중앙PER", "10년평균PER", "PER백분위", "PER밴드", "최근12개월EPS",
                "배당증가유지기간", "해자", "밴드계산기간", "섹터"];
  const body = rows.map((d) => [
    d.sym, `"${d.name}"`, d.px, d.y, d.y50,
    d.pct, (BAND[String(d.band)] || BAND["0"]).label,
    has(d.pe) ? d.pe : "", has(d.pe50) ? d.pe50 : "", has(d.peavg) ? d.peavg : "",
    has(d.pepct) ? d.pepct : "",
    hasPE(d) ? (BAND[String(d.peband)] || BAND["0"]).label : "",
    has(d.peps) ? d.peps : "",
    d.streak, d.moat || (isETF(d) ? "" : "미평가"),
    d.yrs, `"${d.sec}"`].join(","));
  const blob = new Blob(["\uFEFF" + [head.join(","), ...body].join("\n")],
    { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "dividend_screener.csv";
  a.click();
};

document.querySelectorAll("[data-close]").forEach((x) => {
  x.onclick = () => { $("#modal").hidden = true; };
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#modal").hidden = true;
});

syncControls();
load();
