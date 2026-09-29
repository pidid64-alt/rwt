/* Тест интерактивных действий UI (конструктор, профиль, формула, КЗ-детали, сохранение раздела). */
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const BASE = process.env.RZA_URL || "http://localhost:8000";
const STATIC = path.join(__dirname, "..", "rza", "web", "static");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf-8").replace(/<script src[^>]*><\/script>/g, "");
  const dom = new JSDOM(html, { url: BASE + "/", pretendToBeVisual: true, runScripts: "dangerously" });
  const { window } = dom;
  const doc = window.document;
  window.fetch = (url, opts) => fetch(url.startsWith("http") ? url : BASE + url, opts);
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.open = () => null;
  for (const f of ["app.js", "views.js"]) {
    const s = doc.createElement("script");
    s.textContent = fs.readFileSync(path.join(STATIC, f), "utf-8");
    doc.body.appendChild(s);
  }
  const App = window.eval("App");
  await App.boot();
  let fails = 0;
  const check = (name, ok, extra = "") => {
    console.log((ok ? "ok  " : "FAIL") + " " + name + (extra ? " — " + extra : ""));
    if (!ok) fails++;
  };

  // 1. Открыть демо-проект, изменить поле и сохранить раздел meta
  App.STATE.route = "project";
  await App.render();
  await sleep(300);
  const inp = doc.querySelector('input[data-draft="meta|substation"]');
  check("поле meta|substation найдено", !!inp);
  if (inp) {
    inp.value = "ПС 220/110/10 кВ «Демо» (тест)";
    inp.dispatchEvent(new window.Event("input", { bubbles: true }));
    check("черновик обновлён", App.getPath(App.draft("meta"), "substation").includes("тест"),
      String(App.getPath(App.draft("meta"), "substation")));
    // сохранение напрямую через API-путь UI
    await App.saveSection("meta", App.draft("meta"), "UI-тест", "Проверка сохранения из интерфейса");
    const fresh = await App.api("/project");
    check("meta сохранена в проекте", fresh.project.meta.substation.includes("тест"), fresh.project.meta.substation);
    // вернуть обратно
    await App.saveSection("meta", Object.assign(App.draft("meta"), { substation: "ПС 220/110/10 кВ «Демо»" }), "UI-тест", "Возврат исходного значения");
  }

  // 2. Конструктор терминала: открыть, заполнить, проверить, сохранить
  App.STATE.route = "terminals";
  await App.render();
  await sleep(300);
  App.actions.wizardOpen();
  await sleep(100);
  let modalHtml = doc.getElementById("modal-root").innerHTML;
  check("конструктор открыт", /Конструктор нового терминала/.test(modalHtml));
  // шаг 1–2: производитель/модель
  const setWiz = (path, val) => {
    const el = doc.querySelector(`[data-wiz="wiz|${path}"]`);
    if (!el) return false;
    el.value = val;
    el.dispatchEvent(new window.Event("input", { bubbles: true }));
    return true;
  };
  check("поле manufacturer", setWiz("manufacturer", "ТестЗавод"));
  App.actions.wizNext();
  await sleep(50);
  check("поле model", setWiz("model", "Тест-100"));
  setWiz("id", "user.test.terminal." + Date.now().toString(36));
  App.actions.wizNext();
  await sleep(50);
  setWiz("firmware", "V1.0");
  App.actions.wizNext(); // функции
  await sleep(50);
  const fnCb = doc.querySelector('.wiz-fn[value="87T"]');
  if (fnCb) {
    fnCb.checked = true;
    fnCb.dispatchEvent(new window.Event("change", { bubbles: true }));
  }
  App.actions.wizNext(); // параметры
  await sleep(50);
  App.actions.wizAddParam();
  await sleep(50);
  const setP = (i, f, v) => {
    const el = doc.querySelector(`[data-wizp="${i}|${f}"]`);
    if (!el) return false;
    el.value = v;
    el.dispatchEvent(new window.Event("input", { bubbles: true }));
    return true;
  };
  check("параметр: ключ", setP(0, "key", "DIF.Id"));
  setP(0, "name", "Ток срабатывания дифзащиты");
  setP(0, "pfm", "87T.IdiffPickup");
  setP(0, "unit", "I/InO");
  setP(0, "min", "0.02"); setP(0, "max", "2"); setP(0, "step", "0.01");
  App.actions.wizNext(); // шаг «Диапазоны и шаги»
  App.actions.wizNext(); // «Единицы»
  App.actions.wizNext(); // «Соответствие PFM»
  App.actions.wizNext(); // «Источник данных»
  await sleep(100);
  setWiz("src_doc", "Руководство (тест)");
  App.actions.wizNext(); // шаг «Проверка профиля»
  await sleep(100);
  App.actions.wizValidate();
  await sleep(600);
  App.actions.wizGo({ dataset: { i: 9 } }); // шаг «Проверка профиля»
  await sleep(100);
  modalHtml = doc.getElementById("modal-root").innerHTML;
  check("валидация профиля выполнена", /wiz-validation/.test(modalHtml) && !/Нажмите «Проверить профиль»/.test(modalHtml));
  App.actions.wizSave();
  await sleep(700);
  const terms = await App.api("/terminals");
  const created = terms.find((t) => t.id.startsWith("user.test.terminal"));
  check("новый терминал в базе устройств", !!created, created ? created.id : "не найден");
  if (created) {
    check("функция 87T отмечена", created.functions && created.functions["87T"] === true);
    check("параметров: 1", created.n_params === 1, String(created.n_params));
    // удалить
    await App.api("/terminals/" + encodeURIComponent(created.id), { method: "DELETE" });
    const terms2 = await App.api("/terminals");
    check("удаление пользовательского профиля", !terms2.find((t) => t.id === created.id));
  }

  // 3. Модальные окна деталей
  App.STATE.route = "kz";
  await App.render();
  await sleep(500);
  const kzRow = doc.querySelector('[data-act="kzDetail"]');
  check("строка КЗ найдена", !!kzRow);
  if (kzRow) {
    App.actions.kzDetail(kzRow.dataset ? kzRow : { dataset: { mode: "MAXKZ", tap: "nom", node: "HV", ftype: "3ph" } });
    await sleep(500);
    modalHtml = doc.getElementById("modal-root").innerHTML;
    check("детали КЗ открыты", /Составляющие последовательности/.test(modalHtml));
    App.closeModal();
  }

  App.STATE.route = "formulas";
  await App.render();
  await sleep(400);
  const fRow = doc.querySelector('[data-act="formulaDetail"]');
  check("строка формулы найдена", !!fRow);
  if (fRow) {
    App.actions.formulaDetail(fRow);
    await sleep(500);
    modalHtml = doc.getElementById("modal-root").innerHTML;
    check("детали формулы открыты", /Версии/.test(modalHtml) && /Переменные/.test(modalHtml));
    App.closeModal();
  }

  App.STATE.route = "terminals";
  await App.render();
  await sleep(400);
  const pBtn = doc.querySelector('[data-act="profileDetail"]');
  if (pBtn) {
    App.actions.profileDetail(pBtn);
    await sleep(500);
    modalHtml = doc.getElementById("modal-root").innerHTML;
    check("профиль терминала открыт", /Поддерживаемые функции/.test(modalHtml));
    App.closeModal();
  }

  // 4. Проверка отчётов (скачивание бинарных данных через API)
  for (const [kind, fmt] of [["card", "pdf"], ["calc", "docx"], ["kz", "xlsx"], ["changes", "csv"]]) {
    const r = await fetch(`${BASE}/api/report/${kind}?fmt=${fmt}`);
    const buf = await r.arrayBuffer();
    check(`отчёт ${kind}.${fmt}`, r.ok && buf.byteLength > 500, `${r.status}, ${buf.byteLength} байт`);
  }

  console.log(fails ? `\nИТОГ: ${fails} ошибок` : "\nИТОГ: интерактивные проверки пройдены ✔");
  process.exit(fails ? 1 : 0);
}
main();
