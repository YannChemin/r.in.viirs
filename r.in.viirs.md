## DESCRIPTION

*r.in.viirs* queries, downloads and imports VIIRS Day/Night Band (DNB)
granules of Suomi-NPP, NOAA-20 and NOAA-21 into the current GRASS GIS
project. The data come from the NOAA Open Data Dissemination (NODD)
buckets on Amazon Web Services, which need no account. The swath is
cropped to the current region and gridded onto it in the project
coordinate reference system, so only the region is kept, never the
granule files.

```sh
g.region n=9551000 s=9431000 w=276000 e=396000 res=750

# List the night overpasses over the region, without importing.
r.in.viirs -l start=2026-08-01 end=2026-08-31

# Import radiance and lunar zenith angle for both satellites.
r.in.viirs start=2026-08-01 end=2026-08-31 satellite=npp,j01 \
  layers=dnb,lunar_zenith method=max
```

The DNB is a panchromatic band (500-900 nm) sensitive enough to record
city lights, gas flares, fires and the lights of fishing boats at night.
Its pixels are about 742 m on a side at all scan angles.

### Finding the granules

The buckets hold about 1000 granules (85 s each) per satellite and day.
*r.in.viirs* does not open them all. The satellites are on
sun-synchronous orbits that cross the equator at about 01:30 (night,
descending) and 13:30 (day, ascending) local solar time, so the
overpass time over the region centre is predicted from its longitude.
The module then reads the G-Ring polygon (the corners of the granule) of
the granule nearest that time, which costs a few HTTP range requests
and no data, and steps along the pass or to the next orbit until a
G-Ring intersects the region. One night or day is resolved in two to six
such reads per satellite.

Dates are **local solar dates of the overpass**: with `pass=night`, the
date 2026-08-31 at 55°E gives the pass of about 01:30 local time on
31 August, which is 21:48 UTC on 30 August.

### Layers

- **dnb**: radiance in nW cm-2 sr-1 (the SDR values in W cm-2 sr-1
  multiplied by 1e9, the unit of the EOG VIIRS Boat Detection product).
  Fill values become null.
- **qf**: DNB SDR quality flags (`QF1_VIIRSDNBSDR`), always gridded with
  nearest neighbour.
- **lunar_zenith**, **satellite_zenith**, **solar_zenith**: angles in
  degrees, from the geolocation granule.

Each overpass gives one map per layer, named
`<output>_<satellite>_<YYYYmmddTHHMMSS>_<layer>` after the UTC mid time
of the overpass. The granules of one overpass that overlap the region
are mosaicked first.

### Time stamps and space-time datasets

Every map gets the UTC mid time of its overpass as its time stamp
(*r.timestamp*). By default the maps are also registered in one space-time
raster dataset per layer, `<strds>_<layer>` (`viirs_dnb`,
`viirs_lunar_zenith`, ...). An existing dataset is extended, so a long
series can be imported in several runs; with **--overwrite** it is
created again. The **-t** flag skips the registration.

### Metadata

*r.support* records the satellite, the pass, the bucket, the granule
files and the moon illumination of the overpass (percent of the lunar disc lit), which the
analysis of night lights always needs: detections of lit boats fall by
about 95 % around full moon (Elvidge et al. 2018).

### Resampling

The swath is gridded with the GDAL geolocation-array transformer.
**method=nearest** keeps the radiances unchanged; **method=max** keeps
point sources such as boat lights when the output cells are larger than
the DNB pixel; **method=average** smooths. The default resolution is
750 m; at finer resolutions the cells repeat the DNB pixels.

## NOTES

The module reads the HDF5 granules over HTTP and transfers only the
datasets it needs. The datasets are compressed as a single block, so
each read fetches the whole array of the granule (about 3 MB each for
latitude, longitude and radiance; 15 to 20 MB per granule for the DNB
alone). The **-l** flag lists overpasses without reading any array.

The NODD buckets are a near-real-time and archive service of NOAA. The
default bucket template is `https://noaa-nesdis-{sat}-pds.s3.amazonaws.com`
with `{sat}` replaced by `snpp`, `n20` or `n21`; the **bucket** option
accepts a mirror with the same layout.

Python dependencies: numpy, h5py, fsspec with aiohttp, and the GDAL
Python bindings.

Progress is reported through the GRASS percentage messages, which tools
such as [MetaMonitor](https://github.com/YannChemin/MetaMonitor) pick up.

## EXAMPLES

Night radiance over Port Victoria (Seychelles) for one week, gridded at
750 m with the maximum rule, in a UTM zone 40S project:

```sh
g.region n=9551000 s=9431000 w=276000 e=396000 res=750
r.in.viirs start=2026-08-25 end=2026-08-31 satellite=npp,j01,j02 \
  layers=dnb,lunar_zenith method=max output=syc
t.rast.list syc_dnb
```

Print the longitude/latitude bounds used for the query:

```sh
r.in.viirs -p start=2026-08-31 end=2026-08-31
```

## REFERENCES

- Elvidge, C. D., Zhizhin, M., Baugh, K., Hsu, F.-C. (2015). Automatic
  boat identification system for VIIRS low light imaging data. *Remote
  Sensing*, 7(3), 3020-3036.
- Elvidge, C. D., Ghosh, T., Baugh, K., Zhizhin, M., Hsu, F.-C., et al.
  (2018). Rating the effectiveness of fishery closures with Visible
  Infrared Imaging Radiometer Suite boat detection data. *Frontiers in
  Marine Science*, 5, 132.
- NOAA Open Data Dissemination program, JPSS VIIRS SDR on AWS.

## SEE ALSO

*[i.landsat.toar](https://grass.osgeo.org/grass-stable/manuals/i.landsat.toar.html),
[r.import](https://grass.osgeo.org/grass-stable/manuals/r.import.html),
[r.in.ecostress](https://github.com/YannChemin/r.in.ecostress),
[r.in.landsat](https://github.com/YannChemin/r.in.landsat),
[r.in.sentinel](https://github.com/YannChemin/r.in.sentinel),
[r.timestamp](https://grass.osgeo.org/grass-stable/manuals/r.timestamp.html),
[t.register](https://grass.osgeo.org/grass-stable/manuals/t.register.html)*

## AUTHORS

Yann Chemin
