/* rawpick 프론트엔드 — 그리드 셀렉 + 키보드 별점 + 뷰어 */
"use strict";

const $ = (s) => document.querySelector(s);
const grid = $("#grid");
const viewer = $("#viewer");

let photos = [];        // 서버 원본 목록
let view = [];          // 필터 적용된 목록
let selected = new Set();
let anchor = null;      // shift 범위선택 기준 (photo id)
let cursor = null;      // 키보드 커서 (photo id)
let viewerOpen = false;
let currentFolder = localStorage.getItem("rawpick.folder") || "";
let pollTimer = null;

$("#folderInput").value = currentFolder;

/* ---------- API ---------- */
async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function scan() {
  const folder = $("#folderInput").value.trim();
  if (!folder) return;
  currentFolder = folder;
  localStorage.setItem("rawpick.folder", folder);
  try {
    const res = await api("/api/scan", { folder });
    $("#progressWrap").hidden = false;
    startPolling();
    await loadPhotos();
  } catch (e) {
    alert("스캔 실패: " + e.message);
  }
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const p = await api(`/api/progress?folder=${encodeURIComponent(currentFolder)}`);
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 100;
    $("#progressBar").style.width = pct + "%";
    $("#progressText").textContent = p.state === "done" ? "완료" : `${p.done}/${p.total}`;
    if (p.state === "done" || p.state === "idle") {
      clearInterval(pollTimer);
      setTimeout(() => { $("#progressWrap").hidden = true; }, 1500);
      await loadPhotos();
    } else if (p.done > 0 && p.done % 50 === 0) {
      await loadPhotos(); // 중간중간 갱신
    }
  }, 1000);
}

async function loadPhotos() {
  if (!currentFolder) return;
  photos = await api(`/api/photos?folder=${encodeURIComponent(currentFolder)}`);
  applyFilter();
}

/* ---------- 필터/렌더 ---------- */
function applyFilter() {
  const minR = +$("#ratingFilter").value;
  const flagOnly = $("#flagFilter").checked;
  const hideRej = $("#hideRejected").checked;
  view = photos.filter(p =>
    p.rating >= minR &&
    (!flagOnly || p.cull_flag) &&
    (!hideRej || !p.rejected));
  render();
}

function starStr(n) { return n ? "★".repeat(n) : ""; }

function render() {
  const frag = document.createDocumentFragment();
  for (const p of view) {
    const cell = document.createElement("div");
    cell.className = "cell" + (selected.has(p.id) ? " selected" : "") + (p.rejected ? " rejected" : "");
    cell.dataset.id = p.id;
    const flagHtml = p.cull_flag ? `<span class="flag ${p.cull_flag}">${p.cull_flag === "blurry" ? "흐림" : "핀아웃"}</span>` : "";
    const labelHtml = p.color_label ? `<span class="labeldot ${p.color_label}"></span>` : "";
    const rejHtml = p.rejected ? `<span class="rejmark">✕</span>` : "";
    cell.innerHTML = `
      <img src="/api/thumb/${p.id}" loading="lazy" draggable="false">
      <div class="name">${p.filename}</div>
      <div class="badges"><span class="stars">${starStr(p.rating)}</span>${labelHtml}${flagHtml}${rejHtml}</div>`;
    frag.appendChild(cell);
  }
  grid.replaceChildren(frag);
  $("#counter").textContent = `${view.length} / ${photos.length}장 · 선택 ${selected.size}`;
}

function updateCells(ids) {
  for (const id of ids) {
    const p = photos.find(x => x.id === id);
    const cell = grid.querySelector(`.cell[data-id="${id}"]`);
    if (!p || !cell) continue;
    cell.classList.toggle("selected", selected.has(id));
    cell.classList.toggle("rejected", !!p.rejected);
    cell.querySelector(".stars").textContent = starStr(p.rating);
    const badges = cell.querySelector(".badges");
    badges.querySelector(".labeldot")?.remove();
    badges.querySelector(".rejmark")?.remove();
    if (p.color_label) {
      const d = document.createElement("span");
      d.className = "labeldot " + p.color_label;
      badges.appendChild(d);
    }
    if (p.rejected) {
      const d = document.createElement("span");
      d.className = "rejmark"; d.textContent = "✕";
      badges.appendChild(d);
    }
  }
  $("#counter").textContent = `${view.length} / ${photos.length}장 · 선택 ${selected.size}`;
}

/* ---------- 선택 ---------- */
grid.addEventListener("click", (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  const id = +cell.dataset.id;
  const prev = new Set(selected);
  if (e.shiftKey && anchor !== null) {
    const ai = view.findIndex(p => p.id === anchor);
    const bi = view.findIndex(p => p.id === id);
    if (ai >= 0 && bi >= 0) {
      if (!e.ctrlKey) selected.clear();
      for (let i = Math.min(ai, bi); i <= Math.max(ai, bi); i++) selected.add(view[i].id);
    }
  } else if (e.ctrlKey) {
    selected.has(id) ? selected.delete(id) : selected.add(id);
    anchor = id;
  } else {
    selected.clear(); selected.add(id); anchor = id;
  }
  cursor = id;
  updateCells(new Set([...prev, ...selected]));
});

grid.addEventListener("dblclick", (e) => {
  const cell = e.target.closest(".cell");
  if (cell) openViewer(+cell.dataset.id);
});

/* ---------- 별점/라벨/리젝트 ---------- */
function targets() {
  if (selected.size) return [...selected];
  return cursor !== null ? [cursor] : [];
}

async function setRating(r) {
  const ids = targets();
  if (!ids.length) return;
  ids.forEach(id => { const p = photos.find(x => x.id === id); if (p) p.rating = r; });
  updateCells(ids);
  if (viewerOpen) showViewerInfo();
  await api("/api/rating", { ids, rating: r });
}

const LABEL_KEYS = { 6: "red", 7: "yellow", 8: "green", 9: "blue" };
async function setLabel(label) {
  const ids = targets();
  if (!ids.length) return;
  ids.forEach(id => { const p = photos.find(x => x.id === id); if (p) p.color_label = (p.color_label === label ? "" : label); });
  const newLabel = photos.find(x => x.id === ids[0])?.color_label ?? "";
  updateCells(ids);
  await api("/api/label", { ids, label: newLabel });
}

async function toggleReject() {
  const ids = targets();
  if (!ids.length) return;
  const first = photos.find(x => x.id === ids[0]);
  const val = first ? !first.rejected : true;
  ids.forEach(id => { const p = photos.find(x => x.id === id); if (p) p.rejected = val ? 1 : 0; });
  updateCells(ids);
  if (viewerOpen) showViewerInfo();
  await api("/api/reject", { ids, rejected: val });
}

/* ---------- 뷰어 ---------- */
function openViewer(id) {
  cursor = id; viewerOpen = true;
  viewer.hidden = false;
  showViewerImg();
}
function closeViewer() { viewerOpen = false; viewer.hidden = true; }

function showViewerImg() {
  $("#viewerImg").src = `/api/preview/${cursor}`;
  showViewerInfo();
  // 프리로드
  const i = view.findIndex(p => p.id === cursor);
  for (const j of [i + 1, i - 1]) {
    if (view[j]) { const im = new Image(); im.src = `/api/preview/${view[j].id}`; }
  }
}

function showViewerInfo() {
  const p = photos.find(x => x.id === cursor);
  if (!p) return;
  const m = p.meta || {};
  const exif = [m.camera, m.focal, m.aperture, m.shutter, m.iso ? "ISO" + m.iso : null]
    .filter(Boolean).join(" · ");
  const idx = view.findIndex(x => x.id === cursor);
  $("#viewerInfo").innerHTML =
    `<b>${p.filename}</b> (${idx + 1}/${view.length})<br>` +
    `<span class="stars">${starStr(p.rating) || "☆"}</span> ` +
    (p.rejected ? '<span class="rejmark">✕ 리젝트</span> ' : "") +
    (p.cull_flag ? `<span class="flag ${p.cull_flag}">${p.cull_flag === "blurry" ? "흐림" : "핀아웃"}</span> ` : "") +
    `<br><span style="color:var(--dim)">${exif}</span>`;
}

function move(delta) {
  const i = view.findIndex(p => p.id === cursor);
  const ni = Math.max(0, Math.min(view.length - 1, (i < 0 ? 0 : i + delta)));
  if (!view[ni]) return;
  const prev = new Set(selected);
  cursor = view[ni].id;
  selected.clear(); selected.add(cursor); anchor = cursor;
  updateCells(new Set([...prev, cursor]));
  if (viewerOpen) showViewerImg();
  else grid.querySelector(`.cell[data-id="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
}

/* ---------- 키보드 ---------- */
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" && e.target.type === "text") {
    if (e.key === "Enter") scan();
    return;
  }
  if (e.key >= "0" && e.key <= "5") { setRating(+e.key); e.preventDefault(); }
  else if (LABEL_KEYS[e.key]) { setLabel(LABEL_KEYS[e.key]); e.preventDefault(); }
  else if (e.key === "x" || e.key === "X") { toggleReject(); e.preventDefault(); }
  else if (e.key === "ArrowRight") { move(1); e.preventDefault(); }
  else if (e.key === "ArrowLeft") { move(-1); e.preventDefault(); }
  else if (e.key === "ArrowDown" && !viewerOpen) { move(colCount()); e.preventDefault(); }
  else if (e.key === "ArrowUp" && !viewerOpen) { move(-colCount()); e.preventDefault(); }
  else if (e.key === "Enter" && !viewerOpen) { if (cursor !== null) openViewer(cursor); e.preventDefault(); }
  else if (e.key === "Escape") { viewerOpen ? closeViewer() : (selected.clear(), render()); }
  else if ((e.key === "a" || e.key === "A") && !e.ctrlKey) {
    view.forEach(p => selected.add(p.id)); render(); e.preventDefault();
  }
});

function colCount() {
  const style = getComputedStyle(grid);
  return style.gridTemplateColumns.split(" ").length || 1;
}

viewer.addEventListener("click", (e) => { if (e.target === viewer) closeViewer(); });

/* ---------- AI 셀렉 ---------- */
async function aiSelect() {
  if (!currentFolder) { alert("먼저 폴더를 스캔하세요"); return; }
  const target = +$("#targetInput").value || 1500;
  if (!confirm(`AI 셀렉을 실행하면 기존 별점을 덮어씁니다.\n목표 ${target}장 = ★3 / 차점 ★2 / 통과 ★1 / 불량 0\n진행할까요?`)) return;
  await api("/api/autoselect", { folder: currentFolder, target });
  $("#progressWrap").hidden = false;
  const timer = setInterval(async () => {
    const p = await api(`/api/autoselect/progress?folder=${encodeURIComponent(currentFolder)}`);
    if (p.state === "done") {
      clearInterval(timer);
      $("#progressText").textContent = "완료";
      setTimeout(() => { $("#progressWrap").hidden = true; }, 1500);
      await loadPhotos();
      alert(`AI 셀렉 완료\n★3 선발 ${p.star3}장 · ★2 차점 ${p.star2}장 · ★1 통과 ${p.star1}장 · 불량 ${p.flagged}장\n(연사그룹 ${p.groups}개)`);
    } else if (p.state === "error") {
      clearInterval(timer);
      $("#progressWrap").hidden = true;
      alert("AI 셀렉 실패: " + p.msg);
    } else {
      const label = { loading_model: "모델 로딩", scoring: "점수 계산", exposure: "노출 분석", ranking: "선발", writing: "기록" }[p.state] || p.state;
      const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
      $("#progressBar").style.width = pct + "%";
      $("#progressText").textContent = `${label} ${p.done || 0}/${p.total || 0}`;
    }
  }, 1000);
}

/* ---------- 컨트롤 ---------- */
$("#scanBtn").addEventListener("click", scan);
$("#aiBtn").addEventListener("click", aiSelect);
$("#ratingFilter").addEventListener("change", applyFilter);
$("#flagFilter").addEventListener("change", applyFilter);
$("#hideRejected").addEventListener("change", applyFilter);
$("#thumbSize").addEventListener("input", (e) => {
  document.documentElement.style.setProperty("--thumb", e.target.value + "px");
});

if (currentFolder) loadPhotos().catch(() => {});
