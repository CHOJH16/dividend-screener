const DATA_FILE = "data/screener_us.json";

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
  sort: "pct", dir: -1,
};

let ALL = [];
let S = { ...DEFAULTS, idx: new Set(DEFAULTS.idx) };

const $ = (s) => document.querySelector(s);
const fmtP = (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtY = (v) => Number(v).toFixed(2) + "%";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------------------------------------------- 상태 → 화면 동기화 */
function syncControls() {
  $("#f-streak").value = String(S.streak);
  $("#f-miny").value   = String(S.minY);
  $("#f-band").value   = S.band;
  $("#f-moat").value   = S.moat;
  $("#f-q").value      = S.q;
  $("#f-trap").checked = S.trap;
  document.querySelectorAll("#f-idx .chip").forEach((x) =>
    x.classList.toggle("on", S.idx.has(x.dataset.v)));

  if ($("#f-streak").value === "") { S.streak = 0;     $("#f-streak").value = "0"; }
  if ($("#f-miny").value   === "") { S.minY   = 0;     $("#f-miny").value   = "0"; }
  if ($("#f-band").value   === "") { S.band   = "all"; $("#f-band").value   = "all"; }
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
    '<tr><td colspan="8" class="empty">' + title +
    '<br><small style="opacity:.7">' + String(detail || "").slice(0, 200) + "</small><br><br>" +
    '<button type="button" id="btn-retry" class="ghost">다시 시도</button></td></tr>';
  const b = $("#btn-retry");
  if (b) b.onclick = () => {
    $("#tbody").innerHTML = '<tr><td colspan="8" class="empty">다시 불러오는 중입니다…</td></tr>';
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

/* ---------------------------------------------------- 해자 표시 */
function moatRank(d) {
  if (d.moat && MOAT[d.moat]) return MOAT[d.moat].rank;
  if (d.qmoat != null) return d.qmoat >= 0.7 ? 2.5 : d.qmoat >= 0.3 ? 1.5 : 0.5;
  return 0;
}

function moatCell(d) {
  const m = MOAT[d.moat];
  if (m) return `<span class="badge ${m.cls}">${m.label}</span>`;
  if (d.qmoat != null) {
    const q = Number(d.qmoat);
    const lab = q >= 0.7 ? "넓음" : q >= 0.3 ? "좁음" : "없음";
    return `<span class="badge moat-quant" title="애널리스트 등급이 없어 모닝스타 퀀트 모델 값(${q.toFixed(2)})으로 추정한 값입니다">${lab}?</span>`;
  }
  return '<span class="moat-na">-</span>';
}

/* ---------------------------------------------------- 필터 + 정렬 */
function view() {
  const q = S.q.trim().toLowerCase();
  const minStreak = Number(S.streak) || 0;
  const minY = Number(S.minY) || 0;

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
    if (q && !((d.sym || "").toLowerCase().includes(q) ||
               (d.name || "").toLowerCase().includes(q) ||
               (d.sec || "").toLowerCase().includes(q))) return false;
    return true;
  });

  const k = S.sort;
  rows.sort((a, b) => {
    if (k === "moat") return (moatRank(a) - moatRank(b)) * S.dir;
    const x = a[k], y = b[k];
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
      '<tr><td colspan="8" class="empty">조건에 맞는 종목이 없습니다. 필터를 완화해 보세요.</td></tr>';
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

  let moatTxt = "해자 정보 없음";
  if (d.moat && MOAT[d.moat]) {
    moatTxt = "해자 " + MOAT[d.moat].label;
  } else if (d.qmoat != null) {
    moatTxt = `해자 추정 ${Number(d.qmoat).toFixed(2)} (퀀트)`;
  }

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
$("#f-moat").onchange   = (e) => { S.moat   = e.target.value;  render(); };
$("#f-trap").onchange   = (e) => { S.trap   = e.target.checked; render(); };

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
  const head = ["티커", "종목명", "주가", "현재배당수익률", "10년중앙", "백분위", "밴드",
                "배당증가유지기간", "해자", "퀀트해자", "밴드계산기간", "섹터"];
  const body = rows.map((d) => [d.sym, `"${d.name}"`, d.px, d.y, d.y50,
    d.pct, (BAND[String(d.band)] || BAND["0"]).label, d.streak,
    d.moat || "", d.qmoat != null ? d.qmoat : "",
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
