const DATA_URL = "./data/screener_us.json";

const BAND = {
  "-2": { label: "매우 고평가", cls: "b--2" },
  "-1": { label: "고평가",     cls: "b--1" },
  "0":  { label: "중립",       cls: "b-0"  },
  "1":  { label: "저평가",     cls: "b-1"  },
  "2":  { label: "매우 저평가", cls: "b-2"  },
};

/* 이력이 이 값보다 짧으면 '짧은 이력'으로 보고 딱지를 붙인다 */
const FULL_HISTORY = 9.5;

/* 기본 필터값 — 여기만 고치면 화면도 자동으로 따라간다 */
const DEFAULTS = {
  idx: ["SP500", "NDX100"], streak: 10, minY: 0,
  band: "all", q: "", trap: true, hist: false,
  sort: "pct", dir: -1,
};

let ALL = [];
let S = { ...DEFAULTS, idx: new Set(DEFAULTS.idx) };

const $ = (s) => document.querySelector(s);
const fmtP = (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtY = (v) => v.toFixed(2) + "%";

/* ---------------------------------------------------- 상태 → 화면 동기화
   시작할 때와 초기화할 때 내부 값을 화면 컨트롤에 그대로 찍어준다.
   이렇게 해야 '화면엔 10년인데 실제로는 5년으로 걸러지는' 일이 없다. */
function syncControls() {
  $("#f-streak").value = String(S.streak);
  $("#f-miny").value   = String(S.minY);
  $("#f-band").value   = S.band;
  $("#f-q").value      = S.q;
  $("#f-trap").checked = S.trap;
  $("#f-hist").checked = S.hist;
  document.querySelectorAll("#f-idx .chip").forEach((x) =>
    x.classList.toggle("on", S.idx.has(x.dataset.v)));

  /* 드롭다운에 해당 값이 없으면 값이 비어버리므로 안전장치를 둔다 */
  if ($("#f-streak").value === "") { S.streak = 0; $("#f-streak").value = "0"; }
  if ($("#f-miny").value   === "") { S.minY   = 0; $("#f-miny").value   = "0"; }
  if ($("#f-band").value   === "") { S.band   = "all"; $("#f-band").value = "all"; }
}

/* ---------------------------------------------------- 데이터 로드 */
async function load() {
  try {
    const res = await fetch(DATA_URL + "?t=" + Date.now());
    if (!res.ok) throw new Error(res.status);
    const json = await res.json();
    ALL = json.items || [];
    $("#updated").textContent = json.updated || "-";
    $("#cnt-all").textContent = ALL.length;
    render();
  } catch (e) {
    $("#updated").textContent = "불러오기 실패";
    $("#tbody").innerHTML =
      '<tr><td colspan="7" class="empty">데이터 파일이 아직 없습니다.<br>' +
      'GitHub의 Actions 탭에서 update-and-deploy 워크플로를 한 번 실행해 주세요.</td></tr>';
  }
}

/* ---------------------------------------------------- 필터 + 정렬 */
function view() {
  const q = S.q.trim().toLowerCase();
  const minStreak = Number(S.streak) || 0;
  const minY = Number(S.minY) || 0;

  let rows = ALL.filter((d) => {
    if (!d.idx.some((i) => S.idx.has(i))) return false;
    if (minStreak > 0 && Number(d.streak) < minStreak) return false;
    if (minY > 0 && Number(d.y) < minY) return false;
    if (S.trap && d.y > 15) return false;
    if (S.hist && d.yrs < FULL_HISTORY) return false;
    if (S.band === "cheap" && d.pct < 70) return false;
    if (S.band === "verycheap" && d.pct < 90) return false;
    if (S.band === "notrich" && d.pct < 30) return false;
    if (q && !(d.sym.toLowerCase().includes(q) ||
               d.name.toLowerCase().includes(q) ||
               d.sec.toLowerCase().includes(q))) return false;
    return true;
  });

  const k = S.sort;
  rows.sort((a, b) => {
    let x = a[k], y = b[k];
    if (typeof x === "string") return x.localeCompare(y) * S.dir;
    return (x - y) * S.dir;
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
      '<tr><td colspan="7" class="empty">조건에 맞는 종목이 없습니다. 필터를 완화해 보세요.</td></tr>';
    return;
  }

  $("#tbody").innerHTML = rows.map((d) => {
    const b = BAND[String(d.band)];
    const tags = [];
    if (d.idx.includes("DIVETF")) tags.push("ETF");
    else if (d.idx.includes("SP500") && d.idx.includes("NDX100")) tags.push("S&P·NDX");
    else if (d.idx.includes("NDX100")) tags.push("NDX");
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
          <div class="mini"><i style="left:${d.pct}%"></i></div>
          <span class="pnum">${Math.round(d.pct)}%</span>
          <span class="badge ${b.cls}">${b.label}</span>
        </div>
      </td>
      <td class="r">${d.streak}년</td>
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
  const b = BAND[String(d.band)];

  $("#m-name").textContent = d.name;
  $("#m-sym").textContent = `${d.sym} · ${d.sec} · 배당 증가(유지) ${d.streak}년 · 밴드 계산 기간 ${d.yrs}년`;
  $("#m-badge").textContent = b.label;
  $("#m-badge").className = "badge " + b.cls;
  $("#m-px").textContent = fmtP(d.px);
  $("#m-ttm").textContent = "$" + d.ttm.toFixed(2);
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
                 : "평균적인 구간입니다.") +
    (d.yrs < FULL_HISTORY ? " 다만 데이터 기간이 10년보다 짧아 밴드 신뢰도가 낮습니다." : "");
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
$("#f-trap").onchange   = (e) => { S.trap   = e.target.checked; render(); };
$("#f-hist").onchange   = (e) => { S.hist   = e.target.checked; render(); };

let t = null;
$("#f-q").oninput = (e) => {
  clearTimeout(t);
  t = setTimeout(() => { S.q = e.target.value; render(); }, 180);
};

document.querySelectorAll("th.s").forEach((th) => {
  th.onclick = () => {
    const k = th.dataset.key;
    S.dir = S.sort === k ? -S.dir : (["name", "sec"].includes(k) ? 1 : -1);
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
  const head = ["티커", "종목명", "주가", "현재배당수익률", "10년중앙", "백분위", "밴드", "배당증가유지기간", "밴드계산기간", "섹터"];
  const body = rows.map((d) => [d.sym, `"${d.name}"`, d.px, d.y, d.y50,
    d.pct, BAND[String(d.band)].label, d.streak, d.yrs, `"${d.sec}"`].join(","));
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

/* 화면을 내부 값에 맞춘 다음 데이터를 읽는다 */
syncControls();
load();
