"""Импортёр параметров терминалов SIPROTEC 4 (7UT6x) из PDF-руководства → профиль терминала.

ТЗ: «Не придумывать диапазоны и номера параметров 7UT6. Они должны загружаться из проверенного руководства по конкретному
исполнению/версии устройства и храниться в базе устройства.»

Импортёр читает текстовый слой PDF (PyMuPDF):
  • приложение «A.8 Settings» — адреса, названия, функции, диапазоны, значения по умолчанию, комментарии;
  • разд. 4 «Technical Data» — шаги уставок (curated-таблица STEPS со ссылками на страницы, сверена с текстом руководства);
  • «Information List» функций — входы/выходы/сигналы (номер, название, тип, комментарий).
Результат: сырой каталог параметров (rza/terminals/profiles/_raw/…) и профиль (rza/terminals/profiles/siemens_7ut6_v4_6.json).
Сопоставление параметров PFM → адреса (MAPPING) — инженерное решение, вынесено в данные.

Запуск:  python tools/import_siemens_manual.py /путь/к/7UT6x_Manual_A2_V040101_en.pdf
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from datetime import date
from pathlib import Path

DOC = {
    "doc": "SIPROTEC Differential Protection 7UT6x V4.6 Manual",
    "order_no": "C53000-G1176-C230-2",
    "release": "06.2012",
    "url": "https://www.automation-berlin.com/downloads/siemens/energy_ptd/7UT6x_Manual_A2_V040101_en.pdf",
}
NOISE = {"Appendix", "A.8 Settings", "SIPROTEC, 7UT6x, Manual", "C53000-G1176-C230-2, Release date 06.2012"}
HDR = ["Addr.", "Parameter", "Function", "C", "Setting Options", "Default Setting", "Comments"]
C_LABELS = {"1A", "5A", "0.1A"}
EXTRA_FUNCS = {"3I0 O/C", "3I0 O/C 2", "3I0 O/C 3", "1Phase O/C"}
ADDR_RE = re.compile(r"^\d{1,4}A?$")
NO_RE = re.compile(r"\d{3}\.\d{4}|\d{4,5}")
GROUPS_OF_INTEREST = ["Diff. Prot", "Phase O/C", "Phase O/C 2", "Phase O/C 3", "3I0 O/C", "3I0 O/C 2", "3I0 O/C 3", "Earth O/C", "Earth O/C 2",
                      "Unbalance Load", "Therm. Overload", "Therm.Overload2", "REF", "P.System Data 1"]

# Шаги уставок: раздел 4 «Technical Data» руководства (страницы указаны). Для остальных шаг выводится из числа десятичных знаков диапазона.
STEPS = {
    "1221": (0.01, "4.2, с. 471"), "1231": (0.1, "4.2, с. 471"), "1252A": (0.1, "4.2, с. 471"), "1261A": (0.01, "4.2, с. 471"), "1262A": (1, "4.2, с. 471 (1 период)"),
    "1226A": (0.01, "4.2, с. 471"), "1236A": (0.01, "4.2, с. 471"), "1271": (1, "4.2, с. 472"), "1276": (1, "4.2, с. 472"), "1272A": (1, "4.2, с. 472 (1 период)"),
    "1277A": (1, "4.2, с. 472"), "1263A": (1, "4.2, с. 472"),
    "4202": (0.01, "4.9, с. 505"), "4203": (0.1, "4.9, с. 505"), "4204": (1, "4.9, с. 505"), "4205": (0.01, "4.9, с. 505 (0,01 А при I_N = 1 А)"),
    "4207A": (0.1, "4.9, с. 505"), "4208A": (1, "4.9, с. 505"),
}
STEP_BY_RANGE_GROUP = {   # токовые и временные ступени МТЗ / ОП: 0,01 (А для I_N = 1 А; с)
    "Phase O/C": "4.4, с. 480", "Phase O/C 2": "4.4, с. 480", "Phase O/C 3": "4.4, с. 480",
    "3I0 O/C": "4.4, с. 480", "3I0 O/C 2": "4.4, с. 480", "3I0 O/C 3": "4.4, с. 480", "Earth O/C": "4.4, с. 480", "Earth O/C 2": "4.4, с. 480",
    "Unbalance Load": "4.8, с. 496",
}

# Сопоставление PFM → параметры 7UT6x (инженерное решение; адреса и диапазоны берутся из руководства).
# ключ PFM: {instance: адрес} ; transform: тип преобразования универсального значения в единицу терминала
MAPPING = {
    "87T.IdiffPickup": {"": "1221", "transform": "identity"},
    "87T.Slope1": {"": "1241A", "transform": "slope_conv"},
    "87T.BasePoint1": {"": "1242A", "transform": "bp_conv"},
    "87T.Slope2": {"": "1243A", "transform": "slope_conv"},
    "87T.BasePoint2": {"": "1244A", "transform": "bp_conv"},
    "87T.HighSet": {"": "1231", "transform": "identity"},
    "87T.Delay": {"": "1226A", "transform": "identity"},
    "87T.HighSetDelay": {"": "1236A", "transform": "identity"},
    "87T.InrushBlocking": {"": "1206", "transform": "bool_onoff"},
    "87T.Inrush2ndHarm": {"": "1271", "transform": "identity"},
    "87T.NthHarmMode": {"": "1207", "transform": "enum_map", "map": {"off": "OFF", "3": "3. Harmonic", "5": "5. Harmonic"}},
    "87T.NthHarm": {"": "1276", "transform": "identity"},
    "87T.AddOnStab": {"": "1261A", "transform": "bp_conv"},
    "87T.AddOnStabTime": {"": "1262A", "transform": "identity"},
    "51.IPickup": {"HV": "2015", "MV": "3015", "LV": "3215", "transform": "i_rel_side"},
    "51.Delay": {"HV": "2016", "MV": "3016", "LV": "3216", "transform": "identity"},
    "46.I2Pickup": {"HV": "4015", "MV": "4015", "transform": "i_rel_side", "single_instance": True},
    "46.Delay": {"HV": "4016", "MV": "4016", "transform": "identity", "single_instance": True},
    "49.KFactor": {"HV": "4202", "MV": "4202", "LV": "4202", "transform": "identity", "single_instance": True},
    "49.TimeConstant": {"HV": "4203", "MV": "4203", "LV": "4203", "transform": "identity", "single_instance": True},
    "49.ThetaAlarm": {"HV": "4204", "MV": "4204", "LV": "4204", "transform": "identity", "single_instance": True},
    "49.IAlarm": {"HV": "4205", "MV": "4205", "LV": "4205", "transform": "i_rel_side", "single_instance": True},
}
# ТЗНП: ступень 1 → 3I0>> (DT), 2 → 3I0> (DT), 3 → 3I0p (зависимая; независимая выдержка недоступна). Стороны: HV → группа «3I0 O/C», MV → «3I0 O/C 2».
ZNP_GROUPS = {"HV": "3I0 O/C", "MV": "3I0 O/C 2", "LV": "3I0 O/C 3"}
ASSIGN = {    # назначение функций сторонам (структурные параметры)
    "Phase O/C": {"HV": ("420", "Side 1"), "MV": ("430", "Side 2"), "LV": ("432", "Side 3")},
    "3I0 O/C": {"HV": ("422", "Side 1"), "MV": ("434", "Side 2"), "LV": ("436", "Side 3")},
    "Unbalance Load": {"HV": ("440", "Side 1"), "MV": ("440", "Side 2")},
    "Therm. Overload": {"HV": ("442", "Side 1"), "MV": ("442", "Side 2"), "LV": ("442", "Side 3")},
}
FUNCTIONS = {
    "87T": {"supported": True, "group": "Diff. Prot", "note": "Продольная дифференциальная защита; объект «Autotransf.» (адрес 105), стороны 1…3 (адреса 311–335)"},
    "50/51": {"supported": True, "group": "Phase O/C, Phase O/C 2, Phase O/C 3", "note": "Две независимые ступени с выдержкой и одна зависимая; 3 функции для 7UT613/63x (разд. 1.3), назначаются сторонам (адреса 420, 430, 432)"},
    "50N/51N": {"supported": True, "group": "3I0 O/C, 3I0 O/C 2, 3I0 O/C 3", "note": "Ток нулевой последовательности 3I0 (расчёт по фазным токам стороны); 3 функции для 7UT613/63x; независимых ступеней с выдержкой две (3I0>>, 3I0>) и одна зависимая (3I0p)"},
    "46": {"supported": True, "group": "Unbalance Load", "note": "Одна функция, назначается одной стороне (адрес 440); ступени I2>>, I2> с независимой выдержкой и зависимая I2p"},
    "49": {"supported": True, "group": "Therm. Overload", "note": "Тепловая модель IEC 60255-8 (адреса 4201–4212), назначается одной стороне (адрес 442); вторая функция «Therm.Overload2» (44xx) не сопоставлена в MVP"},
    "21": {"supported": False, "note": "В руководстве 7UT6x V4.6 дистанционная защита не описана (перечень функций — разд. 1.3)"},
    "67": {"supported": False, "note": "Направленной токовой защиты в перечне функций 7UT6x (разд. 1.3) нет"},
    "67N": {"supported": False, "note": "Направленной защиты от замыканий на землю в перечне функций 7UT6x (разд. 1.3) нет"},
    "87N": {"supported": True, "group": "REF", "note": "Защита от замыканий на землю (REF); параметры не сопоставлены в MVP", "mapped": False},
    "50BF": {"supported": True, "group": "Breaker Failure", "note": "УРОВ; параметры не сопоставлены в MVP", "mapped": False},
    "27": {"supported": True, "group": "Undervoltage", "note": "Минимальное напряжение; параметры не сопоставлены в MVP", "mapped": False},
    "59": {"supported": True, "group": "Overvoltage", "note": "Максимальное напряжение; параметры не сопоставлены в MVP", "mapped": False},
}


def _pages(txt: str) -> dict[int, str]:
    parts = re.split(r"######## PAGE (\d+) ########\n", txt)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def extract_text(pdf_path: str) -> tuple[str, str]:
    import pymupdf   # noqa
    data = Path(pdf_path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    d = pymupdf.open(pdf_path)
    out = [f"\n\n######## PAGE {i + 1} ########\n{p.get_text()}" for i, p in enumerate(d)]
    return "".join(out), sha


def parse_settings(txt: str) -> list[dict]:
    pages = _pages(txt)
    a8 = sorted(n for n, t in pages.items() if "A.8 Settings" in t[:120])
    lines: list[tuple[int, str]] = []
    for n in a8:
        ls = [l.strip() for l in pages[n].split("\n") if l.strip()]
        cleaned = [l for l in ls if l not in NOISE and not (re.fullmatch(r"\d{3}", l) and int(l) == n)]
        i = 0
        while i < len(cleaned):
            if cleaned[i:i + 7] == HDR:
                i += 7
                continue
            lines.append((n, cleaned[i]))
            i += 1
    cand = collections.Counter()
    for i in range(len(lines) - 2):
        a = lines[i][1]
        if ADDR_RE.match(a) and (len(a.rstrip("A")) >= 3 or a == "0"):
            cand[lines[i + 2][1]] += 1
    funcs = {k for k, v in cand.items() if not re.match(r"^[\d.,]+(\s|$)", k) and k not in C_LABELS and len(k) < 24}
    funcs -= {"CT Rated Secondary Current", "to RTD", "Locations"}
    funcs |= EXTRA_FUNCS
    starts = [i for i in range(len(lines) - 2) if ADDR_RE.match(lines[i][1]) and lines[i + 2][1] in funcs]

    def is_default_like(s):
        return bool(re.match(r"^-?[\d.,]+(\s*(A|V|kV|MVA|sec|%|Cycle|Cycles|min|Min\.|Hz|s|Ohm|°C|°F|kA|kW|MW|I/In[OS]|I/Ip|TD|mA))?$", s)) or s == "∞"

    rows = []
    for si, i in enumerate(starts):
        j = starts[si + 1] if si + 1 < len(starts) else len(lines)
        addr, name, func = lines[i][1], lines[i + 1][1], lines[i + 2][1]
        body = [l[1] for l in lines[i + 3:j]]
        segs = []
        if body and body[0] in C_LABELS:
            cur = None
            for l in body:
                if l in C_LABELS:
                    cur = {"C": l, "lines": []}
                    segs.append(cur)
                else:
                    cur["lines"].append(l)
        else:
            segs = [{"C": None, "lines": body}]
        variants = []
        for sg in segs:
            ls = sg["lines"]
            options, default, comment = [], None, []
            if any(".." in x for x in ls[:2]):
                k = 0
                while k < len(ls) and ".." in ls[k]:
                    options.append(ls[k]); k += 1
                if k < len(ls) and is_default_like(ls[k]):
                    default = ls[k]; k += 1
                comment = ls[k:]
            else:
                seen, k = [], 0
                while k < len(ls):
                    if ls[k] in seen:
                        default = ls[k]; k += 1
                        break
                    seen.append(ls[k]); k += 1
                options = seen
                comment = ls[k:] if default is not None else []
            variants.append({"C": sg["C"], "options": options, "default": default, "comment": " ".join(comment)})
        rows.append({"addr": addr, "name": name, "function": func, "page": lines[i][0], "variants": variants})
    return rows


RANGE_RE = re.compile(r"^\s*(-?[\d.]+)\s*\.\.\s*(-?[\d.]+)\s*(.*?)\s*(?:;\s*(∞|0))?\s*$")


def parse_range(s: str) -> dict | None:
    m = RANGE_RE.match(s.replace("\u2009", " "))
    if not m:
        return None
    lo, hi, unit, sp = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
    dec = max(len(lo.split(".")[1]) if "." in lo else 0, len(hi.split(".")[1]) if "." in hi else 0)
    return {"min": float(lo), "max": float(hi), "unit": unit, "decimals": dec, "special": [sp] if sp else []}


def to_number(s: str | None):
    if s is None:
        return None
    m = re.match(r"^\s*(-?[\d.]+)", s)
    return float(m.group(1)) if m else None


def build_parameters(rows: list[dict]) -> list[dict]:
    params = []
    for r in rows:
        if r["function"] not in GROUPS_OF_INTEREST:
            continue
        addr = r["addr"]
        if r["function"] == "P.System Data 1":
            n = int(addr.rstrip("A"))
            if not (300 <= n <= 355 or 400 <= n <= 444 or 511 <= n <= 553 or n in (105, 112, 270)):
                continue
        if r["name"].startswith("IN-SEC CT"):
            # вторичный номинальный ток ТТ: варианты 1A/5A/0.1A — это допустимые значения, а не конфигурации (прил. A.8, с. 609)
            params.append({"key": addr, "address": addr, "name": r["name"], "group": r["function"], "comment": "CT Rated Secondary Current", "c_variant": None,
                           "source": {"doc": DOC["doc"], "section": "A.8 Settings", "page": r["page"]}, "verified": True,
                           "kind": "enum", "unit": "", "options": ["1A", "5A", "0.1A"], "default": "1A"})
            continue
        for v in r["variants"]:
            key = addr if v["C"] is None else f"{addr}[{v['C']}]"
            p = {"key": key, "address": addr, "name": r["name"], "group": r["function"], "comment": v["comment"], "c_variant": v["C"],
                 "source": {"doc": DOC["doc"], "section": "A.8 Settings", "page": r["page"]}, "verified": True}
            rng = parse_range(v["options"][0]) if v["options"] else None
            if rng and len(v["options"]) >= 1 and ".." in v["options"][0]:
                p.update(kind="float", unit=rng["unit"] or "", min=rng["min"], max=rng["max"], special=rng["special"])
                p["default"] = to_number(v["default"])
                p["default_raw"] = v["default"]
                st = STEPS.get(addr)
                if st:
                    p["step"], p["step_source"], p["step_verified"] = st[0], "Технические данные, разд. " + st[1], True
                elif r["function"] in STEP_BY_RANGE_GROUP and (rng["unit"] in ("A", "I/InS", "sec", "") ):
                    step = 0.01 if rng["decimals"] >= 2 else 10 ** (-rng["decimals"])
                    p["step"] = step
                    p["step_source"] = f"Технические данные, разд. {STEP_BY_RANGE_GROUP[r['function']]} (0,01 А/с); для I/InS принято 0,01"
                    p["step_verified"] = rng["unit"] in ("A", "sec")
                else:
                    step = 10 ** (-rng["decimals"])
                    p["step"], p["step_source"], p["step_verified"] = step, "Не указан явно в руководстве: принят по числу десятичных знаков диапазона (разрешение DIGSI)", False
                if len(v["options"]) > 1:
                    p["range2"] = v["options"][1]
            else:
                p.update(kind="enum", unit="", options=v["options"], default=v["default_raw"] if "default_raw" in v else v["default"])
            params.append(p)
    return params


def parse_signals(txt: str) -> list[dict]:
    pages = _pages(txt)
    signals = []
    for n, t in sorted(pages.items()):
        if not (100 <= n <= 300):
            continue
        ls = [l.strip() for l in t.split("\n") if l.strip()]
        if "Information List" not in t and not any(ls[i:i + 4] == ["No.", "Information", "Type of In-", "formation"] for i in range(len(ls))):
            # продолжение таблицы: строки вида номер/имя/тип
            pass
        chap = ls[1] if len(ls) > 1 else ""
        i = 0
        while i < len(ls) - 3:
            if NO_RE.fullmatch(ls[i]) and ls[i + 2] in ("SP", "OUT", "IntSP", "IntSP_Ev", "SP_Ev", "OUT_Ev", "VI", "MV", "IEC") and ls[i + 1] not in ("SP", "OUT"):
                signals.append({"no": ls[i], "name": ls[i + 1], "type": ls[i + 2], "comment": ls[i + 3] if i + 3 < len(ls) and not NO_RE.fullmatch(ls[i + 3]) else "",
                                "chapter": chap, "page": n})
                i += 4
            else:
                i += 1
    return signals


def signal_function(chapter: str, name: str = "") -> str:
    c, nm = chapter.lower(), name.lower()
    if "differential" in c and "high-imp" not in nm:
        return "87T"
    if "overcurrent" in c and "phase" in c:
        if "3i0" in nm:
            return "50N/51N"
        if "ph" in nm or "i>" in nm or "ip" in nm or "phase" in nm:
            return "50/51"
        return ""
    if "earth current" in c:
        return "50N/51N"
    if "unbalanced" in c:
        return "46"
    if "thermal" in c:
        return "49"
    if "restricted" in c:
        return "87N"
    if "breaker failure" in c:
        return "50BF"
    return ""


def build_profile(rows: list[dict], params: list[dict], signals: list[dict], sha: str) -> dict:
    byaddr: dict[str, dict] = {}
    for p in params:
        byaddr.setdefault(p["address"], p)
    for p in params:
        p["function"] = "87T" if p["group"] == "Diff. Prot" else "50/51" if p["group"].startswith("Phase O/C") else "50N/51N" if p["group"].startswith(("3I0", "Earth")) else \
            "46" if p["group"] == "Unbalance Load" else "49" if p["group"].startswith("Therm") else "87N" if p["group"] == "REF" else "object"
    mapping = {}
    for pid, m in MAPPING.items():
        entry = {"instances": {k: v for k, v in m.items() if k not in ("transform", "map", "single_instance")}, "transform": m["transform"]}
        if "map" in m: entry["map"] = m["map"]
        if m.get("single_instance"): entry["single_instance"] = True
        mapping[pid] = entry
    # ТЗНП: три ступени
    def find(group: str, name: str, unit: str | None = None):
        for r in rows:
            if r["function"] == group and r["name"] == name:
                for v in r["variants"]:
                    if unit is None or (v["options"] and unit in v["options"][0]):
                        return r["addr"]
        return None
    for side, grp in ZNP_GROUPS.items():
        a1, a2 = find(grp, "3I0>>", "I/InS"), find(grp, "3I0>", "I/InS")
        t1, t2 = find(grp, "T 3I0>>"), find(grp, "T 3I0>")
        ap, tp = find(grp, "3I0p", "I/InS"), find(grp, "T 3I0p")
        mp = mapping.setdefault("51N.I0Pickup", {"instances": {}, "transform": "i_rel_side"})
        md = mapping.setdefault("51N.Delay", {"instances": {}, "transform": "identity"})
        if a1: mp["instances"][f"{side}:1"] = a1
        if a2: mp["instances"][f"{side}:2"] = a2
        if ap: mp["instances"][f"{side}:3"] = ap
        if t1: md["instances"][f"{side}:1"] = t1
        if t2: md["instances"][f"{side}:2"] = t2
        if tp: md["instances"][f"{side}:3"] = tp
        md.setdefault("idmt_stage", {})[f"{side}:3"] = {"curve": "IEC_NI", "curve_option": "Normal Inverse", "curve_param": find(grp, "IEC CURVE"), "note": "Ступень 3 реализуется зависимой характеристикой 3I0p (независимая выдержка недоступна); временной множитель подобран для эквивалентного времени в расчётной точке"}
    profile = {
        "schema": "rza-terminal-profile/1",
        "id": "siemens.7ut6.v4_6",
        "manufacturer": "Siemens", "series": "SIPROTEC 4", "model": "7UT6x", "variants": ["7UT612", "7UT613", "7UT633", "7UT635"],
        "firmware": "V4.6", "status": "verified", "adapter": "siemens_7ut6",
        "rated_current_options": ["1 A", "5 A"], "frequency_hz": [50, 60, 16.7],
        "sources": [dict(DOC, file_sha256=sha, retrieved=date.today().isoformat(),
                         note="Параметры извлечены автоматически из текстового слоя PDF (tools/import_siemens_manual.py); шаги — из разд. 4 (Technical Data)")],
        "conventions": {
            "restraint": {"definition": "sum_abs", "k_conv": 2.0, "description": "I_stab = |I1| + |I2| + … (арифметическая сумма); I_diff = |I1 + I2 + …|",
                          "source": {"doc": DOC["doc"], "section": "2.2.1, с. 106–107"}},
            "characteristic_geometry": {"type": "max_of_lines", "description": "Порог = max(I-DIFF>, Slope1·(I_stab − BasePoint1), Slope2·(I_stab − BasePoint2)); ветви b и c — прямые, выходящие из опорных точек на оси I_stab; ограничение I-DIFF>> (рис. 2-23)",
                                        "source": {"doc": DOC["doc"], "section": "2.2.4, рис. 2-23, с. 111"}},
            "pickup_reference": "I/InO — доля номинального тока защищаемого объекта (наибольшая мощность обмоток) на стороне; I/InS — доля номинального тока обмотки стороны",
            "reset_ratio": {"default": 0.95, "49": 0.97, "source": {"doc": DOC["doc"], "section": "4.4 (с. 482), 4.9 (с. 505)"}},
            "tolerances": {"87T.char": 0.05, "source": {"doc": DOC["doc"], "section": "4.2, с. 471 (IDiff> и характеристика ±5 % уставки)"}},
            "regulated_side_voltage": "Для регулируемой обмотки UN-PRI SIDE — напряжение, соответствующее среднему току диапазона: U = 2·Umax·Umin/(Umax+Umin) (разд. 2.1.4, с. 65)",
        },
        "functions": FUNCTIONS,
        "parameters": params,
        "mapping": mapping,
        "assignments": {k: {s: {"address": a, "value": v} for s, (a, v) in d.items()} for k, d in ASSIGN.items()},
        "object_params": {
            "side": {"HV": {"un": "311", "sn": "312", "starpoint": "313", "connection": "314"},
                     "MV": {"un": "321", "sn": "322", "starpoint": "323", "connection": "324", "vector_group": "325"},
                     "LV": {"un": "331", "sn": "332", "starpoint": "333", "connection": "334", "vector_group": "335"}},
            "ct": {"M1": {"starpoint": "511", "primary": "512", "secondary": "513"}, "M2": {"starpoint": "521", "primary": "522", "secondary": "523"}, "M3": {"starpoint": "531", "primary": "532", "secondary": "533"}},
        },
        "dependencies": [
            {"rule": "1241A <= 1243A", "text": "Наклон 2 не менее наклона 1 (инженерное правило; диапазоны 0,10–0,50 и 0,25–0,95)", "source": "инженерное правило (не из руководства)", "verified": False},
            {"rule": "1242A < 1244A", "text": "Опорная точка 1 меньше опорной точки 2", "source": "инженерное правило (не из руководства)", "verified": False},
            {"rule": "1221 <= 1231", "text": "I-DIFF> не больше I-DIFF>>", "source": "инженерное правило", "verified": False},
        ],
        "signals": [dict(s, function=signal_function(s["chapter"], s["name"])) for s in signals if signal_function(s["chapter"], s["name"])],
        "iec61850": {"supported": True, "goose": True, "sampled_values": False, "mms": True,
                     "note": "Порты и протоколы (в т.ч. IEC 61850 через модуль EN100) зависят от исполнения (MLFB); подтверждение по разд. «Communication» руководства требуется", "verified": False},
        "notes": "Профиль создан импортом из руководства. Не сопоставлены в MVP: REF (87N), УРОВ (50BF), напряжения (27/59), Therm.Overload2, однофазная МТЗ, гибкие функции.",
    }
    return profile


def import_manual(pdf_path: str, out_dir: Path) -> dict:
    txt, sha = extract_text(pdf_path)
    rows = parse_settings(txt)
    params = build_parameters(rows)
    signals = parse_signals(txt)
    profile = build_profile(rows, params, signals, sha)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "_raw"
    raw.mkdir(exist_ok=True)
    (raw / "siemens_7ut6_v4_6_settings_raw.json").write_text(json.dumps({"source": DOC, "sha256": sha, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "siemens_7ut6_v4_6.json").write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"rows": len(rows), "params": len(params), "signals": len(signals), "sha256": sha}
