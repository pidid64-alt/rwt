"""Профиль терминала РЗА: схема, доступ к параметрам, проверка профиля (мастер «Добавить устройство», шаг 11).

Профиль — данные (JSON), а не код: расчётное ядро о нём ничего не знает. Профиль сообщает:
    какие функции поддерживает устройство и как они параметризуются (параметры, диапазоны, шаги, единицы, ограничения),
    как параметры PFM связаны с параметрами устройства (mapping + вид преобразования),
    конвенции терминала (определение тормозного тока, коэффициенты возврата, допуски),
    сигналы (входы/выходы), поддержку IEC 61850 (GOOSE, Sampled Values, MMS), источник технических данных.
"""
from __future__ import annotations

from pathlib import Path

from ..errors import ProfileError

SCHEMA = "rza-terminal-profile/1"
STATUSES = {"verified": "верифицирован по руководству", "draft": "черновик (требует сверки с руководством)", "template": "шаблон (условные значения)",
            "not_loaded": "профиль не загружен"}
TRANSFORMS = {"identity", "slope_conv", "bp_conv", "i_rel_side", "i_rel_obj", "i_sec", "bool_onoff", "enum_map", "pct_from_pu", "pu_from_pct", "seconds_to_cycles", "ms_from_s", "kv_from_ratio"}
KINDS = {"float", "enum", "bool", "int", "time"}


class TerminalProfile:
    def __init__(self, data: dict, origin: str = "builtin", path: Path | None = None):
        self.data = data
        self.origin = origin
        self.path = path
        self._params = {p["key"]: p for p in data.get("parameters", [])}

    # ── свойства ──
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def status(self) -> str:
        return self.data.get("status", "draft")

    @property
    def label(self) -> str:
        d = self.data
        return " ".join(x for x in (d.get("manufacturer"), d.get("series"), d.get("model"), d.get("firmware")) if x)

    def param(self, key: str) -> dict | None:
        return self._params.get(key)

    def params(self) -> list[dict]:
        return self.data.get("parameters", [])

    def function(self, fid: str) -> dict | None:
        return self.data.get("functions", {}).get(fid)

    def supports(self, fid: str) -> bool:
        f = self.function(fid)
        return bool(f and f.get("supported"))

    def conv(self, *path, default=None):
        cur = self.data.get("conventions", {})
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def k_conv(self) -> float:
        return float(self.conv("restraint", "k_conv", default=1.0))

    def reset_ratios(self) -> tuple[float | None, dict]:
        rr = self.conv("reset_ratio", default={}) or {}
        by = {k: v for k, v in rr.items() if k not in ("default", "source") and isinstance(v, (int, float))}
        return rr.get("default"), by

    def tolerances(self) -> dict:
        t = self.conv("tolerances", default={}) or {}
        return {k: v for k, v in t.items() if isinstance(v, (int, float))}

    def mapping(self, pfm_id: str) -> dict | None:
        return self.data.get("mapping", {}).get(pfm_id)

    def mapped_key(self, pfm_id: str, instance: str) -> tuple[str | None, dict | None]:
        m = self.mapping(pfm_id)
        if not m:
            return None, None
        inst = m.get("instances", {})
        if instance in inst:
            return inst[instance], m
        if "" in inst and not instance:
            return inst[""], m
        # общий адрес для всех экземпляров
        if "*" in inst:
            return inst["*"], m
        return None, m

    def summary(self) -> dict:
        d = self.data
        funcs = d.get("functions", {})
        return {"id": self.id, "label": self.label, "manufacturer": d.get("manufacturer"), "series": d.get("series"), "model": d.get("model"),
                "firmware": d.get("firmware"), "variants": d.get("variants", []), "status": self.status, "status_label": STATUSES.get(self.status, self.status),
                "origin": self.origin, "adapter": d.get("adapter", "generic"),
                "functions": {k: bool(v.get("supported")) for k, v in funcs.items()}, "n_params": len(d.get("parameters", [])),
                "n_signals": len(d.get("signals", [])), "sources": d.get("sources", []), "iec61850": d.get("iec61850", {})}

    # ── проверка профиля ──
    def validate(self) -> list[dict]:
        d = self.data
        issues: list[dict] = []
        def add(level, code, msg, path=""):
            issues.append({"level": level, "code": code, "message": msg, "path": path})
        if d.get("schema") != SCHEMA:
            add("error", "schema", f"Неверная схема профиля (ожидается {SCHEMA})")
        for f in ("id", "manufacturer", "model"):
            if not d.get(f):
                add("error", "required", f"Не заполнено поле «{f}»", f)
        if not d.get("firmware"):
            add("warning", "firmware", "Не указана версия ПО — диапазоны зависят от версии", "firmware")
        keys = [p.get("key") for p in d.get("parameters", [])]
        if len(keys) != len(set(keys)):
            add("error", "dup_key", "Ключи параметров должны быть уникальны", "parameters")
        for p in d.get("parameters", []):
            k = p.get("key", "?")
            kind = p.get("kind", "float")
            if kind not in KINDS:
                add("error", "kind", f"Параметр {k}: неизвестный тип «{kind}»", f"parameters.{k}")
            if kind in ("float", "int", "time"):
                lo, hi, st = p.get("min"), p.get("max"), p.get("step")
                if lo is None or hi is None:
                    add("warning", "range", f"Параметр {k}: не заданы границы диапазона — уставка не может быть проверена", f"parameters.{k}")
                elif lo > hi:
                    add("error", "range", f"Параметр {k}: min > max", f"parameters.{k}")
                if not st or st <= 0:
                    add("warning", "step", f"Параметр {k}: не задан шаг — округление невозможно", f"parameters.{k}")
                df = p.get("default")
                specials = []
                for sp in p.get("special", []) or []:
                    try:
                        specials.append(float(sp))
                    except (TypeError, ValueError):
                        pass
                if isinstance(df, (int, float)) and df in specials:
                    pass
                elif isinstance(df, (int, float)) and lo is not None and hi is not None and not (lo - 1e-12 <= df <= hi + 1e-12):
                    add("warning", "default", f"Параметр {k}: значение по умолчанию вне диапазона", f"parameters.{k}")
            if kind == "enum" and not p.get("options"):
                add("error", "options", f"Параметр {k}: не заданы допустимые значения", f"parameters.{k}")
            if not p.get("source"):
                add("info", "source", f"Параметр {k}: не указан источник (документ, раздел, страница)", f"parameters.{k}")
        from ..pfm import PFM
        for pid, m in d.get("mapping", {}).items():
            if pid not in PFM:
                add("warning", "pfm", f"Связь с неизвестным параметром PFM «{pid}»", f"mapping.{pid}")
            if m.get("transform") not in TRANSFORMS:
                add("error", "transform", f"{pid}: неизвестное преобразование «{m.get('transform')}»", f"mapping.{pid}")
            for inst, key in (m.get("instances") or {}).items():
                if key not in self._params:
                    add("error", "mapping_key", f"{pid}[{inst}]: параметр устройства «{key}» отсутствует в профиле", f"mapping.{pid}")
        for fid, f in d.get("functions", {}).items():
            if f.get("supported") and f.get("mapped", True):
                mapped = [pid for pid in d.get("mapping", {}) if pid in PFM and PFM[pid].function == fid]
                if not mapped and fid in ("87T", "50/51", "46", "50N/51N", "21", "49"):
                    add("warning", "unmapped", f"Функция {fid} объявлена как поддерживаемая, но параметры PFM не сопоставлены с параметрами устройства", f"functions.{fid}")
        if not d.get("sources"):
            add("warning", "sources", "Не указан источник технических данных (руководство, версия, дата) — профиль не может считаться проверенным", "sources")
        if self.status == "verified" and not d.get("sources"):
            add("error", "verified", "Статус «верифицирован» недопустим без указания источника", "status")
        return issues

    def validate_or_raise(self):
        errs = [i for i in self.validate() if i["level"] == "error"]
        if errs:
            raise ProfileError("; ".join(e["message"] for e in errs))
