#!/usr/bin/env python3
"""Poll FMI WFS stored query for radar dbz composite and save latest geotiff."""
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
from xml.etree import ElementTree as ET

import requests
from requests.auth import HTTPBasicAuth

WFS_URL = os.environ.get(
    "WFS_URL",
    "https://opendata.fmi.fi/wfs?request=getfeature&storedquery_id=fmi::radar::composite::dbz",
)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/data/dbz/geotiff")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL_SECONDS", "10"))
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))
RETENTION_HOURS = float(os.environ.get("RETENTION_HOURS", "6"))
CONVERT_TIMEOUT = float(os.environ.get("CONVERT_TIMEOUT_SECONDS", "120"))

GEOSERVER_HARVEST_ENABLED = os.environ.get("GEOSERVER_HARVEST_ENABLED", "true").lower() == "true"
GEOSERVER_URL = os.environ.get("GEOSERVER_URL", "http://geoserver:8080/geoserver")
GEOSERVER_WORKSPACE = os.environ.get("GEOSERVER_WORKSPACE", "radar")
GEOSERVER_STORE = os.environ.get("GEOSERVER_STORE", "finland_dbz_eureffin")
GEOSERVER_COVERAGE = os.environ.get("GEOSERVER_COVERAGE", "radar_finland_eureffin")
# Mosaic name: also the granule index table name in PostGIS
MOSAIC_NAME = os.environ.get("MOSAIC_NAME", "finland_dbz_eureffin")
GEOSERVER_USER = os.environ.get("GEOSERVER_USER", "admin")
GEOSERVER_PASSWORD = os.environ.get("GEOSERVER_PASSWORD", "geoserver")
GEOSERVER_AUTH = HTTPBasicAuth(GEOSERVER_USER, GEOSERVER_PASSWORD)

POSTGIS_HOST = os.environ.get("POSTGIS_HOST", "postgis")
POSTGIS_PORT = os.environ.get("POSTGIS_PORT", "5432")
POSTGIS_DB = os.environ.get("POSTGIS_DB", "radar")
POSTGIS_USER = os.environ.get("POSTGIS_USER", "radar")
POSTGIS_PASSWORD = os.environ.get("POSTGIS_PASSWORD", "radar")

GWC_LAYER = f"{GEOSERVER_WORKSPACE}:{GEOSERVER_COVERAGE}"
GWC_REST_URL = f"{GEOSERVER_URL}/gwc/rest"

FILENAME_RE = re.compile(r"^(\d{8}T\d{6}Z)_finland_dbz_eureffin\.tif$")

INDEXER_PROPERTIES = f"""Name={MOSAIC_NAME}
TimeAttribute=time
Schema=*the_geom:Polygon,location:String,time:java.util.Date
PropertyCollectors=TimestampFileNameExtractorSPI[timeregex](time)
"""

TIMEREGEX_PROPERTIES = """regex=[0-9]{8}T[0-9]{6}Z
"""

# Mosaic granule index lives in PostGIS instead of a shapefile.
DATASTORE_PROPERTIES = f"""SPI=org.geotools.data.postgis.PostgisNGDataStoreFactory
host={POSTGIS_HOST}
port={POSTGIS_PORT}
database={POSTGIS_DB}
schema=public
user={POSTGIS_USER}
passwd={POSTGIS_PASSWORD}
Loose\\ bbox=true
Estimated\\ extends=false
validate\\ connections=true
Connection\\ timeout=10
min\\ connections=1
max\\ connections=10
preparedStatements=true
"""

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("radar_poller")


def ensure_mosaic_index_files():
    indexer_path = os.path.join(OUTPUT_DIR, "indexer.properties")
    timeregex_path = os.path.join(OUTPUT_DIR, "timeregex.properties")
    # Always rewrite so the mosaic name follows the environment.
    with open(indexer_path, "w") as f:
        f.write(INDEXER_PROPERTIES)
    if not os.path.exists(timeregex_path):
        with open(timeregex_path, "w") as f:
            f.write(TIMEREGEX_PROPERTIES)
    # Always rewrite so connection settings follow the environment.
    with open(os.path.join(OUTPUT_DIR, "datastore.properties"), "w") as f:
        f.write(DATASTORE_PROPERTIES)


def fetch_latest_entry():
    """Return (time_str, geotiff_url) for latest observation, or None."""
    resp = requests.get(WFS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    entries = []
    for ref in root.iter("{http://www.opengis.net/gml/3.2}fileReference"):
        url = ref.text.strip() if ref.text else ""
        if not url:
            continue
        qs = parse_qs(urlparse(url).query)
        time_vals = qs.get("time")
        if not time_vals:
            continue
        entries.append((time_vals[0], url))

    if not entries:
        return None

    entries.sort(key=lambda e: e[0])
    return entries[-1]


def safe_filename(time_str):
    # time_str like 2026-10-03T13:20:00Z -> 20261003T132000Z
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z", time_str)
    y, mo, d, h, mi, s = match.groups()
    stamp = f"{y}{mo}{d}T{h}{mi}{s}Z"
    return f"{stamp}_finland_dbz_eureffin.tif"


def download(url, dest_path):
    """Download the GeoTIFF and store it as a compressed Cloud Optimized GeoTIFF."""
    raw_path = dest_path + ".raw.part"
    cog_path = dest_path + ".part"
    try:
        with requests.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
            resp.raise_for_status()
            with open(raw_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        # Source is uncompressed and strip-organized (~36 MB). COG with DEFLATE is
        # ~3 MB, tiled and has overviews. NEAREST keeps overview values real dBZ.
        subprocess.run(
            [
                "gdal_translate", "-q", "-of", "COG",
                "-co", "COMPRESS=DEFLATE",
                "-co", "PREDICTOR=2",
                "-co", "RESAMPLING=NEAREST",
                raw_path, cog_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=CONVERT_TIMEOUT,
        )
        os.replace(cog_path, dest_path)
    finally:
        for path in (raw_path, cog_path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def harvest_granule(dest_path):
    if not GEOSERVER_HARVEST_ENABLED:
        return
    url = (
        f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}"
        f"/coveragestores/{GEOSERVER_STORE}/external.imagemosaic"
    )
    try:
        resp = requests.post(
            url,
            data=dest_path,
            headers={"Content-Type": "text/plain"},
            auth=GEOSERVER_AUTH,
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            log.warning("GeoServer harvest failed (%s): %s", resp.status_code, resp.text)
    except requests.RequestException as exc:
        log.warning("GeoServer harvest request failed: %s", exc)


def remove_granule(filename):
    if not GEOSERVER_HARVEST_ENABLED:
        return
    url = (
        f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}"
        f"/coveragestores/{GEOSERVER_STORE}/coverages/{GEOSERVER_COVERAGE}"
        f"/index/granules.json"
    )
    try:
        resp = requests.delete(
            url,
            params={"filter": f"location='{filename}'"},
            auth=GEOSERVER_AUTH,
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            log.warning("GeoServer granule removal failed (%s): %s", resp.status_code, resp.text)
    except requests.RequestException as exc:
        log.warning("GeoServer granule removal request failed: %s", exc)
    match = FILENAME_RE.match(filename)
    if match:
        truncate_time_tiles(datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ"))


def truncate_latest_tiles():
    """Remove cached tiles requested without TIME; they show the previous latest image.

    The seed endpoint truncates only the default parameter set, so tiles cached
    for explicit TIME values stay.
    """
    if not GEOSERVER_HARVEST_ENABLED:
        return
    try:
        resp = requests.get(
            f"{GWC_REST_URL}/layers/{GWC_LAYER}.json", auth=GEOSERVER_AUTH, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        layer = resp.json()["GeoServerLayer"]
        for gridset in (g["gridSetName"] for g in layer.get("gridSubsets", [])):
            for fmt in layer.get("mimeFormats", []):
                # zoomStop is clamped to the gridset's last level
                body = {"seedRequest": {
                    "name": GWC_LAYER, "gridSetId": gridset, "format": fmt,
                    "zoomStart": 0, "zoomStop": 30, "type": "truncate", "threadCount": 1,
                }}
                resp = requests.post(
                    f"{GWC_REST_URL}/seed/{GWC_LAYER}.json",
                    json=body,
                    auth=GEOSERVER_AUTH,
                    timeout=REQUEST_TIMEOUT,
                )
                if not resp.ok:
                    log.warning("Tile cache truncate failed for %s %s (%s): %s",
                                gridset, fmt, resp.status_code, resp.text)
    except (requests.RequestException, ValueError, KeyError) as exc:
        log.warning("Tile cache truncate request failed: %s", exc)


def truncate_time_tiles(granule_time):
    """Remove cached tiles for an expired image's TIME value."""
    if not GEOSERVER_HARVEST_ENABLED:
        return
    try:
        resp = requests.get(
            f"{GEOSERVER_URL}/rest/layers/{GWC_LAYER}.json", auth=GEOSERVER_AUTH, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        # Cached parameter sets include the resolved default style
        style = resp.json()["layer"]["defaultStyle"]["name"]
        # Both spellings the TIME parameter filter accepts
        for value in (granule_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      granule_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")):
            body = (
                f"<truncateParameters><layerName>{GWC_LAYER}</layerName><parameters>"
                f"<entry><string>STYLES</string><string>{style}</string></entry>"
                f"<entry><string>TIME</string><string>{value}</string></entry>"
                f"</parameters></truncateParameters>"
            )
            resp = requests.post(
                f"{GWC_REST_URL}/masstruncate",
                data=body,
                headers={"Content-Type": "text/xml"},
                auth=GEOSERVER_AUTH,
                timeout=REQUEST_TIMEOUT,
            )
            if not resp.ok:
                log.warning("Tile cache truncate failed for TIME=%s (%s): %s",
                            value, resp.status_code, resp.text)
    except (requests.RequestException, ValueError, KeyError) as exc:
        log.warning("Tile cache truncate request failed: %s", exc)


def reconcile_index():
    """Remove mosaic index entries whose backing file no longer exists on disk."""
    if not GEOSERVER_HARVEST_ENABLED:
        return
    url = (
        f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}"
        f"/coveragestores/{GEOSERVER_STORE}/coverages/{GEOSERVER_COVERAGE}"
        f"/index/granules.json"
    )
    try:
        resp = requests.get(url, auth=GEOSERVER_AUTH, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            log.warning("GeoServer index listing failed (%s): %s", resp.status_code, resp.text)
            return
        locations = {
            feature["properties"]["location"]
            for feature in resp.json().get("features", [])
        }
    except (requests.RequestException, ValueError, KeyError) as exc:
        log.warning("GeoServer index listing request failed: %s", exc)
        return

    for location in locations:
        if not os.path.exists(os.path.join(OUTPUT_DIR, location)):
            log.info("Removing orphaned index entry %s (file missing on disk)", location)
            remove_granule(location)


def cleanup_old_files():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)
    for name in os.listdir(OUTPUT_DIR):
        if name.endswith(".part"):
            # Leftover from an interrupted run; downloads in this process
            # remove their own temporary files.
            log.info("Removing stale temporary file %s", name)
            try:
                os.remove(os.path.join(OUTPUT_DIR, name))
            except OSError as exc:
                log.warning("Failed to remove %s: %s", name, exc)
            continue
        match = FILENAME_RE.match(name)
        if not match:
            continue
        file_time = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if file_time < cutoff:
            log.info("Removing expired file %s (older than %sh)", name, RETENTION_HOURS)
            remove_granule(name)
            try:
                os.remove(os.path.join(OUTPUT_DIR, name))
            except OSError as exc:
                log.warning("Failed to remove %s: %s", name, exc)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ensure_mosaic_index_files()
    last_time = None

    log.info("Start polling %s every %ss", WFS_URL, POLL_INTERVAL)

    while True:
        try:
            entry = fetch_latest_entry()
            if entry is None:
                log.warning("No geotiff entries found in response")
            else:
                time_str, url = entry
                if last_time is None or time_str > last_time:
                    filename = safe_filename(time_str)
                    dest_path = os.path.join(OUTPUT_DIR, filename)
                    log.info("New image %s -> %s", time_str, dest_path)
                    download(url, dest_path)
                    harvest_granule(dest_path)
                    truncate_latest_tiles()
                    last_time = time_str
                else:
                    log.debug("No new image (latest still %s)", last_time)

            cleanup_old_files()
            reconcile_index()
        except requests.RequestException as exc:
            log.error("Request failed: %s", exc)
        except subprocess.CalledProcessError as exc:
            log.error("GeoTIFF conversion failed: %s", exc.stderr.strip())
        except subprocess.TimeoutExpired:
            log.error("GeoTIFF conversion timed out after %ss", CONVERT_TIMEOUT)
        except ET.ParseError as exc:
            log.error("Failed to parse WFS response: %s", exc)
        except Exception:
            log.exception("Unexpected error in poll loop")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
