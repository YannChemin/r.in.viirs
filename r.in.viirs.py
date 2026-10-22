#!/usr/bin/env python3
############################################################################
#
# MODULE:       r.in.viirs
# AUTHOR(S):    Yann Chemin
# PURPOSE:      Queries, downloads and imports VIIRS Day/Night Band (DNB)
#               granules from the NOAA Open Data Dissemination buckets on
#               AWS, cropped and gridded to the current region.
#
# SPDX-License-Identifier: Unlicense
#
############################################################################

# %Module
# % description: Queries, downloads and imports VIIRS Day/Night Band radiance (Suomi-NPP, NOAA-20, NOAA-21) from the NOAA Open Data Dissemination buckets on AWS, cropped to the current region.
# % keyword: raster
# % keyword: import
# % keyword: imagery
# % keyword: satellite
# % keyword: VIIRS
# % keyword: night lights
# % keyword: download
# %end

# %option
# % key: satellite
# % type: string
# % required: no
# % multiple: yes
# % options: npp,j01,j02
# % answer: npp,j01
# % description: Satellites to query: npp (Suomi-NPP), j01 (NOAA-20), j02 (NOAA-21)
# % guisection: Filter
# %end

# %option
# % key: start
# % type: string
# % required: yes
# % multiple: no
# % description: Start date (YYYY-MM-DD, UTC)
# % guisection: Filter
# %end

# %option
# % key: end
# % type: string
# % required: yes
# % multiple: no
# % description: End date (YYYY-MM-DD, UTC, inclusive)
# % guisection: Filter
# %end

# %option
# % key: pass
# % type: string
# % required: no
# % multiple: no
# % options: night,day,both
# % answer: night
# % description: Overpass to import: night (descending, about 01:30 local), day (ascending, about 13:30 local) or both
# % guisection: Filter
# %end

# %option
# % key: layers
# % type: string
# % required: no
# % multiple: yes
# % options: dnb,qf,lunar_zenith,satellite_zenith,solar_zenith
# % answer: dnb
# % description: Layers to import: dnb (radiance, nW cm-2 sr-1), qf (DNB SDR quality flags), lunar_zenith, satellite_zenith, solar_zenith (degrees)
# % guisection: Config
# %end

# %option
# % key: resolution
# % type: double
# % required: no
# % multiple: no
# % answer: 750
# % description: Output resolution in metres (the DNB pixel is about 742 m on a side)
# % guisection: Config
# %end

# %option
# % key: method
# % type: string
# % required: no
# % multiple: no
# % options: nearest,average,max
# % answer: nearest
# % description: Swath-to-grid resampling (max keeps sub-pixel light spikes)
# % guisection: Config
# %end

# %option
# % key: output
# % type: string
# % required: no
# % multiple: no
# % answer: viirs
# % description: Prefix for output raster map names
# % guisection: Output
# %end

# %option
# % key: strds
# % type: string
# % required: no
# % multiple: no
# % answer: viirs
# % description: Prefix for Space-Time Raster Dataset names (one STRDS per layer, created or extended)
# % guisection: Output
# %end

# %option
# % key: bucket
# % type: string
# % required: no
# % multiple: no
# % answer: https://noaa-nesdis-{sat}-pds.s3.amazonaws.com
# % description: Bucket URL template; {sat} becomes snpp, n20 or n21
# % guisection: Config
# %end

# %flag
# % key: l
# % description: List the granules covering the region and exit without importing
# %end

# %flag
# % key: p
# % description: Print the region bounds used for the query and exit
# %end

# %flag
# % key: t
# % description: Do not register the imported maps in Space-Time Raster Datasets
# %end

# %rules
# % exclusive: -l, -p
# %end

import datetime as dt
import os
import re
import sys
import xml.etree.ElementTree as ET

import grass.script as gs

SAT_BUCKET = {"npp": "snpp", "j01": "n20", "j02": "n21"}
SAT_NAME = {"npp": "Suomi-NPP", "j01": "NOAA-20", "j02": "NOAA-21"}
SDR = "VIIRS-DNB-SDR"
GEO = "VIIRS-DNB-GEO"
# JPSS granule file names: SVDNB_npp_d20260831_t0001063_e0002305_b76905_...
GRAN_RE = re.compile(
    r"(?P<kind>SVDNB|GDNBO)_(?P<sat>\w+?)_d(?P<d>\d{8})_t(?P<t>\d{7})_e(?P<e>\d{7})_b(?P<b>\d+)_"
)
GRANULE_S = 85.35  # Nominal duration of one 48-scan JPSS granule.
ORBIT_S = 101.44 * 60  # Nominal orbital period of the JPSS satellites.
# Local solar time of the subsatellite point at the equator crossing.
NODE_HOURS = {"night": 1.5, "day": 13.5}
# Half-width of the overpass window around the nominal time: the swath
# reaches about 1500 km to each side, about 1 h of local time at the equator.
WINDOW_S = 75 * 60
MAX_PROBES = 10
BIG_BLOCK = 4 * 1024 * 1024
LAYER_SRC = {
    "dnb": (SDR, "All_Data/VIIRS-DNB-SDR_All/Radiance"),
    "qf": (SDR, "All_Data/VIIRS-DNB-SDR_All/QF1_VIIRSDNBSDR"),
    "lunar_zenith": (GEO, "All_Data/VIIRS-DNB-GEO_All/LunarZenithAngle"),
    "satellite_zenith": (GEO, "All_Data/VIIRS-DNB-GEO_All/SatelliteZenithAngle"),
    "solar_zenith": (GEO, "All_Data/VIIRS-DNB-GEO_All/SolarZenithAngle"),
}
LAYER_UNITS = {
    "dnb": "nW cm-2 sr-1",
    "lunar_zenith": "degrees",
    "satellite_zenith": "degrees",
    "solar_zenith": "degrees",
}
GEO_ALL = "All_Data/VIIRS-DNB-GEO_All"


def parse_granule(key):
    """Parse a JPSS granule object key into a dict, or None."""
    m = GRAN_RE.search(key)
    if not m:
        return None
    day = m.group("d")
    start = dt.datetime.strptime(day + m.group("t")[:6], "%Y%m%d%H%M%S")
    end = dt.datetime.strptime(day + m.group("e")[:6], "%Y%m%d%H%M%S")
    if end < start:
        end += dt.timedelta(days=1)
    return {
        "key": key,
        "kind": m.group("kind"),
        "sat": m.group("sat"),
        "start": start,
        "end": end,
        # Granules of the same acquisition share date, start, end and orbit
        # in SDR and GEO files; their creation stamps differ.
        "id": (m.group("d"), m.group("t"), m.group("e"), m.group("b")),
    }


def list_day(bucket, product, day):
    """List the granules of one product and UTC day in a NODD bucket."""
    import urllib.parse
    import urllib.request

    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    prefix = f"{product}/{day:%Y/%m/%d}/"
    out, token = [], None
    while True:
        url = f"{bucket}/?list-type=2&prefix={prefix}"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token)
        with urllib.request.urlopen(url, timeout=120) as r:
            root = ET.fromstring(r.read())
        for c in root.iter(ns + "Contents"):
            key = c.find(ns + "Key").text
            if key.endswith(".h5"):
                g = parse_granule(key)
                if g:
                    out.append(g)
        nxt = root.find(ns + "NextContinuationToken")
        if nxt is None:
            break
        token = nxt.text
    return out


def unwrap(lons, ref):
    """Shift longitudes by 360 so they lie within 180 degrees of ref."""
    return [x - 360.0 * round((x - ref) / 360.0) for x in lons]


def point_in_ring(lon, lat, ring_lon, ring_lat):
    """Ray-casting test of a point against a granule G-Ring polygon."""
    xs = unwrap(ring_lon, lon)
    inside = False
    n = len(xs)
    for i in range(n):
        x1, y1, x2, y2 = xs[i], ring_lat[i], xs[(i + 1) % n], ring_lat[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            if lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _segments_cross(p1, p2, q1, q2):
    """True when segments p1-p2 and q1-q2 intersect."""

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def ring_covers(bounds, ring_lon, ring_lat):
    """True when the G-Ring polygon intersects the region box."""
    w, s, e, n = bounds
    corners = [(w, s), (e, s), (e, n), (w, n)]
    if any(point_in_ring(x, y, ring_lon, ring_lat) for x, y in corners):
        return True
    ring = list(zip(unwrap(ring_lon, (w + e) / 2.0), ring_lat))
    if any(w <= x <= e and s <= y <= n for x, y in ring):
        return True
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        for j in range(4):
            if _segments_cross(a, b, corners[j], corners[(j + 1) % 4]):
                return True
    return False


def nominal_time(day, lon, which):
    """Nominal UTC time of the night or day overpass at a longitude."""
    hours = NODE_HOURS[which] - lon / 15.0
    return dt.datetime.combine(day, dt.time()) + dt.timedelta(hours=hours)


class Remote:
    """Partial HTTP reads of HDF5 granules (only the needed blocks)."""

    def __init__(self):
        import fsspec

        self.fs = fsspec.filesystem("https")
        self.bytes = 0

    def open(self, url, block_size=64 * 1024):
        """Open a remote HDF5 file.

        Small blocks suit the metadata reads of the granule search; whole
        datasets are read with large blocks, in a few requests.
        """
        import h5py

        f = self.fs.open(url, block_size=block_size, cache_type="blockcache")
        return f, h5py.File(f, "r")

    def ring(self, url, product):
        """G-Ring polygon, day/night flag and times of a granule."""
        f, h = self.open(url)
        try:
            a = h[f"Data_Products/{product}/{product}_Gran_0"].attrs
            return {
                "lon": [float(x) for x in a["G-Ring_Longitude"].ravel()],
                "lat": [float(x) for x in a["G-Ring_Latitude"].ravel()],
                "daynight": a["N_Day_Night_Flag"].ravel()[0].decode(),
            }
        finally:
            h.close()
            f.close()


def find_overpasses(remote, bucket, sat, day, bounds, which, listing):
    """Granules of one satellite covering the region on one overpass.

    The overpass time is predicted from the local solar time of the
    sun-synchronous orbit, then refined on the granule G-Rings: along the
    pass the latitude changes by about one granule height per granule, and
    the next orbit is 101 min later and about 25 degrees further west.
    """
    w, s, e, n = bounds
    lon_c, lat_c = (w + e) / 2.0, (s + n) / 2.0
    t0 = nominal_time(day, lon_c, which)
    cands = sorted(
        (
            g
            for g in listing
            if abs((g["start"] - t0).total_seconds()) <= WINDOW_S + ORBIT_S
        ),
        key=lambda g: g["start"],
    )
    if not cands:
        return []
    url = lambda g: f"{bucket}/{g['key']}"  # noqa: E731
    seen = {}

    def probe(i):
        if i < 0 or i >= len(cands):
            return None
        if i not in seen:
            seen[i] = remote.ring(url(cands[i]), SDR)
        return seen[i]

    idx = min(
        range(len(cands)), key=lambda i: abs((cands[i]["start"] - t0).total_seconds())
    )
    hits = []
    for _ in range(MAX_PROBES):
        r = probe(idx)
        if r is None:
            break
        if ring_covers(bounds, r["lon"], r["lat"]):
            hits.append(idx)
            break
        rlat = sum(r["lat"]) / len(r["lat"])
        rlon = sum(unwrap(r["lon"], lon_c)) / len(r["lon"])
        height = max(r["lat"]) - min(r["lat"])
        ascending = which == "day"
        # Granules to move along the pass to reach the region latitude.
        step = round((lat_c - rlat) / max(height, 1.0))
        if step == 0 and not min(r["lat"]) <= lat_c <= max(r["lat"]):
            # The region lies just beyond the granule edge: one granule on.
            step = 1 if lat_c > rlat else -1
        if not ascending:
            step = -step
        if step == 0:
            # Scan lines are slanted, so a region near the granule edge can
            # sit in the previous or next granule at the same latitude.
            near = [
                j
                for j in (idx - 1, idx + 1)
                if probe(j) and ring_covers(bounds, seen[j]["lon"], seen[j]["lat"])
            ]
            if near:
                hits.append(near[0])
                break
            # Right latitude, wrong longitude: jump one orbit. A region to
            # the west of the swath is seen on the next orbit.
            orbit_steps = round(ORBIT_S / GRANULE_S)
            step = orbit_steps if lon_c < rlon else -orbit_steps
        # Snap to the candidate whose start time is closest to the jump.
        target = cands[idx]["start"] + dt.timedelta(seconds=step * GRANULE_S)
        new = min(
            range(len(cands)),
            key=lambda i: abs((cands[i]["start"] - target).total_seconds()),
        )
        if new == idx:
            break
        idx = new
    if not hits:
        return []
    # Neighbours of the same pass can also overlap the region.
    for j in (hits[0] - 1, hits[0] + 1):
        r = probe(j)
        if (
            r
            and abs((cands[j]["start"] - cands[hits[0]]["start"]).total_seconds())
            < 2 * GRANULE_S
        ):
            if ring_covers(bounds, r["lon"], r["lat"]):
                hits.append(j)
    out = []
    for i in sorted(hits):
        g = dict(cands[i])
        g["daynight"] = seen[i]["daynight"]
        out.append(g)
    return out


def region_bounds():
    """Lon/lat bounds (w, s, e, n) of the current region."""
    reg = gs.parse_command("g.region", flags="bg", format="shell")
    if "ll_w" in reg:
        return (
            float(reg["ll_w"]),
            float(reg["ll_s"]),
            float(reg["ll_e"]),
            float(reg["ll_n"]),
        )
    reg = gs.region()
    return (float(reg["w"]), float(reg["s"]), float(reg["e"]), float(reg["n"]))


def crop_window(lat, lon, bounds, margin_px=4):
    """Row/column window of the swath that falls inside the bounds."""
    import numpy as np

    w, s, e, n = bounds
    lon_u = lon - 360.0 * np.round((lon - (w + e) / 2.0) / 360.0)
    inside = (lat >= s) & (lat <= n) & (lon_u >= w) & (lon_u <= e) & (lat > -90.5)
    rows, cols = np.nonzero(inside)
    if rows.size == 0:
        return None
    r0 = max(rows.min() - margin_px, 0)
    r1 = min(rows.max() + margin_px + 1, lat.shape[0])
    c0 = max(cols.min() - margin_px, 0)
    c1 = min(cols.max() + margin_px + 1, lat.shape[1])
    return r0, r1, c0, c1


def read_granule(remote, bucket, sdr, geo, layers, bounds):
    """Read the cropped swath arrays of one granule."""
    import numpy as np

    out = {}
    f, h = remote.open(f"{bucket}/{geo['key']}", BIG_BLOCK)
    try:
        lat = h[f"{GEO_ALL}/Latitude"][...]
        lon = h[f"{GEO_ALL}/Longitude"][...]
        win = crop_window(lat, lon, bounds)
        if win is None:
            return None
        r0, r1, c0, c1 = win
        out["lat"] = lat[r0:r1, c0:c1]
        out["lon"] = lon[r0:r1, c0:c1]
        # MoonIllumFraction is the illuminated part of the lunar disc in percent.
        out["moon_percent"] = float(h[f"{GEO_ALL}/MoonIllumFraction"][0])
        for name in layers:
            prod, path = LAYER_SRC[name]
            if prod == GEO:
                out[name] = h[path][r0:r1, c0:c1]
    finally:
        h.close()
        f.close()
    if any(LAYER_SRC[n][0] == SDR for n in layers):
        f, h = remote.open(f"{bucket}/{sdr['key']}", BIG_BLOCK)
        try:
            for name in layers:
                prod, path = LAYER_SRC[name]
                if prod == SDR:
                    out[name] = h[path][r0:r1, c0:c1]
        finally:
            h.close()
            f.close()
    for name in list(out):
        a = out[name]
        if not hasattr(a, "dtype") or name == "qf":
            continue
        a = a.astype("float32")
        # JPSS fill values are large negative numbers (-999.x and below).
        a[a <= -999.0] = np.nan
        if name == "dnb":
            # W cm-2 sr-1 to nW cm-2 sr-1, as in the VBD product.
            a *= 1.0e9
        out[name] = a
    for name in ("lat", "lon"):
        out[name][~np.isfinite(out[name])] = -999.0
    return out


def warp_to_region(swaths, name, resolution, method, tmpdir):
    """Grid one layer of one or more swaths onto the region in the project CRS."""
    from osgeo import gdal, osr

    gdal.UseExceptions()
    wkt = gs.read_command("g.proj", flags="w").strip()
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    reg = gs.region()
    is_ll = srs.IsGeographic()
    res = resolution / 111320.0 if is_ll else resolution
    srcs = []
    for k, sw in enumerate(swaths):
        paths = {}
        for band in ("lat", "lon", name):
            arr = sw[band]
            p = os.path.join(tmpdir, f"{name}_{k}_{band}.tif")
            dtype = gdal.GDT_Byte if band == "qf" else gdal.GDT_Float32
            ds = gdal.GetDriverByName("GTiff").Create(
                p, arr.shape[1], arr.shape[0], 1, dtype
            )
            ds.GetRasterBand(1).WriteArray(arr)
            if band == "qf":
                ds.GetRasterBand(1).SetNoDataValue(255)
            elif band == name:
                ds.GetRasterBand(1).SetNoDataValue(float("nan"))
            ds = None
            paths[band] = p
        src = gdal.Open(paths[name], gdal.GA_Update)
        src.SetMetadata(
            {
                "X_DATASET": paths["lon"],
                "X_BAND": "1",
                "Y_DATASET": paths["lat"],
                "Y_BAND": "1",
                "PIXEL_OFFSET": "0",
                "LINE_OFFSET": "0",
                "PIXEL_STEP": "1",
                "LINE_STEP": "1",
                "SRS": osr.SRS_WKT_WGS84_LAT_LONG,
                "GEOREFERENCING_CONVENTION": "PIXEL_CENTER",
            },
            "GEOLOCATION",
        )
        src = None
        srcs.append(paths[name])
    out = os.path.join(tmpdir, f"{name}_grid.tif")
    alg = {"nearest": "near", "average": "average", "max": "max"}[method]
    if name == "qf":
        alg = "near"
    gdal.Warp(
        out,
        srcs,
        geoloc=True,
        dstSRS=wkt,
        outputBounds=(
            float(reg["w"]),
            float(reg["s"]),
            float(reg["e"]),
            float(reg["n"]),
        ),
        xRes=res,
        yRes=res,
        resampleAlg=alg,
        dstNodata=255 if name == "qf" else float("nan"),
    )
    return out


def grass_date(t):
    """GRASS timestamp string, with English month names in any locale."""
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{t.day} {months[t.month - 1]} {t.year} {t:%H:%M:%S}"


def import_map(path, map_name):
    """Import a gridded layer, keeping the region extent."""
    gs.run_command(
        "r.import",
        input=path,
        output=map_name,
        extent="region",
        resolution="value",
        resolution_value=_res_of(path),
        overwrite=gs.overwrite(),
        quiet=True,
    )


def _res_of(path):
    from osgeo import gdal

    ds = gdal.Open(path)
    return abs(ds.GetGeoTransform()[1])


def main():
    options, flags = gs.parser()
    try:
        import fsspec  # noqa: F401
        import h5py  # noqa: F401
        import numpy  # noqa: F401
        from osgeo import gdal  # noqa: F401
    except ImportError as err:
        gs.fatal(
            _(
                "Required Python library not found: {}. Install numpy, h5py, fsspec, aiohttp and GDAL."
            ).format(err)
        )

    sats = options["satellite"].split(",")
    start = dt.date.fromisoformat(options["start"])
    end = dt.date.fromisoformat(options["end"])
    if end < start:
        gs.fatal(_("End date {} is before start date {}").format(end, start))
    which = ["night", "day"] if options["pass"] == "both" else [options["pass"]]
    layers = options["layers"].split(",")
    resolution = float(options["resolution"])
    method = options["method"]
    prefix = options["output"]
    tmpl = options["bucket"]

    bounds = region_bounds()
    gs.verbose(
        _("Region bounds (lon/lat): w={:.4f} s={:.4f} e={:.4f} n={:.4f}").format(
            *bounds
        )
    )
    if flags["p"]:
        print("w={:.6f}\ns={:.6f}\ne={:.6f}\nn={:.6f}".format(*bounds))
        return 0

    remote = Remote()
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    plan = []
    total = len(days) * len(sats) * len(which)
    k = 0
    gs.message(_("Searching granules covering the region..."))
    for sat in sats:
        bucket = tmpl.format(sat=SAT_BUCKET[sat])
        cache = {}

        def listing(d):
            if d not in cache:
                try:
                    cache[d] = list_day(bucket, SDR, d)
                except Exception as err:  # noqa: BLE001
                    gs.warning(_("Listing {} {} failed: {}").format(sat, d, err))
                    cache[d] = []
            return cache[d]

        for day in days:
            for wh in which:
                gs.percent(k, total, 1)
                k += 1
                t0 = nominal_time(day, (bounds[0] + bounds[2]) / 2.0, wh)
                lst = []
                for d in {
                    (t0 - dt.timedelta(hours=3)).date(),
                    t0.date(),
                    (t0 + dt.timedelta(hours=3)).date(),
                }:
                    lst += listing(d)
                try:
                    hits = find_overpasses(remote, bucket, sat, day, bounds, wh, lst)
                except Exception as err:  # noqa: BLE001
                    gs.warning(
                        _("{} {} {}: search failed: {}").format(sat, day, wh, err)
                    )
                    continue
                if hits:
                    plan.append((sat, bucket, wh, hits))
    gs.percent(1, 1, 1)
    if not plan:
        gs.message(_("No granule covers the region for the given dates."))
        return 0

    if flags["l"]:
        print("satellite|pass|start_utc|end_utc|day_night|granules")
        for sat, _b, wh, hits in plan:
            print(
                f"{sat}|{wh}|{hits[0]['start']:%Y-%m-%dT%H:%M:%S}|{hits[-1]['end']:%Y-%m-%dT%H:%M:%S}|"
                f"{hits[0]['daynight']}|{len(hits)}"
            )
        return 0

    import tempfile

    registry = {name: [] for name in layers}
    gs.message(_("Importing {} overpass(es)...").format(len(plan)))
    for i, (sat, bucket, wh, hits) in enumerate(plan):
        gs.percent(i, len(plan), 1)
        stamp = hits[0]["start"]
        geos = {g["id"]: g for d in {stamp.date()} for g in list_day(bucket, GEO, d)}
        swaths = []
        for g in hits:
            geo = geos.get(g["id"])
            if geo is None:
                gs.warning(_("{}: no geolocation granule for {}").format(sat, g["key"]))
                continue
            sw = read_granule(remote, bucket, g, geo, layers, bounds)
            if sw is not None:
                swaths.append(sw)
        if not swaths:
            continue
        mid = hits[0]["start"] + (hits[-1]["end"] - hits[0]["start"]) / 2
        moon = swaths[0]["moon_percent"]
        base = f"{prefix}_{sat}_{mid:%Y%m%dT%H%M%S}"
        with tempfile.TemporaryDirectory(
            dir=os.path.dirname(gs.tempfile(create=False))
        ) as tmp:
            for name in layers:
                grid = warp_to_region(swaths, name, resolution, method, tmp)
                map_name = f"{base}_{name}"
                import_map(grid, map_name)
                gs.run_command(
                    "r.timestamp",
                    map=map_name,
                    date=grass_date(mid),
                    quiet=True,
                )
                support = {
                    "map": map_name,
                    "title": f"VIIRS DNB {name}, {SAT_NAME[sat]}, {wh} pass {mid:%Y-%m-%d %H:%M:%S} UTC",
                    "source1": bucket,
                    "source2": ", ".join(os.path.basename(g["key"]) for g in hits),
                    "description": f"moon_illumination_percent={moon:.1f} method={method} resolution={resolution} m",
                }
                if name in LAYER_UNITS:
                    support["units"] = LAYER_UNITS[name]
                gs.run_command("r.support", quiet=True, **support)
                if name == "dnb":
                    gs.run_command(
                        "r.colors", map=map_name, color="grey", flags="g", quiet=True
                    )
                gs.raster_history(map_name, overwrite=True)
                registry[name].append(map_name)
        gs.verbose(
            _("{}: {} granule(s), moon illumination {:.0f} %").format(
                base, len(hits), moon
            )
        )
    gs.percent(1, 1, 1)
    n_maps = sum(len(v) for v in registry.values())
    gs.message(_("Imported {} raster map(s).").format(n_maps))

    if options["strds"] and n_maps and not flags["t"]:
        for name, maps in registry.items():
            if not maps:
                continue
            strds = f"{options['strds']}_{name}"
            exists = gs.read_command(
                "t.list", type="strds", where=f"name='{strds}'", quiet=True
            ).strip()
            if exists and not gs.overwrite():
                gs.verbose(_("Adding to existing STRDS <{}>").format(strds))
            else:
                gs.run_command(
                    "t.create",
                    type="strds",
                    temporaltype="absolute",
                    output=strds,
                    title=f"VIIRS DNB {name}",
                    description=f"Imported by r.in.viirs, {start} to {end}",
                    overwrite=gs.overwrite(),
                    quiet=True,
                )
            gs.run_command(
                "t.register",
                type="raster",
                input=strds,
                maps=",".join(maps),
                quiet=True,
            )
            gs.message(_("STRDS <{}>: {} map(s) registered.").format(strds, len(maps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
