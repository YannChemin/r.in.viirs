# r.in.viirs

A [GRASS GIS](https://grass.osgeo.org/) addon that queries, downloads and
imports VIIRS Day/Night Band (DNB) radiance of Suomi-NPP, NOAA-20 and
NOAA-21 straight from the **NOAA Open Data Dissemination buckets on AWS**
(no account needed), cropped and gridded to the current region.

```
g.region n=9551000 s=9431000 w=276000 e=396000 res=750

r.in.viirs -l start=2026-08-01 end=2026-08-31            # list overpasses
r.in.viirs start=2026-08-01 end=2026-08-31 satellite=npp,j01 \
  layers=dnb,lunar_zenith method=max                    # import
t.rast.list viirs_dnb
```

## Why

The VIIRS DNB sees the night: city lights, gas flares and the lights of
fishing boats. Derived products such as the EOG VIIRS Boat Detection
tables require an account and, for scripted access, a subscription. The
DNB Sensor Data Records themselves are public on AWS. This addon brings
them into GRASS so that one can run one's own night-light or boat
detection, following the same pattern as
[r.in.sentinel](https://github.com/YannChemin/r.in.sentinel),
[r.in.landsat](https://github.com/YannChemin/r.in.landsat) and
[r.in.ecostress](https://github.com/YannChemin/r.in.ecostress).

## How

- Predicts the overpass time from the region longitude (sun-synchronous
  orbits, 01:30 and 13:30 local solar time), then reads only the G-Ring
  corners of a few granules to find those covering the region.
- Reads latitude, longitude and the requested layers over HTTP (h5py on
  fsspec), crops them to the region and grids them with the GDAL
  geolocation-array transformer into the project CRS.
- Imports one map per overpass and layer, with the UTC time stamp, units,
  moon illumination and source granules in the metadata, and registers
  them in one space-time raster dataset per layer (default; `-t` skips).
- Keeps nothing else: no granule file is written to disk.

## Install

```
g.extension r.in.viirs url=/path/to/r.in.viirs
```

Requires numpy, h5py, fsspec, aiohttp and the GDAL Python bindings.

## Tests

```
grass --tmp-project XY --exec python3 -m pytest tests
```

## Licence

Public domain ([Unlicense](LICENSE)).
