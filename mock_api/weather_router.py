from datetime import datetime, timezone
from fastapi import APIRouter, Query

router = APIRouter()

@router.get("/weather", summary="Get mock weather data")
async def get_weather(city: str = Query("islamabad", description="City name")):
    """
    Returns mock weather data based on the city.
    If city contains 'islamabad', 'g10', or 'g-10', returns heavy rain data.
    Otherwise, returns normal weather data.
    """
    import os
    from fastapi import HTTPException
    
    if os.getenv("SIMULATE_WEATHER_FAILURE", "False").lower() in ("true", "1", "yes"):
        raise HTTPException(status_code=503, detail="Weather API unavailable")

    city_lower = city.lower()
    timestamp = datetime.now(timezone.utc).isoformat()
    
    if "islamabad" in city_lower or "g10" in city_lower or "g-10" in city_lower:
        return {
            "city": city,
            "condition": "HEAVY_RAIN",
            "rainfall_mm_per_hour": 45,
            "alert_level": "HIGH",
            "credibility": 0.95,
            "source": "Pakistan Meteorological Department (Mock)",
            "timestamp": timestamp
        }
    else:
        return {
            "city": city,
            "condition": "CLEAR",
            "rainfall_mm_per_hour": 0,
            "alert_level": "LOW",
            "credibility": 0.95,
            "source": "Pakistan Meteorological Department (Mock)",
            "timestamp": timestamp
        }
