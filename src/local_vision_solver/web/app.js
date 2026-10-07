"use strict";
function consumePairingToken() { const token=new URLSearchParams(location.hash.slice(1)).get("pair"); if(token) history.replaceState(null,"",location.pathname); return token; }
const initialPairingToken=consumePairingToken();
const $ = id => document.getElementById(id);
const MiB = 1024 * 1024;
const stages = {
  RECEIVING: [0, "Отправляем страницы"], QUEUED: [0, "Задача в очереди"],
  VALIDATING_IMAGES: [0, "Проверяем качество фото"], UNDERSTANDING: [1, "Читаем задание"],
  UNDERSTANDING_RETRY: [1, "Уточняем неясные символы"], SOLVING: [2, "Решаем задачу"],
  VERIFYING: [3, "Проверяем решение"], VERIFYING_INDEPENDENT: [3, "Независимо проверяем ответ"],
  VERIFYING_AUDIT: [3, "Сверяем с исходными фото"], CORRECTING: [3, "Исправляем решение"],
  RUNNING: [1, "Обрабатываем задачу"], ANSWER_READY: [4, "Проверенный текст готов"], PACKAGING: [4, "Упаковываем ответ"], RENDERING: [4, "Готовим карточки"], SENDING: [4, "Упаковываем ответ"]
};
let state = freshState(), health = null, online = false, running = false, epoch = 0;
let previews = [], previewIndex = -1, previewURL = null, fallbackURL = null, previewAbort = null;
let dbPromise = null, saveChain = Promise.resolve(), toastTimer;
const urls = new Set();
function uuid() {
  // randomUUID requires HTTPS; getRandomValues is available on a local HTTP page.
  const b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
  return [...b].map((v, i) => ([4, 6, 8, 10].includes(i) ? "-" : "") + v.toString(16).padStart(2, "0")).join("");
}
function freshState() { return { version: 2, id: uuid(), pages: [], phase: "draft", created: false, started: null }; }
function el(tag, text, className) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; }
function objectURL(blob) { const url = URL.createObjectURL(blob); urls.add(url); return url; }
function releaseURL(url) { if (url) { URL.revokeObjectURL(url); urls.delete(url); } }
function closePreview() { previewAbort?.abort(); releaseURL(previewURL); releaseURL(fallbackURL); previewURL = fallbackURL = null; }
function changedPhotos() { if (state.created) { const old = state.id; if (["draft","uploading"].includes(state.phase)) api(`/v1/sessions/${old}`, {method:"DELETE"}).catch(() => {}); epoch++; state.id = uuid(); state.created = false; state.phase = "draft"; state.started = null; } }
function current(token, id) { return token === epoch && id === state.id; }
function pairingRequired() { error("Сопряжение истекло. На ноутбуке откройте «Подключить телефон» и отсканируйте новый QR."); $("processing").hidden = true; $("composer").hidden = false; }
function toast(text) { $("toast").textContent = text; $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").hidden = true, 3500); }
function error(text, retry = false) { $("error-message").textContent = text; $("error").hidden = !text; $("retry").hidden = !retry; }
function database() {
  if (!dbPromise) dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open("vision-local", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("tasks");
    req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
  });
  return dbPromise;
}
async function storage(action, value) {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("tasks", action === "get" ? "readonly" : "readwrite");
    const req = action === "get" ? tx.objectStore("tasks").get("active") : tx.objectStore("tasks").put(value, "active");
    tx.oncomplete = () => resolve(req.result); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
  });
}
function persist() {
  const snapshot = { ...state, pages: state.pages.map(p => ({ file: p.file })) };
  saveChain = saveChain.catch(() => {}).then(() => storage("put", snapshot)).catch(() => toast("Браузер не сохранил задачу. Не закрывайте вкладку до получения ответа."));
  return saveChain;
}
async function api(path, options = {}) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: "no-store" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const detail = typeof payload.detail === "string" ? payload.detail : `Ошибка сервера ${response.status}`;
      const failure = new Error(detail); failure.status = response.status; failure.retryAfter = Math.min(60, Number(response.headers.get("Retry-After")) || 0); throw failure;
    }
    return response.status === 204 ? null : options.asText ? await response.text() : await response.json();
  } catch (e) {
    if (e instanceof TypeError || e.name === "AbortError") throw new Error("Связь с ноутбуком потеряна. Проверьте Wi-Fi и запущенную программу, затем повторите.");
    throw e;
  } finally { clearTimeout(timer); }
}
function json(body) { return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }; }
async function checkHealth() {
  try {
    health = await api("/health"); online = health.demo || health.model === "ready";
    $("demo-notice").hidden = !health.demo;
    $("connection-label").textContent = health.demo ? "Ноутбук подключён · проверка доставки" : online ? "Ноутбук подключён · Qwen готов" : health.model === "loading" ? "Ноутбук подключён · модель загружается" : "Ноутбук подключён · модель недоступна";
  } catch (_) { online = false; $("connection-label").textContent = "Нет связи с ноутбуком"; }
  $("connection-status").classList.toggle("offline", !online); $("reconnect").hidden = online; updateButtons();
}
function updateButtons() {
  $("solve").disabled = !state.pages.length || !online || running;
  $("new-task").disabled = false;
  $("camera-button").disabled = running; $("files-button").disabled = running;
}
function renderPages() {
  $("pages").replaceChildren(); $("empty-state").hidden = !!state.pages.length;
  state.pages.forEach((page, index) => {
    const item = el("li", null, "page"); const img = el("img", null, "page-image");
    img.alt = `Страница ${index + 1}`; img.src = page.url || (page.url = objectURL(page.file));
    img.onerror = () => { const fallback = el("div", "HEIC · оригинал сохранён", "page-placeholder"); img.replaceWith(fallback); };
    img.addEventListener("click", () => openPreview(page.file, index));
    const bar = el("div", null, "page-bar"); bar.append(el("strong", `Страница ${index + 1}`));
    const controls = el("div", null, "page-controls");
    for (const [label, symbol, move] of [["Переместить выше", "↑", -1], ["Переместить ниже", "↓", 1], ["Удалить страницу", "×", 0]]) {
      const button = el("button", symbol, "icon-button"); button.type = "button"; button.setAttribute("aria-label", `${label} ${index + 1}`);
      button.disabled = running || (move && (index + move < 0 || index + move >= state.pages.length));
      button.onclick = () => { changedPhotos(); if (move) [state.pages[index], state.pages[index + move]] = [state.pages[index + move], state.pages[index]]; else { releaseURL(state.pages[index].url); state.pages.splice(index, 1); } renderPages(); persist(); };
      controls.append(button);
    }
    bar.append(controls); item.append(img, bar, el("div", `${page.file.name} · ${(page.file.size / MiB).toFixed(1)} МБ`, "page-size")); $("pages").append(item);
  });
  $("page-summary").textContent = state.pages.length ? `${state.pages.length} стр. · ${(state.pages.reduce((n,p) => n + p.file.size, 0) / MiB).toFixed(1)} МБ · исходное качество` : "JPEG, PNG, HEIC · исходное качество";
  updateButtons();
}
async function openPreview(file, index = -1) {
  const operationEpoch = epoch, sessionId = state.id; closePreview(); previewIndex = index; previewAbort = new AbortController();
  const currentOperation = () => operationEpoch === epoch && sessionId === state.id;
  const current = previewAbort; previewURL = objectURL(file);
  $("preview-media").replaceChildren(); $("accept-photo").hidden = index >= 0; $("reject-photo").hidden = index >= 0; $("accept-photo").disabled = false;
  const img = el("img"); img.alt = "Предпросмотр страницы"; img.src = previewURL; $("preview-media").append(img);
  if (!$("preview-dialog").open) $("preview-dialog").showModal();
  img.onerror = async () => {
    img.onerror = null; $("accept-photo").disabled = true;
    $("preview-media").replaceChildren(el("div", "Готовим локальный предпросмотр…", "preview-fallback"));
    try {
      const response = await fetch("/preview", { method: "POST", body: file, signal: current.signal });
      if (!response.ok) throw new Error("Этот снимок не удалось прочитать. Выберите JPEG, PNG или HEIC с чётким текстом.");
      const blob = await response.blob(); if (current.signal.aborted || !currentOperation()) return;
      fallbackURL = objectURL(blob); img.src = fallbackURL; $("preview-media").replaceChildren(img); $("accept-photo").disabled = false;
    } catch (e) { if (e.name !== "AbortError") $("preview-media").replaceChildren(el("div", e.message, "preview-fallback")); }
  };
}
function nextPreview() { if (previews.length) openPreview(previews[0]); else { closePreview(); $("preview-dialog").close(); } }
function chooseFiles(files) {
  if (running) return;
  const maximum = health?.max_pages || 12, maxFile = health?.max_page_megabytes || 60, maxTotal = health?.max_input_megabytes || 300;
  const chosen = Array.from(files); error("");
  if (!chosen.length) return;
  if (state.pages.length + chosen.length > maximum) return error(`В одной задаче максимум ${maximum} страниц.`);
  if (chosen.some(f => !/\.(jpe?g|png|hei[cf]|webp)$/i.test(f.name))) return error("Выберите фото JPEG, PNG, HEIC/HEIF или WebP.");
  if (chosen.some(f => !f.size || f.size > maxFile * MiB)) return error(`Максимум ${maxFile} МБ на фото. Пустые файлы не принимаются.`);
  if ([...state.pages.map(p => p.file), ...chosen].reduce((n,f) => n + f.size, 0) > maxTotal * MiB) return error(`В одной задаче максимум ${maxTotal} МБ.`);
  previews = chosen; nextPreview();
}
$("accept-photo").onclick = () => { changedPhotos(); state.pages.push({ file: previews.shift() }); renderPages(); persist(); nextPreview(); };
$("reject-photo").onclick = () => { previews.shift(); nextPreview(); };
$("close-preview").onclick = () => { previews = []; closePreview(); $("preview-dialog").close(); };
$("preview-dialog").addEventListener("cancel", () => { previews = []; closePreview(); });
$("camera-button").onclick = () => $("camera-input").click(); $("files-button").onclick = () => $("files-input").click();
for (const id of ["camera-input", "files-input"]) $(id).onchange = () => { chooseFiles($(id).files); $(id).value = ""; };
function stage(code, detail) {
  const [index, label] = stages[code] || [1, "Обрабатываем задачу"];
  $("stage-label").textContent = label;
  $("stage-detail").textContent = detail || (code === "QUEUED" ? "Ноутбук завершает предыдущую задачу. Вы можете оставить эту страницу открытой." : "Полное решение проходит проверку. Если вкладка закроется, откройте сайт снова.");
  [...$("stages").children].forEach((n,i) => { n.classList.toggle("done", i < index); n.classList.toggle("current", i === index); });
}
function elapsed() {
  if (!state.started || $("processing").hidden) return;
  const s = Math.round((Date.now() - state.started) / 1000);
  $("elapsed").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2,"0")} · ${s > 60 ? "Задача занимает больше минуты. Проверка не пропускается ради скорости." : "Время зависит от сложности и количества страниц."}`;
}
function upload(number, file, token, sessionId) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); xhr.open("PUT", `/v1/sessions/${sessionId}/pages/${number}`); xhr.timeout = 180000;
    xhr.upload.onprogress = e => { if (token === epoch && e.lengthComputable) stage("RECEIVING", `Страница ${number} из ${state.pages.length} · ${Math.round(e.loaded / e.total * 100)}%`); };
    xhr.onload = () => { if (xhr.status >= 200 && xhr.status < 300) resolve(); else { let detail = `Ошибка загрузки ${xhr.status}`; try { detail = JSON.parse(xhr.responseText).detail || detail; } catch (_) {} const e = new Error(typeof detail === "string" ? detail : "Не удалось загрузить страницу"); e.status = xhr.status; reject(e); } };
    xhr.onerror = xhr.ontimeout = () => reject(new Error("Загрузка прервана. Проверьте связь и повторите — уже загруженные страницы сохраняются.")); xhr.send(file);
  });
}
async function solve() {
  if (running || !state.pages.length || !online) return;
  if (["complete","failed"].includes(state.phase)) { state.id = uuid(); state.created = false; state.started = null; }
  const operationEpoch = epoch, sessionId = state.id, pages = state.pages.slice();
  error(""); running = true; state.phase = "uploading"; state.started ||= Date.now();
  $("composer").hidden = true; $("result").hidden = true; $("processing").hidden = false; $("resume").hidden = true; updateButtons(); stage("RECEIVING");
  try {
    await persist(); if (!current(operationEpoch,sessionId)) return;
    await api("/v1/sessions", json({ session_id: sessionId })); if (!current(operationEpoch,sessionId)) { api(`/v1/sessions/${sessionId}`,{method:"DELETE"}).catch(()=>{}); return; }
    state.created = true; await persist(); if (!current(operationEpoch,sessionId)) return;
    for (let i=0; i<pages.length; i++) { await upload(i+1,pages[i].file,operationEpoch,sessionId); if (!current(operationEpoch,sessionId)) return; }
    await api(`/v1/sessions/${sessionId}/solve`,json({page_count:pages.length,page_order:pages.map((_,i)=>i+1)})); if (!current(operationEpoch,sessionId)) return;
    state.phase = "processing"; await persist(); if (!current(operationEpoch,sessionId)) return;
    await poll(operationEpoch,sessionId);
  } catch (e) {
    if (!current(operationEpoch,sessionId)) return;
    if (e.status === 401) pairingRequired();
    else {
      error(e.message,true); $("processing").hidden = true; $("composer").hidden = false;
      if ([404,409,422].includes(e.status)) { state.phase = "draft"; state.created = false; state.id = uuid(); }
    }
    await persist();
  } finally { if (operationEpoch === epoch) { running = false; renderPages(); } }
}
async function poll(operationEpoch,sessionId) {
  let statusFailures = 0, resultFailures = 0;
  while (current(operationEpoch,sessionId)) {
    let delay = 1500, fetchingResult = false;
    try {
      const status = await api(`/v1/sessions/${sessionId}`); if (!current(operationEpoch,sessionId)) return;
      statusFailures = 0;
      if (status.state === "ERROR") { state.phase = "failed"; await persist(); if (!current(operationEpoch,sessionId)) return; error(friendlyFailure(status.error),!!state.pages.length); $("processing").hidden=true; $("composer").hidden=false; return; }
      if (status.result_available) {
        fetchingResult = true;
        const answer = await api(`/v1/sessions/${sessionId}/result`); if (!current(operationEpoch,sessionId)) return;
        if (answer.session_id !== sessionId) throw new Error("Ответ принадлежит другой задаче");
        resultFailures = 0; state.phase = "complete"; await persist(); if (!current(operationEpoch,sessionId)) return;
        showResult(answer,sessionId,operationEpoch); return;
      }
      if (status.answer_available && status.output_error) {
        fetchingResult=true;
        const text=await api(`/v1/sessions/${sessionId}/answer.txt`,{asText:true}); if (!current(operationEpoch,sessionId)) return;
        state.phase = "answer_ready"; await persist(); if (!current(operationEpoch,sessionId)) return;
        showResult({session_id:sessionId,plain_text_answer:text,cards:[],warnings:[],demo:status.demo},sessionId,operationEpoch); tab(true);
        $("processing").hidden = true; $("result").hidden = false; $("answer-cards").replaceChildren();
        $("result-title").textContent = "Проверенный текст готов"; $("zip-download").hidden=true; $("text-download").href=`/v1/sessions/${sessionId}/answer.txt`;
        $("render-retry").hidden=false; error("Не удалось подготовить карточки. TXT доступен; повтор не запускает модель."); return;
      }
      error(""); stage(status.stage || status.state);
    } catch (e) {
      if (!current(operationEpoch,sessionId)) return;
      if (e.status===401) { pairingRequired(); return; }
      if (e.status===404) { state.id=uuid(); state.created=false; state.phase="draft"; await persist(); if (operationEpoch!==epoch) return; $("processing").hidden=true; $("composer").hidden=false; error("Сессия удалена. Фото сохранены в этой вкладке. Отправьте заново.",!!state.pages.length); $("retry").textContent="Отправить заново"; return; }
      const failures = fetchingResult ? ++resultFailures : ++statusFailures;
      error(e.message); delay = Math.max([1500,3000,6000][Math.min(failures-1,2)],(e.retryAfter||0)*1000);
      if (failures>=3) { $("resume").hidden=false; return; }
    }
    await new Promise(resolve=>setTimeout(resolve,delay));
  }
}
function friendlyFailure(e) {
  const labels = { interrupted: "Ноутбук перезапустился во время решения. Повторите задачу.", image_unreadable: "Снимок не удалось прочитать. Переснимите нужную страницу.", retake_required: "На снимке недостаточно информации. Переснимите нужную страницу.", model_unavailable: "Модель недоступна. Проверьте программу на ноутбуке." };
  return labels[e?.code] || `Не удалось завершить задачу. ${e?.message || "Повторите или создайте новую задачу."}`;
}
async function resume() {
  if (running) return; running = true; const token = epoch, sessionId = state.id; error(""); $("processing").hidden = false; $("composer").hidden = true; $("result").hidden=true; $("resume").hidden = true; updateButtons();
  try { await poll(token,sessionId); } finally { if (token === epoch) { running = false; updateButtons(); } }
}
function showResult(answer,sessionId,operationEpoch) {
  if (answer.session_id !== sessionId || !current(operationEpoch,sessionId)) return;
  $("zip-download").hidden=false; $("render-retry").hidden=true;
  $("processing").hidden = true; $("composer").hidden = true; $("result").hidden = false; error("");
  $("task-title").textContent = "Задача завершена";
  $("result-title").textContent = answer.demo ? "Проверка доставки завершена" : "Решение готово";
  const languages = {ru:"Русский",kk:"Қазақша",en:"English"};
  $("result-meta").textContent = `${languages[answer.detected_language] || answer.detected_language} · ${answer.cards.length} карточек${answer.demo ? " · без нейросети" : ""}`;
  const base = `/v1/sessions/${sessionId}`;
  $("zip-download").href = `${base}/package`; $("text-download").href = `${base}/answer.txt`;
  $("answer-text").textContent = answer.plain_text_answer;
  $("warnings").replaceChildren(); $("warnings").hidden = !answer.warnings?.length;
  for (const warning of answer.warnings || []) $("warnings").append(el("div", warning));
  $("answer-cards").replaceChildren();
  answer.cards.forEach((card,i) => {
    const article = el("article",null,"answer-card"); const img = el("img"); img.alt = `Карточка ${i+1}: ${card.section || "решение"}`; img.src = `${base}/cards/${i+1}`; img.loading = "lazy";
    const bar = el("div"); bar.append(el("span", `${i+1} / ${answer.cards.length}`)); const link = el("a","Скачать PNG"); link.href = `${base}/cards/${i+1}?download=true`; link.download = card.file; bar.append(link); article.append(img,bar); $("answer-cards").append(article);
  });
  if (!document.hidden) $("result").scrollIntoView({behavior:"smooth",block:"start"});
}
function tab(text) { $("cards-view").hidden = text; $("text-view").hidden = !text; for (const [id,active] of [["cards-tab",!text],["text-tab",text]]) { $(id).classList.toggle("active",active); $(id).setAttribute("aria-selected",String(active)); } }
$("cards-tab").onclick = () => tab(false); $("text-tab").onclick = () => tab(true);
$("copy-answer").onclick = async () => {
  const text = $("answer-text").textContent;
  try { if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text); else { const area = el("textarea",text); document.body.append(area); area.select(); const ok = document.execCommand("copy"); area.remove(); if (!ok) throw new Error(); } toast("Текст скопирован"); }
  catch (_) { toast("Выделите текст вручную или скачайте TXT."); }
};
$("new-task").onclick = async () => {
  if (state.pages.length && state.phase !== "complete" && !confirm("Начать новую задачу? Текущие фото исчезнут из этой вкладки.")) return;
  if (state.created && ["draft","uploading"].includes(state.phase)) api(`/v1/sessions/${state.id}`, {method:"DELETE"}).catch(()=>{});
  closePreview(); previews=[]; $("preview-dialog").close(); epoch++; running = false; state = freshState(); for (const url of urls) URL.revokeObjectURL(url); urls.clear();
  $("task-title").textContent = "Новая задача"; $("composer").hidden = false; $("processing").hidden = true; $("result").hidden = true; $("answer-text").textContent=""; $("answer-cards").replaceChildren(); error(""); tab(false); renderPages(); await persist();
};
$("solve").onclick = solve; $("retry").onclick = () => state.phase === "processing" ? resume() : solve(); $("resume").onclick = resume; $("render-retry").onclick = async () => { const token=epoch, id=state.id; try { await api(`/v1/sessions/${id}/render`,json({})); if (!current(token,id)) return; state.phase="processing"; await persist(); if (current(token,id)) resume(); } catch(e) { if(current(token,id)) error(e.message); } }; $("reconnect").onclick = checkHealth;
$("connect-button").onclick = async () => {
  $("connect-dialog").showModal(); const box = $("connection-links"); box.replaceChildren(el("p","Ищем адрес Wi-Fi…"));
  try { const value = await api("/connection"); box.replaceChildren();
    if (!value.urls.length) box.append(el("p","Адрес сети не найден. Подключите ноутбук к Wi-Fi iPhone и откройте это окно снова."));
    value.urls.forEach(url => { const row = el("div",null,"connection-link"); const qr = el("img"); qr.alt = `QR-код ${url}`; qr.src = `/connection/qr?address=${encodeURIComponent(url)}`; const content = el("div"); const link = el("a",url); link.href = url; content.append(link,el("p","Safari на iPhone → этот адрес")); row.append(qr,content); box.append(row); });
  } catch(e) { box.replaceChildren(el("p",e.message)); }
};
$("close-connect").onclick = () => $("connect-dialog").close();
document.addEventListener("visibilitychange", () => { if (!document.hidden) { checkHealth(); if (state.phase === "processing" && !running) resume(); } });
async function init() {
  $("camera-button").disabled = true; $("files-button").disabled = true; $("new-task").disabled = true;
  try { const saved = await storage("get"); if (saved?.version === 2 && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(saved.id) && Array.isArray(saved.pages) && saved.pages.length <= 12 && saved.pages.every(p=>p.file instanceof Blob && typeof p.file.name === "string") && ["draft","uploading","processing","complete","failed","answer_ready"].includes(saved.phase) && typeof saved.created === "boolean" && (saved.started===null || Number.isFinite(saved.started))) state = saved; } catch (_) {}
  const token = initialPairingToken;
  if (token) { try { await api("/v1/pairing/exchange",json({token})); toast("Телефон подключён"); } catch(e) { pairingRequired(); } }
  renderPages(); await checkHealth();
  if (state.created && ["processing","complete","answer_ready"].includes(state.phase)) resume();
  else if (state.phase === "uploading") { error("Загрузка не завершена. Нажмите «Решить задачу», чтобы продолжить с теми же страницами."); }
  setInterval(checkHealth,15000); setInterval(elapsed,1000);
}
init();
window.addEventListener("hashchange",async () => {
  const token=consumePairingToken(); if(!token) return;
  try { await api("/v1/pairing/exchange",json({token})); error(""); toast("Телефон подключён"); await checkHealth(); if(state.created && !running) resume(); }
  catch(e) { pairingRequired(); }
});
