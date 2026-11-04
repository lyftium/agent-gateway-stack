from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_stack.agent.tools import (
    TOOLS,
    ConvertArgs,
    IsaArgs,
    StackupArgs,
    convert_units,
    isa_atmosphere,
    tolerance_stackup,
)


@pytest.mark.parametrize(
    ("altitude", "temperature", "pressure", "density"),
    [
        # Reference values from the ISA tables (ICAO Doc 7488).
        (0, 288.15, 101325.0, 1.2250),
        (5000, 255.65, 54019.9, 0.73612),
        (11000, 216.65, 22632.0, 0.36392),
        (15000, 216.65, 12044.6, 0.19367),
    ],
)
def test_isa_matches_reference_tables(altitude, temperature, pressure, density):
    out = isa_atmosphere(IsaArgs(altitude_m=altitude))
    assert out["temperature_k"] == pytest.approx(temperature, abs=0.01)
    assert out["pressure_pa"] == pytest.approx(pressure, rel=2e-4)
    assert out["density_kg_m3"] == pytest.approx(density, rel=5e-4)


def test_isa_sea_level_speed_of_sound():
    assert isa_atmosphere(IsaArgs(altitude_m=0))["speed_of_sound_m_s"] == pytest.approx(340.29)


def test_isa_rejects_out_of_range_altitude():
    with pytest.raises(ValidationError):
        IsaArgs(altitude_m=30000)


@pytest.mark.parametrize(
    ("value", "src", "dst", "expected"),
    [
        (1, "ft", "m", 0.3048),
        (14.7, "psi", "kpa", 101.3529),
        (100, "c", "f", 212),
        (0, "c", "k", 273.15),
        (1, "lbf", "n", 4.448222),
        (25.4, "mm", "in", 1),
    ],
)
def test_convert_units(value, src, dst, expected):
    out = convert_units(ConvertArgs(value=value, from_unit=src, to_unit=dst))
    assert out["result"] == pytest.approx(expected, rel=1e-5)


def test_convert_refuses_mismatched_quantities():
    with pytest.raises(ValueError, match="cannot convert"):
        convert_units(ConvertArgs(value=1, from_unit="m", to_unit="psi"))
    with pytest.raises(ValueError, match="cannot convert"):
        convert_units(ConvertArgs(value=1, from_unit="c", to_unit="m"))


def test_tolerance_stackup_worst_case_and_rss():
    args = StackupArgs(
        dimensions=[
            {"nominal": 25.0, "tolerance": 0.1},
            {"nominal": 10.0, "tolerance": 0.05},
            {"nominal": 5.0, "tolerance": 0.2, "direction": -1},
        ]
    )
    out = tolerance_stackup(args)
    assert out["nominal"] == pytest.approx(30.0)
    assert out["worst_case"] == pytest.approx(0.35)
    assert out["rss"] == pytest.approx((0.1**2 + 0.05**2 + 0.2**2) ** 0.5, rel=1e-6)


def test_every_tool_exposes_a_json_schema():
    for tool in TOOLS.values():
        schema = tool.schema()
        assert schema["function"]["name"] == tool.name
        assert schema["function"]["parameters"]["type"] == "object"
    assert [t.name for t in TOOLS.values() if t.requires_approval] == ["submit_simulation_job"]
