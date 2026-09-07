# World countries basemap

`countries-50m.geojson` is Natural Earth 1:50m Admin 0 countries, taken from the
`world-atlas` 2.0.2 npm package (TopoJSON) and decoded to plain GeoJSON with
coordinates rounded to two decimals and all properties stripped. Natural Earth
data is in the public domain and needs no attribution.

Used by the site map on the Reports page as a flat vector basemap so the
console needs no tile server, no CDN, and no API key.
