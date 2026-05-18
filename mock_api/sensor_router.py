from datetime import datetime, timezone
from fastapi import APIRouter, Query

router = APIRouter()

@router.get("/sensors", summary="Get mock sensor data")
async def get_sensors(area: str = Query("g10", description="Area code")):
    """
    Returns mock sensor data based on area.
    g10 -> water_level=45 (flood threshold=30), temp=normal
    f8 -> water_level=5 (normal), temp=42 (heatwave threshold=40)
    else -> normal water, normal temp
    """
    area_lower = area.lower()
    timestamp = datetime.now(timezone.utc).isoformat()
    
    if "g10" in area_lower or "g-10" in area_lower:
        return {
            "area": area,
            "water_level_cm": 45,
            "temperature_celsius": 26,
            "humidity_percent": 85,
            "flood_threshold_cm": 30,
            "heatwave_threshold_celsius": 40,
            "timestamp": timestamp,
            "source": "City Sensor Network (Mock)"
        }
    elif "f8" in area_lower or "f-8" in area_lower:
        return {
            "area": area,
            "water_level_cm": 5,
            "temperature_celsius": 42,
            "humidity_percent": 30,
            "flood_threshold_cm": 30,
            "heatwave_threshold_celsius": 40,
            "timestamp": timestamp,
            "source": "City Sensor Network (Mock)"
        }
    else:
        return {
            "area": area,
            "water_level_cm": 2,
            "temperature_celsius": 28,
            "humidity_percent": 45,
            "flood_threshold_cm": 30,
            "heatwave_threshold_celsius": 40,
            "timestamp": timestamp,
            "source": "City Sensor Network (Mock)"
        }
