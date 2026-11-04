"""Tools the agent may call. Each tool has a typed argument model, a version and
an approval flag. The model only ever sees the JSON schema; arguments it produces
are validated before anything runs.

Calculations are deterministic and cite their source so results can be checked
by hand. Tools with side effects (`requires_approval=True`) are never executed by
the agent loop: the run stops and returns the proposed call for a human.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

# ISA constants, ICAO Doc 7488 / ISO 2533.
_G0 = 9.80665
_R_AIR = 287.05287
_GAMMA = 1.4
_T0, _P0 = 288.15, 101325.0
_LAPSE = -0.0065
_H_TROPOPAUSE, _T_TROPOPAUSE = 11000.0, 216.65
_P_TROPOPAUSE = _P0 * (_T_TROPOPAUSE / _T0) ** (-_G0 / (_LAPSE * _R_AIR))


class IsaArgs(BaseModel):
    altitude_m: float = Field(ge=-500, le=20000, description="Geopotential altitude in metres")


def isa_atmosphere(args: IsaArgs) -> dict[str, float]:
    """Temperature, pressure, density and speed of sound, 0-20 km ISA model."""
    h = args.altitude_m
    if h <= _H_TROPOPAUSE:
        t = _T0 + _LAPSE * h
        p = _P0 * (t / _T0) ** (-_G0 / (_LAPSE * _R_AIR))
    else:
        t = _T_TROPOPAUSE
        p = _P_TROPOPAUSE * math.exp(-_G0 * (h - _H_TROPOPAUSE) / (_R_AIR * t))
    return {
        "altitude_m": h,
        "temperature_k": round(t, 3),
        "pressure_pa": round(p, 1),
        "density_kg_m3": round(p / (_R_AIR * t), 5),
        "speed_of_sound_m_s": round(math.sqrt(_GAMMA * _R_AIR * t), 2),
    }


_TO_SI: dict[str, tuple[str, float]] = {
    "m": ("length", 1.0),
    "mm": ("length", 1e-3),
    "in": ("length", 0.0254),
    "ft": ("length", 0.3048),
    "pa": ("pressure", 1.0),
    "kpa": ("pressure", 1e3),
    "bar": ("pressure", 1e5),
    "psi": ("pressure", 6894.757293168),
    "n": ("force", 1.0),
    "kn": ("force", 1e3),
    "lbf": ("force", 4.4482216152605),
    "kg": ("mass", 1.0),
    "lb": ("mass", 0.45359237),
}
_TEMPERATURE = {"k", "c", "f"}
Unit = Literal[
    "m", "mm", "in", "ft", "pa", "kpa", "bar", "psi", "n", "kn", "lbf", "kg", "lb", "k", "c", "f"
]


class ConvertArgs(BaseModel):
    value: float
    from_unit: Unit
    to_unit: Unit


def _to_kelvin(value: float, unit: str) -> float:
    return {"k": value, "c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15}[unit]


def _from_kelvin(value: float, unit: str) -> float:
    return {"k": value, "c": value - 273.15, "f": (value - 273.15) * 9 / 5 + 32}[unit]


def convert_units(args: ConvertArgs) -> dict[str, Any]:
    src, dst = args.from_unit, args.to_unit
    if src in _TEMPERATURE or dst in _TEMPERATURE:
        if not (src in _TEMPERATURE and dst in _TEMPERATURE):
            raise ValueError(f"cannot convert {src} to {dst}")
        result = _from_kelvin(_to_kelvin(args.value, src), dst)
    else:
        (q_src, f_src), (q_dst, f_dst) = _TO_SI[src], _TO_SI[dst]
        if q_src != q_dst:
            raise ValueError(f"cannot convert {q_src} to {q_dst}")
        result = args.value * f_src / f_dst
    return {"value": args.value, "from_unit": src, "to_unit": dst, "result": round(result, 6)}


class Dimension(BaseModel):
    nominal: float
    tolerance: float = Field(ge=0, description="Symmetric tolerance, same unit as nominal")
    direction: Literal[1, -1] = 1


class StackupArgs(BaseModel):
    dimensions: list[Dimension] = Field(min_length=1, max_length=50)


def tolerance_stackup(args: StackupArgs) -> dict[str, float]:
    """1-D stack: worst case adds tolerances, RSS assumes independent normal variation."""
    nominal = sum(d.direction * d.nominal for d in args.dimensions)
    worst = sum(d.tolerance for d in args.dimensions)
    rss = math.sqrt(sum(d.tolerance**2 for d in args.dimensions))
    return {"nominal": round(nominal, 6), "worst_case": round(worst, 6), "rss": round(rss, 6)}


class SubmitJobArgs(BaseModel):
    case_name: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    solver: Literal["cfd", "fea"]
    mesh_cells: int = Field(gt=0, le=50_000_000)


def submit_simulation_job(args: SubmitJobArgs) -> dict[str, Any]:
    raise RuntimeError("side-effecting tool must go through human approval")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    fn: Callable[[Any], dict[str, Any]]
    version: str
    requires_approval: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args.model_json_schema(),
            },
        }


# Closed allowlist: the agent loop may only invoke names in this set.
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "isa_atmosphere",
        "convert_units",
        "tolerance_stackup",
        "submit_simulation_job",
    }
)

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "isa_atmosphere",
            "ISA standard atmosphere properties at an altitude (0-20 km).",
            IsaArgs,
            isa_atmosphere,
            "1.0",
        ),
        Tool(
            "convert_units",
            "Convert length, pressure, force, mass or temperature units.",
            ConvertArgs,
            convert_units,
            "1.0",
        ),
        Tool(
            "tolerance_stackup",
            "1-D tolerance stack-up, worst case and RSS.",
            StackupArgs,
            tolerance_stackup,
            "1.0",
        ),
        Tool(
            "submit_simulation_job",
            "Queue a CFD or FEA job on the cluster. Needs approval.",
            SubmitJobArgs,
            submit_simulation_job,
            "1.0",
            requires_approval=True,
        ),
    )
}

if set(TOOLS) != ALLOWED_TOOL_NAMES:
    raise RuntimeError(
        f"TOOLS registry drifted from allowlist: {sorted(set(TOOLS) ^ ALLOWED_TOOL_NAMES)}"
    )
