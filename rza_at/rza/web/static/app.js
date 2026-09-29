/* ═══════════════ РЗА-АТ · ядро интерфейса ═══════════════
   API-клиент, состояние, роутер, модальные окна, «Показать расчёт», графики SVG.  */
"use strict";

const App = (() => {
  /* ─────────── утилиты ─────────── */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const nfmt = (v, sig = 4) => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "boolean") return v ? "да" : "нет";
    const n = Number(v);
    if (!isFinite(n)) return String(v);
    let s;
    if (Number.isInteger(n) && Math.abs(n) < 1e12) s = String(n);
    else {
      const abs = Math.abs(n);
      if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) s = n.toExponential(3).replace(".", ",");
      else {
        s = n.toPrecision(sig).replace(/\.?0+$/, "");
        if (s.includes(".")) s = s.replace(".", ",");
        else s = String(parseFloat(s));
      }
    }
    return s;
  };
  const pct = (v) => (v === null || v === undefined ? "—" : nfmt(v * 100, 3) + " %");
  const fdate = (s) => (s ? String(s).replace("T", " ") : "—");

  const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
  const setPath = (obj, path, val) => {
    const keys = path.split(".");
    let cur = obj;
    for (let i = 0; i < keys.length - 1; i++) {
      const k = keys[i];
      if (cur[k] == null || typeof cur[k] !== "object") cur[k] = /^\d+$/.test(keys[i + 1]) ? [] : {};
      cur = cur[k];
    }
    cur[keys[keys.length - 1]] = val;
  };
  const clone = (o) => JSON.parse(JSON.stringify(o));

  /* ─────────── API ─────────── */
  async function api(path, opts = {}) {
    const o = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      o.headers["Content-Type"] = "application/json";
      o.body = JSON.stringify(opts.body);
    }
    let r;
    try {
      r = await fetch("/api" + path, o);
    } catch (e) {
      toast("Нет связи с сервером: " + e.message, "err");
      throw e;
    }
    if (!r.ok) {
      let detail = r.statusText, extra = null;
      try {
        const j = await r.json();
        detail = j.detail || JSON.stringify(j);
        extra = j;
      } catch { /* ignore */ }
      const err = new Error(detail);
      err.payload = extra;
      err.status = r.status;
      if (!opts.quiet) toast(detail, "err");
      throw err;
    }
    if (r.status === 204) return null;
    return r.json();
  }

  /* ─────────── состояние ─────────── */
  const STATE = {
    route: "dashboard",
    params: {},
    info: null,
    project: null,
    derived: null,
    summary: null,
    stale: true,
    editable: true,
    drafts: {},          // черновики разделов для форм
    view: {},            // состояние внутри представлений (фильтры, вкладки)
  };

  /* ─────────── тосты ─────────── */
  function toast(msg, kind = "", ms = 4200) {
    const root = document.getElementById("toast-root");
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  /* ─────────── модальные окна ─────────── */
  function modal(html, { wide = false, onOpen } = {}) {
    const root = document.getElementById("modal-root");
    root.innerHTML = `<div class="overlay"><div class="modal ${wide ? "wide" : ""}">${html}</div></div>`;
    root.querySelector(".overlay").addEventListener("mousedown", (e) => {
      if (e.target.classList.contains("overlay")) closeModal();
    });
    if (onOpen) onOpen(root);
    return root;
  }
  function closeModal() {
    document.getElementById("modal-root").innerHTML = "";
  }
  function modalShell(title, bodyHtml, footHtml = "", wide = false) {
    return `<div class="modal-head"><h3>${title}</h3><button class="x-btn" data-act="closeModal">×</button></div>
      <div class="modal-body">${bodyHtml}</div>
      ${footHtml ? `<div class="modal-foot">${footHtml}</div>` : ""}`;
  }

  /* диалог причины изменения (журнал изменений, ТЗ п. 21, 41) */
  function askReason(title, cb, { needReason = false, okText = "Сохранить" } = {}) {
    const user = STATE.project?.meta?.author || "пользователь";
    modal(modalShell(title, `
      <div class="frow"><label>Автор изменения</label>
        <input type="text" id="rz-user" value="${esc(user)}"></div>
      <div class="frow"><label>Причина изменения ${needReason ? '<span class="chip chip-bad">обязательно</span>' : "<span class='faint'>(опционально, попадёт в журнал)</span>"}</label>
        <textarea id="rz-reason" placeholder="Например: уточнение по паспорту оборудования"></textarea></div>
      <div class="hint">Изменение будет зафиксировано в журнале изменений проекта.</div>`,
      `<button class="btn" data-act="closeModal">Отмена</button>
       <button class="btn btn-primary" id="rz-ok">${esc(okText)}</button>`), {
      onOpen: (root) => {
        root.querySelector("#rz-ok").addEventListener("click", () => {
          const reason = root.querySelector("#rz-reason").value.trim();
          if (needReason && !reason) {
            toast("Укажите причину изменения", "err");
            return;
          }
          const user = root.querySelector("#rz-user").value.trim() || "пользователь";
          closeModal();
          cb(user, reason);
        });
      },
    });
  }

  /* ─────────── статусы / чипы ─────────── */
  const statusChip = (status, label) => {
    const map = { ok: "chip-ok", pass: "chip-ok", verified: "chip-ok", check: "chip-warn", fail: "chip-bad", error: "chip-bad", missing: "chip-orng", out_of_range: "chip-bad", na: "chip-na", draft: "chip-draft", template: "chip-warn", not_loaded: "chip-na", review: "chip-warn", approved: "chip-ok" };
    return `<span class="chip ${map[status] || "chip"}">${esc(label || status)}</span>`;
  };

  /* ─────────── загрузка данных ─────────── */
  async function loadProject() {
    const d = await api("/project");
    STATE.project = d.project;
    STATE.derived = d.derived;
    STATE.editable = d.editable;
    STATE.stale = d.stale;
  }
  async function loadSummary() {
    try {
      STATE.summary = await api("/calc/summary");
      STATE.stale = STATE.summary.stale;
    } catch (e) {
      STATE.summary = null;
    }
  }
  async function runCalc() {
    const btn = document.getElementById("btn-run");
    if (btn) { btn.disabled = true; btn.textContent = "⏳ Расчёт…"; }
    try {
      const s = await api("/calc/run", { method: "POST", body: {} });
      STATE.summary = s;
      STATE.stale = false;
      toast(`Расчёт выполнен за ${nfmt(s.seconds, 3)} с`, "ok");
      await render();
    } catch (e) {
      toast("Расчёт не выполнен: " + e.message, "err");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "▶ Рассчитать"; }
    }
  }

  /* ─────────── меню ─────────── */
  const NAV = [
    { group: "Проект", items: [
      { id: "dashboard", label: "Обзор и статус", ico: "◧" },
      { id: "project", label: "Проект и версии", ico: "🗂" },
      { id: "changelog", label: "Журнал изменений", ico: "📜" },
    ] },
    { group: "Объект и сеть", items: [
      { id: "transformer", label: "Автотрансформатор", ico: "⚡" },
      { id: "network", label: "Сеть и режимы", ico: "🖧" },
      { id: "modes", label: "Библиотека режимов", ico: "🔁" },
      { id: "ctvt", label: "ТТ / ТН", ico: "▭" },
    ] },
    { group: "Расчёты защит", items: [
      { id: "kz", label: "Токи КЗ", ico: "💥" },
      { id: "fn-87T", label: "87T · дифференциальная", ico: "" },
      { id: "fn-50/51", label: "50/51 · МТЗ", ico: "" },
      { id: "fn-46", label: "46 · обратная посл.", ico: "" },
      { id: "fn-50N/51N", label: "50N/51N · нулевая посл.", ico: "" },
      { id: "fn-21", label: "21 · дистанционная", ico: "" },
      { id: "fn-49", label: "49 · перегрузка", ico: "" },
      { id: "checks", label: "Проверки (ч./с.)", ico: "🛡" },
    ] },
    { group: "Терминалы", items: [
      { id: "terminals", label: "База устройств", ico: "🔌" },
      { id: "assign", label: "Назначение", ico: "🔗" },
      { id: "compare", label: "Сравнение терминалов", ico: "⇄" },
      { id: "card", label: "Карта уставок", ico: "📋" },
    ] },
    { group: "Документация", items: [
      { id: "reports", label: "Отчёты и экспорт", ico: "📄" },
      { id: "norms", label: "Нормативная база", ico: "⚖" },
      { id: "formulas", label: "Библиотека формул", ico: "∑" },
      { id: "b13", label: "13Б vs современная РЗА", ico: "⇄" },
      { id: "assistant", label: "AI-ассистент", ico: "🤖" },
      { id: "tests", label: "Контрольные тесты", ico: "✅" },
    ] },
    { group: "", items: [{ id: "settings", label: "Настройки", ico: "⚙" }] },
  ];

  function renderNav() {
    const nav = document.getElementById("nav");
    nav.innerHTML = NAV.map((g) => `
      ${g.group ? `<div class="nav-group">${esc(g.group)}</div>` : `<div class="nav-group"></div>`}
      ${g.items.map((it) => `
        <div class="nav-item ${STATE.route === it.id ? "active" : ""}" data-act="nav" data-route="${it.id}">
          <span class="ico">${it.ico}</span><span>${esc(it.label)}</span>
        </div>`).join("")}
    `).join("");
  }

  function crumbs() {
    let label = "";
    for (const g of NAV) for (const it of g.items) if (it.id === STATE.route) label = it.label;
    if (STATE.route.startsWith("fn-")) label = label || STATE.route;
    document.getElementById("crumbs").innerHTML = `РЗА-АТ <span class="sep">/</span> <span class="cur">${esc(label)}</span>`;
    const note = document.getElementById("editable-note");
    const st = STATE.project?.meta?.status;
    const stChip = st === "approved" ? `<span class="chip chip-ok">Утверждён · только чтение</span>`
      : st === "review" ? `<span class="chip chip-warn">На проверке</span>`
      : `<span class="chip chip-draft">Черновик</span>`;
    note.outerHTML = `<span id="editable-note">${stChip}</span>`;
  }

  /* ─────────── рендер ─────────── */
  const views = {};  // заполняется в views.js

  async function render() {
    renderNav();
    crumbs();
    const mini = document.getElementById("proj-mini-name");
    if (mini && STATE.project) {
      mini.textContent = STATE.project.meta.name || STATE.project.meta.id;
      document.getElementById("proj-mini-ver").textContent = "v" + STATE.project.meta.version;
      const st = STATE.project.meta.status;
      document.getElementById("proj-mini-status").outerHTML =
        `<span id="proj-mini-status" class="chip ${st === "approved" ? "chip-ok" : st === "review" ? "chip-warn" : "chip-na"}">${st === "approved" ? "УТВЕРЖДЁН" : st === "review" ? "НА ПРОВЕРКЕ" : "ЧЕРНОВИК"}</span>`;
    }
    const sn = document.getElementById("stale-note");
    if (sn) sn.textContent = STATE.stale ? "⚠ данные изменены — требуется пересчёт" : "";
    const main = document.getElementById("main");
    const fn = views[STATE.route] || views.dashboard;
    try {
      await fn(main);
    } catch (e) {
      main.innerHTML = `<div class="banner banner-bad">Ошибка отображения: ${esc(e.message)}</div>`;
    }
  }

  function go(route) {
    STATE.route = route;
    render();
  }

  /* ─────────── «Показать расчёт» (ТЗ п. 19–20) ─────────── */
  async function openTrace(fid, key, terminal) {
    let d;
    try {
      d = await api(`/trace?function=${encodeURIComponent(fid)}&key=${encodeURIComponent(key)}` + (terminal ? `&terminal=${encodeURIComponent(terminal)}` : ""));
    } catch (e) { return; }
    const tr = d.trace || {};
    const steps = tr.steps || [];

    const ioTable = (vars) => `<div class="trace-io"><table>${vars.map((v) => `
      <tr><td class="mono">${esc(v.name)}</td>
          <td class="mono" style="text-align:right"><b>${typeof v.value === "object" && v.value ? `${nfmt(v.value.re)} ${v.value.im >= 0 ? "+" : "−"} j${nfmt(Math.abs(v.value.im))}` : nfmt(v.value)}</b> ${esc(v.unit || "")}</td>
          <td class="muted">${esc(v.desc || "")}</td>
          <td class="faint">${esc(v.src || "")}</td></tr>`).join("")}</table></div>`;

    const stepHtml = steps.map((s, i) => {
      const tagCls = { input: "tag-input", choice: "tag-choice", calc: "tag-calc", note: "tag-note", check: "tag-check", rounding: "tag-rounding" }[s.kind] || "tag-note";
      const tagText = { input: "Исходные данные", choice: "Выбор", calc: "Формула", note: "Примечание", check: "Проверка", rounding: "Округление" }[s.kind] || s.kind;
      let body = "";
      if (s.kind === "calc") {
        body = `${s.display ? `<div class="trace-formula">${esc(s.display)}<div class="faint" style="margin-top:4px">${esc(s.formula_id)} · версия ${s.formula_version}</div></div>` : ""}
          ${s.inputs?.length ? ioTable(s.inputs) : ""}
          ${s.substituted ? `<div class="trace-subst">${esc(s.substituted)}</div>` : ""}
          ${s.result ? `<div class="trace-result">Результат: ${nfmt(s.result.value)} ${esc(s.result.unit || "")}</div>` : ""}`;
      } else if (s.kind === "input") {
        body = s.result ? ioTable([s.result]) : "";
      } else if (s.kind === "choice") {
        body = `${s.result ? `<div class="trace-result">Принято: ${nfmt(s.result.value)} ${esc(s.result.unit || "")}</div>` : ""}
          ${s.options?.length ? `<details><summary class="hint">Варианты выбора</summary>${ioTable(s.options.map((o) => ({ name: o.title || o.name || "вариант", value: o.value, unit: o.unit, desc: o.note || o.desc, src: o.source || o.src })))}</details>` : ""}`;
      } else if (s.kind === "note") {
        body = `<div class="muted">${esc(s.note || "")}</div>`;
      }
      return `<div class="trace-step">
        <span class="tag ${tagCls}">${tagText}</span>
        <div class="st-title">${i + 1}. ${esc(s.title)}</div>
        ${body}
        ${s.note && s.kind !== "note" ? `<div class="faint">Примечание: ${esc(s.note)}</div>` : ""}
        ${s.source ? `<div class="trace-src">📖 Источник: ${esc(s.source)}</div>` : ""}
      </div>`;
    }).join("");

    const round = tr.rounding;
    const roundingHtml = round ? `
      <div class="trace-step"><span class="tag tag-rounding">Принятая уставка · округление</span>
        <div class="st-title">${round.deviation >= 0 ? "Округление вверх" : "Округление вниз"} до шага терминала</div>
        <table class="tbl" style="margin-top:6px">
          <tr><td>Расчётная уставка</td><td class="num mono"><b>${nfmt(round.calc)}</b> ${esc(round.unit || "")}</td></tr>
          <tr><td>Допустимый диапазон терминала</td><td class="num mono">${nfmt(round.min)} … ${nfmt(round.max)}</td></tr>
          <tr><td>Шаг терминала</td><td class="num mono">${nfmt(round.step)}</td></tr>
          <tr><td>Политика округления</td><td>${esc(round.policy)}</td></tr>
          <tr class="sum"><td>Принято</td><td class="num mono" style="color:var(--ok)"><b>${nfmt(round.accepted)}</b> ${esc(round.unit || "")}</td></tr>
          <tr><td>Отклонение</td><td class="num mono">${nfmt(round.deviation_abs ?? (round.accepted - round.calc))} (${pct(round.deviation_rel)})</td></tr>
        </table>
        ${round.terminal_source ? `<div class="trace-src">📖 Источник параметров терминала: ${esc(round.terminal_source.doc || "")} ${esc(round.terminal_source.release || "")}</div>` : ""}
      </div>` : "";

    const row = d.row;
    const rowHtml = row ? `
      <h3 class="sub">Параметр терминала</h3>
      <table class="tbl">
        <tr><td>Терминал</td><td><b>${esc(row.terminal)}</b> ${statusChip(row.profile_status)}</td></tr>
        <tr><td>Параметр устройства</td><td class="mono">${esc(row.param_name || row.param_key)} <span class="faint">ключ ${esc(row.param_key)}</span></td></tr>
        <tr><td>Единица устройства</td><td>${esc(row.unit)}</td></tr>
        <tr><td>Диапазон / шаг</td><td class="mono">${nfmt(row.min)} … ${nfmt(row.max)} / ${nfmt(row.step)}</td></tr>
        <tr class="sum"><td>Принятая уставка</td><td class="mono" style="font-size:15px">${nfmt(row.accepted)} ${esc(row.unit)}</td></tr>
        ${row.override ? `<tr><td>Ручная уставка</td><td class="mono">${nfmt(row.override.value)} — ${esc(row.override.reason)} (${esc(row.override.author)})</td></tr>` : ""}
      </table>
      ${row.reason ? `<div class="hint" style="margin-top:6px">Комментарий: ${esc(row.reason)}</div>` : ""}
      ${(d.terminal_source && d.terminal_source.length) ? `<div class="trace-src">📖 ${d.terminal_source.map((s) => esc(s.doc || "") + (s.release ? `, ${esc(s.release)}` : "")).join("; ")}</div>` : ""}` : "";

    const checks = [...(d.calc_checks || []), ...(d.recheck || [])];
    const checksHtml = checks.length ? `
      <h3 class="sub">Проверки</h3>
      ${checks.map((c) => `<div class="item-card">
        <div class="head">${statusChip(c.status, c.icon + " " + c.status_label)} <span>${esc(c.title)}</span></div>
        <div>${esc(c.reason)}</div>
        ${c.threshold != null ? `<div class="faint">Порог: ${esc(c.cmp)} ${nfmt(c.threshold)} ${esc(c.unit || "")}</div>` : ""}
      </div>`).join("")}` : "";

    const criteriaHtml = d.criteria?.length ? `
      <h3 class="sub">Критерии выбора уставки</h3>
      <table class="tbl">
        <tr><th>Критерий</th><th class="num">Граница</th><th>Основание</th></tr>
        ${d.criteria.map((c) => `<tr><td>${esc(c.title)}${c.note ? `<div class="sub">${esc(c.note)}</div>` : ""}</td>
          <td class="num mono">${c.kind === "lower" ? "≥" : c.kind === "upper" ? "≤" : "="} ${nfmt(c.value)}</td>
          <td class="sub">${esc(c.ref)} ${c.formula_id ? `<div class="formula-id">${esc(c.formula_id)}</div>` : ""}</td></tr>`).join("")}
      </table>` : "";

    modal(modalShell(`Показать расчёт · ${esc(d.title || key)}`, `
      <div class="banner banner-info">Цепочка расчёта: <b>Исходные данные → Формула → Подстановка → Результат → Принятая уставка → Проверка</b>.
      Каждая формула имеет идентификатор, версию и нормативное основание.</div>
      <table class="tbl" style="margin-bottom:12px">
        <tr><td>Параметр (PFM)</td><td class="mono">${esc(key)}</td></tr>
        <tr><td>Расчётная уставка</td><td class="mono"><b>${nfmt(d.calc)}</b> ${esc(d.unit || "")}</td></tr>
        <tr><td>Допустимый интервал</td><td class="mono">${nfmt(d.lower)} … ${nfmt(d.upper)}</td></tr>
        <tr><td>Статус</td><td>${esc(d.reason || d.status)}</td></tr>
      </table>
      ${criteriaHtml}
      <h3 class="sub">Ход расчёта</h3>
      <div class="docflow">${stepHtml || "<div class='faint'>Трасса пуста</div>"}</div>
      ${roundingHtml}
      ${rowHtml}
      ${checksHtml}`,
      `<button class="btn btn-primary" data-act="closeModal">Закрыть</button>`, true));
  }

  /* ─────────── трасса проверки ─────────── */
  function openCheckObj(c) {
    const tr = c.trace;
    const steps = tr?.steps || [];
    const stepHtml = steps.map((s, i) => {
      const tagCls = { input: "tag-input", choice: "tag-choice", calc: "tag-calc", note: "tag-note", check: "tag-check", rounding: "tag-rounding" }[s.kind] || "tag-note";
      const tagText = { input: "Исходные данные", choice: "Выбор", calc: "Формула", note: "Примечание", check: "Проверка", rounding: "Округление" }[s.kind] || s.kind;
      return `<div class="trace-step">
        <span class="tag ${tagCls}">${tagText}</span>
        <div class="st-title">${i + 1}. ${esc(s.title)}</div>
        ${s.kind === "calc" && s.display ? `<div class="trace-formula">${esc(s.display)}<div class="faint" style="margin-top:4px">${esc(s.formula_id)} · версия ${s.formula_version}</div></div>` : ""}
        ${s.substituted ? `<div class="trace-subst">${esc(s.substituted)}</div>` : ""}
        ${s.result ? `<div class="trace-result">= ${nfmt(s.result.value)} ${esc(s.result.unit || "")}</div>` : ""}
        ${s.note ? `<div class="faint">${esc(s.note)}</div>` : ""}
        ${s.source ? `<div class="trace-src">📖 ${esc(s.source)}</div>` : ""}
      </div>`;
    }).join("");
    const det = (c.details || []).slice(0, 40);
    modal(modalShell(`Проверка · ${esc(c.title)}`, `
      <div class="banner ${c.status === "ok" ? "banner-ok" : c.status === "check" ? "banner-warn" : "banner-bad"}">
        ${esc(c.icon || "")} ${esc(c.status_label || c.status)} — ${esc(c.reason)}
      </div>
      <table class="tbl" style="margin-bottom:12px">
        <tr><td>Вид проверки</td><td>${esc(c.kind)}</td></tr>
        <tr><td>Значение</td><td class="mono"><b>${nfmt(c.value)}</b> ${esc(c.unit || "")}</td></tr>
        <tr><td>Требование</td><td class="mono">${esc(c.cmp)} ${nfmt(c.threshold)}</td></tr>
        ${c.worst && Object.keys(c.worst).length ? `<tr><td>Наихудший случай</td><td class="sub">${Object.entries(c.worst).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</td></tr>` : ""}
      </table>
      ${(c.refs || []).length ? `<div class="trace-src">📖 Основание: ${c.refs.map(esc).join("; ")}</div>` : ""}
      ${det.length ? `<h3 class="sub">Расчётные случаи (${det.length}${(c.details || []).length > det.length ? " из " + c.details.length : ""})</h3>
        <div class="tbl-wrap"><table class="tbl">
        <tr>${Object.keys(det[0]).filter((k) => !["x_res", "i_unb", "i_diff", "margin", "kch"].includes(k)).slice(0, 6).map((k) => `<th>${esc(k)}</th>`).join("")}<th class="num">значение</th></tr>
        ${det.map((d) => `<tr>${Object.keys(det[0]).filter((k) => !["x_res", "i_unb", "i_diff", "margin", "kch"].includes(k)).slice(0, 6).map((k) => `<td class="sub">${esc(d[k])}</td>`).join("")}
          <td class="num mono">${nfmt(d.i_diff ?? d.i_unb ?? d.margin ?? d.kch)}</td></tr>`).join("")}
        </table></div>` : ""}
      ${steps.length ? `<h3 class="sub">Расчёт проверки</h3><div class="docflow">${stepHtml}</div>` : ""}`,
      `<button class="btn btn-primary" data-act="closeModal">Закрыть</button>`, true));
  }
  async function openCheck(cid, scope, terminal) {
    try {
      const c = await api(`/check_trace?cid=${encodeURIComponent(cid)}&scope=${encodeURIComponent(scope)}` + (terminal ? `&terminal=${encodeURIComponent(terminal)}` : ""));
      openCheckObj(c);
    } catch (e) { /* toast уже показан */ }
  }

  /* ─────────── сохранение раздела проекта ─────────── */
  async function saveSection(section, data, user, reason) {
    try {
      const r = await api(`/project/section/${section}`, { method: "PUT", body: { data, user, reason } });
      toast(`Сохранено. Зафиксировано изменений: ${r.changes}`, "ok");
      dropDraft(section);
      await loadProject();
      STATE.stale = true;
      await render();
      return true;
    } catch (e) {
      return false;
    }
  }
  async function patchPath(path, value, user, reason) {
    try {
      await api("/project/path", { method: "PATCH", body: { path, value, user, reason } });
      toast("Изменение сохранено", "ok");
      await loadProject();
      STATE.stale = true;
      await render();
      return true;
    } catch (e) {
      return false;
    }
  }

  /* черновик раздела */
  function draft(section) {
    if (!STATE.drafts[section]) {
      const src = section === "meta" ? STATE.project.meta
        : section === "cts" ? STATE.project.cts
        : section === "vts" ? STATE.project.vts
        : section === "modes" ? STATE.project.modes
        : section === "terminals" ? STATE.project.terminals
        : STATE.project[section];
      STATE.drafts[section] = clone(src);
    }
    return STATE.drafts[section];
  }
  function dropDraft(section) { delete STATE.drafts[section]; }

  /* ─────────── SVG-графики ─────────── */
  function svg87t(d) {
    if (!d || !d.available) return `<div class="faint">График недоступен — выполните расчёт 87T</div>`;
    const W = 640, H = 400, ml = 56, mr = 14, mt = 14, mb = 40;
    const xmax = d.x_max, ymax = Math.max(d.curve[d.curve.length - 1][1] * 1.25, ...(d.int || []).map((p) => p.y * 1.1), 1);
    const X = (x) => ml + (x / xmax) * (W - ml - mr);
    const Y = (y) => H - mb - (y / ymax) * (H - mt - mb);
    const poly = d.curve.map(([x, y]) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
    const grid = [];
    for (let i = 0; i <= 5; i++) {
      const x = (xmax * i) / 5, y = (ymax * i) / 5;
      grid.push(`<line x1="${X(x)}" y1="${mt}" x2="${X(x)}" y2="${H - mb}" stroke="#e8eef5"/>`);
      grid.push(`<text x="${X(x)}" y="${H - mb + 16}" font-size="10" fill="#8496ab" text-anchor="middle">${nfmt(x, 3)}</text>`);
      grid.push(`<line x1="${ml}" y1="${Y(y)}" x2="${W - mr}" y2="${Y(y)}" stroke="#e8eef5"/>`);
      grid.push(`<text x="${ml - 6}" y="${Y(y) + 3}" font-size="10" fill="#8496ab" text-anchor="end">${nfmt(y, 3)}</text>`);
    }
    const ext = (d.ext || []).map((p) => `
      <circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4.5" fill="#1667c8"><title>${esc(p.label)} · запас ${nfmt(p.margin)}</title></circle>`).join("");
    const int = (d.int || []).map((p) => `
      <circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4.5" fill="#e05555"><title>${esc(p.label)} · k_ч ${nfmt(p.kch)}</title></circle>`).join("");
    return `<div class="chart-box">
      <svg viewBox="0 0 ${W} ${H}">
        ${grid.join("")}
        <line x1="${ml}" y1="${H - mb}" x2="${W - mr}" y2="${H - mb}" stroke="#c3cfdd"/>
        <line x1="${ml}" y1="${mt}" x2="${ml}" y2="${H - mb}" stroke="#c3cfdd"/>
        <polyline points="${poly}" fill="none" stroke="#f6c445" stroke-width="2.6"/>
        ${ext}${int}
        <text x="${W / 2}" y="${H - 6}" font-size="11" fill="#55657a" text-anchor="middle">I_торм, о.е.</text>
        <text x="14" y="${H / 2}" font-size="11" fill="#55657a" transform="rotate(-90 14 ${H / 2})" text-anchor="middle">I_диф, о.е.</text>
      </svg>
      <div class="chart-legend">
        <span class="k"><span class="sw" style="background:#f6c445"></span>характеристика срабатывания</span>
        <span class="k"><span class="sw" style="background:#1667c8"></span>внешние КЗ (точки небаланса)</span>
        <span class="k"><span class="sw" style="background:#e05555"></span>КЗ в зоне защиты</span>
      </div>
    </div>`;
  }

  function svgTcc(d) {
    if (!d || !d.available) return `<div class="faint">График недоступен — требуется расчёт 50/51 и данные смежных защит</div>`;
    const W = 680, H = 420, ml = 56, mr = 14, mt = 14, mb = 42;
    const xlo = d.i_lo, xhi = d.i_hi;
    const lx = (i) => Math.log10(Math.max(i, 1e-6));
    const X = (i) => ml + ((lx(i) - lx(xlo)) / (lx(xhi) - lx(xlo))) * (W - ml - mr);
    let tmax = 0.1;
    for (const s of d.series) for (const p of s.points) if (isFinite(p[1])) tmax = Math.max(tmax, p[1]);
    tmax *= 1.15;
    const Y = (t) => H - mb - (Math.min(t, tmax) / tmax) * (H - mt - mb);
    const colors = ["#1667c8", "#e05555", "#1e9e5a", "#9b59b6", "#e67e22", "#16a085"];
    const grid = [];
    for (let e = Math.ceil(lx(xlo)); e <= Math.floor(lx(xhi)); e++) {
      const x = X(Math.pow(10, e));
      grid.push(`<line x1="${x}" y1="${mt}" x2="${x}" y2="${H - mb}" stroke="#e8eef5"/>`);
      grid.push(`<text x="${x}" y="${H - mb + 16}" font-size="10" fill="#8496ab" text-anchor="middle">10^${e}</text>`);
    }
    for (let i = 0; i <= 5; i++) {
      const t = (tmax * i) / 5;
      grid.push(`<line x1="${ml}" y1="${Y(t)}" x2="${W - mr}" y2="${Y(t)}" stroke="#e8eef5"/>`);
      grid.push(`<text x="${ml - 6}" y="${Y(t) + 3}" font-size="10" fill="#8496ab" text-anchor="end">${nfmt(t, 3)}</text>`);
    }
    const zonePts = (d.zone || []).filter((p) => p.ok);
    const zone = zonePts.length ? `<rect x="${X(zonePts[0].i)}" y="${mt}" width="${Math.max(X(zonePts[zonePts.length - 1].i) - X(zonePts[0].i), 1)}" height="${H - mt - mb}" fill="#1e9e5a" opacity="0.07"/>` : "";
    const lines = d.series.map((s, idx) => {
      const c = colors[idx % colors.length];
      const pts = s.points.filter((p) => isFinite(p[1]) && p[1] <= tmax).map(([i, t]) => `${X(i).toFixed(1)},${Y(t).toFixed(1)}`).join(" ");
      return `<polyline points="${pts}" fill="none" stroke="${c}" stroke-width="${s.role === "own" ? 2.8 : 1.8}" ${s.role !== "own" ? 'stroke-dasharray="5 3"' : ""}/>`;
    }).join("");
    return `<div class="chart-box">
      <svg viewBox="0 0 ${W} ${H}">
        ${grid.join("")}${zone}${lines}
        <line x1="${ml}" y1="${H - mb}" x2="${W - mr}" y2="${H - mb}" stroke="#c3cfdd"/>
        <line x1="${ml}" y1="${mt}" x2="${ml}" y2="${H - mb}" stroke="#c3cfdd"/>
        <text x="${W / 2}" y="${H - 6}" font-size="11" fill="#55657a" text-anchor="middle">ток, А (сторона ${esc(d.side)})</text>
        <text x="14" y="${H / 2}" font-size="11" fill="#55657a" transform="rotate(-90 14 ${H / 2})" text-anchor="middle">t, с</text>
      </svg>
      <div class="chart-legend">
        ${d.series.map((s, idx) => `<span class="k"><span class="sw" style="background:${colors[idx % colors.length]}"></span>${esc(s.name)}</span>`).join("")}
        <span class="k"><span class="sw" style="background:#1e9e5a;opacity:.4"></span>зона селективности</span>
      </div>
    </div>`;
  }

  /* ─────────── каркас страницы с табами ─────────── */
  function pageShell(title, subtitle, tabsHtml, bodyHtml) {
    return `<h2 class="sec">${title}</h2>${subtitle ? `<div class="sect-note">${subtitle}</div>` : ""}
      ${tabsHtml || ""}${bodyHtml}`;
  }

  /* ─────────── обработчики (делегирование) ─────────── */
  const actions = {
    nav: (el) => go(el.dataset.route),
    closeModal: () => closeModal(),
    runCalc: () => runCalc(),
    openTrace: (el) => openTrace(el.dataset.fn, el.dataset.key, el.dataset.terminal || null),
    openCheck: (el) => openCheck(el.dataset.cid, el.dataset.scope || "calc", el.dataset.terminal || null),
  };

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const fn = actions[el.dataset.act] || App.actions[el.dataset.act];
    if (fn) {
      e.preventDefault();
      fn(el, e);
    }
  });

  document.addEventListener("input", (e) => {
    const el = e.target.closest("[data-draft]");
    if (!el) return;
    const [section, ...rest] = el.dataset.draft.split("|");
    const path = rest.join("|");
    let val;
    if (el.type === "checkbox") val = el.checked;
    else if (el.type === "number") val = el.value === "" ? null : Number(el.value);
    else val = el.value;
    if (el.dataset.keepEmpty === "1" && el.value === "") val = null;
    setPath(draft(section), path, val);
    if (actions.onDraftInput) actions.onDraftInput(el);
  });

  document.addEventListener("change", (e) => {
    const el = e.target.closest("[data-draft][data-onchange]");
    if (el && actions[el.dataset.onchange]) actions[el.dataset.onchange](el, e);
    const sel = e.target.closest("select[data-draft], input[type=checkbox][data-draft]");
    if (sel && actions.onDraftInput) actions.onDraftInput(sel);
  });

  /* ─────────── старт ─────────── */
  async function boot() {
    try {
      STATE.info = await api("/info");
      await loadProject();
      await loadSummary();
    } catch (e) {
      document.getElementById("main").innerHTML = `<div class="banner banner-bad">Не удалось загрузить проект: ${esc(e.message)}</div>`;
      return;
    }
    document.getElementById("btn-run").addEventListener("click", runCalc);
    document.getElementById("btn-quick-checks").addEventListener("click", () => go("checks"));
    document.getElementById("btn-quick-card").addEventListener("click", () => go("card"));
    document.getElementById("btn-quick-report").addEventListener("click", () => go("reports"));
    await render();
  }

  return {
    esc, nfmt, pct, fdate, getPath, setPath, clone, api, toast,
    modal, closeModal, modalShell, askReason, statusChip, pageShell,
    STATE, actions, views, boot, render, go, runCalc,
    loadProject, loadSummary, saveSection, patchPath, draft, dropDraft,
    openTrace, openCheck, openCheckObj, svg87t, svgTcc, NAV,
  };
})();
