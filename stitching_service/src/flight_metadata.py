# src/flight_metadata.py
"""
Correct EXIF/GPS/attitude extraction and admission filters for the
composable stitching orchestrator.

Unlike PROGRAM_JUANG/PROGRAM-SENDER1/stitcher.py's _extract_flight_metadata,
this module NEVER converts yaw/pitch/roll to radians -- geometry.computeUnRotMatrix
does that conversion itself (see docs/BUG_REPORT_ATTITUDE_UNIT_MISMATCH.md).
"""
import json
import math
from typing import Dict, List, Optional, Tuple

import exifread
import numpy as np

def extract_flight_metadata(image_path: str) -> Dict:
    """
    Read GPS (lat/lon/alt, GPS IFD) + yaw (GPSImgDirection) + roll/pitch
    (ImageDescription JSON) from a JPEG's EXIF, matching the convention
    PROGRAM_JUANG/PROGRAM-SENDER1/sender.py's embed_flight_metadata_exif()
    writes. All angles returned in DEGREES.

    Returns has_telemetry=False + zero pose (never fabricated GPS) if no
    GPS EXIF is present.
    """

    result = {
        "latitude": None, "longitude": None, "altitude": 0.0,
        "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
        "has_telemetry": False,
    }
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f, details=False)
        if "GPS GPSLatitude" in tags and "GPS GPSLongitude" in tags:
            lat_vals = tags["GPS GPSLatitude"].values
            lon_vals = tags["GPS GPSLongitude"].values
            lat_ref = str(tags.get("GPS GPSLatitudeRef", "N"))
            lon_ref = str(tags.get("GPS GPSLongitudeRef", "E"))
            alt_tag = tags.get("GPS GPSAltitude")
            dir_tag = tags.get("GPS GPSImgDirection")

            # Convert DMS to decimal degrees
            lat = (lat_vals[0].num / lat_vals[0].den +
                   lat_vals[1].num / (lat_vals[1].den * 60) +
                   lat_vals[2].num / (lat_vals[2].den * 3600))

            lon = (lon_vals[0].num / lon_vals[0].den +
                   lon_vals[1].num / (lon_vals[1].den * 60) +
                   lon_vals[2].num / (lon_vals[2].den * 3600))

            alt = float(alt_tag.values[0].num / alt_tag.values[0].den) if alt_tag else 0.0
            yaw = float(dir_tag.values[0].num / dir_tag.values[0].den) if dir_tag else 0.0

            if lat_ref.strip() == "S":
                lat = -lat
            if lon_ref.strip() == "W":
                lon = -lon

            result.update({
                "latitude": lat, "longitude": lon, "altitude": alt,
                "yaw": yaw, "has_telemetry": True,
            })

        desc_tag = tags.get("Image ImageDescription")
        if desc_tag is not None:
            try:
                attitude = json.loads(str(desc_tag))
                result["roll"] = float(attitude.get("roll", 0.0))
                result["pitch"] = float(attitude.get("pitch", 0.0))
            except (ValueError, TypeError):
                pass

    except Exception as e:
        print(f"[flight_metadata] Failed to extract EXIF metadata from {image_path}: {type(e).__name__}: {e}")

    if result["latitude"] is None:
        result["latitude"] = 0.0
        result["longitude"] = 0.0
        result["altitude"] = 0.0
        result["roll"] = 0.0
        result["pitch"] = 0.0
        result["yaw"] = 0.0
        result["has_telemetry"] = False

    """
    output result dictionary with keys:
    - latitude: float (degrees)
    - longitude: float (degrees)
    - altitude: float (meters)
    - roll: float (degrees)
    - pitch: float (degrees)
    - yaw: float (degrees)
    - has_telemetry: bool (True if GPS data was present, False otherwise)
    """
    return result

def build_data_matrix(metadata_list: List[Dict], origin: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """
    Build the Nx6 [X, Y, Z, Yaw, Pitch, Roll] pose matrix Combiner.Combiner expects.
    X/Y are local meters relative to `origin` (defaults to the first entry's lat/lon).
    Yaw/Pitch/Roll stay in DEGREES -- geometry.computeUnRotMatrix converts to
    radians itself; converting here would reintroduce the double-conversion bug.
    """
    if origin is None:
        origin_lat = metadata_list[0]["latitude"]
        origin_lon = metadata_list[0]["longitude"]
    else:
        origin_lat, origin_lon = origin

    data_matrix = np.zeros((len(metadata_list), 7), dtype=np.float64)
    for i, meta in enumerate(metadata_list):
        lat = meta["latitude"]
        lon = meta["longitude"]
        x = (lon - origin_lon) * 111320 * math.cos(math.radians(origin_lat))
        y = (lat - origin_lat) * 110540
        data_matrix[i, 0] = x
        data_matrix[i, 1] = y
        data_matrix[i, 2] = meta["altitude"]
        data_matrix[i, 3] = meta["yaw"]
        data_matrix[i, 4] = meta["pitch"]
        data_matrix[i, 5] = meta["roll"]
        data_matrix[i, 6] = 1.0  if meta["has_telemetry"] else 0.0
    return data_matrix


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two lat/lon points."""
    R = 6371000  # Earth radius, meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GPSDistanceFilter:
    """
    Redundancy filter: only accepts a new position if it's at least
    `threshold_m` away from the last ACCEPTED position. One instance
    per session -- sharing an instance across sessions/UAVs would compare
    positions from unrelated flights.
    """

    def __init__(self, threshold_m: float = 3.0):
        self.threshold_m = threshold_m
        self._last_lat: Optional[float] = None
        self._last_lon: Optional[float] = None

    def should_accept(self, lat: float, lon: float) -> Tuple[bool, float]:
        if self._last_lat is None:
            self._last_lat = lat
            self._last_lon = lon
            return True, 0.0

        dist = haversine_m(self._last_lat, self._last_lon, lat, lon)
        if dist >= self.threshold_m:
            self._last_lat = lat
            self._last_lon = lon
            return True, dist
        return False, dist

class AttitudeThresholdFilter:
    """
    Quality gate: rejects a frame if roll or pitch exceeds threshold_deg.
    Checked BEFORE GPSDistanceFilter in the admission pipeline -- swapping
    the order would let a tilt-rejected frame still mutate the GPS filter's
    reference position as a side effect.
    """

    def __init__(self, threshold_deg: float = 30.0):
        self.threshold_deg = threshold_deg

    def should_accept(self, roll_deg: float, pitch_deg: float) -> Tuple[bool, float]:
        worst = max(abs(roll_deg), abs(pitch_deg))
        return worst < self.threshold_deg, worst