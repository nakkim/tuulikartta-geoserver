# tuulikartta-geoserver

Serves the FMI radar reflectivity (dBZ) composite for Finland as a time-enabled WMS/WMTS layer.

## Services

| Service | Role |
|---|---|
| `radar-poller` | Polls the FMI open data WFS, downloads new GeoTIFFs, converts them to compressed Cloud Optimized GeoTIFF in `data/dbz/geotiff/`, harvests them into the mosaic and removes images older than `RETENTION_HOURS`. |
| `geoserver` | GeoServer (kartoza/geoserver) with an ImageMosaic store `radar:finland_dbz_eureffin`. |
| `postgis` | Holds the mosaic granule index (table `finland_dbz_eureffin`). |
| `proxy` | nginx. The only public entry point; allows GET/HEAD to WMS and WMTS only. |
| `geoserver-init` | One-shot setup: workspace, store, layer, time dimension, WMS limits. |

Published layer: `radar:radar_finland_eureffin` (EPSG:3067, also served in EPSG:3857), time dimension in ISO 8601, default is the latest image.

## Quick start

```sh
cp .env.example .env   # set passwords and options
docker compose up -d --build
```

To use the prebuilt `radar-poller` and `geoserver-init` images from GHCR instead of building them locally:

```sh
docker compose pull radar-poller geoserver-init
docker compose up -d
```

GitHub Actions builds and pushes these images when `VERSION` changes on `main`. Increase `VERSION` to publish a new release.

All variables in `.env` are required; see `.env.example` for descriptions.

Endpoints (with `PROXY_PORT=8088`):

- WMS: `http://localhost:8088/geoserver/wms`
- WMTS: `http://localhost:8088/geoserver/gwc/service/wmts`

Example request:

```
http://localhost:8088/geoserver/wms?service=WMS&version=1.1.1&request=GetMap&layers=radar:radar_finland_eureffin&bbox=-196593,6255329,1044176,8084432&srs=EPSG:3067&width=512&height=760&format=image/png
```

Add `&time=2026-10-09T16:05:00Z` to request a specific image.

## Administration

The GeoServer port 8080 binds to `GEOSERVER_BIND_ADDRESS` and is not routed through the proxy.

- Web UI: `http://127.0.0.1:8080/geoserver/web` (only when `GEOSERVER_DISABLE_WEB_INTERFACE=false`)
- REST API: `http://127.0.0.1:8080/geoserver/rest`

On a server, keep `GEOSERVER_BIND_ADDRESS=127.0.0.1` and use an SSH tunnel:

```sh
ssh -L 8080:127.0.0.1:8080 <server>
```

Changing the admin password in `.env` takes effect when the container is recreated (`docker compose up -d`), not on `docker restart`. The PostGIS password is applied only when the `postgis_data` volume is first created.

## Production notes

- Terminate TLS in front of the proxy and set GeoServer's Proxy Base URL to the public `https://` address.
- Keep `GEOSERVER_DISABLE_WEB_INTERFACE=true`.
- WMTS tiles are cached per `TIME` value. `TIME` must be a single instant such as `2026-10-14T12:55:00Z` or `2026-10-14T12:55:00.000Z`; omit it for the latest image. `radar-poller` clears the latest-image tiles after each new image and the tiles of expired images. The tile cache is limited to 1 GiB (`geoserver_data/gwc/geowebcache-diskquota.xml`, least recently used tiles are removed first).
- Only WMS and WMTS are enabled. WFS, WCS, WPS and CSW are disabled.
- Request limits: `geoserver_data/controlflow.properties` (per-IP throttling via `X-Forwarded-For` set by the proxy) and WMS limits in `geoserver_init/setup.sh`.
- Behind another reverse proxy, the proxy takes the client IP from `X-Forwarded-For` only when the request comes from a private address (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). The proxy in front must set or append the real client IP.
- `geoserver_data/security/` and `data/dbz/geotiff/datastore.properties` contain secrets and are not committed.
