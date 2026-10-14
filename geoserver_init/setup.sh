#!/bin/sh
set -eu

GEOSERVER_URL="${GEOSERVER_URL:-http://geoserver:8080/geoserver}"
GEOSERVER_USER="${GEOSERVER_USER:-admin}"
GEOSERVER_PASSWORD="${GEOSERVER_PASSWORD:-geoserver}"
GEOSERVER_WORKSPACE="${GEOSERVER_WORKSPACE:-radar}"
GEOSERVER_STORE="${GEOSERVER_STORE:-finland_dbz_eureffin}"
GEOSERVER_COVERAGE="${GEOSERVER_COVERAGE:-radar_finland_eureffin}"
MOSAIC_NAME="${MOSAIC_NAME:-finland_dbz_eureffin}"
MOSAIC_DIR="${MOSAIC_DIR:-/data/dbz/geotiff}"

AUTH="${GEOSERVER_USER}:${GEOSERVER_PASSWORD}"

echo "Waiting for GeoServer REST API at ${GEOSERVER_URL}..."
until curl -sf -u "${AUTH}" "${GEOSERVER_URL}/rest/about/version.json" > /dev/null; do
    sleep 5
done
echo "GeoServer is up."

# maxRequestMemory in KB, maxRenderingTime in seconds
echo "Restricting advertised WMS SRS list and setting WMS resource limits"
curl -sf -u "${AUTH}" -XPUT -H "Content-type: application/json" \
    -d '{"wms":{"srs":{"string":["EPSG:3857","EPSG:3067"]},"maxRequestMemory":65536,"maxRenderingTime":30,"maxRenderingErrors":1000}}' \
    "${GEOSERVER_URL}/rest/services/wms/settings.json"

echo "Waiting for first GeoTIFF granule in ${MOSAIC_DIR}..."
until [ -n "$(find "${MOSAIC_DIR}" -maxdepth 1 -name '*.tif' -print -quit 2>/dev/null)" ]; do
    sleep 5
done
echo "Granule found."

echo "Waiting for datastore.properties in ${MOSAIC_DIR}..."
until [ -f "${MOSAIC_DIR}/datastore.properties" ]; do
    sleep 5
done

# Workspace
if ! curl -sf -u "${AUTH}" "${GEOSERVER_URL}/rest/workspaces/${GEOSERVER_WORKSPACE}.json" > /dev/null; then
    echo "Creating workspace ${GEOSERVER_WORKSPACE}"
    curl -sf -u "${AUTH}" -XPOST -H "Content-type: text/xml" \
        -d "<workspace><name>${GEOSERVER_WORKSPACE}</name></workspace>" \
        "${GEOSERVER_URL}/rest/workspaces"
else
    echo "Workspace ${GEOSERVER_WORKSPACE} already exists"
fi

# Coverage store (ImageMosaic). Granule index goes to PostGIS via datastore.properties.
if ! curl -sf -u "${AUTH}" "${GEOSERVER_URL}/rest/workspaces/${GEOSERVER_WORKSPACE}/coveragestores/${GEOSERVER_STORE}.json" > /dev/null; then
    echo "Creating ImageMosaic store ${GEOSERVER_STORE} on ${MOSAIC_DIR}"
    curl -sf -u "${AUTH}" -XPUT -H "Content-type: text/plain" \
        -d "${MOSAIC_DIR}" \
        "${GEOSERVER_URL}/rest/workspaces/${GEOSERVER_WORKSPACE}/coveragestores/${GEOSERVER_STORE}/external.imagemosaic?configure=none"
else
    echo "Coverage store ${GEOSERVER_STORE} already exists"
fi

# Publish the mosaic under an explicit layer name (native name is the mosaic directory name)
if ! curl -sf -u "${AUTH}" "${GEOSERVER_URL}/rest/workspaces/${GEOSERVER_WORKSPACE}/coveragestores/${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}.json" > /dev/null; then
    echo "Publishing coverage ${GEOSERVER_COVERAGE} (native ${MOSAIC_NAME})"
    curl -sf -u "${AUTH}" -XPOST -H "Content-type: text/xml" \
        -d "<coverage><name>${GEOSERVER_COVERAGE}</name><nativeName>${MOSAIC_NAME}</nativeName><nativeCoverageName>${MOSAIC_NAME}</nativeCoverageName></coverage>" \
        "${GEOSERVER_URL}/rest/workspaces/${GEOSERVER_WORKSPACE}/coveragestores/${GEOSERVER_STORE}/coverages"
else
    echo "Coverage ${GEOSERVER_COVERAGE} already exists"
fi

# Enable time dimension on the published coverage (idempotent)
echo "Configuring time dimension on coverage ${GEOSERVER_COVERAGE}"
curl -sf -u "${AUTH}" -XPUT -H "Content-type: text/xml" \
    -d "<coverage><metadata><entry key=\"time\"><dimensionInfo><enabled>true</enabled><presentation>LIST</presentation><units>ISO8601</units><defaultValue><strategy>MAXIMUM</strategy></defaultValue></dimensionInfo></entry></metadata></coverage>" \
    "${GEOSERVER_URL}/rest/workspaces/${GEOSERVER_WORKSPACE}/coveragestores/${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}"

# Cache tiles per TIME value. Without this filter GeoWebCache ignores TIME and
# serves the same cached tile for every time step. Empty TIME (latest image) is
# its own cache entry, which radar-poller truncates after each new image.
GWC_LAYER_URL="${GEOSERVER_URL}/gwc/rest/layers/${GEOSERVER_WORKSPACE}:${GEOSERVER_COVERAGE}.xml"
TIME_FILTER='<regexParameterFilter><key>TIME</key><defaultValue></defaultValue><regex>\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{3})?Z</regex></regexParameterFilter>'
GWC_LAYER="$(curl -sf -u "${AUTH}" "${GWC_LAYER_URL}")"
if printf '%s' "${GWC_LAYER}" | grep -q '<key>TIME</key>'; then
    echo "Tile cache TIME parameter filter already exists"
elif ! printf '%s' "${GWC_LAYER}" | grep -q '</parameterFilters>'; then
    echo "Tile cache layer has no parameterFilters element; cannot add TIME filter" >&2
    exit 1
else
    echo "Adding TIME parameter filter to tile cache layer"
    printf '%s' "${GWC_LAYER}" \
        | sed "s#</parameterFilters>#${TIME_FILTER}</parameterFilters>#" \
        | curl -sf -u "${AUTH}" -XPUT -H "Content-type: text/xml" --data-binary @- "${GWC_LAYER_URL}"
    echo
fi

echo "GeoServer setup complete."
