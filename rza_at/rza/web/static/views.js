/* ═══════════════ РЗА-АТ · представления (разделы интерфейса) ═══════════════ */
"use strict";
(() => {
  const A = App;
  const { esc, nfmt, pct, clone, api, toast, modal, closeModal, modalShell, askReason, statusChip, STATE } = A;

  const fnTitles = {
    "87T": "Дифференциальная защита 87T",
    "50/51": "Максимальная токовая защита 50/51",
    "46": "Защита от несимметричных КЗ (обратная последовательность) 46",
    "50N/51N": "Токовая защита нулевой последовательности 50N/51N",
    "21": "Дистанционная защита 21",
    "49": "Защита от перегрузки (тепловая) 49",
  };

  /* вспомогательное: поле формы, привязанное к черновику */
  const fNum = (section, path, label, unit, attrs = "") =>
    `<div class="frow"><label>${label} ${unit ? `<span class="unit">[${unit}]</span>` : ""}</label>
      <input type="number" step="any" data-draft="${section}|${path}" value="${A.getPath(A.draft(section), path) ?? ""}" ${attrs}></div>`;
  const fText = (section, path, label, attrs = "") =>
    `<div class="frow"><label>${label}</label>
      <input type="text" data-draft="${section}|${path}" value="${esc(A.getPath(A.draft(section), path) ?? "")}" ${attrs}></div>`;
  const fArea = (section, path, label, rows = 3) =>
    `<div class="frow"><label>${label}</label>
      <textarea rows="${rows}" data-draft="${section}|${path}">${esc(A.getPath(A.draft(section), path) ?? "")}</textarea></div>`;
  const fCheck = (section, path, label) =>
    `<label class="check-line"><input type="checkbox" data-draft="${section}|${path}" ${A.getPath(A.draft(section), path) ? "checked" : ""}> <span>${label}</span></label>`;
  const fSel = (section, path, label, options) => {
    const cur = A.getPath(A.draft(section), path);
    return `<div class="frow"><label>${label}</label>
      <select data-draft="${section}|${path}">${options.map(([v, t]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>`;
  };

  const saveBtn = (section, label = "Сохранить раздел") =>
    `<button class="btn btn-primary" data-act="saveSection" data-section="${section}">💾 ${label}</button>
     <button class="btn" data-act="revertSection" data-section="${section}">↺ Отменить правки</button>`;

  A.actions.saveSection = (el) => {
    const section = el.dataset.section;
    askReason("Сохранение раздела: " + section, (user, reason) => A.saveSection(section, A.draft(section), user, reason));
  };
  A.actions.revertSection = (el) => {
    A.dropDraft(el.dataset.section);
    A.render();
    toast("Правки отменены");
  };

  /* ═══════════════ ОБЗОР И СТАТУС ═══════════════ */
  A.views.dashboard = async (main) => {
    const s = STATE.summary;
    const p = STATE.project;
    const d = STATE.derived;
    const st = (s && s.statuses) || [];
    const issues = (s && s.issues) || [];
    const fn = (s && s.functions) || {};
    const cards = (s && s.cards) || {};
    main.innerHTML = A.pageShell(
      "Обзор и статус расчёта",
      esc(p.meta.name) + " · " + esc(p.meta.substation) + " · версия " + esc(p.meta.version),
      "",
      `
      ${s && s.blocked ? `<div class="banner banner-bad"><b>Расчёт заблокирован ошибками исходных данных.</b> Устраните замечания в разделе «Обзор» или в исходных данных.</div>` : ""}
      ${STATE.stale ? `<div class="banner banner-warn">Данные изменены после последнего расчёта — выполните <b>▶ Рассчитать</b>.</div>` : ""}
      <div class="status-line">
        ${st.map((x) => `<div class="status-pill ${x.color}">
          <span>${x.ok ? "🟢" : x.color === "yellow" ? "🟡" : x.color === "orange" ? "🟠" : "🔴"}</span>
          <span>${esc(x.label)}</span>
          ${x.detail && x.detail.length ? `<span class="det">— ${esc(x.detail[0])}${x.detail.length > 1 ? ` <b>(ещё ${x.detail.length - 1})</b>` : ""}</span>` : ""}
        </div>`).join("")}
      </div>

      <div class="grid grid-3">
        <div class="panel">
          <div class="panel-title">Автотрансформатор</div>
          <table class="tbl kv-table">
            <tr><td>Тип</td><td>${esc(p.transformer.type_name || "—")}</td></tr>
            <tr><td>Мощность</td><td class="mono">${nfmt(p.transformer.s_nom_mva)} МВА</td></tr>
            <tr><td>Напряжения</td><td class="mono">${(d.sides || []).map((s) => nfmt(s.u_nom_kv) + " кВ").join(" / ")}</td></tr>
            <tr><td>Группа соединения</td><td>${esc(d.group || "—")}</td></tr>
            <tr><td>Типовая мощность (АТ)</td><td class="mono">${nfmt(d.alpha != null ? d.s_typ : null)} МВА</td></tr>
          </table>
          <button class="btn btn-sm" data-act="nav" data-route="transformer" style="margin-top:8px">Открыть паспорт →</button>
        </div>
        <div class="panel">
          <div class="panel-title">Номинальные токи</div>
          <table class="tbl">
            <tr><th>Сторона</th><th class="num">U, кВ</th><th class="num">I_ном, А</th></tr>
            ${(d.rated || []).map((r) => `<tr><td>${esc(r.side_ru || r.side)}</td><td class="num mono">${nfmt(r.u_kv)}</td><td class="num mono"><b>${nfmt(r.i_a)}</b></td></tr>`).join("")}
          </table>
          <div class="faint" style="margin-top:8px">РПН: ${d.oltc_table && d.oltc_table.length ? `${d.oltc_table.length} положений, ступень ${nfmt(p.transformer.oltc.step_pct)} %` : "нет"}</div>
        </div>
        <div class="panel">
          <div class="panel-title">Терминалы проекта</div>
          ${Object.keys(cards).length ? Object.entries(cards).map(([tid, c]) => `
            <div style="display:flex;align-items:center;gap:8px;margin:6px 0">
              ${statusChip(c.status, c.icon + " " + (c.status === "ok" ? "выполнено" : "есть замечания"))}
              <span style="flex:1">${esc(c.label)}</span>
              <button class="btn btn-sm" data-act="nav" data-route="card">Карта</button>
            </div>`).join("") : `<div class="faint">Терминалы не назначены — раздел «Назначение».</div>`}
          <button class="btn btn-sm" data-act="nav" data-route="assign" style="margin-top:8px">Назначить терминал →</button>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">Функции защиты — результаты расчёта <span class="spacer"></span>
          <button class="btn btn-sm btn-accent" data-act="runCalc">▶ Пересчитать</button></div>
        <div class="tbl-wrap"><table class="tbl">
          <tr><th>Функция</th><th>Статус</th><th class="num">Параметров</th><th class="num">Проверок</th><th>Примечания</th></tr>
          ${Object.entries(fn).map(([fid, f]) => `
            <tr class="click" data-act="nav" data-route="fn-${fid}">
              <td><b>${esc(fid)}</b> · ${esc(f.title)}</td>
              <td>${statusChip(f.status, f.icon + " " + (f.status === "ok" ? "выполнено" : f.status === "fail" ? "критерий не выполнен" : f.status))}</td>
              <td class="num mono">${f.n_params}</td>
              <td class="num mono">${f.n_checks}</td>
              <td class="sub">${(f.warnings || []).concat(f.missing || []).map(esc).join("; ") || "—"}</td>
            </tr>`).join("") || `<tr><td colspan="5" class="faint">Расчёт не выполнялся</td></tr>`}
        </table></div>
      </div>

      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Замечания контроля данных (${issues.length})</div>
          ${issues.length ? `<div class="tbl-wrap"><table class="tbl">
            <tr><th>Уровень</th><th>Сообщение</th><th>Раздел</th></tr>
            ${issues.map((i) => `<tr><td>${i.level === "error" ? `<span class="chip chip-bad">ошибка</span>` : `<span class="chip chip-warn">предупреждение</span>`}</td>
              <td>${esc(i.message)}${i.hint ? `<div class="sub">${esc(i.hint)}</div>` : ""}</td><td class="sub mono">${esc(i.path)}</td></tr>`).join("")}
          </table></div>` : `<div class="banner banner-ok">Замечаний нет.</div>`}
        </div>
        <div class="panel">
          <div class="panel-title">Быстрые ссылки</div>
          <div class="grid" style="gap:8px">
            <button class="btn btn-block" data-act="nav" data-route="kz">💥 Расчёт токов КЗ</button>
            <button class="btn btn-block" data-act="nav" data-route="fn-87T">⚡ 87T — дифференциальная защита</button>
            <button class="btn btn-block" data-act="nav" data-route="checks">🛡 Проверки чувствительности и селективности</button>
            <button class="btn btn-block" data-act="nav" data-route="compare">⇄ Сравнение терминалов</button>
            <button class="btn btn-block" data-act="nav" data-route="reports">📄 Сформировать отчёт</button>
            <button class="btn btn-block" data-act="nav" data-route="assistant">🤖 Помощь ассистента</button>
          </div>
        </div>
      </div>`);
  };

  /* ═══════════════ ПРОЕКТ И ВЕРСИИ ═══════════════ */
  A.views.project = async (main) => {
    const p = STATE.project;
    const s = STATE.summary;
    main.innerHTML = A.pageShell("Проект и версии", "Реквизиты, роли согласования, версионность (ТЗ п. 21). Утверждённый проект защищён от изменений.", "", `
      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Реквизиты проекта ${A.saveBtnHTML ? "" : ""}</div>
          ${fText("meta", "name", "Наименование проекта")}
          ${fText("meta", "substation", "Подстанция / объект")}
          ${fArea("meta", "description", "Описание", 2)}
          <div class="grid grid-3" style="gap:0 12px">
            ${fText("meta", "author", "Автор (инженер РЗА)")}
            ${fText("meta", "reviewer", "Проверяющий")}
            ${fText("meta", "approver", "Утверждающий")}
          </div>
          <div class="hint">Версия: <b>${esc(p.meta.version)}</b> · предыдущая: ${esc(p.meta.prev_version || "—")} · дата: ${esc(p.meta.date || "—")} · причина: ${esc(p.meta.reason || "—")}</div>
          ${saveBtn("meta")}
        </div>

        <div class="panel">
          <div class="panel-title">Статус и версии</div>
          <div style="margin-bottom:10px">Текущий статус: ${statusChip(p.meta.status, p.meta.status === "draft" ? "Черновик" : p.meta.status === "review" ? "На проверке" : "Утверждён")}</div>
          <div class="hint" style="margin-bottom:10px">
            🔒 Черновик → На проверке → Утверждён. Утверждённый проект нельзя изменить без создания новой версии.
            Экспорт окончательной карты уставок требует полного контроля проекта.
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn" data-act="setReview">→ На проверку</button>
            <button class="btn btn-primary" data-act="setApprove">✓ Утвердить</button>
            <button class="btn btn-accent" data-act="newVersion">✚ Новая версия</button>
          </div>
          <h3 class="sub">История версий</h3>
          ${(p.history || []).length ? `<table class="tbl">
            <tr><th>Версия</th><th>Дата</th><th>Автор</th><th>Причина</th></tr>
            ${p.history.map((h) => `<tr><td class="mono">${esc(h.version)}</td><td>${esc(h.date)}</td><td>${esc(h.author)}</td><td class="sub">${esc(h.reason)}</td></tr>`).join("")}
          </table>` : `<div class="faint">Снимков предыдущих версий ещё нет.</div>`}
        </div>
      </div>

      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Проекты</div>
          <div id="projects-list" class="faint">Загрузка…</div>
          <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
            <button class="btn btn-primary" data-act="newProjectDemo">✚ Новый демо-проект</button>
            <button class="btn" data-act="newProjectBlank">✚ Пустой проект</button>
          </div>
        </div>
        <div class="panel">
          <div class="panel-title">Импорт / экспорт</div>
          <div class="hint" style="margin-bottom:10px">JSON — полный обмен проектом (данные, журнал, история). Форматы отчётов — в разделе «Отчёты и экспорт».</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <a class="btn btn-primary" href="/api/project/export.json">⬇ Экспорт JSON</a>
            <button class="btn" data-act="importProject">⬆ Импорт JSON</button>
          </div>
          <h3 class="sub">Последние записи журнала</h3>
          <div id="mini-changelog" class="faint">Загрузка…</div>
        </div>
      </div>`);
    api("/projects").then((list) => {
      const el = document.getElementById("projects-list");
      if (!el) return;
      el.innerHTML = `<table class="tbl">
        <tr><th>Проект</th><th>Версия</th><th>Статус</th><th></th></tr>
        ${list.map((x) => `<tr>
          <td><b>${esc(x.name)}</b><div class="sub mono">${esc(x.id)}</div></td>
          <td class="mono">${esc(x.version)}</td>
          <td>${statusChip(x.status)}</td>
          <td>${x.current ? `<span class="chip chip-ok">текущий</span>` : `<button class="btn btn-sm" data-act="openProject" data-id="${esc(x.id)}">Открыть</button>`}</td>
        </tr>`).join("")}</table>`;
    }).catch(() => {});
    api("/changelog").then((log) => {
      const el = document.getElementById("mini-changelog");
      if (!el) return;
      el.innerHTML = `<table class="tbl">${log.slice(0, 8).map((c) => `
        <tr><td class="sub mono nowrap">${esc(c.ts)}</td><td class="sub">${esc(c.kind)} · ${esc(c.section)}.${esc(c.path)}</td></tr>`).join("")}</table>
        <button class="btn btn-sm" data-act="nav" data-route="changelog" style="margin-top:8px">Весь журнал →</button>`;
    }).catch(() => {});
  };

  A.actions.openProject = async (el) => {
    await api(`/projects/open/${el.dataset.id}`, { method: "POST", body: {} });
    STATE.drafts = {};
    await A.loadProject();
    await A.loadSummary();
    A.go("dashboard");
    toast("Проект открыт");
  };
  A.actions.newProjectDemo = () => askReason("Новый демо-проект", async (user, reason) => {
    await api("/projects/new", { method: "POST", body: { kind: "demo", author: user } });
    STATE.drafts = {};
    await A.loadProject(); await A.loadSummary();
    A.go("dashboard");
    toast("Создан демо-проект", "ok");
  }, { okText: "Создать" });
  A.actions.newProjectBlank = () => askReason("Новый пустой проект", async (user, reason) => {
    await api("/projects/new", { method: "POST", body: { kind: "blank", author: user } });
    STATE.drafts = {};
    await A.loadProject(); await A.loadSummary();
    A.go("dashboard");
    toast("Создан пустой проект", "ok");
  }, { okText: "Создать" });
  A.actions.importProject = () => {
    modal(modalShell("Импорт проекта из JSON", `
      <div class="frow"><label>Файл проекта JSON</label><input type="file" id="imp-file" accept=".json"></div>
      <div class="hint">Текущий проект будет заменён импортированным. Действие попадёт в журнал.</div>`,
      `<button class="btn" data-act="closeModal">Отмена</button><button class="btn btn-primary" id="imp-ok">Импортировать</button>`), {
      onOpen: (root) => root.querySelector("#imp-ok").addEventListener("click", async () => {
        const f = root.querySelector("#imp-file").files[0];
        if (!f) { toast("Выберите файл", "err"); return; }
        try {
          const data = JSON.parse(await f.text());
          await api("/project/import", { method: "POST", body: data });
          STATE.drafts = {};
          await A.loadProject(); await A.loadSummary();
          closeModal();
          A.go("dashboard");
          toast("Проект импортирован", "ok");
        } catch (e) { toast("Ошибка импорта: " + e.message, "err"); }
      }),
    });
  };
  A.actions.setReview = () => askReason("Передать проект на проверку", async (user) => {
    try {
      await api("/project/status", { method: "POST", body: { status: "review", by: user } });
      await A.loadProject(); A.render();
      toast("Статус: на проверке", "ok");
    } catch (e) { /* toast */ }
  }, { okText: "На проверку" });
  A.actions.setApprove = () => {
    api("/report/guard").then((g) => {
      modal(modalShell("Утверждение проекта", `
        ${g.final_allowed ? `<div class="banner banner-ok">Полный контроль проекта пройден — можно утверждать.</div>`
          : `<div class="banner banner-bad"><b>Полный контроль проекта НЕ пройден.</b> Утверждение возможно только с явным подтверждением.
             <ul>${(g.reasons || []).slice(0, 10).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`}
        <div class="frow"><label>Утверждающий</label><input type="text" id="ap-user" value="${esc(STATE.project.meta.author || "")}"></div>
        ${!g.final_allowed ? `<label class="check-line"><input type="checkbox" id="ap-force"> <span>Утвердить несмотря на замечания (я осознаю ответственность)</span></label>` : ""}`,
        `<button class="btn" data-act="closeModal">Отмена</button><button class="btn btn-primary" id="ap-ok">✓ Утвердить</button>`), {
        onOpen: (root) => root.querySelector("#ap-ok").addEventListener("click", async () => {
          const force = root.querySelector("#ap-force")?.checked;
          try {
            await api("/project/status", { method: "POST", body: { status: "approved", by: root.querySelector("#ap-user").value, force } });
            await A.loadProject();
            closeModal();
            A.render();
            toast("Проект утверждён", "ok");
          } catch (e) { /* toast */ }
        }),
      });
    });
  };
  A.actions.newVersion = () => askReason("Создание новой версии (текущая версия будет сохранена как снимок)", async (user, reason) => {
    try {
      const r = await api("/project/new_version", { method: "POST", body: { author: user, reason } });
      await A.loadProject();
      A.render();
      toast("Создана версия " + r.version, "ok");
    } catch (e) { /* toast */ }
  }, { needReason: true, okText: "Создать версию" });

  /* ═══════════════ ЖУРНАЛ ИЗМЕНЕНИЙ ═══════════════ */
  A.views.changelog = async (main) => {
    const log = await api("/changelog");
    const vf = STATE.view.logFilter || "all";
    const rows = log.filter((c) => vf === "all" || c.kind === vf);
    main.innerHTML = A.pageShell("Журнал изменений", "Каждое изменение исходных данных, формул, профилей и экспорт фиксируется (ТЗ п. 21, 41).", "", `
      <div class="pill-tabs">
        ${["all", "edit", "version", "status", "formula", "profile", "export", "calc"].map((k) =>
          `<div class="pill-tab ${vf === k ? "active" : ""}" data-act="logFilter" data-k="${k}">${k === "all" ? "все" : k}</div>`).join("")}
      </div>
      <div class="panel">
        <div class="tbl-wrap"><table class="tbl">
          <tr><th>Дата</th><th>Пользователь</th><th>Тип</th><th>Раздел</th><th>Путь</th><th>Было</th><th>Стало</th><th>Причина</th><th>Версия</th></tr>
          ${rows.map((c) => `<tr>
            <td class="mono nowrap sub">${esc(c.ts)}</td>
            <td>${esc(c.user)}</td>
            <td><span class="chip chip-na">${esc(c.kind)}</span></td>
            <td class="sub">${esc(c.section)}</td>
            <td class="mono sub">${esc(c.path)}</td>
            <td class="sub">${esc(typeof c.old === "object" ? JSON.stringify(c.old) : c.old)}</td>
            <td class="sub">${esc(typeof c.new === "object" ? JSON.stringify(c.new) : c.new)}</td>
            <td class="sub">${esc(c.reason)}</td>
            <td class="mono sub">${esc(c.version)}</td>
          </tr>`).join("") || `<tr><td colspan="9" class="faint">Записей нет</td></tr>`}
        </table></div>
      </div>`);
  };
  A.actions.logFilter = (el) => { STATE.view.logFilter = el.dataset.k; A.render(); };

  /* ═══════════════ АВТОТРАНСФОРМАТОР ═══════════════ */
  A.views.transformer = async (main) => {
    const t = A.draft("transformer");
    const d = STATE.derived;
    const sides = ["HV", "MV", "LV"];
    const sideRu = { HV: "ВН", MV: "СН", LV: "НН" };
    main.innerHTML = A.pageShell("Автотрансформатор · паспорт", "Паспорт объекта, обмотки, u_к, РПН (отдельный объект расчёта), тепловая модель (ТЗ п. 5, 6).", "", `
      <div class="panel">
        <div class="panel-title">Общие данные</div>
        <div class="form-grid">
          ${fSel("transformer", "kind", "Тип объекта", [["auto", "Автотрансформатор (АТ)"], ["auto_group_1ph", "Однофазная группа АТ"], ["two_winding", "Двухобмоточный трансформатор"], ["three_winding", "Трёхобмоточный трансформатор"]])}
          ${fText("transformer", "manufacturer", "Производитель")}
          ${fText("transformer", "type_name", "Тип / марка")}
          ${fText("transformer", "serial_number", "Заводской номер")}
          ${fNum("transformer", "year", "Год выпуска")}
          ${fNum("transformer", "frequency_hz", "Частота", "Гц")}
          ${fNum("transformer", "s_nom_mva", "Номинальная мощность S_ном", "МВА")}
          ${fNum("transformer", "s_typ_mva", "Типовая мощность (АТ)", "МВА", 'placeholder="auto"')}
          ${fNum("transformer", "x0_over_x1", "Отношение X0/X1")}
          ${fText("transformer", "grounding_scheme", "Схема заземления нейтрали")}
        </div>
        ${fArea("transformer", "builtin_protections", "Встроенные защиты (через «;»)", 2)}
      </div>

      <div class="panel">
        <div class="panel-title">Обмотки</div>
        <div class="tbl-wrap"><table class="tbl">
          <tr><th>Обмотка</th><th class="num">U_ном, кВ</th><th class="num">S_ном, МВА</th><th>Соединение</th><th class="num">Часы</th><th>Нейтраль</th><th class="num">Z нейтрали, Ом</th></tr>
          ${sides.filter((s) => t.windings && t.windings[s]).map((s) => `
            <tr>
              <td><b>${sideRu[s]} (${s})</b></td>
              <td class="num"><input type="number" step="any" style="width:90px" data-draft="transformer|windings.${s}.u_nom_kv" value="${t.windings[s].u_nom_kv ?? ""}"></td>
              <td class="num"><input type="number" step="any" style="width:90px" data-draft="transformer|windings.${s}.s_nom_mva" value="${t.windings[s].s_nom_mva ?? ""}" placeholder="S_ном"></td>
              <td><select data-draft="transformer|windings.${s}.connection" style="width:80px">
                ${["YN", "Y", "D", "Z"].map((c) => `<option ${t.windings[s].connection === c ? "selected" : ""}>${c}</option>`).join("")}</select></td>
              <td class="num"><input type="number" style="width:64px" data-draft="transformer|windings.${s}.clock" value="${t.windings[s].clock ?? 0}"></td>
              <td><select data-draft="transformer|windings.${s}.neutral" style="width:110px">
                ${[["solid", "глухо"], ["impedance", "через Z"], ["isolated", "изолирована"]].map(([v, tx]) => `<option value="${v}" ${t.windings[s].neutral === v ? "selected" : ""}>${tx}</option>`).join("")}</select></td>
              <td class="num"><input type="number" step="any" style="width:80px" data-draft="transformer|windings.${s}.neutral_z_ohm" value="${t.windings[s].neutral_z_ohm ?? 0}"></td>
            </tr>`).join("")}
        </table></div>
        ${fCheck("transformer", "regulating_winding", "Есть регулировочная обмотка / ЛРТ")}
      </div>

      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Напряжения короткого замыкания u_к</div>
          <div class="tbl-wrap"><table class="tbl">
            <tr><th>Пара</th><th class="num">u_к min, %</th><th class="num">u_к ном, %</th><th class="num">u_к max, %</th><th class="num">S_отн, МВА</th></tr>
            ${(t.uk ? Object.keys(t.uk) : []).map((pair) => `
              <tr>
                <td><b>${esc(pair)}</b></td>
                <td class="num"><input type="number" step="any" style="width:80px" data-draft="transformer|uk.${pair}.min" value="${t.uk[pair].min ?? ""}"></td>
                <td class="num"><input type="number" step="any" style="width:80px" data-draft="transformer|uk.${pair}.nom" value="${t.uk[pair].nom ?? ""}"></td>
                <td class="num"><input type="number" step="any" style="width:80px" data-draft="transformer|uk.${pair}.max" value="${t.uk[pair].max ?? ""}"></td>
                <td class="num"><input type="number" step="any" style="width:80px" data-draft="transformer|uk.${pair}.s_ref_mva" value="${t.uk[pair].s_ref_mva ?? ""}"></td>
              </tr>
              <tr><td colspan="5" class="sub">Источник: <input type="text" data-draft="transformer|uk.${pair}.source" value="${esc(t.uk[pair].source || "")}"></td></tr>`).join("")}
          </table></div>
          <div class="form-grid" style="margin-top:10px">
            ${fNum("transformer", "p0_kw", "Потери холостого хода P_0", "кВт")}
            ${fNum("transformer", "i0_pct", "Ток холостого хода I_0", "%")}
          </div>
          <div class="faint">Потери КЗ по парам, кВт:</div>
          <div class="form-grid">
            ${(t.pk_kw ? Object.keys(t.pk_kw) : []).map((pair) => fNum("transformer", `pk_kw.${pair}`, `P_к ${pair}`, "кВт")).join("")}
          </div>
        </div>

        <div class="panel">
          <div class="panel-title">РПН — регулирование напряжения</div>
          ${fCheck("transformer", "oltc.present", "РПН имеется")}
          <div class="form-grid">
            ${fSel("transformer", "oltc.side", "Регулируемая сторона", [["HV", "ВН"], ["MV", "СН"], ["LV", "НН"]])}
            ${fSel("transformer", "oltc.location", "Расположение", [["line", "в линии"], ["neutral", "в нейтрали"], ["winding", "в обмотке"], ["separate", "ЛРТ (отдельный)"]])}
            ${fNum("transformer", "oltc.n_steps_minus", "Ступени вниз")}
            ${fNum("transformer", "oltc.n_steps_plus", "Ступени вверх")}
            ${fNum("transformer", "oltc.step_pct", "Ступень регулирования", "%")}
            ${fNum("transformer", "oltc.nominal_position", "Номинальное положение")}
            ${fNum("transformer", "oltc.used_min_position", "Используемое min")}
            ${fNum("transformer", "oltc.used_max_position", "Используемое max")}
          </div>
          ${fText("transformer", "oltc.description", "Описание / данные РПН")}
          ${d.oltc_table && d.oltc_table.length ? `
            <details ${d.oltc_table.length <= 20 ? "open" : ""}><summary class="hint">Таблица положений (${d.oltc_table.length})</summary>
            <div class="tbl-wrap" style="max-height:220px;overflow-y:auto"><table class="tbl">
              <tr><th>№</th><th class="num">ΔU, %</th><th></th></tr>
              ${d.oltc_table.map((r) => `<tr><td class="mono">${r.number}</td><td class="num mono">${nfmt(r.delta_pct)}</td>
                <td>${r.is_min ? `<span class="chip chip-na">min</span>` : ""}${r.is_nom ? `<span class="chip chip-ok">ном</span>` : ""}${r.is_max ? `<span class="chip chip-na">max</span>` : ""}</td></tr>`).join("")}
            </table></div></details>` : ""}
        </div>
      </div>

      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Тепловая модель и перегрузка</div>
          <div class="form-grid">
            ${fNum("transformer", "thermal.k_factor", "k_доп (допустимый длительный ток / I_ном)")}
            ${fNum("transformer", "thermal.tau_min", "Тепловая постоянная τ", "мин")}
            ${fText("transformer", "thermal.cooling", "Охлаждение (напр. ONAN/ONAF)")}
          </div>
          ${fArea("transformer", "thermal.overload_curve", 'Кривая допустимой перегрузки JSON, напр. [{"multiple":1.3,"minutes":120}]', 2)}
          ${fText("transformer", "thermal.curve_source", "Источник кривой перегрузки")}
        </div>
        <div class="panel">
          <div class="panel-title">Производные величины</div>
          <table class="tbl kv-table">
            <tr><td>Группа соединения</td><td>${esc(d.group || "—")}</td></tr>
            <tr><td>Типовая мощность S_тип</td><td class="mono">${nfmt(d.s_typ)} МВА</td></tr>
            <tr><td>α (отношение мощностей)</td><td class="mono">${nfmt(d.alpha)}</td></tr>
          </table>
          <h3 class="sub">Номинальные токи</h3>
          <table class="tbl">
            <tr><th>Сторона</th><th class="num">U, кВ</th><th class="num">S, МВА</th><th class="num">I_ном, А</th></tr>
            ${(d.rated || []).map((r) => `<tr><td>${esc(r.side_ru || r.side)}</td><td class="num mono">${nfmt(r.u_kv)}</td><td class="num mono">${nfmt(r.s_mva)}</td><td class="num mono"><b>${nfmt(r.i_a)}</b></td></tr>`).join("")}
          </table>
        </div>
      </div>
      <div class="panel"><div style="display:flex;gap:9px">${saveBtn("transformer")}</div></div>`);
  };

  /* ═══════════════ СЕТЬ ═══════════════ */
  A.views.network = async (main) => {
    const n = A.draft("network");
    const modes = STATE.project.modes || [];
    main.innerHTML = A.pageShell("Сеть", "Эквиваленты источников (макс/мин), линии, уставки смежных защит для согласования, параллельный АТ (ТЗ п. 8, 16).", "", `
      <div class="panel">
        <div class="panel-title">Базовые напряжения сторон</div>
        <div class="form-grid">
          ${fNum("network", "base_kv.HV", "ВН", "кВ")}
          ${fNum("network", "base_kv.MV", "СН", "кВ")}
          ${fNum("network", "base_kv.LV", "НН", "кВ")}
        </div>
        ${fCheck("network", "parallel_at.present", "На подстанции работает параллельный такой же АТ")}
        <div class="form-grid">
          <div class="frow"><label>Защита шин</label>
            <div>
              ${["HV", "MV", "LV"].map((s) => `<label class="check-line" style="display:inline-flex;margin-right:12px"><input type="checkbox" data-draft="network|bus_protection.${s}" ${n.bus_protection?.[s] ? "checked" : ""}> <span>${s}</span></label>`).join("")}
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">Эквивалентные источники <span class="spacer"></span>
          <button class="btn btn-sm" data-act="addSource">✚ Источник</button></div>
        ${(n.sources || []).map((s, i) => `
          <div class="item-card">
            <div class="head"><span>Источник ${esc(s.id)}</span><span class="spacer"></span>
              <button class="btn btn-sm btn-danger" data-act="delItem" data-section="network" data-path="sources" data-i="${i}">✕ Удалить</button></div>
            <div class="form-grid">
              ${fText("network", `sources.${i}.id`, "ID")}
              ${fText("network", `sources.${i}.name`, "Наименование")}
              ${fSel("network", `sources.${i}.side`, "Сторона подключения", [["HV", "ВН"], ["MV", "СН"], ["LV", "НН"]])}
              ${fText("network", `sources.${i}.notes`, "Примечание")}
            </div>
            <div class="grid grid-2" style="gap:0 16px">
              <div>
                <b class="sub">Режим максимальной мощности КЗ</b>
                <div class="form-grid">
                  ${fNum("network", `sources.${i}.max.r1`, "R1 max", "Ом")}
                  ${fNum("network", `sources.${i}.max.x1`, "X1 max", "Ом")}
                  ${fNum("network", `sources.${i}.max.r0`, "R0 max", "Ом")}
                  ${fNum("network", `sources.${i}.max.x0`, "X0 max", "Ом")}
                </div>
              </div>
              <div>
                <b class="sub">Режим минимальной мощности КЗ</b>
                <div class="form-grid">
                  ${fNum("network", `sources.${i}.min.r1`, "R1 min", "Ом")}
                  ${fNum("network", `sources.${i}.min.x1`, "X1 min", "Ом")}
                  ${fNum("network", `sources.${i}.min.r0`, "R0 min", "Ом")}
                  ${fNum("network", `sources.${i}.min.x0`, "X0 min", "Ом")}
                </div>
              </div>
            </div>
            <button class="btn btn-sm" data-act="zFromSk" data-i="${i}">∑ Рассчитать Z из S_к…</button>
          </div>`).join("") || `<div class="faint">Источники не заданы</div>`}
      </div>

      <div class="panel">
        <div class="panel-title">Линии (смежные элементы) <span class="spacer"></span>
          <button class="btn btn-sm" data-act="addLine">✚ Линия</button></div>
        ${(n.lines || []).map((l, i) => `
          <div class="item-card">
            <div class="head"><span>${esc(l.name)} (${esc(l.id)})</span><span class="spacer"></span>
              <button class="btn btn-sm btn-danger" data-act="delItem" data-section="network" data-path="lines" data-i="${i}">✕ Удалить</button></div>
            <div class="form-grid">
              ${fText("network", `lines.${i}.id`, "ID")}
              ${fText("network", `lines.${i}.name`, "Наименование")}
              ${fSel("network", `lines.${i}.side`, "Сторона", [["HV", "ВН"], ["MV", "СН"], ["LV", "НН"]])}
              ${fNum("network", `lines.${i}.length_km`, "Длина", "км")}
              ${fNum("network", `lines.${i}.r1`, "r1", "Ом/км")}
              ${fNum("network", `lines.${i}.x1`, "x1", "Ом/км")}
              ${fNum("network", `lines.${i}.r0`, "r0", "Ом/км")}
              ${fNum("network", `lines.${i}.x0`, "x0", "Ом/км")}
            </div>
            <details><summary class="hint">Подпитка с противоположного конца и уставки защит линии (для согласования)</summary>
              <div class="form-grid">
                ${fText("network", `lines.${i}.remote_source.id`, "ID противоположного источника")}
                ${fText("network", `lines.${i}.remote_source.name`, "Наименование")}
                ${fNum("network", `lines.${i}.remote_source.max.x1`, "X1 max противоп. источника", "Ом")}
                ${fNum("network", `lines.${i}.remote_source.min.x1`, "X1 min противоп. источника", "Ом")}
              </div>
              ${["dist", "i0", "mtz", "neg"].map((grp) => `
                <div style="margin:8px 0">
                  <b class="sub">Уставки: ${grp} <button class="btn btn-sm" data-act="addStage" data-i="${i}" data-g="${grp}">✚</button></b>
                  ${(l.prot?.[grp] || []).map((st, j) => `
                    <div style="display:flex;gap:8px;align-items:center;margin:4px 0">
                      <input type="number" step="any" style="width:110px" placeholder="I/Z, А/Ом" data-draft="network|lines.${i}.prot.${grp}.${j}.i_a" value="${st.i_a ?? ""}">
                      <input type="number" step="any" style="width:80px" placeholder="t, с" data-draft="network|lines.${i}.prot.${grp}.${j}.t_s" value="${st.t_s ?? 0}">
                      <input type="number" step="any" style="width:90px" placeholder="Z, Ом" data-draft="network|lines.${i}.prot.${grp}.${j}.z_ohm" value="${st.z_ohm ?? ""}">
                      <select data-draft="network|lines.${i}.prot.${grp}.${j}.curve" style="width:110px">
                        ${["definite", "IEC_NI", "IEC_VI", "IEC_EI", "IEC_LTI"].map((c) => `<option ${st.curve === c ? "selected" : ""}>${c}</option>`).join("")}</select>
                      <button class="btn btn-sm btn-danger" data-act="delItem" data-section="network" data-path="lines.${i}.prot.${grp}" data-i="${j}">✕</button>
                    </div>`).join("")}
                </div>`).join("")}
              ${fText("network", `lines.${i}.prot.source`, "Источник уставок смежной защиты")}
            </details>
          </div>`).join("") || `<div class="faint">Линии не заданы — согласование по току/времени недоступно</div>`}
      </div>

      <div class="panel">
        <div class="panel-title">Вышестоящие / нижестоящие защиты (для времятоковых характеристик) <span class="spacer"></span>
          <button class="btn btn-sm" data-act="addTcc">✚ Запись</button></div>
        ${(n.tcc || []).map((te, i) => `
          <div class="item-card">
            <div class="head"><span>${esc(te.name)}</span><span class="spacer"></span>
              <button class="btn btn-sm btn-danger" data-act="delItem" data-section="network" data-path="tcc" data-i="${i}">✕ Удалить</button></div>
            <div class="form-grid">
              ${fText("network", `tcc.${i}.id`, "ID")}
              ${fText("network", `tcc.${i}.name`, "Наименование")}
              ${fSel("network", `tcc.${i}.role`, "Роль", [["upstream", "вышестоящая"], ["downstream", "нижестоящая"]])}
              ${fSel("network", `tcc.${i}.side`, "Сторона", [["HV", "ВН"], ["MV", "СН"], ["LV", "НН"]])}
            </div>
            ${(te.stages || []).map((st, j) => `
              <div style="display:flex;gap:8px;align-items:center;margin:4px 0">
                <span class="sub">Ступень ${j + 1}:</span>
                <input type="number" step="any" style="width:110px" placeholder="I, А" data-draft="network|tcc.${i}.stages.${j}.i_a" value="${st.i_a ?? ""}">
                <input type="number" step="any" style="width:80px" placeholder="t, с" data-draft="network|tcc.${i}.stages.${j}.t_s" value="${st.t_s ?? 0}">
                <input type="number" step="any" style="width:90px" placeholder="Z, Ом" data-draft="network|tcc.${i}.stages.${j}.z_ohm" value="${st.z_ohm ?? ""}">
                <select data-draft="network|tcc.${i}.stages.${j}.curve" style="width:110px">
                  ${["definite", "IEC_NI", "IEC_VI", "IEC_EI", "IEC_LTI"].map((c) => `<option ${st.curve === c ? "selected" : ""}>${c}</option>`).join("")}</select>
                <button class="btn btn-sm btn-danger" data-act="delItem" data-section="network" data-path="tcc.${i}.stages" data-i="${j}">✕</button>
              </div>`).join("")}
            <button class="btn btn-sm" data-act="addTccStage" data-i="${i}">✚ Ступень</button>
            ${fText("network", `tcc.${i}.source`, "Источник уставок")}
          </div>`).join("") || `<div class="faint">Записей нет</div>`}
      </div>
      <div class="panel"><div style="display:flex;gap:9px">${saveBtn("network")}</div></div>`);
  };

  A.actions.addSource = () => {
    A.draft("network").sources.push({ id: "SRC" + (A.draft("network").sources.length + 1), name: "Новый источник", side: "HV", max: { r1: 0, x1: 10, r0: 0, x0: 12 }, min: { r1: 0, x1: 20, r0: 0, x0: 24 }, notes: "" });
    A.render();
  };
  A.actions.addLine = () => {
    A.draft("network").lines.push({ id: "L" + (A.draft("network").lines.length + 1), name: "Новая линия", side: "HV", length_km: 50, r1: 0.075, x1: 0.42, r0: 0.25, x0: 1.3, remote_source: null, prot: { dist: [], i0: [], mtz: [], neg: [], source: "" } });
    A.render();
  };
  A.actions.addTcc = () => {
    A.draft("network").tcc.push({ id: "T" + (A.draft("network").tcc.length + 1), name: "Новая защита", role: "upstream", side: "HV", stages: [{ i_a: 500, t_s: 1.0 }], source: "" });
    A.render();
  };
  A.actions.addTccStage = (el) => {
    A.draft("network").tcc[Number(el.dataset.i)].stages.push({ i_a: null, t_s: 0 });
    A.render();
  };
  A.actions.addStage = (el) => {
    const l = A.draft("network").lines[Number(el.dataset.i)];
    l.prot = l.prot || { dist: [], i0: [], mtz: [], neg: [], source: "" };
    l.prot[el.dataset.g] = l.prot[el.dataset.g] || [];
    l.prot[el.dataset.g].push({ i_a: null, t_s: 0, z_ohm: null, curve: "definite" });
    A.render();
  };
  A.actions.delItem = (el) => {
    const p = el.dataset.path;
    const arr = p ? A.getPath(A.draft(el.dataset.section), p) : A.draft(el.dataset.section);
    if (Array.isArray(arr)) arr.splice(Number(el.dataset.i), 1);
    A.render();
  };
  A.actions.zFromSk = (el) => {
    const i = Number(el.dataset.i);
    modal(modalShell("Эквивалент источника из мощности КЗ", `
      <div class="form-grid">
        <div class="frow"><label>Напряжение шин U <span class="unit">[кВ]</span></label><input type="number" id="sk-u" step="any" value="${STATE.project.network.base_kv[A.draft("network").sources[i].side] || 230}"></div>
        <div class="frow"><label>S_к (3ф) <span class="unit">[МВА]</span></label><input type="number" id="sk-s" step="any" value="5000"></div>
        <div class="frow"><label>X/R</label><input type="number" id="sk-xr" step="any" value="10"></div>
        <div class="frow"><label>X0/X1</label><input type="number" id="sk-x0x1" step="any" value="1.2"></div>
      </div>
      <div class="hint">|Z1| = U²/S_к. Результат заполнит выбранную группу (max или min) источника ${esc(A.draft("network").sources[i].id)}.</div>
      <label class="check-line"><input type="checkbox" id="sk-tomin"> <span>Заполнить режим «min» (по умолчанию — «max»)</span></label>`,
      `<button class="btn" data-act="closeModal">Отмена</button><button class="btn btn-primary" id="sk-ok">Рассчитать и заполнить</button>`), {
      onOpen: (root) => root.querySelector("#sk-ok").addEventListener("click", () => {
        const u = Number(root.querySelector("#sk-u").value), sk = Number(root.querySelector("#sk-s").value);
        const xr = Number(root.querySelector("#sk-xr").value), x0x1 = Number(root.querySelector("#sk-x0x1").value);
        if (!(u > 0 && sk > 0)) { toast("Проверьте U и S_к", "err"); return; }
        const z = (u * u) / sk;
        const x1 = z * xr / Math.hypot(1, xr), r1 = z / Math.hypot(1, xr);
        const x0 = x1 * x0x1, r0 = r1 * x0x1;
        const grp = root.querySelector("#sk-tomin").checked ? "min" : "max";
        Object.assign(A.draft("network").sources[i][grp], { r1: +r1.toFixed(5), x1: +x1.toFixed(5), r0: +r0.toFixed(5), x0: +x0.toFixed(5) });
        closeModal();
        A.render();
        toast(`Z источника рассчитан: |Z1| = ${nfmt(z)} Ом`, "ok");
      }),
    });
  };

  /* ═══════════════ РЕЖИМЫ ═══════════════ */
  A.views.modes = async (main) => {
    const modes = A.draft("modes");
    const srcIds = (A.draft("network").sources || []).map((s) => s.id);
    const roleNames = { max_kz: "макс. КЗ", min_kz: "мин. КЗ", load: "нагрузка", post_accident: "послеаварийный", energization: "опробование" };
    main.innerHTML = A.pageShell("Библиотека режимов", "Каждый режим имеет идентификатор и роли (ТЗ п. 27). Положения РПН перебираются автоматически (ТЗ п. 28).", "", `
      <div class="panel">
        <div class="panel-title">Режимы (${modes.length}) <span class="spacer"></span>
          <button class="btn btn-sm" data-act="addMode">✚ Пользовательский режим</button>
          <button class="btn btn-sm btn-accent" data-act="regenModes">↺ Пересоздать библиотеку</button></div>
        <div class="tbl-wrap"><table class="tbl">
          <tr><th>ID</th><th>Наименование</th><th>Роли</th><th>Источники</th><th>Пар. АТ</th><th>РПН</th><th class="num">k_нагр</th><th class="num">c</th><th></th></tr>
          ${modes.map((m, i) => `
            <tr>
              <td class="mono"><input type="text" style="width:100px" data-draft="modes|${i}.id" value="${esc(m.id)}" ${m.builtin ? "disabled" : ""}></td>
              <td><input type="text" data-draft="modes|${i}.name" value="${esc(m.name)}" ${m.builtin ? "disabled" : ""}></td>
              <td>${(m.roles || []).map((r) => `<span class="chip chip-na">${esc(roleNames[r] || r)}</span>`).join(" ")}</td>
              <td>${srcIds.map((sid) => `
                <div style="display:flex;gap:5px;align-items:center;margin:2px 0">
                  <span class="sub mono">${esc(sid)}</span>
                  <select data-draft="modes|${i}.sources.${sid}" style="width:86px">
                    ${[["max", "max"], ["min", "min"], ["off", "откл"]].map(([v, t]) => `<option value="${v}" ${(m.sources || {})[sid] === v ? "selected" : ""}>${t}</option>`).join("")}
                  </select>
                </div>`).join("")}</td>
              <td><input type="checkbox" data-draft="modes|${i}.parallel_at" ${m.parallel_at ? "checked" : ""}></td>
              <td><select data-draft="modes|${i}.tap" style="width:96px">
                ${[["", "min/nom/max"], ["min", "min"], ["nom", "ном"], ["max", "max"]].map(([v, t]) => `<option value="${v}" ${String(m.tap || "") === v ? "selected" : ""}>${t}</option>`).join("")}
              </select></td>
              <td class="num"><input type="number" step="any" style="width:72px" data-draft="modes|${i}.load_factor" value="${m.load_factor ?? ""}" ${m.builtin ? "disabled" : ""}></td>
              <td class="num"><input type="number" step="any" style="width:64px" data-draft="modes|${i}.c_factor" value="${m.c_factor ?? ""}" ${m.builtin ? "disabled" : ""}></td>
              <td>${m.builtin ? `<span class="chip chip-na">встроенный</span>` : `<button class="btn btn-sm btn-danger" data-act="delItem" data-section="modes" data-path="" data-i="${i}">✕</button>`}</td>
            </tr>
            <tr><td colspan="9" class="sub">Описание: <input type="text" data-draft="modes|${i}.description" value="${esc(m.description || "")}" ${m.builtin ? "disabled" : ""}></td></tr>`).join("")}
        </table></div>
      </div>
      <div class="panel"><div style="display:flex;gap:9px">${saveBtn("modes")}</div></div>`);
  };
  A.actions.addMode = () => {
    A.draft("modes").push({ id: "CUSTOM" + (A.draft("modes").length + 1), name: "Пользовательский режим", kind: "custom", roles: ["min_kz"], sources: {}, parallel_at: false, tap: null, load_factor: 1, c_factor: 1, description: "", builtin: false });
    A.render();
  };
  A.actions.regenModes = () => askReason("Пересоздание библиотеки режимов по составу источников (пользовательские режимы сохранятся)", async (user, reason) => {
    await api("/project/regen_modes", { method: "POST", body: { user, reason } });
    A.dropDraft("modes");
    await A.loadProject();
    A.render();
  }, { okText: "Пересоздать" });

  /* ═══════════════ ТТ / ТН ═══════════════ */
  A.views.ctvt = async (main) => {
    const cts = A.draft("cts");
    const vts = A.draft("vts");
    const derived = STATE.derived;
    const locs = [["built_in", "встроенный"], ["external", "выносной"], ["breaker", "ТТ выключателя"], ["bushing", "ТТ ввода"], ["neutral", "ТТ нейтрали"], ["zero_seq", "ТТ нул. послед."]];
    main.innerHTML = A.pageShell("Трансформаторы тока и напряжения", "ТТ: классы, нагрузка, предельная кратность, схемы, назначение защитам (ТЗ п. 7).", "", `
      <div class="panel">
        <div class="panel-title">Трансформаторы тока (${cts.length}) <span class="spacer"></span>
          <button class="btn btn-sm" data-act="addCt">✚ ТТ</button></div>
        ${cts.map((c, i) => `
          <div class="item-card">
            <div class="head"><span>${esc(c.name || c.id)} · ${esc(c.side)}</span><span class="spacer"></span>
              <button class="btn btn-sm btn-danger" data-act="delItem" data-section="cts" data-path="" data-i="${i}">✕ Удалить</button></div>
            <div class="form-grid">
              ${fText("cts", `${i}.id`, "ID")}
              ${fText("cts", `${i}.name`, "Наименование")}
              ${fSel("cts", `${i}.side`, "Сторона", [["HV", "ВН"], ["MV", "СН"], ["LV", "НН"], ["N", "Нейтраль"]])}
              ${fSel("cts", `${i}.location`, "Расположение", locs)}
              ${fNum("cts", `${i}.i1_a`, "Первичный ток I1", "А")}
              ${fNum("cts", `${i}.i2_a`, "Вторичный ток I2", "А")}
              ${fText("cts", `${i}.accuracy_class`, "Класс точности")}
              ${fText("cts", `${i}.protection_class`, "Класс защиты")}
              ${fNum("cts", `${i}.alf`, "Номинальная предельная кратность K_ном")}
              ${fNum("cts", `${i}.s_nom_va`, "Номинальная нагрузка S_ном", "ВА")}
              ${fNum("cts", `${i}.s_fact_va`, "Фактическая нагрузка S_факт", "ВА")}
              ${fNum("cts", `${i}.r_winding_ohm`, "R вторичной обмотки", "Ом")}
              ${fNum("cts", `${i}.r_circuit_ohm`, "R вторичной цепи", "Ом", 'placeholder="из S_факт"')}
              ${fSel("cts", `${i}.connection`, "Схема соединения", [["Y", "звезда (Y)"], ["D", "треугольник (D)"]])}
              ${fSel("cts", `${i}.polarity`, "Полярность (начало Л1)", [["to_object", "в сторону объекта"], ["to_bus", "в сторону шин"]])}
            </div>
            ${fText("cts", `${i}.purpose`, "Назначение")}
            <div class="frow"><label>Принадлежность защитам (через «;»)</label>
              <input type="text" data-draft="cts|${i}.protections_join" value="${esc((c.protections || []).join("; "))}" data-onchange="ctProt"></div>
            ${(() => {
              const dd = (derived.cts || []).find((x) => x.id === c.id);
              return dd ? `<div class="hint">k_т = ${nfmt(dd.ratio)} · K_дейст = ${nfmt(dd.alf_actual)} · I_нас (первичный) ≈ ${nfmt(dd.i_no_sat_a)} А</div>` : "";
            })()}
          </div>`).join("") || `<div class="faint">ТТ не заданы — расчёт защит невозможен</div>`}
      </div>

      <div class="panel">
        <div class="panel-title">Трансформаторы напряжения (${vts.length}) <span class="spacer"></span>
          <button class="btn btn-sm" data-act="addVt">✚ ТН</button></div>
        ${vts.map((v, i) => `
          <div class="item-card">
            <div class="head"><span>${esc(v.name || v.id)}</span><span class="spacer"></span>
              <button class="btn btn-sm btn-danger" data-act="delItem" data-section="vts" data-path="" data-i="${i}">✕ Удалить</button></div>
            <div class="form-grid">
              ${fText("vts", `${i}.id`, "ID")}
              ${fText("vts", `${i}.name`, "Наименование")}
              ${fSel("vts", `${i}.side`, "Сторона", [["HV", "ВН"], ["MV", "СН"], ["LV", "НН"]])}
              ${fNum("vts", `${i}.u1_kv`, "Первичное напряжение U1", "кВ")}
              ${fNum("vts", `${i}.u2_v`, "Вторичное (междуфазное) U2", "В")}
              ${fNum("vts", `${i}.u2_delta_v`, "3U0 (обр. треугольник)", "В")}
              ${fText("vts", `${i}.accuracy_class`, "Класс точности")}
              ${fText("vts", `${i}.connection`, "Схема")}
            </div>
          </div>`).join("") || `<div class="faint">ТН не заданы</div>`}
      </div>
      <div class="panel"><div style="display:flex;gap:9px">${saveBtn("cts")}<span class="hint" style="align-self:center">Сохранение раздела «ТТ» и «ТН» выполняется вместе (черновик раздела cts/vts).</span></div>
      <div style="margin-top:8px">${saveBtn("vts", "Сохранить ТН")}</div></div>`);
  };
  A.actions.ctProt = (el) => {
    const [section, i] = el.dataset.draft.split("|");
    A.draft("cts")[Number(i)].protections = el.value.split(";").map((x) => x.trim()).filter(Boolean);
  };
  A.actions.addCt = () => {
    A.draft("cts").push({ id: "TA" + (A.draft("cts").length + 1), name: "Новый ТТ", side: "HV", location: "breaker", purpose: "Защита", protections: ["87T", "50/51"], i1_a: 600, i2_a: 1, accuracy_class: "5P", protection_class: "5P20", alf: 20, s_nom_va: 30, s_fact_va: 10, r_winding_ohm: 3, r_circuit_ohm: null, connection: "Y", polarity: "to_object" });
    A.render();
  };
  A.actions.addVt = () => {
    A.draft("vts").push({ id: "TV" + (A.draft("vts").length + 1), name: "Новый ТН", side: "HV", u1_kv: 220, u2_v: 100, u2_delta_v: 100, accuracy_class: "0.5/3P", connection: "Y/Y/Δ" });
    A.render();
  };

  /* ═══════════════ ТОКИ КЗ ═══════════════ */
  A.views.kz = async (main) => {
    const meta = await api("/kz/meta");
    const v = STATE.view.kz = STATE.view.kz || { mode: meta.modes[0]?.id || "", ftypes: "3ph,2ph,2ph_g,1ph", nodes: "" };
    const rows = await api(`/kz/table?${new URLSearchParams({ ...(v.mode ? { mode: v.mode } : {}), ...(v.nodes ? { nodes: v.nodes } : {}), ftypes: v.ftypes })}`);
    const ftypeRu = { "3ph": "трёхфазное", "2ph": "двухфазное", "2ph_g": "двухфазное на землю", "1ph": "однофазное на землю" };
    main.innerHTML = A.pageShell("Расчёт токов короткого замыкания",
      "Все виды КЗ в режимах max/min, по сторонам и за трансформатором; результаты автоматически используются защитами (ТЗ п. 8).", "", `
      <div class="panel">
        <div class="filters">
          <div class="frow"><label>Режим</label>
            <select id="kz-mode">
              <option value="">— все режимы —</option>
              ${meta.modes.map((m) => `<option value="${esc(m.id)}" ${v.mode === m.id ? "selected" : ""}>${esc(m.name)}</option>`).join("")}
            </select></div>
          <div class="frow"><label>Узлы КЗ</label>
            <select id="kz-nodes">
              <option value="">— все —</option>
              ${meta.nodes.map((n) => `<option value="${esc(n)}" ${v.nodes === n ? "selected" : ""}>${esc(n)}</option>`).join("")}
            </select></div>
          <div class="frow"><label>Виды КЗ</label>
            <div style="display:flex;gap:10px;padding-top:6px">
              ${Object.keys(ftypeRu).map((f) => `<label class="check-line" style="margin:0"><input type="checkbox" class="kz-ft" value="${f}" ${v.ftypes.includes(f) ? "checked" : ""}> <span class="sub">${ftypeRu[f]}</span></label>`).join("")}
            </div>
          </div>
          <button class="btn btn-primary" id="kz-apply">Показать</button>
        </div>
        <div class="tbl-wrap" style="max-height:64vh;overflow-y:auto"><table class="tbl">
          <tr><th>Режим</th><th>РПН</th><th>Узел</th><th>Вид КЗ</th><th class="num">I_к, А</th><th class="num">Z1, Ом</th><th class="num">Z0, Ом</th>
            <th class="num">I_ВН max, А</th><th class="num">I_СН max, А</th><th class="num">I_НН max, А</th><th class="num">3I0 нейтр., А</th></tr>
          ${rows.map((r) => `<tr class="click" data-act="kzDetail" data-mode="${esc(r.mode)}" data-tap="${esc(r.tap)}" data-node="${esc(r.node)}" data-ftype="${esc(r.ftype)}">
            <td>${esc(r.mode)}</td>
            <td class="mono">${esc(r.tap)} <span class="sub">поз. ${r.position ?? "—"}</span></td>
            <td><b>${esc(r.node)}</b></td>
            <td class="sub">${ftypeRu[r.ftype] || esc(r.ftype)}</td>
            <td class="num mono"><b>${nfmt(r.i_fault_a)}</b></td>
            <td class="num mono">${nfmt(r.z1)}</td>
            <td class="num mono">${nfmt(r.z0)}</td>
            <td class="num mono">${nfmt(r.i_HV_max_a)}</td>
            <td class="num mono">${nfmt(r.i_MV_max_a)}</td>
            <td class="num mono">${nfmt(r.i_LV_max_a)}</td>
            <td class="num mono">${nfmt(r.i_neutral_a)}</td>
          </tr>`).join("") || `<tr><td colspan="11" class="faint">Нет данных — измените фильтры</td></tr>`}
        </table></div>
        <div class="hint" style="margin-top:8px">Строка таблицы — расчётный случай: режим → положение РПН → узел → вид КЗ. Нажмите строку для детального расчёта.</div>
      </div>`);
    const apply = () => {
      v.mode = document.getElementById("kz-mode").value;
      v.nodes = document.getElementById("kz-nodes").value;
      v.ftypes = [...document.querySelectorAll(".kz-ft:checked")].map((x) => x.value).join(",") || "3ph";
      A.render();
    };
    document.getElementById("kz-apply").addEventListener("click", apply);
    document.querySelectorAll(".kz-ft").forEach((x) => x.addEventListener("change", apply));
    document.getElementById("kz-mode").addEventListener("change", apply);
    document.getElementById("kz-nodes").addEventListener("change", apply);
  };
  A.actions.kzDetail = async (el) => {
    const { mode, tap, node, ftype } = el.dataset;
    const d = await api(`/kz/detail?mode=${encodeURIComponent(mode)}&tap=${encodeURIComponent(tap)}&node=${encodeURIComponent(node)}&ftype=${encodeURIComponent(ftype)}`);
    const cx = (z) => `${nfmt(z.abs)} ∠ ${nfmt(z.deg)}°`;
    const sidesRu = { HV: "ВН", MV: "СН", LV: "НН" };
    modal(modalShell(`КЗ: ${esc(mode)} · РПН ${esc(tap)} · ${esc(node)} · ${esc(ftype)}`, `
      <h3 class="sub">Токи фаз в точке КЗ</h3>
      <table class="tbl"><tr><th>Фаза</th><th class="num">I, А</th><th class="num">∠, °</th></tr>
        ${d.fault.map((z, i) => `<tr><td>${"ABC"[i]}</td><td class="num mono">${nfmt(z.abs)}</td><td class="num mono">${nfmt(z.deg)}</td></tr>`).join("")}
      </table>
      <h3 class="sub">Составляющие последовательности</h3>
      <table class="tbl">
        <tr><th>Величина</th><th class="num">Значение</th></tr>
        <tr><td>I1</td><td class="num mono">${cx(d.seq[0])}</td></tr>
        <tr><td>I2</td><td class="num mono">${cx(d.seq[1])}</td></tr>
        <tr><td>I0</td><td class="num mono">${cx(d.seq[2])}</td></tr>
        <tr><td>Z1</td><td class="num mono">${cx(d.z[0])}</td></tr>
        <tr><td>Z2</td><td class="num mono">${cx(d.z[1])}</td></tr>
        <tr><td>Z0</td><td class="num mono">${cx(d.z[2])}</td></tr>
        <tr><td>3I0 в нейтрали</td><td class="num mono">${cx(d.neutral_3i0)}</td></tr>
      </table>
      ${Object.entries(d.sides).map(([s, sd]) => `
        <h3 class="sub">Сторона ${sidesRu[s] || esc(s)}</h3>
        <table class="tbl">
          <tr><th>Фаза</th><th class="num">I, А</th><th class="num">U, кВ</th></tr>
          ${[0, 1, 2].map((i) => `<tr><td>${"ABC"[i]}</td><td class="num mono">${cx(sd.i[i])}</td><td class="num mono">${cx(sd.u[i])}</td></tr>`).join("")}
          <tr class="sum"><td>I1 / I2 / I0</td><td class="num mono" colspan="2">${cx(sd.i1)} · ${cx(sd.i2)} · ${cx(sd.i0)}</td></tr>
        </table>`).join("")}
      ${d.flags && Object.keys(d.flags).length ? `<div class="hint">Признаки: ${Object.entries(d.flags).map(([k, v]) => `${esc(k)}=${esc(v)}`).join(", ")}</div>` : ""}`,
      `<button class="btn btn-primary" data-act="closeModal">Закрыть</button>`, true));
  };

  /* ═══════════════ СТРАНИЦЫ ФУНКЦИЙ ЗАЩИТ ═══════════════ */
  const fnPage = (fid) => async (main) => {
    let res;
    try {
      res = await api(`/results/${encodeURIComponent(fid)}`);
    } catch (e) {
      main.innerHTML = A.pageShell(fnTitles[fid] || fid, "", "",
        `<div class="banner banner-warn">Функция не рассчитана. Выполните расчёт (▶ Рассчитать) и проверьте исходные данные.</div>`);
      return;
    }
    const params = res.params || [];
    const checks = res.checks || [];
    const groups = {};
    for (const p of params) (groups[p.group || "Параметры"] = groups[p.group || "Параметры"] || []).push(p);

    let charts = "";
    if (fid === "87T") {
      const ch = await api("/chart/87t");
      charts = `<div class="panel"><div class="panel-title">Характеристика дифференциальной защиты</div>
        ${A.svg87t(ch)}
        <div class="hint">Синие точки — режимы внешних КЗ (небаланс), красные — КЗ в зоне. График строится по расчётным и принятым уставкам.</div></div>`;
    }
    if (fid === "50/51") {
      const sides = (STATE.derived.sides || []).map((s) => s.side);
      if (sides.length) {
        charts = `<div class="panel"><div class="panel-title">Времятоковые характеристики и зона селективности</div>
          <div class="pill-tabs">${sides.map((s, i) => `<div class="pill-tab ${i === 0 ? "active" : ""}" data-act="tccSide" data-side="${s}">${s}</div>`).join("")}</div>
          <div id="tcc-chart">Загрузка…</div></div>`;
        setTimeout(() => A.actions.tccSide({ dataset: { side: sides[0] } }), 0);
      }
    }

    main.innerHTML = A.pageShell(fnTitles[fid] || fid,
      `Универсальная модель функции (PFM) → расчёт → критерии → проверки. Нажмите «Показать расчёт» у любого параметра (ТЗ п. 20).`, "", `
      ${res.missing?.length ? `<div class="banner banner-orng banner-warn"><b>Не хватает исходных данных:</b><ul>${res.missing.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>` : ""}
      ${res.warnings?.length ? `<div class="banner banner-warn"><b>Предупреждения:</b><ul>${res.warnings.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>` : ""}
      ${Object.entries(groups).map(([g, ps]) => `
        <div class="panel">
          <div class="panel-title">${esc(g)}</div>
          <div class="tbl-wrap"><table class="tbl">
            <tr><th>Параметр</th><th class="num">Расчётная уставка</th><th class="num">Допустимый интервал</th><th>Статус</th><th>Основание / критерий</th><th></th></tr>
            ${ps.map((p) => `
              <tr>
                <td><div class="param-name">${esc(p.title)}</div><div class="param-key">${esc(p.key)}${p.instance ? " @" + esc(p.instance) : ""} · ${esc(p.unit || "")}</div></td>
                <td class="num"><span class="big-val">${p.calc == null ? "—" : nfmt(p.calc)}</span></td>
                <td class="num mono sub">${p.lower != null || p.upper != null ? `${nfmt(p.lower)} … ${nfmt(p.upper)}` : "—"}</td>
                <td>${statusChip(p.status, p.icon + " " + p.status_label)}${p.reason ? `<div class="sub">${esc(p.reason)}</div>` : ""}</td>
                <td class="sub">${(p.criteria || []).slice(0, 3).map((c) => `<div>${esc(c.title)}${c.value != null ? `: ${nfmt(c.value)}` : ""} <span class="faint">${esc(c.ref)}</span></div>`).join("")}</td>
                <td><button class="btn btn-sm" data-act="openTrace" data-fn="${esc(fid)}" data-key="${esc(p.key)}">Показать расчёт</button></td>
              </tr>`).join("")}
          </table></div>
        </div>`).join("")}
      ${charts}
      <div class="panel">
        <div class="panel-title">Проверки функции (${checks.length})</div>
        ${checks.map((c) => `
          <div class="item-card">
            <div class="head">${statusChip(c.status, c.icon + " " + c.status_label)} <span>${esc(c.title)}</span>
              <span class="spacer"></span>
              <button class="btn btn-sm" data-act="openCheck" data-cid="${esc(c.id)}" data-scope="calc">Подробнее</button></div>
            <div>${esc(c.reason)}</div>
            <div class="faint">Значение: <b class="mono">${nfmt(c.value)}</b> ${esc(c.unit || "")} ${c.threshold != null ? `· требование: ${esc(c.cmp)} ${nfmt(c.threshold)}` : ""}
              ${c.worst && Object.keys(c.worst).length ? ` · наихудший случай: ${Object.entries(c.worst).map(([k, v]) => `${esc(k)}=${esc(v)}`).join(", ")}` : ""}</div>
          </div>`).join("") || `<div class="faint">Проверок нет</div>`}
      </div>`);
  };
  for (const fid of ["87T", "50/51", "46", "50N/51N", "21", "49"]) A.views["fn-" + fid] = fnPage(fid);

  A.actions.tccSide = async (el) => {
    const side = el.dataset.side;
    document.querySelectorAll("[data-act=tccSide]").forEach((x) => x.classList.toggle("active", x.dataset.side === side));
    const box = document.getElementById("tcc-chart");
    if (!box) return;
    box.innerHTML = "Загрузка…";
    try {
      const d = await api(`/chart/tcc?side=${encodeURIComponent(side)}`);
      box.innerHTML = A.svgTcc(d)
        + (d.available && d.checks?.length ? `<div class="tbl-wrap" style="margin-top:10px"><table class="tbl">
            <tr><th>Смежная защита</th><th>Роль</th><th class="num">Запас времени</th><th>Статус</th></tr>
            ${d.checks.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.role === "upstream" ? "вышестоящая" : "нижестоящая"}</td>
              <td class="num mono">${nfmt(c.margin)} с</td><td>${c.ok ? `<span class="chip chip-ok">селективно</span>` : `<span class="chip chip-bad">нарушение</span>`}</td></tr>`).join("")}
          </table></div>` : "");
    } catch (e) {
      box.innerHTML = `<div class="faint">График недоступен: ${esc(e.message)}</div>`;
    }
  };

  /* ═══════════════ ПРОВЕРКИ ═══════════════ */
  A.views.checks = async (main) => {
    const all = await api("/checks");
    const v = STATE.view.checks = STATE.view.checks || { kind: "all", status: "all" };
    const kindRu = { sensitivity: "чувствительность", stability: "устойчивость", selectivity: "селективность", coordination: "согласование", ct: "ТТ", requirement: "требование", data: "данные" };
    const rows = all.filter((c) => (v.kind === "all" || c.kind === v.kind) && (v.status === "all" || c.status === v.status));
    main.innerHTML = A.pageShell("Проверки чувствительности, устойчивости и селективности",
      "Статусы: 🟢 выполнено · 🟡 требуется проверка · 🔴 не выполнено — с обязательным указанием причины (ТЗ п. 15, 16).", "", `
      <div class="panel">
        <div class="filters">
          <div class="frow"><label>Вид проверки</label><select id="ck-kind">
            <option value="all">все</option>
            ${Object.entries(kindRu).map(([k, t]) => `<option value="${k}" ${v.kind === k ? "selected" : ""}>${t}</option>`).join("")}
          </select></div>
          <div class="frow"><label>Статус</label><select id="ck-status">
            ${[["all", "все"], ["ok", "🟢 выполнено"], ["check", "🟡 требуется проверка"], ["fail", "🔴 не выполнено"]].map(([k, t]) => `<option value="${k}" ${v.status === k ? "selected" : ""}>${t}</option>`).join("")}
          </select></div>
          <div class="frow"><label>&nbsp;</label><span class="hint">Всего проверок: ${all.length}, отобрано: ${rows.length}</span></div>
        </div>
        <div class="tbl-wrap" style="max-height:66vh;overflow-y:auto"><table class="tbl">
          <tr><th>Функция</th><th>Проверка</th><th>Вид</th><th class="num">Значение</th><th class="num">Требование</th><th>Статус</th><th>Наихудший случай</th><th></th></tr>
          ${rows.map((c) => `
            <tr>
              <td class="mono"><b>${esc(c.function)}</b>${c.terminal_label ? `<div class="sub">${esc(c.terminal_label)}</div>` : ""}</td>
              <td>${esc(c.title)}</td>
              <td class="sub">${esc(kindRu[c.kind] || c.kind)}</td>
              <td class="num mono">${nfmt(c.value)}</td>
              <td class="num mono">${esc(c.cmp)} ${nfmt(c.threshold)}</td>
              <td>${statusChip(c.status, c.icon + " " + c.status_label)}</td>
              <td class="sub">${c.worst && Object.keys(c.worst).length ? Object.entries(c.worst).map(([k, val]) => `${esc(k)}: ${esc(val)}`).join(" · ") : "—"}</td>
              <td><button class="btn btn-sm" data-act="openCheck" data-cid="${esc(c.id)}" data-scope="${esc(c.scope)}" data-terminal="${esc(c.terminal || "")}">Показать расчёт</button></td>
            </tr>`).join("") || `<tr><td colspan="8" class="faint">Нет проверок по фильтру</td></tr>`}
        </table></div>
      </div>`);
    document.getElementById("ck-kind").addEventListener("change", (e) => { v.kind = e.target.value; A.render(); });
    document.getElementById("ck-status").addEventListener("change", (e) => { v.status = e.target.value; A.render(); });
  };

  /* ═══════════════ БАЗА УСТРОЙСТВ (ТЕРМИНАЛЫ) ═══════════════ */
  A.views.terminals = async (main) => {
    const list = await api("/terminals");
    main.innerHTML = A.pageShell("База терминалов РЗА",
      "Расширяемая база: профили загружаются из каталога и добавляются пользователем через конструктор (ТЗ п. 11, 35, 36). Добавление устройства не требует изменения расчётного ядра.", "", `
      <div class="panel">
        <div class="panel-title">Устройства (${list.length}) <span class="spacer"></span>
          <button class="btn btn-accent" data-act="wizardOpen">✚ Добавить устройство (конструктор)</button></div>
        <div class="grid grid-2">
          ${list.map((t) => `
            <div class="item-card">
              <div class="head">${statusChip(t.status, t.status_label)} <span>${esc(t.label)}</span></div>
              <div class="hint mono">${esc(t.id)}</div>
              <div style="margin:7px 0;display:flex;flex-wrap:wrap;gap:5px">
                ${Object.entries(t.functions || {}).filter(([, v]) => v).map(([f]) => `<span class="chip chip-ok">${esc(f)}</span>`).join("") || `<span class="faint">функции не описаны</span>`}
              </div>
              <div class="faint">Параметров: ${t.n_params} · сигналов: ${t.n_signals} · адаптер: ${esc(t.adapter)} · происхождение: ${t.origin === "builtin" ? "встроенный" : "пользовательский"}</div>
              <div style="display:flex;gap:7px;margin-top:9px;flex-wrap:wrap">
                <button class="btn btn-sm btn-primary" data-act="profileDetail" data-id="${esc(t.id)}">Профиль</button>
                <a class="btn btn-sm" href="/api/terminals/${encodeURIComponent(t.id)}/export.json">⬇ JSON</a>
                <button class="btn btn-sm" data-act="assignOne" data-id="${esc(t.id)}">Назначить проекту</button>
                ${t.origin === "user" ? `<button class="btn btn-sm btn-danger" data-act="profileDelete" data-id="${esc(t.id)}">Удалить</button>` : ""}
              </div>
            </div>`).join("")}
        </div>
      </div>`);
  };

  A.actions.assignOne = async (el) => {
    const t = await api(`/terminals/${encodeURIComponent(el.dataset.id)}`);
    const funcs = Object.entries(t.functions || {}).filter(([, v]) => v && v.supported !== false).map(([k]) => k);
    const cur = clone(STATE.project.terminals || []);
    if (!cur.find((x) => x.terminal_id === t.id)) {
      cur.push({ terminal_id: t.id, variant: "", firmware: t.firmware || "", functions: funcs, side_map: {}, note: "" });
      await A.saveSection("terminals", cur, STATE.project.meta.author, "Назначение терминала " + t.id);
    } else {
      toast("Терминал уже назначен проекту");
    }
  };
  A.actions.profileDelete = (el) => askReason("Удаление пользовательского профиля " + el.dataset.id, async () => {
    await api(`/terminals/${encodeURIComponent(el.dataset.id)}`, { method: "DELETE" });
    A.render();
    toast("Профиль удалён", "ok");
  }, { needReason: true, okText: "Удалить" });

  A.actions.profileDetail = async (el) => {
    const d = await api(`/terminals/${encodeURIComponent(el.dataset.id)}`);
    const params = d.parameters || [];
    modal(modalShell(`Профиль · ${esc(d.manufacturer)} ${esc(d.model)} ${esc(d.firmware || "")}`, `
      ${d._validation?.length ? `<div class="banner ${d._validation.some((i) => i.level === "error") ? "banner-bad" : "banner-warn"}">
        <ul>${d._validation.map((i) => `<li>[${esc(i.level)}] ${esc(i.message)}</li>`).join("")}</ul></div>`
        : `<div class="banner banner-ok">Профиль не содержит замечаний.</div>`}
      <table class="tbl" style="margin-bottom:12px">
        <tr><td>ID / схема</td><td class="mono">${esc(d.id)} · ${esc(d.schema)}</td></tr>
        <tr><td>Версия ПО</td><td>${esc(d.firmware || "—")}</td></tr>
        <tr><td>Исполнения</td><td>${(d.variants || []).map(esc).join(", ") || "—"}</td></tr>
        <tr><td>IEC 61850</td><td>${Object.entries(d.iec61850 || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</td></tr>
      </table>
      <h3 class="sub">Поддерживаемые функции</h3>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${Object.entries(d.functions || {}).map(([f, cfg]) => cfg && cfg.supported ? `<span class="chip chip-ok" title="${esc(cfg.note || "")}">${esc(f)}${cfg.group ? " · " + esc(cfg.group) : ""}</span>` : `<span class="chip chip-na">${esc(f)}</span>`).join("")}
      </div>
      <h3 class="sub">Параметры (${params.length})</h3>
      <div class="tbl-wrap" style="max-height:320px;overflow-y:auto"><table class="tbl">
        <tr><th>Ключ</th><th>Наименование</th><th class="num">Ед.</th><th class="num">Min</th><th class="num">Max</th><th class="num">Шаг</th><th>Соответствие PFM</th><th>Источник</th></tr>
        ${params.map((p) => {
          const m = (d.mapping || {});
          const pfm = Object.entries(m).find(([, cfg]) => Object.values(cfg.instances || {}).includes(p.key));
          return `<tr>
            <td class="mono sub">${esc(p.key)}</td>
            <td>${esc(p.name)}</td>
            <td class="sub">${esc(p.unit || "")}</td>
            <td class="num mono">${nfmt(p.min)}</td>
            <td class="num mono">${nfmt(p.max)}</td>
            <td class="num mono">${nfmt(p.step)}</td>
            <td class="mono sub">${pfm ? esc(pfm[0]) : "—"}</td>
            <td class="sub">${esc(p.source?.doc || "")}${p.verified ? " ✓" : ""}</td>
          </tr>`;
        }).join("")}
      </table></div>
      <h3 class="sub">Источники технических данных</h3>
      ${(d.sources || []).map((s) => `<div class="hint">📖 ${esc(s.doc || "")} ${esc(s.order_no || "")} ${esc(s.release || "")} ${esc(s.url || "")} ${s.file_sha256 ? `<div class="mono faint">sha256: ${esc(String(s.file_sha256).slice(0, 24))}…</div>` : ""}</div>`).join("") || `<div class="faint">Источники не указаны</div>`}
      ${(d.notes || "") ? `<h3 class="sub">Примечания</h3><div class="hint">${esc(d.notes)}</div>` : ""}`,
      `<button class="btn btn-primary" data-act="closeModal">Закрыть</button>`, true));
  };

  /* конструктор терминала (ТЗ п. 36) */
  const wiz = { step: 0, data: null };
  A.actions.wizardOpen = () => {
    wiz.step = 0;
    wiz.data = {
      schema: "rza-terminal-profile/1", id: "user." + Date.now().toString(36), manufacturer: "", series: "", model: "",
      firmware: "", variants: [], status: "draft", adapter: "generic", rated_current_options: ["1 A", "5 A"],
      frequency_hz: [50], sources: [], conventions: { restraint: { kind: "" } }, functions: {}, parameters: [], mapping: {},
      dependencies: [], signals: [], iec61850: { supported: null, goose: null, sampled_values: null, mms: null, note: "" }, notes: "",
    };
    wizRender();
  };
  function wizRender() {
    const d = wiz.data;
    const steps = ["Производитель", "Модель", "Версия", "Функции", "Параметры", "Диапазоны и шаги", "Единицы", "Соответствие PFM", "Источник данных", "Проверка профиля", "Сохранение"];
    const body = [
      `<div class="form-grid">
        ${wizField("wiz|manufacturer", "Производитель", d.manufacturer)}
        ${wizField("wiz|series", "Серия", d.series)}
      </div>`,
      `<div class="form-grid">
        ${wizField("wiz|model", "Модель", d.model)}
        ${wizField("wiz|id", "Идентификатор профиля (латиницей)", d.id)}
      </div>`,
      `<div class="form-grid">
        ${wizField("wiz|firmware", "Версия ПО / исполнение", d.firmware)}
        ${wizField("wiz|variants", "Исполнения (через «;»)", (d.variants || []).join("; "))}
      </div>
      <div class="hint">Диапазоны и шаги зависят от версии ПО — указывайте их в источнике данных.</div>`,
      `<div class="hint">Отметьте поддерживаемые универсальные функции (PFM):</div>
       ${["87T", "50/51", "50N/51N", "46", "21", "49", "50BF", "27", "59", "67", "67N", "87N", "24"].map((f) =>
        `<label class="check-line"><input type="checkbox" class="wiz-fn" value="${f}" ${d.functions[f]?.supported ? "checked" : ""}> <span>${esc(f)}</span></label>`).join("")}`,
      `<div class="hint">Добавьте параметры устройства (ключ, наименование, PFM-параметр, диапазон, шаг, единица).</div>
       <table class="tbl"><tr><th>Ключ</th><th>Наименование</th><th>PFM</th><th class="num">Ед.</th><th class="num">Min</th><th class="num">Max</th><th class="num">Шаг</th><th></th></tr>
       ${d.parameters.map((p, i) => `<tr>
         <td><input data-wizp="${i}|key" value="${esc(p.key)}"></td>
         <td><input data-wizp="${i}|name" value="${esc(p.name)}"></td>
         <td><input data-wizp="${i}|pfm" value="${esc(p.pfm || "")}" placeholder="87T.IdiffPickup"></td>
         <td><input data-wizp="${i}|unit" value="${esc(p.unit || "")}"></td>
         <td><input type="number" step="any" data-wizp="${i}|min" value="${p.min ?? ""}"></td>
         <td><input type="number" step="any" data-wizp="${i}|max" value="${p.max ?? ""}"></td>
         <td><input type="number" step="any" data-wizp="${i}|step" value="${p.step ?? ""}"></td>
         <td><button class="btn btn-sm btn-danger" data-act="wizDelParam" data-i="${i}">✕</button></td>
       </tr>`).join("")}</table>
       <button class="btn btn-sm" data-act="wizAddParam" style="margin-top:8px">✚ Параметр</button>`,
      `<div class="hint">Диапазоны и шаги вводятся в таблице параметров (колонки Min / Max / Шаг) и должны соответствовать руководству по эксплуатации.
        Неуказанные шаги помечаются как неверифицированные.</div>`,
      `<div class="hint">Единицы измерения указываются в таблице параметров (колонка «Ед.»). Внутреннее расчётное ядро использует универсальные единицы PFM
        (о.е., А, Ом, с, %) — адаптер выполнит преобразование.</div>`,
      `<div class="hint">Для каждого параметра укажите PFM-идентификатор (колонка «PFM» на шаге «Параметры»), например:
        <div class="mono trace-formula">87T.IdiffPickup · 87T.Slope1 · 87T.Slope2 · 87T.HighSet · 51.IPickup · 46.I2Pickup · 50N51N.I0Pickup · 21.ZPickup · 49.Threshold</div>
        Соответствие сохраняется в поле «mapping» профиля и не требует изменения расчётного ядра.</div>`,
      `<div class="hint">Источник технических данных (руководство, версия). Без источники диапазоны считаются неверифицированными.</div>
       <div class="form-grid">
         <div class="frow"><label>Документ</label><input type="text" data-wiz="wiz|src_doc" value="${esc((d.sources[0] || {}).doc || "")}"></div>
         <div class="frow"><label>Заказной номер / выпуск</label><input type="text" data-wiz="wiz|src_release" value="${esc((d.sources[0] || {}).release || "")}"></div>
         <div class="frow"><label>URL</label><input type="text" data-wiz="wiz|src_url" value="${esc((d.sources[0] || {}).url || "")}"></div>
       </div>`,
      `<div class="hint">Проверка заполненности и корректности профиля.</div>
       <div id="wiz-validation">${wiz.issues ? (wiz.issues.length
          ? wiz.issues.map((i) => `<div class="banner ${i.level === "error" ? "banner-bad" : i.level === "warning" ? "banner-warn" : "banner-info"}">[${esc(i.level)}] ${esc(i.message)}</div>`).join("")
          : `<div class="banner banner-ok">✅ Замечаний нет.</div>`)
        : `<div class="banner banner-info">Нажмите «Проверить профиль».</div>`}</div>
       <button class="btn" data-act="wizValidate">Проверить профиль</button>`,
      `<div class="hint">Сохраните профиль — он появится в списке терминалов и станет доступен для расчёта.</div>
       <div class="banner banner-info">ID: <b class="mono">${esc(d.id)}</b> · ${esc(d.manufacturer)} ${esc(d.model)}</div>`,
    ][wiz.step];

    modal(modalShell("Конструктор нового терминала", `
      <div class="wiz-steps">${steps.map((s, i) => `<div class="wiz-step ${i === wiz.step ? "active" : i < wiz.step ? "done" : ""}" data-act="wizGo" data-i="${i}">${i + 1}. ${esc(s)}</div>`).join("")}</div>
      ${body || ""}`,
      `${wiz.step > 0 ? `<button class="btn" data-act="wizPrev">← Назад</button>` : ""}
       ${wiz.step < steps.length - 1 ? `<button class="btn btn-primary" data-act="wizNext">Далее →</button>` : ""}
       <button class="btn btn-accent" data-act="wizSave">💾 Сохранить профиль</button>
       <button class="btn" data-act="closeModal">Отмена</button>`, true), {
      onOpen: (root) => {
        root.addEventListener("input", (e) => {
          const el = e.target;
          if (el.dataset.wiz) {
            const [, path] = el.dataset.wiz.split("|");
            if (path === "variants") wiz.data.variants = el.value.split(";").map((x) => x.trim()).filter(Boolean);
            else if (path.startsWith("src_")) {
              wiz.data.sources = wiz.data.sources && wiz.data.sources.length ? wiz.data.sources : [{ doc: "", release: "", url: "" }];
              wiz.data.sources[0][path.slice(4)] = el.value;
            } else wiz.data[path] = el.value;
          }
          if (el.dataset.wizp !== undefined) {
            const [i, f] = el.dataset.wizp.split("|");
            const p = wiz.data.parameters[Number(i)];
            p[f] = f === "key" || f === "name" || f === "pfm" || f === "unit" ? el.value : (el.value === "" ? null : Number(el.value));
          }
        });
        root.addEventListener("change", (e) => {
          const el = e.target;
          if (el.classList && el.classList.contains("wiz-fn")) {
            wiz.data.functions = wiz.data.functions || {};
            if (el.checked) wiz.data.functions[el.value] = { supported: true, group: "", note: "" };
            else delete wiz.data.functions[el.value];
          }
        });
      },
    });
  }
  const wizField = (dk, label, val) =>
    `<div class="frow"><label>${label}</label><input type="text" data-wiz="${dk}" value="${esc(val ?? "")}"></div>`;

  A.actions.wizNext = () => { wiz.step = Math.min(wiz.step + 1, 10); wizRender(); };
  A.actions.wizPrev = () => { wiz.step = Math.max(wiz.step - 1, 0); wizRender(); };
  A.actions.wizGo = (el) => { wiz.step = Number(el.dataset.i); wizRender(); };
  /* сбор данных, которые могли остаться в DOM (чекбоксы функций живут на отдельном шаге) */
  function wizCollect() {
    const d = wiz.data;
    const boxes = [...document.querySelectorAll(".wiz-fn")];
    if (boxes.length) {
      d.functions = {};
      for (const x of boxes) if (x.checked) d.functions[x.value] = { supported: true, group: "", note: "" };
    }
    d.mapping = {};
    for (const p of d.parameters) {
      if (p.pfm) d.mapping[p.pfm] = { instances: { "": p.key }, transform: "identity" };
    }
    return d;
  }
  A.actions.wizAddParam = () => {
    wiz.data.parameters.push({ key: "P" + (wiz.data.parameters.length + 1), name: "", pfm: "", unit: "", min: 0, max: 1, step: 0.01, kind: "float", function: "", default: null, comment: "", verified: false, step_verified: false, source: {} });
    wizRender();
  };
  A.actions.wizDelParam = (el) => { wiz.data.parameters.splice(Number(el.dataset.i), 1); wizRender(); };
  A.actions.wizValidate = async () => {
    const d = wizCollect();
    const issues = await api("/terminals/validate", { method: "POST", body: d, quiet: true }).catch((e) => [{ level: "error", code: "validate", message: e.message }]);
    wiz.issues = issues;
    wizRender();
  };
  A.actions.wizSave = async () => {
    const d = wizCollect();
    try {
      const r = await api("/terminals", { method: "POST", body: { profile: d, user: STATE.project.meta.author, reason: "Добавление профиля терминала через конструктор" } });
      closeModal();
      toast(`Профиль «${d.id}» сохранён${r.issues?.length ? " (есть замечания)" : ""}`, "ok");
      A.render();
    } catch (e) { /* toast */ }
  };

  /* ═══════════════ НАЗНАЧЕНИЕ ТЕРМИНАЛОВ ═══════════════ */
  A.views.assign = async (main) => {
    const list = await api("/terminals");
    const assigns = A.draft("terminals");
    main.innerHTML = A.pageShell("Назначение терминалов проекту",
      "Укажите терминалы и реализуемые ими функции — для каждого сформируется своя карта уставок (ТЗ п. 38).", "", `
      <div class="panel">
        <div class="panel-title">Терминалы</div>
        ${list.map((t) => {
          const a = assigns.find((x) => x.terminal_id === t.id);
          const supported = Object.entries(t.functions || {}).filter(([, v]) => v && v.supported !== false).map(([k]) => k);
          return `<div class="item-card">
            <div class="head">
              <label class="check-line" style="margin:0"><input type="checkbox" class="asg-on" data-id="${esc(t.id)}" ${a ? "checked" : ""}></label>
              <span>${esc(t.label)}</span>
              ${statusChip(t.status, t.status_label)}
              <span class="spacer"></span>
              <span class="mono faint">${esc(t.id)}</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:8px">
              ${supported.map((f) => `<label class="check-line" style="margin:0">
                <input type="checkbox" class="asg-fn" data-id="${esc(t.id)}" value="${esc(f)}" ${!a || (a.functions || []).includes(f) ? "checked" : ""} ${a ? "" : "disabled"}>
                <span class="chip chip-na">${esc(f)}</span></label>`).join("") || `<span class="faint">профиль не описывает функции — заполните базу устройств</span>`}
            </div>
            ${a ? `<div class="frow" style="margin-top:8px"><label>Примечание к назначению</label>
              <input type="text" data-draft="terminals|${assigns.indexOf(a)}.note" value="${esc(a.note || "")}"></div>` : ""}
          </div>`;
        }).join("")}
      </div>
      <div class="panel"><div style="display:flex;gap:9px">${saveBtn("terminals", "Сохранить назначение")}</div></div>`);

    document.querySelectorAll(".asg-on").forEach((cb) => cb.addEventListener("change", () => {
      const tid = cb.dataset.id;
      const arr = A.draft("terminals");
      const idx = arr.findIndex((x) => x.terminal_id === tid);
      if (cb.checked && idx < 0) {
        const t = list.find((x) => x.id === tid);
        arr.push({ terminal_id: tid, variant: "", firmware: t.firmware || "", functions: Object.entries(t.functions || {}).filter(([, v]) => v && v.supported !== false).map(([k]) => k), side_map: {}, note: "" });
      } else if (!cb.checked && idx >= 0) arr.splice(idx, 1);
      A.render();
    }));
    document.querySelectorAll(".asg-fn").forEach((cb) => cb.addEventListener("change", () => {
      const arr = A.draft("terminals");
      const a = arr.find((x) => x.terminal_id === cb.dataset.id);
      if (!a) return;
      const set = new Set(a.functions || []);
      cb.checked ? set.add(cb.value) : set.delete(cb.value);
      a.functions = [...set];
    }));
  };

  /* ═══════════════ СРАВНЕНИЕ ТЕРМИНАЛОВ ═══════════════ */
  A.views.compare = async (main) => {
    const list = await api("/terminals");
    const sel = STATE.view.cmpSel = STATE.view.cmpSel || list.filter((t) => t.status !== "not_loaded").map((t) => t.id);
    main.innerHTML = A.pageShell("Сравнение терминалов",
      "Один расчёт → несколько устройств. Программа не выбирает «лучшее» устройство автоматически (ТЗ п. 14).", "", `
      <div class="panel">
        <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center">
          ${list.map((t) => `<label class="check-line" style="margin:0">
            <input type="checkbox" class="cmp-t" value="${esc(t.id)}" ${sel.includes(t.id) ? "checked" : ""}>
            <span>${esc(t.label)} ${t.status === "not_loaded" ? '<span class="chip chip-na">не загружен</span>' : ""}</span></label>`).join("")}
          <button class="btn btn-primary" id="cmp-run">Сравнить</button>
        </div>
      </div>
      <div id="cmp-result"></div>`);
    document.getElementById("cmp-run").addEventListener("click", async () => {
      const ids = [...document.querySelectorAll(".cmp-t:checked")].map((x) => x.value);
      STATE.view.cmpSel = ids;
      const box = document.getElementById("cmp-result");
      box.innerHTML = "<div class='loading-block'>Расчёт матрицы…</div>";
      try {
        const d = await api("/compare", { method: "POST", body: { terminal_ids: ids } });
        box.innerHTML = `
          <div class="panel">
            <div class="panel-title">Матрица сравнения <span class="spacer"></span>
              <button class="btn btn-sm" onclick="window.open('/api/report/compare?fmt=pdf')">📄 PDF</button>
              <button class="btn btn-sm" onclick="window.open('/api/report/compare?fmt=xlsx')">📊 Excel</button></div>
            <div class="tbl-wrap" style="max-height:64vh;overflow-y:auto"><table class="tbl">
              <tr>${d.header.map((h) => `<th>${esc(h)}</th>`).join("")}<th>Статус</th></tr>
              ${d.rows.map((r, ri) => `<tr>
                <td class="mono sub">${esc(r.function)}</td>
                <td><div class="param-name">${esc(r.title)}</div><div class="param-key">${esc(r.key)}</div></td>
                <td class="num mono"><b>${nfmt(r.calc)}</b> ${esc(r.unit || "")}</td>
                ${r.cells.map((c) => c.text !== undefined
                  ? `<td class="sub">${esc(c.text)}${c.note ? `<div class="faint">${esc(c.note)}</div>` : ""}</td>`
                  : `<td>${statusChip(c.status, nfmt(c.accepted) + " " + (c.unit || ""))}<div class="sub">${esc(c.param || "")}</div>
                      <div class="faint">шаг ${nfmt(c.step)} · ${nfmt(c.range?.[0])} … ${nfmt(c.range?.[1])}</div>
                      ${c.note ? `<div class="faint">${esc(c.note)}</div>` : ""}</td>`).join("")}
                <td>${statusChip(d.row_status[ri])}</td>
              </tr>`).join("")}
            </table></div>
            <div class="hint" style="margin-top:8px">Принятые уставки показаны с учётом диапазона и шага конкретного терминала. Статус строки — наихудший по устройствам.</div>
          </div>`;
      } catch (e) {
        box.innerHTML = `<div class="banner banner-bad">Не удалось построить матрицу: ${esc(e.message)}</div>`;
      }
    });
  };

  /* ═══════════════ КАРТА УСТАВОК ═══════════════ */
  A.views.card = async (main) => {
    const s = STATE.summary;
    const tids = s ? Object.keys(s.cards || {}) : [];
    const cur = STATE.view.cardTid = STATE.view.cardTid || tids[0] || null;
    if (!cur) {
      main.innerHTML = A.pageShell("Карта уставок", "", "",
        `<div class="banner banner-warn">Терминалы не назначены проекту. Перейдите в раздел «Назначение».</div>`);
      return;
    }
    const card = await api(`/card/${encodeURIComponent(cur)}`);
    const groups = {};
    for (const r of card.rows) (groups[r.group || "Прочее"] = groups[r.group || "Прочее"] || []).push(r);
    main.innerHTML = A.pageShell("Карта уставок",
      `Расчётная уставка → параметр терминала (диапазон, шаг) → принятая уставка → повторная проверка (ТЗ п. 12, 18, 40).`, "", `
      <div class="pill-tabs">
        ${tids.map((t) => `<div class="pill-tab ${t === cur ? "active" : ""}" data-act="cardTid" data-id="${esc(t)}">${esc(s.cards[t].label)}</div>`).join("")}
      </div>
      <div class="panel">
        <div class="panel-title">${esc(card.label)} ${statusChip(card.status, card.icon + " " + card.status_label)}
          ${statusChip(card.profile_status, "профиль: " + card.profile_status_label)}
          <span class="spacer"></span>
          <button class="btn btn-sm" onclick="window.open('/api/report/card?fmt=pdf&terminal=${encodeURIComponent(cur)}')">📄 PDF</button>
          <button class="btn btn-sm" onclick="window.open('/api/report/card?fmt=xlsx&terminal=${encodeURIComponent(cur)}')">📊 Excel</button>
          <button class="btn btn-sm" onclick="window.open('/api/report/card?fmt=csv&terminal=${encodeURIComponent(cur)}')">🗒 CSV</button>
        </div>
        ${card.warnings?.length ? `<div class="banner banner-warn"><ul>${card.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
        <div class="hint" style="margin-bottom:10px">Политика округления: <b>${esc(card.policy)}</b> · функции: ${card.functions.map(esc).join(", ")}
          ${card.source?.length ? ` · источник: ${card.source.map((s2) => esc(s2.doc || "")).join("; ")}` : ""}</div>
        ${Object.entries(groups).map(([g, rows]) => `
          <h3 class="sub">${esc(g)}</h3>
          <div class="tbl-wrap"><table class="tbl">
            <tr><th>Функция</th><th>Параметр</th><th class="num">Расчёт</th><th class="num">Принято</th><th>Ед.</th><th class="num">Диапазон</th><th class="num">Шаг</th><th>Статус</th><th>Основание</th><th></th></tr>
            ${rows.map((r) => `
              <tr>
                <td class="mono"><b>${esc(r.function)}</b>${r.instance ? `<div class="sub">${esc(r.instance)}</div>` : ""}</td>
                <td><div class="param-name">${esc(r.title)}</div><div class="param-key">${esc(r.param_name || r.param_key || "")}</div></td>
                <td class="num mono">${nfmt(r.calc)}</td>
                <td class="num mono"><b style="font-size:14px;color:${r.range_state !== "in" ? "var(--bad)" : "var(--ok)"}">${r.accepted == null ? "—" : nfmt(r.accepted)}</b>
                  ${r.deviation_rel != null && Math.abs(r.deviation_rel) > 1e-9 ? `<div class="faint">Δ ${pct(r.deviation_rel)}</div>` : ""}</td>
                <td class="sub">${esc(r.unit || "")}</td>
                <td class="num mono sub">${nfmt(r.min)} … ${nfmt(r.max)}</td>
                <td class="num mono sub">${nfmt(r.step)}</td>
                <td>${statusChip(r.status, r.icon + " " + r.status_label)}${r.reason ? `<div class="sub">${esc(r.reason)}</div>` : ""}${r.alt_safe != null ? `<div class="faint">вариант: ${nfmt(r.alt_safe)} ${esc(r.unit || "")}</div>` : ""}</td>
                <td class="sub">${esc(r.basis || "")}${r.comment ? `<div class="faint">${esc(r.comment)}</div>` : ""}</td>
                <td>
                  ${r.pfm_id && r.pfm_id !== "obj" ? `<button class="btn btn-sm" data-act="openTrace" data-fn="${esc(r.function)}" data-key="${esc(r.pfm_key)}" data-terminal="${esc(cur)}">Расчёт</button>` : ""}
                  ${r.supported ? `<button class="btn btn-sm btn-ghost" data-act="overrideRow" data-tid="${esc(cur)}" data-key="${esc(r.pfm_key)}" data-title="${esc(r.title)}">✎</button>` : ""}
                </td>
              </tr>`).join("")}
          </table></div>`).join("")}
      </div>
      ${Object.keys(card.checks || {}).length ? `
        <div class="panel">
          <div class="panel-title">Повторные проверки после округления</div>
          ${Object.entries(card.checks).map(([fid, cs]) => cs.map((c) => `
            <div class="item-card">
              <div class="head">${statusChip(c.status, c.icon + " " + c.status_label)} <span>${esc(fid)} · ${esc(c.title)}</span>
                <span class="spacer"></span>
                <button class="btn btn-sm" data-act="openCheck" data-cid="${esc(c.id)}" data-scope="card" data-terminal="${esc(cur)}">Показать расчёт</button></div>
              <div>${esc(c.reason)}</div>
            </div>`).join("")).join("")}
        </div>` : ""}`);
  };
  A.actions.cardTid = (el) => { STATE.view.cardTid = el.dataset.id; A.render(); };
  A.actions.overrideRow = (el) => {
    const { tid, key, title } = el.dataset;
    modal(modalShell(`Ручная уставка · ${esc(title)}`, `
      <div class="banner banner-warn">Ручное изменение принятой уставки фиксируется в журнале и требует проверки критериев.
        Причина изменения обязательна (ТЗ п. 41).</div>
      <div class="frow"><label>Новое значение (в единицах параметра терминала; пусто — сброс к расчётному)</label>
        <input type="number" step="any" id="ov-val"></div>
      <div class="frow"><label>Причина <span class="chip chip-bad">обязательно</span></label><textarea id="ov-reason"></textarea></div>
      <div class="frow"><label>Автор</label><input type="text" id="ov-user" value="${esc(STATE.project.meta.author || "")}"></div>`,
      `<button class="btn" data-act="closeModal">Отмена</button>
       <button class="btn btn-danger" id="ov-reset">Сбросить</button>
       <button class="btn btn-primary" id="ov-ok">Применить</button>`), {
      onOpen: (root) => {
        const apply = async (val) => {
          const reason = root.querySelector("#ov-reason").value.trim();
          if (!reason) { toast("Укажите причину", "err"); return; }
          await api("/project/override", { method: "POST", body: { terminal_id: tid, key, value: val, reason, user: root.querySelector("#ov-user").value } });
          closeModal();
          await A.loadProject();
          A.render();
          toast("Ручная уставка сохранена", "ok");
        };
        root.querySelector("#ov-ok").addEventListener("click", () => {
          const v = root.querySelector("#ov-val").value;
          apply(v === "" ? null : Number(v));
        });
        root.querySelector("#ov-reset").addEventListener("click", () => apply(null));
      },
    });
  };

  /* ═══════════════ ОТЧЁТЫ ═══════════════ */
  A.views.reports = async (main) => {
    const info = STATE.info;
    const guard = await api("/report/guard");
    const tids = STATE.summary ? Object.keys(STATE.summary.cards || {}) : [];
    const fmts = [["pdf", "PDF"], ["docx", "Word (DOCX)"], ["xlsx", "Excel"], ["csv", "CSV"], ["json", "JSON"]];
    main.innerHTML = A.pageShell("Отчёты и экспорт",
      "Перед экспортом окончательной карты уставок выполняется полный контроль проекта (ТЗ п. 33, 41).", "", `
      ${guard.final_allowed
        ? `<div class="banner banner-ok">✅ Полный контроль проекта пройден — карта уставок может быть экспортирована как окончательная.</div>`
        : `<div class="banner banner-bad"><b>Полный контроль проекта не пройден</b> — карта уставок экспортируется как <b>ПРЕДВАРИТЕЛЬНАЯ</b>.
           <ul>${(guard.reasons || []).slice(0, 8).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
           ${guard.reasons?.length > 8 ? `<div class="hint">… и ещё ${guard.reasons.length - 8}</div>` : ""}</div>`}
      <div class="panel">
        <div class="panel-title">Фильтры</div>
        <div class="filters">
          <div class="frow"><label>Терминал (для карты уставок)</label>
            <select id="rep-terminal"><option value="">все терминалы</option>
              ${tids.map((t) => `<option value="${esc(t)}">${esc(STATE.summary.cards[t].label)}</option>`).join("")}
            </select></div>
        </div>
      </div>
      ${Object.entries(info.kinds).map(([k, title]) => `
        <div class="panel">
          <div class="panel-title">${esc(title)} <span class="spacer"></span>
            ${fmts.map(([f, fl]) => `<button class="btn btn-sm ${f === "pdf" ? "btn-primary" : ""}" data-act="report" data-kind="${k}" data-fmt="${f}">${fl}</button>`).join("")}
          </div>
          <div class="hint">${({
            calc: "Полный инженерный расчёт: исходные данные, формулы, подстановки, результаты, проверки.",
            card: "Только итоговые параметры: функция | параметр | расчёт | принято | ед. | основание.",
            kz: "Все расчётные режимы КЗ: виды замыканий, режимы, положения РПН.",
            sens: "Все коэффициенты чувствительности с наихудшими случаями.",
            selectivity: "Таблицы и графики согласования по току, времени и направлению.",
            compare: "Расчётные и принятые параметры по всем назначенным терминалам.",
            changes: "История проекта: версии, журнал изменений, роли согласования.",
          })[k]}</div>
        </div>`).join("")}`);
    document.getElementById("rep-terminal").addEventListener("change", (e) => { STATE.view.repTid = e.target.value; });
    STATE.view.repTid = STATE.view.repTid || "";
  };
  A.actions.report = (el) => {
    const tid = STATE.view.repTid;
    const q = `?fmt=${el.dataset.fmt}${tid ? `&terminal=${encodeURIComponent(tid)}` : ""}`;
    window.open(`/api/report/${el.dataset.kind}${q}`, "_blank");
  };

  /* ═══════════════ НОРМАТИВНАЯ БАЗА ═══════════════ */
  A.views.norms = async (main) => {
    const d = await api("/norms");
    const short = Object.fromEntries(d.sources.map((s) => [s.id, s.short || s.id]));
    main.innerHTML = A.pageShell("Нормативно-методическая база",
      "Приоритет источников настраивается. Для каждого критерия хранятся: источник, документ, раздел, пункт, формула, область применения, дата/версия (ТЗ п. 3).", "", `
      <div class="panel">
        <div class="panel-title">Приоритет источников (сверху — высший)</div>
        <table class="tbl">
          <tr><th>Уровень</th><th>Документ</th><th>Издатель</th><th>Версия / дата</th><th>Статус</th></tr>
          ${d.priority.map((lv, i) => {
            const s = d.sources.find((x) => x.id === lv) || {};
            return `<tr>
              <td class="mono">${i + 1}. ${esc(lv)}</td>
              <td>${esc(s.title || lv)}<div class="sub">${esc(s.url || "")}</div></td>
              <td class="sub">${esc(s.issuer || "")}</td>
              <td class="sub">${esc(s.version || "")} ${esc(s.date || "")}</td>
              <td>${s.verified ? `<span class="chip chip-ok">сверен</span>` : `<span class="chip chip-warn">не сверен</span>`}</td>
            </tr>`;
          }).join("")}
        </table>
      </div>
      <div class="panel">
        <div class="panel-title">Нормативные значения (${d.values.length})</div>
        <div class="tbl-wrap" style="max-height:60vh;overflow-y:auto"><table class="tbl">
          <tr><th>Норма</th><th>Варианты значений</th></tr>
          ${d.values.map((v) => `
            <tr>
              <td><div class="param-name">${esc(v.title)}</div><div class="param-key">${esc(v.id)}</div>
                ${d.overrides && d.overrides[v.id] ? `<div class="chip chip-warn">переопределено пользователем: ${nfmt(d.overrides[v.id].value)}</div>` : ""}</td>
              <td>${(v.values || []).map((alt) => `
                <div style="margin:3px 0"><b class="mono">${nfmt(alt.value)}</b>
                  <span class="chip chip-na">${esc(short[alt.source] || alt.source)}</span>
                  <span class="sub">${esc(alt.clause || "")}</span>
                  ${alt.verified ? "✓" : ""}
                  ${alt.note ? `<div class="faint">${esc(alt.note)}</div>` : ""}
                </div>`).join("")}</td>
            </tr>`).join("")}
        </table></div>
      </div>`);
  };

  /* ═══════════════ БИБЛИОТЕКА ФОРМУЛ ═══════════════ */
  A.views.formulas = async (main) => {
    const list = await api("/formulas");
    main.innerHTML = A.pageShell("Библиотека инженерных формул",
      "Безымянных формул нет: каждая имеет идентификатор, версию, источник и пункт документа. Формула не изменяется без создания новой версии (ТЗ п. 29).", "", `
      <div class="panel">
        <div class="panel-title">Формулы (${list.length})</div>
        <div class="tbl-wrap" style="max-height:70vh;overflow-y:auto"><table class="tbl">
          <tr><th>ID</th><th class="num">Вер.</th><th>Наименование</th><th>Математическая запись</th><th>Источник</th><th>Область</th><th>Статус</th></tr>
          ${list.map((f) => `
            <tr class="click" data-act="formulaDetail" data-id="${esc(f.id)}">
              <td class="mono sub">${esc(f.id)}</td>
              <td class="num mono">${f.version}</td>
              <td>${esc(f.name)}</td>
              <td class="mono sub">${esc(f.display || f.expression)}</td>
              <td class="sub">${esc(f.source_id || "")} ${esc(f.clause || "")}</td>
              <td class="sub">${esc(f.scope || "")}</td>
              <td>${f.verified ? `<span class="chip chip-ok">сверена</span>` : `<span class="chip chip-warn">не сверена</span>`}</td>
            </tr>`).join("")}
        </table></div>
      </div>`);
  };
  A.actions.formulaDetail = async (el) => {
    const versions = await api(`/formulas/${encodeURIComponent(el.dataset.id)}`);
    const f = versions[versions.length - 1];
    modal(modalShell(`Формула ${esc(f.id)} · версия ${f.version}`, `
      <table class="tbl" style="margin-bottom:12px">
        <tr><td>Наименование</td><td><b>${esc(f.name)}</b></td></tr>
        <tr><td>Математическая запись</td><td class="mono">${esc(f.display || f.expression)}</td></tr>
        <tr><td>Выражение для вычисления</td><td class="mono faint">${esc(f.expression)}</td></tr>
        <tr><td>Результат</td><td>${esc(f.result?.name || "")} ${esc(f.result?.unit || "")} <span class="faint">${esc(f.result?.desc || "")}</span></td></tr>
        <tr><td>Источник</td><td>${esc(f.source_id || "")} ${esc(f.clause || "")} <span class="faint">${esc(f.scope || "")}</span></td></tr>
        <tr><td>Описание</td><td class="sub">${esc(f.description || "")}</td></tr>
      </table>
      <h3 class="sub">Переменные</h3>
      <table class="tbl">
        <tr><th>Переменная</th><th>Ед.</th><th>Описание</th></tr>
        ${Object.entries(f.variables || {}).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${esc(v.unit || "")}</td><td class="sub">${esc(v.desc || "")}</td></tr>`).join("")}
      </table>
      <h3 class="sub">Версии (${versions.length})</h3>
      <table class="tbl">
        <tr><th>Версия</th><th>Дата</th><th>Автор</th><th>Причина</th></tr>
        ${versions.map((v) => `<tr><td class="mono">v${v.version}${v.status !== "active" ? ` (${esc(v.status)})` : ""}</td><td>${esc(v.date || "")}</td><td>${esc(v.author || "")}</td><td class="sub">${esc(v.reason || "")}</td></tr>`).join("")}
      </table>`,
      `<button class="btn btn-primary" data-act="closeModal">Закрыть</button>`, true));
  };

  /* ═══════════════ 13Б vs СОВРЕМЕННАЯ РЗА ═══════════════ */
  A.views.b13 = async (main) => {
    const rows = await api("/b13");
    main.innerHTML = A.pageShell("Выпуск 13Б vs современная РЗА",
      "13Б — расчётно-методическая основа. Показывается, какой физический критерий старой методики реализуется современной функцией. Автоматическая эквивалентность электромеханического реле и микропроцессорной функции НЕ утверждается (ТЗ п. 2, 31).", "", `
      ${rows.map((r) => `
        <div class="panel">
          <div class="panel-title">Физический критерий: ${esc(r.physical)}</div>
          <div class="grid grid-2">
            <div class="item-card" style="background:#f7f4ec">
              <div class="head">📘 Методика 13Б</div>
              <div class="faint">Основание: ${esc(r.b13?.clause || "")}</div>
              <div class="trace-formula">${esc(r.b13?.formula || "")}</div>
              <div class="sub">Схема: ${esc(r.b13?.scheme || "")}</div>
              <div class="sub">Критерий: ${esc(r.b13?.criterion || "")}</div>
            </div>
            <div class="item-card" style="background:#eef4fb">
              <div class="head">⚡ Современная реализация</div>
              <div class="sub"><b>${esc(r.modern?.function || "")}</b></div>
              <div class="sub">Алгоритм: ${esc(r.modern?.algorithm || "")}</div>
              <div style="margin-top:6px">${(r.modern?.params || []).map((p) => `<span class="chip chip-na mono">${esc(p)}</span>`).join(" ")}</div>
            </div>
          </div>
          <h3 class="sub">Значения проекта</h3>
          ${(r.project_values || []).length ? `<table class="tbl">
            <tr><th>Параметр</th><th>Расчёт</th><th class="num">Интервал</th></tr>
            ${r.project_values.map((p) => `<tr>
              <td>${esc(p.param)}<div class="param-key">${esc(p.pfm)}</div></td>
              <td class="mono"><b>${nfmt(p.calc)}</b> ${esc(p.unit || "")}</td>
              <td class="num mono sub">${nfmt(p.lower)} … ${nfmt(p.upper)}</td></tr>`).join("")}
          </table>` : `<div class="faint">Нет данных — выполните расчёт.</div>`}
        </div>`).join("")}`);
  };

  /* ═══════════════ AI-АССИСТЕНТ ═══════════════ */
  A.views.assistant = async (main) => {
    const review = await api("/assistant/review");
    const sevRu = { error: "ошибка", warning: "предупреждение", missing: "недостаточно данных", info: "информация" };
    main.innerHTML = A.pageShell("Инженерный AI-ассистент",
      "Ассистент объясняет расчёт, находит ошибки и недостатки данных, проверяет логическую согласованность. Он НЕ утверждает уставки — любая рекомендация содержит основание, формулу и исходные данные (ТЗ п. 24).", "", `
      <div class="panel">
        <div class="panel-title">Разбор проекта (${review.length})</div>
        ${review.map((r) => `
          <div class="item-card">
            <div class="head">
              ${r.severity === "error" ? `<span class="chip chip-bad">ошибка</span>`
                : r.severity === "warning" ? `<span class="chip chip-warn">предупреждение</span>`
                : r.severity === "missing" ? `<span class="chip chip-orng">недостаточно данных</span>`
                : `<span class="chip chip-na">информация</span>`}
              <span>${esc(r.title)}</span>
            </div>
            ${r.basis ? `<div class="sub">Основание: ${esc(r.basis)}</div>` : ""}
            ${r.formula ? `<div class="trace-subst">${esc(r.formula)}</div>` : ""}
            ${(r.inputs || []).length ? `<div class="faint">Исходные данные: ${r.inputs.map(esc).join("; ")}</div>` : ""}
            ${r.source ? `<div class="trace-src">📖 ${esc(r.source)}</div>` : ""}
            ${r.warning ? `<div class="banner banner-warn" style="margin:8px 0 0">⚠ ${esc(r.warning)}</div>` : ""}
          </div>`).join("")}
      </div>
      <div class="panel">
        <div class="panel-title">Объяснить параметр</div>
        <div class="filters">
          <div class="frow"><label>Функция</label><select id="ai-fn">
            ${["87T", "50/51", "46", "50N/51N", "21", "49"].map((f) => `<option value="${f}">${f}</option>`).join("")}
          </select></div>
          <div class="frow"><label>Параметр</label><select id="ai-key" style="min-width:320px"></select></div>
          <div class="frow"><label>Терминал (для перевода уставки)</label><select id="ai-term">
            <option value="">— универсальный расчёт —</option>
            ${(STATE.summary ? Object.entries(STATE.summary.cards || {}) : []).map(([t, c]) => `<option value="${esc(t)}">${esc(c.label)}</option>`).join("")}
          </select></div>
          <button class="btn btn-primary" id="ai-run">Объяснить</button>
        </div>
        <div id="ai-out"></div>
      </div>`);
    const fnSel = document.getElementById("ai-fn"), keySel = document.getElementById("ai-key");
    const fill = async () => {
      try {
        const r = await api(`/results/${encodeURIComponent(fnSel.value)}`);
        keySel.innerHTML = (r.params || []).map((p) => `<option value="${esc(p.key)}">${esc(p.title)}</option>`).join("");
      } catch { keySel.innerHTML = ""; }
    };
    fnSel.addEventListener("change", fill);
    fill();
    document.getElementById("ai-run").addEventListener("click", async () => {
      const out = document.getElementById("ai-out");
      out.innerHTML = "<div class='loading-block'>Анализ…</div>";
      try {
        const d = await api("/assistant/explain", { method: "POST", body: { function: fnSel.value, key: keySel.value, terminal: document.getElementById("ai-term").value || null } });
        if (!d.ok) { out.innerHTML = `<div class="banner banner-warn">${esc(d.message)}</div>`; return; }
        out.innerHTML = `
          <h3 class="sub">${esc(d.title)}</h3>
          ${(d.text || []).map((t) => `<div style="margin:6px 0">${esc(t)}</div>`).join("")}
          ${(d.steps || []).length ? `<details open><summary class="hint">Формулы расчёта</summary>
            ${d.steps.map((s) => `<div class="trace-step"><span class="tag tag-calc">Формула</span>
              <div class="st-title">${esc(s.title)}</div>
              <div class="trace-formula">${esc(s.formula || "")}</div>
              <div class="trace-subst">${esc(s.substituted || "")}</div>
              ${s.source ? `<div class="trace-src">📖 ${esc(s.source)}</div>` : ""}</div>`).join("")}
          </details>` : ""}
          ${d.terminal ? `<div class="banner banner-info">Перевод в терминал «${esc(d.terminal.terminal)}»: параметр <b class="mono">${esc(d.terminal.param)}</b>,
            диапазон ${nfmt(d.terminal.range?.[0])} … ${nfmt(d.terminal.range?.[1])}, шаг ${nfmt(d.terminal.step)} → принято <b>${nfmt(d.terminal.accepted)}</b> ${esc(d.terminal.unit || "")}.
            ${esc(d.terminal.reason || "")}</div>` : ""}
          ${(d.warnings || []).map((w) => `<div class="banner banner-warn">⚠ ${esc(w)}</div>`).join("")}
          <div class="banner banner-info" style="margin-top:12px"><b>Ограничение ассистента:</b> ${esc(d.disclaimer || "")}</div>
          <button class="btn" data-act="openTrace" data-fn="${esc(fnSel.value)}" data-key="${esc(keySel.value)}">Полная «Показать расчёт» →</button>`;
      } catch (e) {
        out.innerHTML = `<div class="banner banner-bad">${esc(e.message)}</div>`;
      }
    });
  };

  /* ═══════════════ КОНТРОЛЬНЫЕ ТЕСТЫ ═══════════════ */
  A.views.tests = async (main) => {
    const d = await api("/tests");
    main.innerHTML = A.pageShell("Контрольные расчёты (примеры Вып. 13Б)",
      "Автоматические тесты по расчётным примерам методики 13Б: исходные данные → ожидаемый результат → фактический → допуск → статус (ТЗ п. 30).", "", `
      <div class="banner ${d.summary.failed ? "banner-warn" : "banner-ok"}">
        Пройдено <b>${d.summary.passed}</b> из <b>${d.summary.total}</b>${d.summary.failed ? ` · не пройдено: ${d.summary.failed}` : " · все контрольные расчёты сошлись ✅"}
      </div>
      <div class="panel">
        <div class="tbl-wrap"><table class="tbl">
          <tr><th>Тест</th><th>Величина</th><th class="num">Ожидание</th><th class="num">Факт</th><th class="num">Допуск</th><th class="num">Отклонение</th><th>Статус</th><th>Источник</th></tr>
          ${d.rows.map((r) => `<tr>
            <td><b>${esc(r.test)}</b><div class="sub">${esc(r.title)}</div></td>
            <td class="mono sub">${esc(r.quantity)}</td>
            <td class="num mono">${nfmt(r.expected)}</td>
            <td class="num mono">${nfmt(r.actual)}</td>
            <td class="num mono sub">${r.tolerance != null ? pct(r.tolerance) : "—"}</td>
            <td class="num mono sub">${r.deviation != null ? pct(r.deviation) : "—"}</td>
            <td>${r.status === "pass" ? `<span class="chip chip-ok">✓ пройден</span>` : r.status === "error" ? `<span class="chip chip-bad">ошибка</span>` : `<span class="chip chip-bad">✗ не пройден</span>`}
              ${r.note ? `<div class="sub">${esc(r.note)}</div>` : ""}</td>
            <td class="sub">${esc(r.source || "")}</td>
          </tr>`).join("")}
        </table></div>
      </div>`);
  };

  /* ═══════════════ НАСТРОЙКИ ═══════════════ */
  A.views.settings = async (main) => {
    const a = A.draft("assumptions");
    const labels = {
      k_aper: ["k_апер — коэффициент апериодической составляющей", ""],
      k_odn: ["k_одн — коэффициент одновременности/однофазности", ""],
      eps_ct: ["ε — погрешность ТТ при внешних КЗ (доли)", ""],
      eps_lin: ["ε_лин — погрешность ТТ в зоне умеренных токов (доли)", ""],
      eps_load: ["ε_нагр — погрешность ТТ при нагрузке (доли)", ""],
      delta_f: ["Δf — погрешность выравнивания токов сторон (доли)", ""],
      k_stab: ["k_отс дифзащиты (пусто → значение нормы)", ""],
      inrush_2h_pct: ["Порог блокировки по 2-й гармонике", "%"],
      nth_harm_pct: ["Порог блокировки по n-й гармонике", "%"],
      inrush_peak_pu: ["Ожидаемый бросок намагничивания", "о.е. I_ном"],
      highset_k: ["k_отс высшей ступени от сквозного тока", ""],
      bp1_pu: ["Опорная точка 1 характеристики", "о.е."],
      x_lin_pu: ["Сквозной ток линейной области (излом)", "о.е."],
      k_self_start: ["k_самозапуска", ""],
      dt_step_s: ["Ступень селективности Δt (пусто → норма)", "с"],
      i2_asym_pu: ["I_2 от несимметрии системы", "о.е. I_ном"],
      i0_unb_extra_pu: ["Дополнительный 3I0 в послеаварийном режиме", "о.е. I_ном"],
      i0_oapv_a: ["3I0 при ОАПВ смежных линий (пусто → расчёт)", "А"],
      load_pf_deg: ["Угол сопротивления нагрузки φ_нагр", "град"],
      max_torque_deg: ["Угол максимальной чувствительности", "град"],
      u_work_min_pu: ["Минимальное рабочее напряжение", "о.е. U_ном"],
      z_offset_a: ["Смещение характеристики 2-й ступени ДЗ", "о.е."],
      overload_curr_factor: ["Допустимый длительный ток (тепловая)", "от I_ном"],
      signal_delay_s: ["Выдержка сигнала перегрузки (пусто → норма)", "с"],
    };
    main.innerHTML = A.pageShell("Настройки расчёта",
      "Коэффициенты и допущения проекта сопровождаются ссылками на источники (раздел «Нормативная база»). Изменения фиксируются в журнале.", "", `
      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Дифференциальная защита 87T</div>
          <div class="form-grid">
            ${Object.entries(labels).slice(0, 13).map(([k, [t, u]]) => fNum("assumptions", k, t, u)).join("")}
            ${fSel("assumptions", "inrush_strategy", "Стратегия отстройки от броска намагничивания", [["harmonic", "блокировка по 2-й гармонике"], ["pickup", "отстройка током срабатывания (как в 13Б)"]])}
            ${fSel("assumptions", "nth_harm_mode", "Блокировка при перевозбуждении", [["off", "выключена"], ["3", "3-я гармоника"], ["5", "5-я гармоника"]])}
            ${fSel("assumptions", "ref_tap", "Положение РПН для выравнивания токов", [["opt", "оптимальное напряжение"], ["nom", "номинальное"], ["mid", "среднее"]])}
            ${fSel("assumptions", "device_class", "Класс аппарата (коэффициент возврата)", [["microprocessor", "микропроцессорный терминал"], ["electromechanical", "электромеханическое реле"]])}
          </div>
        </div>
        <div class="panel">
          <div class="panel-title">МТЗ, обратная и нулевая последовательности, ДЗ</div>
          <div class="form-grid">
            ${Object.entries(labels).slice(13, 22).map(([k, [t, u]]) => fNum("assumptions", k, t, u)).join("")}
            ${fCheck("assumptions", "use_voltage_start", "МТЗ с пуском по напряжению")}
            ${fCheck("assumptions", "limit_46_sens", "Ограничить k_ч защиты ОП в зоне резервирования (≤ 1,5)")}
            ${fCheck("assumptions", "hv_class_330_plus", "Сторона 330–500 кВ")}
          </div>
        </div>
      </div>
      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-title">Перегрузка и общие</div>
          <div class="form-grid">
            ${Object.entries(labels).slice(22).map(([k, [t, u]]) => fNum("assumptions", k, t, u)).join("")}
            ${fSel("assumptions", "overload_side", "Сторона тепловой модели", [["auto", "автоматически (нерегулируемая)"], ["HV", "ВН"], ["MV", "СН"], ["LV", "НН"]])}
            ${fCheck("assumptions", "overload_trip_enabled", "Отключение при перегрузке предусмотрено схемой")}
            ${fSel("assumptions", "rounding_policy", "Политика округления уставок", [["safe", "ближайшее допустимое (в безопасную сторону)"], ["nearest", "ближайшее"], ["up", "вверх"], ["down", "вниз"]])}
          </div>
          <h3 class="sub">Отображаемые единицы</h3>
          <div class="form-grid">
            ${fSel("assumptions", "display_units.current", "Ток", [["А", "А"], ["кА", "кА"]])}
            ${fSel("assumptions", "display_units.voltage", "Напряжение", [["кВ", "кВ"], ["В", "В"]])}
            ${fSel("assumptions", "display_units.impedance", "Сопротивление", [["Ом", "Ом"]])}
            ${fSel("assumptions", "display_units.power", "Мощность", [["МВА", "МВА"], ["кВА", "кВА"]])}
          </div>
          <div class="hint">Внутреннее расчётное ядро использует фиксированные базовые единицы; настройка влияет только на отображение.</div>
        </div>
        <div class="panel">
          <div class="panel-title">Приоритет нормативных источников</div>
          <div class="hint">Порядок уровней определяет, какой документ имеет приоритет при расхождении значений. Редактируется в «Нормативной базе» / JSON проекта.</div>
          <table class="tbl">
            ${(a.norm_priority || []).map((lv, i) => `<tr><td class="mono">${i + 1}. ${esc(lv)}</td></tr>`).join("")}
          </table>
        </div>
      </div>
      <div class="panel"><div style="display:flex;gap:9px">${saveBtn("assumptions")}</div></div>`);
  };
})();
