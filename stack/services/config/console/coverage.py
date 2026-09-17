"""ResCCOM 2.1-d — predicted coverage: Hata (urban) model, nothing fancier.

RFC-0006 D2: "a simple, documented propagation model... always labelled as
a model estimate, with the model named; never shown on user-facing pages
as coverage fact." This computes one path-loss-limited radius per cell and
renders it as a circle -- no terrain, no clutter classes, no attempt at
realism beyond the textbook Okumura-Hata urban formula. A cell with no
tx_power_dbm (every cell in the lab profile: ZMQ/rfsimulator rigs have no
real transmit power to model) simply has no predicted coverage -- CLAUDE.md
"don't invent RF numbers" applies here as much as to the schema itself.
"""
from __future__ import annotations

import math

MODEL_NAME = "Hata (urban), 3GPP-band, informational only"

# Okumura-Hata is defined for 150-1500 MHz; used here as a named,
# documented approximation outside that range too (2/3 GHz cellular
# bands) since RFC-0006 D2 only asks for "one simple named model", not
# validated accuracy -- the legend/label always says so.
MIN_FREQ_MHZ = 150
MAX_FREQ_MHZ = 2600


def band_to_freq_mhz(rat: str, band: str) -> float | None:
    """A tiny, explicit LTE/NR band -> center frequency table -- just the
    bands this project's own configs actually use (stack/ran/), not a
    general 3GPP band database."""
    table = {
        ("lte", "7"): 2650.0,  # E-UTRA band 7 downlink, EARFCN 3350 (stack/ran)
        ("nr", "n78"): 3500.0,  # NR band n78 mid-band, but see MAX_FREQ_MHZ note
    }
    return table.get((rat, band))


def hata_urban_range_km(
    *,
    freq_mhz: float,
    tx_power_dbm: float,
    tx_height_m: float = 20.0,
    rx_height_m: float = 1.5,
    rx_sensitivity_dbm: float = -100.0,
    tx_antenna_gain_dbi: float = 0.0,
) -> float:
    """Distance (km) at which received power falls to `rx_sensitivity_dbm`,
    per the Okumura-Hata urban path-loss model, solved for distance:

        L = 69.55 + 26.16*log10(f) - 13.82*log10(h_b) - a(h_m)
            + (44.9 - 6.55*log10(h_b)) * log10(d)

    where f is in MHz, h_b/h_m are base/mobile antenna heights in metres,
    d is in km, and a(h_m) is the "medium/small city" mobile-height
    correction term. L is the max tolerable path loss (tx EIRP minus the
    receiver's sensitivity); the formula is inverted for d.
    """
    freq_mhz = max(MIN_FREQ_MHZ, min(MAX_FREQ_MHZ, freq_mhz))
    a_hm = (1.1 * math.log10(freq_mhz) - 0.7) * rx_height_m - (1.56 * math.log10(freq_mhz) - 0.8)
    eirp_dbm = tx_power_dbm + tx_antenna_gain_dbi
    max_path_loss_db = eirp_dbm - rx_sensitivity_dbm

    a = 69.55 + 26.16 * math.log10(freq_mhz) - 13.82 * math.log10(tx_height_m) - a_hm
    b = 44.9 - 6.55 * math.log10(tx_height_m)
    log10_d = (max_path_loss_db - a) / b
    return max(0.0, 10**log10_d)


def circle_polygon(lat: float, lon: float, radius_km: float, n: int = 32) -> list[list[float]]:
    """A GeoJSON-ready [lon, lat] ring approximating a circle of
    `radius_km` around (lat, lon) -- flat-earth (equirectangular)
    approximation, adequate at the scale a single cell covers."""
    lat_rad = math.radians(lat)
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(lat_rad) or 1e-9

    ring = []
    for i in range(n + 1):
        theta = 2 * math.pi * i / n
        dlat = (radius_km * math.sin(theta)) / km_per_deg_lat
        dlon = (radius_km * math.cos(theta)) / km_per_deg_lon
        ring.append([lon + dlon, lat + dlat])
    return ring


def predicted_coverage_feature(site: dict, cell_index: int, cell: dict) -> dict | None:
    """A GeoJSON Feature for one cell's predicted coverage, or None if
    there isn't enough real data to compute one (no invented numbers)."""
    if site.get("lat") is None or site.get("lon") is None:
        return None
    if cell.get("tx_power_dbm") is None:
        return None
    freq = band_to_freq_mhz(cell.get("rat"), cell.get("band"))
    if freq is None:
        return None

    height_m = site.get("height_m") if site.get("height_m") is not None else 20.0
    radius_km = hata_urban_range_km(
        freq_mhz=freq,
        tx_power_dbm=cell["tx_power_dbm"],
        tx_height_m=max(height_m, 1.0),
    )
    if radius_km <= 0:
        return None

    return {
        "type": "Feature",
        "properties": {
            "site_id": site["id"],
            "cell_index": cell_index,
            "rat": cell["rat"],
            "band": cell["band"],
            "model": MODEL_NAME,
            "radius_km": round(radius_km, 2),
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [circle_polygon(site["lat"], site["lon"], radius_km)],
        },
    }
