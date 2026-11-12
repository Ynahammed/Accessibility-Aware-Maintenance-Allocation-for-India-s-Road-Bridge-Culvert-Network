"""The live assumptions register: defaults plus validated PWD/RTI overrides.

``scripts/ingest_pwd_reply.py`` writes
``data/processed/pwd_reply/register_overrides.json``. This module is the **only** place
the application reads it, so a reply changes the register that the simulator, the
optimizer and the planner actually use — not just a badge in the dashboard.

Rules (mirroring the loader, and deliberately conservative):

* no file, unreadable JSON, or an entry without provenance -> the default stays;
* an override is applied only when the name is a known parameter, the value is a finite
  number and the source tag is ``real`` | ``fitted`` | ``assumed``;
* a measured value outside the registered sweep range **widens** the range instead of
  being clipped, and its provenance is carried on the parameter;
* every rejection is collected in ``warnings`` so an ignored reply is visible rather than
  silently discarded.

The file is re-read when its modification time or size changes, so re-running the loader
takes effect without restarting the server, while an unchanged file costs one ``stat``.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from rra.assumptions import AssumptionRegister
from rra.cost.sor import DEFAULT_BASE_COST_CRORE, DEFAULT_LABOUR_DAYS, ScheduleOfRates

ROOT = Path(__file__).resolve().parents[3]
OVERRIDES_RELPATH = Path("data") / "processed" / "pwd_reply" / "register_overrides.json"
DEFAULT_SOR_SOURCE = "assumed (placeholder until PWD SoR entered)"
_SOURCE_TAGS = frozenset({"real", "fitted", "assumed"})


@dataclass(frozen=True)
class LiveRegister:
    """The register a request should use, plus where its values came from."""

    register: AssumptionRegister
    sor: ScheduleOfRates
    applied: dict = field(default_factory=dict)  # parameter -> provenance record
    rates: dict = field(default_factory=dict)  # structure type -> provenance record
    labour: dict = field(default_factory=dict)  # structure type -> provenance record
    manifest: dict = field(default_factory=dict)
    source_path: str | None = None
    fingerprint: str = "default"
    warnings: tuple = ()
    #: overrides the loader refused, in display form (parameter, reason, detail)
    refused: tuple = ()
    #: loader coverage findings that are not an override attempt (unmapped types, ...)
    coverage_warnings: tuple = ()

    @property
    def measured(self) -> bool:
        """True when at least one quantity came from a reply."""
        return bool(self.applied or self.rates or self.labour)

    def markdown(self) -> str:
        """The register rendered for display, naming the reply when values are measured.

        Rendering from the live register (rather than serving the generated
        ``docs/assumptions.md``) keeps one source of truth: the markdown cannot disagree
        with the values the planner and simulator are using. Refused overrides are named
        here too, so a partly refused reply is never presented as a clean one.
        """
        parts: list[str] = []
        if self.measured:
            ref = self.manifest.get("application_ref") or "an unidentified PWD/RTI reply"
            parts = [f"**Live register — measured values applied.** Source: PWD/RTI application {ref}"]
            if self.manifest.get("office"):
                parts.append(f"({self.manifest['office']})")
            if self.manifest.get("reply_date"):
                parts.append(f"reply dated {self.manifest['reply_date']}")
            applied = f"{len(self.applied)} parameter(s)"
            if self.rates:
                applied += f" and {len(self.rates)} structure type(s) priced"
            parts.append(
                f"replaced {applied}. `fitted` values are computed from the reply's rows by "
                "`scripts/ingest_pwd_reply.py`; every other row remains an assumption."
            )
        if self.refused:
            parts.append(
                f"**{len(self.refused)} override(s) were refused rather than applied** "
                "(implausible magnitude, sample too small or contradicted by the reply); "
                "the affected rows below keep their assumed value."
            )
        return self.register.to_markdown(
            note=" ".join(parts) or None, measured=self.measured
        )

    def describe(self) -> dict:
        """JSON-safe provenance block for API payloads."""
        return {
            "source": "pwd_rti" if self.measured else "default",
            "path": self.source_path,
            "office": self.manifest.get("office"),
            "application_ref": self.manifest.get("application_ref"),
            "reply_date": self.manifest.get("reply_date"),
            "generated_utc": self.manifest.get("generated_utc"),
            "parameters": sorted(self.applied),
            "structure_types": sorted(self.rates),
            "fingerprint": self.fingerprint,
            "warnings": list(self.warnings),
            "refused": len(self.refused),
            "coverage_warnings": len(self.coverage_warnings),
        }


def overrides_path(root: str | Path | None = None) -> Path:
    return (Path(root) if root is not None else ROOT) / OVERRIDES_RELPATH


def _finite(value) -> float | None:
    """A finite float, or None. ``bool`` is not a measurement."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fingerprint(applied: dict, rates: dict, labour: dict, manifest: dict) -> str:
    if not (applied or rates or labour):
        return "default"
    blob = json.dumps(
        {
            "params": {k: v["value"] for k, v in applied.items()},
            "rates": {k: v["value"] for k, v in rates.items()},
            "labour": {k: v["value"] for k, v in labour.items()},
            "ref": manifest.get("application_ref"),
            "reply_date": manifest.get("reply_date"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


_REASON_LABEL = {
    "implausible_magnitude": "implausible magnitude",
    "fewer_than_min_n": "sample too small",
    "insufficient_or_contradictory": "contradicted by the reply",
    "no_matching_sor_items": "no matching SoR items",
    "no_intervention_with_enough_rows": "no priced intervention",
    "no_base_cost_intervention": "no base cost priced",
}


def _refusal_label(parameter: str) -> str:
    """``base_cost::major_bridge`` -> ``base cost, major bridge``."""
    kind, _, stype = parameter.partition("::")
    if not stype:
        return parameter
    name = {"base_cost": "base cost", "labour_days": "crew days"}.get(
        kind, kind.replace("_", " ")
    )
    return f"{name}, {stype.replace('_', ' ')}"


def _num(value) -> str | None:
    number = _finite(value)
    if number is None:
        return None
    return f"{number:g}"


def _refusal_detail(entry: dict, parameter: str = "") -> str:
    """One readable line explaining why an override was not applied."""
    reason = str(entry.get("reason") or "")
    parts: list[str] = []
    if reason == "implausible_magnitude":
        rate = _num(entry.get("median_rate_crore"))
        base = _num(entry.get("base_cost_crore"))
        ratio = _num(entry.get("ratio_to_placeholder"))
        placeholder = _num(entry.get("placeholder_crore"))
        if base and ratio and placeholder:
            parts.append(
                f"median rate {rate} cr gives a base cost of {base} cr, {ratio}× the "
                f"{placeholder} cr placeholder"
            )
    elif reason == "fewer_than_min_n":
        n, required = _num(entry.get("n")), _num(entry.get("required"))
        if n is not None:
            parts.append(f"n={n}" + (f" of {required} required" if required else ""))
    elif reason == "insufficient_or_contradictory":
        n, required = _num(entry.get("n")), _num(entry.get("required"))
        if n is not None:
            parts.append(f"n={n}" + (f" of {required} required" if required else ""))
        if entry.get("contradictions"):
            parts.append(f"{entry['contradictions']} contradiction(s)")
        if entry.get("unadjudicated"):
            parts.append(f"{entry['unadjudicated']} unadjudicated worse reading(s)")
    hint = entry.get("hint")
    if hint:
        parts.append(str(hint))
    known = {"parameter", "reason", "hint", "required", "n", "contradictions",
             "unadjudicated", "median_rate_crore", "base_cost_crore",
             "ratio_to_placeholder", "placeholder_crore"}
    parts += [f"{k}={v}" for k, v in entry.items() if k not in known and v is not None]
    if not parts and parameter.startswith("labour_days::"):
        # the loader skips crew days with the same reason as the refused rate, without
        # repeating its numbers; say what that means for this row
        return "no crew days derived: the rate for this type was not applied"
    return " · ".join(parts) or reason.replace("_", " ")


def refused_overrides(payload: dict) -> tuple[dict, ...]:
    """The loader's refusals, formatted for display (never silently dropped)."""
    skipped = payload.get("skipped") if isinstance(payload, dict) else None
    if not isinstance(skipped, list):
        return ()
    out = []
    for entry in skipped:
        if not isinstance(entry, dict) or not entry.get("parameter"):
            continue
        parameter = str(entry["parameter"])
        reason = str(entry.get("reason") or "unstated")
        out.append(
            {
                "parameter": parameter,
                "label": _refusal_label(parameter),
                "reason": reason,
                "reason_label": _REASON_LABEL.get(reason, reason.replace("_", " ")),
                "detail": _refusal_detail(entry, parameter),
            }
        )
    return tuple(out)


def coverage_warnings(payload: dict, refused: tuple = ()) -> tuple[str, ...]:
    """Coverage findings a reader must see: rows excluded, types unmapped, rates rejected.

    A rejected base-cost rate is already among ``refused``; it is not repeated here.
    """
    coverage = payload.get("coverage") if isinstance(payload, dict) else None
    if not isinstance(coverage, dict):
        return ()
    refused = {r["parameter"] for r in refused}
    out: list[str] = []

    structures = coverage.get("structures") or {}
    unmapped = structures.get("unmapped_types") or []
    if unmapped:
        out.append(
            f"{len(unmapped)} structure type(s) excluded as unmapped: " + ", ".join(unmapped)
        )

    inspections = coverage.get("inspections") or {}
    refused_rows = inspections.get("refused_unstated_scale_or_unparseable") or 0
    if refused_rows:
        out.append(
            f"{refused_rows} inspection row(s) refused (unstated rating scale or "
            "unparseable date)"
        )

    closures = coverage.get("closures") or {}
    for key, text in (
        ("unparseable_closed_date", "closure row(s) with an unparseable date dropped"),
        ("negative_duration", "closure row(s) with a negative duration dropped"),
        ("still_closed", "closure(s) still open at the reply date kept for coverage but "
                         "excluded from the outage median"),
    ):
        count = closures.get(key) or 0
        if count:
            out.append(f"{count} {text}")

    expenditure = coverage.get("expenditure") or {}
    work_types = expenditure.get("unmapped_work_types") or []
    if work_types:
        out.append(
            f"{len(work_types)} work type(s) excluded as unmapped: " + ", ".join(work_types)
        )

    for entry in ((coverage.get("schedule_of_rates") or {}).get("rejected_implausible") or []):
        stype = str(entry.get("structure_type") or "?")
        if f"base_cost::{stype}" in refused:
            continue  # already shown as a refused override
        ratio, placeholder = _num(entry.get("ratio_to_placeholder")), _num(
            entry.get("placeholder_crore")
        )
        work = str(entry.get("intervention") or "rate")
        detail = f" ({ratio}× the {placeholder} cr placeholder)" if ratio and placeholder else ""
        out.append(f"{stype} {work} rate refused as implausible{detail}")

    pairs = coverage.get("repair_pairs") or {}
    if pairs.get("worsened"):
        out.append(
            f"{pairs['worsened']} repair pair(s) contradict the repair (worse than the "
            "no-repair counterfactual)"
        )
    if pairs.get("unadjudicated"):
        out.append(
            f"{pairs['unadjudicated']} post-repair reading(s) worse with no pre-work "
            "history to judge them against"
        )
    return tuple(out)


def _sor_source(manifest: dict, measured: bool) -> str:
    if not measured:
        return DEFAULT_SOR_SOURCE
    ref = manifest.get("application_ref") or "PWD/RTI reply"
    office = manifest.get("office")
    return f"PWD/RTI {ref}" + (f", {office}" if office else "")


def apply_payload(
    payload: dict,
    base: AssumptionRegister | None = None,
    path: str | Path | None = None,
) -> LiveRegister:
    """Apply one loader payload to a register. Pure: no I/O, no global state.

    Anything that cannot be trusted keeps the assumption and appends a warning.
    """
    base = base or AssumptionRegister.default()
    warnings: list[str] = []

    manifest: dict = {}
    raw_manifest = payload.get("manifest") if isinstance(payload, dict) else None
    if isinstance(raw_manifest, dict):
        manifest.update(raw_manifest)
    if payload.get("generated_utc"):
        manifest["generated_utc"] = payload["generated_utc"]

    params = dict(base.parameters)
    applied: dict[str, dict] = {}
    payload_register = payload.get("register") if isinstance(payload, dict) else None
    if payload_register is not None and not isinstance(payload_register, dict):
        warnings.append("'register' is not an object; all assumptions kept")

    for name, entry in (payload_register or {}).items():
        if not isinstance(entry, dict):
            warnings.append(f"{name}: entry is not an object; assumption kept")
            continue
        if name not in params:
            warnings.append(f"{name}: unknown register parameter; ignored")
            continue
        value = _finite(entry.get("value"))
        if value is None:
            warnings.append(f"{name}: value is not a finite number; assumption kept")
            continue
        source = str(entry.get("source") or "fitted")
        if source not in _SOURCE_TAGS:
            warnings.append(f"{name}: source {source!r} is not one of {sorted(_SOURCE_TAGS)}; assumption kept")
            continue
        prov = entry.get("provenance")
        prov = dict(prov) if isinstance(prov, dict) else {}
        ref = str(prov.get("application_ref") or manifest.get("application_ref") or "").strip()
        if not ref:
            warnings.append(f"{name}: no provenance (application_ref); assumption kept")
            continue

        current = params[name]
        low, high = min(current.low, value), max(current.high, value)
        prov = {
            "office": manifest.get("office"),
            "application_ref": ref,
            "reply_date": manifest.get("reply_date"),
            **prov,
        }
        prov["application_ref"] = prov.get("application_ref") or ref
        params[name] = replace(
            current,
            default=value,
            low=float(low),
            high=float(high),
            source=source,
            how=f"measured — {prov.get('statistic') or 'stated'} "
            f"n={prov.get('n', '?')}, RTI {ref}",
        )
        applied[name] = {
            "value": value,
            "source": source,
            "provenance": prov,
            "previous": entry.get("previous") or {"default": current.default, "source": current.source},
        }

    rates: dict[str, dict] = {}
    base_costs = dict(DEFAULT_BASE_COST_CRORE)
    for stype, entry in (payload.get("schedule_of_rates") or {}).items():
        if stype not in base_costs:
            warnings.append(f"schedule_of_rates: unknown structure type {stype!r}; ignored")
            continue
        value = _finite(entry.get("value")) if isinstance(entry, dict) else None
        if value is None or value <= 0:
            warnings.append(f"schedule_of_rates: {stype} has no positive cost; placeholder kept")
            continue
        base_costs[stype] = value
        rates[stype] = {
            "value": value,
            "source": entry.get("source", "fitted"),
            "provenance": entry.get("provenance", {}),
        }

    labour: dict[str, dict] = {}
    labour_days = dict(DEFAULT_LABOUR_DAYS)
    for stype, entry in (payload.get("labour_days") or {}).items():
        if stype not in labour_days:
            warnings.append(f"labour_days: unknown structure type {stype!r}; ignored")
            continue
        value = _finite(entry.get("value")) if isinstance(entry, dict) else None
        if value is None or value <= 0:
            warnings.append(f"labour_days: {stype} has no positive crew-days; placeholder kept")
            continue
        labour_days[stype] = value
        labour[stype] = {
            "value": value,
            "source": entry.get("source", "fitted"),
            "provenance": entry.get("provenance", {}),
        }

    measured = bool(applied or rates or labour)
    sor = ScheduleOfRates(
        base_cost_crore=base_costs,
        labour_days=labour_days,
        source=_sor_source(manifest, measured),
    )
    refused = refused_overrides(payload)
    return LiveRegister(
        register=AssumptionRegister(params),
        sor=sor,
        applied=applied,
        rates=rates,
        labour=labour,
        manifest=manifest,
        source_path=str(path) if path is not None else None,
        fingerprint=_fingerprint(applied, rates, labour, manifest),
        warnings=tuple(warnings),
        refused=refused,
        coverage_warnings=coverage_warnings(payload, refused),
    )


# --- cached file access --------------------------------------------------------------

_LABEL = str(OVERRIDES_RELPATH)
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple[int, int], LiveRegister]] = {}


def live_register(root: str | Path | None = None) -> LiveRegister:
    """Defaults plus whatever a validated reply file currently says.

    Re-read when the file's ``(mtime_ns, size)`` changes; a missing or invalid file always
    yields the default register, so planning never fails because of the loader.
    """
    path = overrides_path(root)
    key = str(path)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        with _LOCK:
            _CACHE.pop(key, None)
        return apply_payload({}, path=None)

    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            live = replace(
                apply_payload({}, path=path),
                warnings=(f"could not read {_LABEL} ({exc}); defaults kept",),
            )
        else:
            if not isinstance(payload, dict):
                live = replace(
                    apply_payload({}, path=path),
                    warnings=(f"{_LABEL} is not a JSON object; defaults kept",),
                )
            else:
                live = apply_payload(payload, path=path)

        _CACHE[key] = (stamp, live)
        return live


def assumptions_payload() -> dict:
    """The discovery payload for the assumptions register, shared by both transports.

    FastAPI and the stdlib demo server return exactly this object, so the two cannot drift
    on the register or on the provenance it reports.
    """
    live = live_register()
    return {
        "ok": True,
        "parameters": live.register.as_dict(),
        "source": live.describe(),
        "refused": list(live.refused),
        "coverage_warnings": list(live.coverage_warnings),
        "register_markdown": live.markdown(),
    }


def cache_clear() -> None:
    """Drop the cached file read (tests and long-lived processes)."""
    with _LOCK:
        _CACHE.clear()
