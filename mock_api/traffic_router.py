from datetime import datetime, timezone
from fastapi import APIRouter, Query

router = APIRouter()

@router.get("/traffic", summary="Get mock traffic data")
async def get_traffic(area: str = Query("g10", description="Area code")):
    """
    Returns mock traffic congestion data based on area.
    g10 -> high congestion
    f8 -> medium congestion
    else -> normal
    """
    area_lower = area.lower()
    timestamp = datetime.now(timezone.utc).isoformat()
    
    if "g10" in area_lower or "g-10" in area_lower:
        return {
            "area": area,
            "congestion_level": 9,
            "blocked_routes": ["Main Margalla Road", "G-10 Markaz Underpass"],
            "normal_congestion": 3,
            "anomaly_detected": True,
            "credibility": 0.90,
            "source": "Google Maps Traffic API (Mock)",
            "timestamp": timestamp
        }
    elif "f8" in area_lower or "f-8" in area_lower:
        return {
            "area": area,
            "congestion_level": 6,
            "blocked_routes": ["F-8 Markaz Road"],
            "normal_congestion": 4,
            "anomaly_detected": True,
            "credibility": 0.85,
            "source": "Google Maps Traffic API (Mock)",
            "timestamp": timestamp
        }
    else:
        return {
            "area": area,
            "congestion_level": 2,
            "blocked_routes": [],
            "normal_congestion": 2,
            "anomaly_detected": False,
            "credibility": 0.90,
            "source": "Google Maps Traffic API (Mock)",
            "timestamp": timestamp
        }
