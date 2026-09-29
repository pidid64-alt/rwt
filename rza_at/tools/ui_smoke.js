/* Смоук-тест интерфейса РЗА-АТ: прогон всех разделов и модальных окон в jsdom против живого API.
 * Запуск:  NODE_PATH=<путь к node_modules с jsdom> node tools/ui_smoke.js   (сервер должен быть на localhost:8000) */
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const BASE = process.env.RZA_URL || "http://localhost:8000";
const STATIC = path.join(__dirname, "..", "rza", "web", "static");

async function main() {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf-8")
    .replace(/<script src[^>]*><\/script>/g, ""); // скрипты вставим сами
  const dom = new JSDOM(html, { url: BASE + "/", pretendToBeVisual: true, runScripts: "dangerously" });
  const { window } = dom;
  window.fetch = (url, opts) => fetch(url.startsWith("http") ? url : BASE + url, opts);
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.open = () => null;

  const errors = [];
  window.addEventListener("error", (e) => errors.push("window.onerror: " + (e.error ? e.error.stack || e.error.message : e.message)));

  for (const f of ["app.js", "views.js"]) {
    const s = window.document.createElement("script");
    s.textContent = fs.readFileSync(path.join(STATIC, f), "utf-8");
    window.document.body.appendChild(s);
  }
  let App;
  try {
    App = window.eval("App");
  } catch (e) {
    console.log("App не определён:", e.message);
    process.exit(1);
  }
  if (!App) { console.log("App = undefined"); process.exit(1); }

  try {
    await App.boot();
    console.log("boot: ok, route =", App.STATE.route);
  } catch (e) {
    console.log("boot FAIL:", e.message, "\n", e.stack);
    process.exit(1);
  }

  const routes = App.NAV.flatMap((g) => g.items.map((i) => i.id));
  let fails = 0;
  for (const r of routes) {
    try {
      App.STATE.route = r;
      await App.render();
      await new Promise((res) => setTimeout(res, 500));
      await App.render();
      const mainEl = window.document.getElementById("main");
      const len = (mainEl.innerHTML || "").length;
      const hasErr = /Ошибка отображения/.test(mainEl.innerHTML);
      if (hasErr || len < 200) {
        console.log(`VIEW FAIL ${r}: len=${len} ${hasErr ? "(ошибка отображения)" : "(пусто)"}`);
        if (hasErr) console.log("   ", mainEl.textContent.slice(0, 400));
        fails++;
      } else {
        console.log(`VIEW ok ${r}: ${len} симв.`);
      }
    } catch (e) {
      console.log(`VIEW THROW ${r}: ${e.message}`);
      console.log((e.stack || "").split("\n").slice(0, 5).join("\n"));
      fails++;
    }
  }

  try {
    await App.openTrace("87T", "87T.IdiffPickup", "siemens.7ut6.v4_6");
    await new Promise((res) => setTimeout(res, 400));
    const m = window.document.getElementById("modal-root").innerHTML;
    if (m.length > 1000 && /Показать расчёт/.test(m)) console.log(`MODAL trace: ok (${m.length})`);
    else { console.log("MODAL trace FAIL:", m.slice(0, 300)); fails++; }
    App.closeModal();
    await App.openCheck("87T.sens", "calc", null);
    await new Promise((res) => setTimeout(res, 400));
    const m2 = window.document.getElementById("modal-root").innerHTML;
    if (m2.length > 500 && /Проверка/.test(m2)) console.log(`MODAL check: ok (${m2.length})`);
    else { console.log("MODAL check FAIL:", m2.slice(0, 300)); fails++; }
    App.closeModal();
  } catch (e) {
    console.log("MODAL THROW:", e.message);
    fails++;
  }

  if (errors.length) { console.log("window errors:", errors.slice(0, 5)); fails += errors.length; }
  console.log(fails ? `\nИТОГ: ${fails} ошибок` : "\nИТОГ: все проверки пройдены ✔");
  process.exit(fails ? 1 : 0);
}
main();
