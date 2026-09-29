"""Генератор профилей: универсальный ШАБЛОН терминала и ЗАГОТОВКИ устройств из ТЗ (без выдуманных диапазонов).

Шаблон (template.generic) содержит УСЛОВНЫЕ диапазоны и шаги — он нужен для демонстрации сравнения терминалов и как основа
для копирования в «Конструкторе нового терминала». Заготовки (Siemens 7UT8, GE Multilin, SEL, ABB/Hitachi Energy, ЭКРА)
не содержат ни функций, ни диапазонов: они заполняются пользователем из руководства по конкретному исполнению и версии.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "rza" / "terminals" / "profiles"
SRC_T = [{"doc": "Шаблон профиля РЗА-АТ: диапазоны и шаги условные, не относятся к реальному устройству", "note": "Заменить данными из руководства по эксплуатации конкретного терминала"}]


def P(key, name, function, unit, lo, hi, step, default=None, comment=""):
    return {"key": key, "address": key, "name": name, "function": function, "kind": "float", "unit": unit, "min": lo, "max": hi, "step": step, "default": default,
            "comment": comment, "verified": False, "step_verified": False, "source": {"doc": "Шаблон (условные значения)", "section": "—", "page": 0}}


def E(key, name, function, options, default):
    return {"key": key, "address": key, "name": name, "function": function, "kind": "enum", "unit": "", "options": options, "default": default,
            "verified": False, "source": {"doc": "Шаблон (условные значения)"}}


template = {
    "schema": "rza-terminal-profile/1", "id": "template.generic", "manufacturer": "Пользовательский", "series": "Шаблон", "model": "Универсальный терминал (условные диапазоны)",
    "firmware": "—", "variants": ["шаблон"], "status": "template", "adapter": "generic", "rated_current_options": ["1 A", "5 A"], "frequency_hz": [50],
    "sources": SRC_T,
    "conventions": {
        "restraint": {"definition": "half_sum", "k_conv": 1.0, "description": "I_торм = ½·Σ|I| (среднее); наклоны в % от сквозного тока", "source": {"doc": "Шаблон"}},
        "characteristic_geometry": {"type": "max_of_lines", "description": "Как в универсальной модели"},
        "reset_ratio": {"default": 0.95, "49": 0.97},
        "tolerances": {"87T.char": 0.03},
    },
    "functions": {
        "87T": {"supported": True, "group": "Дифференциальная защита", "note": "шаблон"},
        "50/51": {"supported": True, "group": "МТЗ", "note": "шаблон (ток — первичные амперы)"},
        "50N/51N": {"supported": True, "group": "ТЗНП", "note": "шаблон"},
        "46": {"supported": True, "group": "Обратная последовательность", "note": "шаблон"},
        "21": {"supported": True, "group": "Дистанционная защита", "note": "шаблон (сопротивления — первичные Ом)"},
        "49": {"supported": True, "group": "Тепловая защита", "note": "шаблон"},
        "67": {"supported": False, "note": "не заложено в шаблоне"}, "67N": {"supported": False, "note": "не заложено в шаблоне"},
    },
    "parameters": [
        P("DIF.Id", "Минимальный дифференциальный ток I_д>", "87T", "% In", 5, 100, 1, 20), P("DIF.S1", "Наклон 1", "87T", "%", 10, 80, 1, 25), P("DIF.B1", "Опорная точка 1", "87T", "× In", 0, 2, 0.05, 0),
        P("DIF.S2", "Наклон 2", "87T", "%", 20, 150, 1, 50), P("DIF.B2", "Опорная точка 2", "87T", "× In", 0, 10, 0.05, 1.0), P("DIF.Idd", "Ток срабатывания высшей ступени I_д>>", "87T", "× In", 2, 30, 0.5, 8),
        P("DIF.T", "Выдержка I_д>", "87T", "с", 0, 5, 0.01, 0), P("DIF.Tdd", "Выдержка I_д>>", "87T", "с", 0, 5, 0.01, 0),
        E("DIF.Inr", "Блокировка по 2-й гармонике", "87T", ["ON", "OFF"], "ON"), P("DIF.H2", "Порог 2-й гармоники", "87T", "%", 5, 50, 1, 15),
        E("DIF.Hn", "Блокировка n-й гармоникой", "87T", ["OFF", "3", "5"], "OFF"), P("DIF.HnL", "Порог n-й гармоники", "87T", "%", 10, 60, 1, 30),
        P("OC.I", "Ток срабатывания МТЗ", "50/51", "A перв.", 10, 20000, 1, 600), P("OC.T", "Выдержка МТЗ", "50/51", "с", 0, 20, 0.05, 1),
        P("NP.I", "Ток срабатывания ТЗНП (3I0)", "50N/51N", "A перв.", 10, 10000, 1, 300), P("NP.T", "Выдержка ТЗНП", "50N/51N", "с", 0, 20, 0.05, 1),
        P("NS.I2", "Ток срабатывания защиты ОП", "46", "A перв.", 5, 5000, 1, 100), P("NS.T", "Выдержка защиты ОП", "46", "с", 0, 20, 0.05, 1),
        P("Z.Z1", "Сопротивление 1-й ступени", "21", "Ом перв.", 0.1, 500, 0.01, 10), P("Z.T1", "Выдержка 1-й ступени", "21", "с", 0, 5, 0.05, 0.3),
        P("Z.Z2", "Сопротивление 2-й ступени", "21", "Ом перв.", 0.1, 1000, 0.01, 50), P("Z.T2", "Выдержка 2-й ступени", "21", "с", 0, 10, 0.05, 1),
        P("Z.A2", "Смещение 2-й ступени", "21", "о.е.", -0.1, 0.5, 0.01, 0),
        P("TH.K", "K-фактор", "49", "о.е.", 0.5, 2.0, 0.01, 1.05), P("TH.TAU", "Постоянная времени", "49", "мин", 1, 1000, 1, 60),
        P("TH.ALM", "Уровень предупреждения по температуре", "49", "%", 50, 100, 1, 90), P("TH.IAL", "Токовый уровень сигнала перегрузки", "49", "A перв.", 10, 20000, 1, 600),
        P("TH.TAL", "Выдержка сигнала перегрузки", "49", "с", 0, 600, 0.5, 10),
    ],
    "mapping": {
        "87T.IdiffPickup": {"instances": {"": "DIF.Id"}, "transform": "pct_from_pu"}, "87T.Slope1": {"instances": {"": "DIF.S1"}, "transform": "pct_from_pu"},
        "87T.BasePoint1": {"instances": {"": "DIF.B1"}, "transform": "identity"}, "87T.Slope2": {"instances": {"": "DIF.S2"}, "transform": "pct_from_pu"},
        "87T.BasePoint2": {"instances": {"": "DIF.B2"}, "transform": "identity"}, "87T.HighSet": {"instances": {"": "DIF.Idd"}, "transform": "identity"},
        "87T.Delay": {"instances": {"": "DIF.T"}, "transform": "identity"}, "87T.HighSetDelay": {"instances": {"": "DIF.Tdd"}, "transform": "identity"},
        "87T.InrushBlocking": {"instances": {"": "DIF.Inr"}, "transform": "bool_onoff"}, "87T.Inrush2ndHarm": {"instances": {"": "DIF.H2"}, "transform": "identity"},
        "87T.NthHarmMode": {"instances": {"": "DIF.Hn"}, "transform": "enum_map", "map": {"off": "OFF", "3": "3", "5": "5"}}, "87T.NthHarm": {"instances": {"": "DIF.HnL"}, "transform": "identity"},
        "51.IPickup": {"instances": {"*": "OC.I"}, "transform": "identity"}, "51.Delay": {"instances": {"*": "OC.T"}, "transform": "identity"},
        "51N.I0Pickup": {"instances": {"*": "NP.I"}, "transform": "identity"}, "51N.Delay": {"instances": {"*": "NP.T"}, "transform": "identity"},
        "46.I2Pickup": {"instances": {"*": "NS.I2"}, "transform": "identity"}, "46.Delay": {"instances": {"*": "NS.T"}, "transform": "identity"},
        "21.Z1": {"instances": {"*": "Z.Z1"}, "transform": "identity"}, "21.Z1Delay": {"instances": {"*": "Z.T1"}, "transform": "identity"},
        "21.Z2": {"instances": {"*": "Z.Z2"}, "transform": "identity"}, "21.Z2Delay": {"instances": {"*": "Z.T2"}, "transform": "identity"}, "21.Z2Offset": {"instances": {"*": "Z.A2"}, "transform": "identity"},
        "49.KFactor": {"instances": {"*": "TH.K"}, "transform": "identity"}, "49.TimeConstant": {"instances": {"*": "TH.TAU"}, "transform": "identity"},
        "49.ThetaAlarm": {"instances": {"*": "TH.ALM"}, "transform": "identity"}, "49.IAlarm": {"instances": {"*": "TH.IAL"}, "transform": "identity"},
        "49.AlarmDelay": {"instances": {"*": "TH.TAL"}, "transform": "identity"},
    },
    "dependencies": [{"rule": "DIF.S1 <= DIF.S2", "text": "Наклон 2 не менее наклона 1", "source": "шаблон", "verified": False}],
    "signals": [], "iec61850": {"supported": False, "goose": False, "sampled_values": False, "mms": False, "note": "заполняется пользователем"},
    "notes": "ШАБЛОН: все диапазоны, шаги и единицы условные. Для реального устройства создайте копию через «Конструктор терминала» и заполните из руководства.",
}
(OUT / "template_generic.json").write_text(json.dumps(template, ensure_ascii=False, indent=1), encoding="utf-8")


def skeleton(pid, manufacturer, series, model, note):
    return {"schema": "rza-terminal-profile/1", "id": pid, "manufacturer": manufacturer, "series": series, "model": model, "firmware": "", "variants": [], "status": "not_loaded",
            "adapter": "generic", "functions": {}, "parameters": [], "mapping": {}, "sources": [], "signals": [],
            "iec61850": {"supported": None, "goose": None, "sampled_values": None, "mms": None, "note": "не заполнено"},
            "notes": note}


NOTE = ("ЗАГОТОВКА. Функции, параметры, диапазоны и шаги не заданы: их нужно загрузить из проверенного руководства по конкретному исполнению и версии ПО "
        "(мастер «Добавить устройство» либо импорт JSON). Расчётное ядро при этом не меняется.")
skeletons = [
    skeleton("siemens.7ut8x", "Siemens", "SIPROTEC 5", "7UT85 / 7UT86 / 7UT87", NOTE),
    skeleton("ge.multilin.t60", "GE Vernova", "Multilin", "T60 (защита трансформатора)", NOTE),
    skeleton("sel.387e", "SEL", "SEL-387", "SEL-387E", NOTE),
    skeleton("hitachi.ret670", "Hitachi Energy (ABB)", "Relion 670", "RET670 (защита трансформатора)", NOTE),
    skeleton("ekra.she2607", "ЭКРА", "ШЭ2607", "Шкафы защит трансформаторов и АТ", NOTE),
]
for s in skeletons:
    (OUT / (s["id"].replace(".", "_") + ".json")).write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
print("Профили сформированы:", 1 + len(skeletons))
