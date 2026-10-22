"""Tests of the granule search helpers of r.in.viirs (no network)."""

import datetime as dt
import importlib.machinery
import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("grass.script")

_path = Path(__file__).resolve().parents[1] / "r.in.viirs.py"
_loader = importlib.machinery.SourceFileLoader("r_in_viirs", str(_path))
_spec = importlib.util.spec_from_loader("r_in_viirs", _loader)
riv = importlib.util.module_from_spec(_spec)
_loader.exec_module(riv)

KEY = (
    "VIIRS-DNB-SDR/2026/08/30/SVDNB_j01_d20260830_t2126038_e2127266_b45507_"
    "c20260830220114523000_oebc_ops.h5"
)
# G-Ring of the NOAA-20 granule above, which covers Port Victoria.
RING_LON = [46.1, 60.0, 74.2, 73.0, 72.0, 59.0, 47.0, 46.5]
RING_LAT = [0.4, -0.9, -2.0, -5.0, -8.7, -7.4, -6.0, -3.0]
PORT_VICTORIA = (54.9, -5.2, 56.1, -4.0)


def test_parse_granule():
    g = riv.parse_granule(KEY)
    assert g["kind"] == "SVDNB"
    assert g["sat"] == "j01"
    assert g["start"] == dt.datetime(2026, 8, 30, 21, 26, 3)
    assert g["end"] == dt.datetime(2026, 8, 30, 21, 27, 26)
    geo = riv.parse_granule(KEY.replace("SVDNB", "GDNBO").replace("c2026083022", "c2026083023"))
    assert geo["id"] == g["id"]


def test_parse_granule_crossing_midnight():
    g = riv.parse_granule("SVDNB_npp_d20260830_t2359300_e0000542_b76905_c1_oebc_ops.h5")
    assert g["end"] - g["start"] == dt.timedelta(seconds=84)


def test_parse_granule_rejects_other_files():
    assert riv.parse_granule("VIIRS-DNB-SDR/2026/08/30/README.txt") is None


def test_point_in_ring_across_dateline():
    lon = [170.0, -170.0, -170.0, 170.0]
    lat = [10.0, 10.0, -10.0, -10.0]
    assert riv.point_in_ring(179.5, 0.0, lon, lat)
    assert riv.point_in_ring(-179.5, 0.0, lon, lat)
    assert not riv.point_in_ring(160.0, 0.0, lon, lat)


def test_ring_covers_region_inside():
    assert riv.ring_covers(PORT_VICTORIA, RING_LON, RING_LAT)


def test_ring_covers_partial_overlap():
    # Only an edge of the ring crosses the box: no corner on either side
    # lies inside the other polygon.
    lon = [55.0, 55.4, 55.4, 55.0]
    lat = [-3.0, -3.0, -6.0, -6.0]
    assert riv.ring_covers(PORT_VICTORIA, lon, lat)


def test_ring_misses_region():
    lon = [20.0, 48.0, 48.0, 20.0]
    lat = [-2.7, -2.7, -11.9, -11.9]
    assert not riv.ring_covers(PORT_VICTORIA, lon, lat)


def test_nominal_time_is_local_solar():
    # 01:30 local solar time at 55.5 E is 21:48 UTC the evening before.
    t = riv.nominal_time(dt.date(2026, 8, 31), 55.5, "night")
    assert t == dt.datetime(2026, 8, 30, 21, 48)
    t = riv.nominal_time(dt.date(2026, 8, 31), 0.0, "day")
    assert t == dt.datetime(2026, 8, 31, 13, 30)


def test_crop_window_with_margin():
    lat, lon = np.meshgrid(np.linspace(-10, 0, 101), np.linspace(50, 60, 101), indexing="ij")
    r0, r1, c0, c1 = riv.crop_window(lat, lon, PORT_VICTORIA, margin_px=2)
    assert lat[r0 + 2, 0] >= -5.2 and lat[r1 - 3, 0] <= -4.0
    assert lon[0, c0 + 2] >= 54.9 and lon[0, c1 - 3] <= 56.1


def test_crop_window_outside_and_fill():
    lat = np.full((4, 4), -999.3)
    lon = np.full((4, 4), -999.3)
    assert riv.crop_window(lat, lon, PORT_VICTORIA) is None


def test_grass_date_is_english():
    assert riv.grass_date(dt.datetime(2026, 8, 30, 21, 26, 45)) == "30 Aug 2026 21:26:45"
