from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Query

router = APIRouter()

# In-memory store for false positive scenario
_FIELD_REPORTS = []

class FieldReportInput(BaseModel):
    area: str
    report: str
    is_false_alarm: bool

@router.get("/social", summary="Get mock social media signals")
async def get_social(area: str = Query("g10", description="Area code")):
    """
    Returns mock social signals based on area.
    g10 -> 3 flood signals
    f8 -> 2 heatwave signals
    else -> 1 generic signal
    """
    area_lower = area.lower()
    timestamp = datetime.now(timezone.utc).isoformat()
    
    if "g10" in area_lower or "g-10" in area_lower:
        return {
            "area": area,
            "signals": [
                {
                    "text": "G-10 mein pani bhar gaya gaariyan phans gayi hain",
                    "language": "roman_urdu",
                    "timestamp": timestamp,
                    "credibility": 0.72,
                    "mention_velocity": 8
                },
                {
                    "text": "Flooding on main margalla road avoid if possible",
                    "language": "english",
                    "timestamp": timestamp,
                    "credibility": 0.65,
                    "mention_velocity": 5
                },
                {
                    "text": "Road blocked after heavy rain near G-10/4",
                    "language": "english",
                    "timestamp": timestamp,
                    "credibility": 0.60,
                    "mention_velocity": 6
                }
            ],
            "total_mentions": 19,
            "dominant_keyword": "flood",
            "source": "Twitter/X Mock Feed"
        }
    elif "f8" in area_lower or "f-8" in area_lower:
        return {
            "area": area,
            "signals": [
                {
                    "text": "F-8 mein bohat garmi hai, log behosh ho rahe hain",
                    "language": "roman_urdu",
                    "timestamp": timestamp,
                    "credibility": 0.70,
                    "mention_velocity": 6
                },
                {
                    "text": "Heatstroke cases reported near F-8 Markaz",
                    "language": "english",
                    "timestamp": timestamp,
                    "credibility": 0.68,
                    "mention_velocity": 4
                }
            ],
            "total_mentions": 12,
            "dominant_keyword": "heatwave",
            "source": "Twitter/X Mock Feed"
        }
    else:
        return {
            "area": area,
            "signals": [
                {
                    "text": "Traffic is moving slow today.",
                    "language": "english",
                    "timestamp": timestamp,
                    "credibility": 0.50,
                    "mention_velocity": 1
                }
            ],
            "total_mentions": 1,
            "dominant_keyword": "traffic",
            "source": "Twitter/X Mock Feed"
        }

@router.post("/field-report", summary="Inject a mock field report")
async def post_field_report(report: FieldReportInput):
    """
    Accepts a field report (useful for triggering false positive scenario).
    Stores it in a temporary in-memory list.
    """
    report_dict = report.model_dump()
    report_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    _FIELD_REPORTS.append(report_dict)
    
    return {
        "status": "success",
        "message": "Field report accepted",
        "data": report_dict
    }

@router.get("/field-report", summary="Get injected field reports")
@router.get("/field-reports", summary="Get injected field reports (alias)", deprecated=True)
async def get_field_reports(area: Optional[str] = Query(None, description="Filter by area")):
    """Retrieve the injected field reports for agents to check, optionally filtered by area."""
    if not area:
        return {"reports": _FIELD_REPORTS}
        
    area_lower = area.lower()
    filtered_reports = [
        r for r in _FIELD_REPORTS 
        if area_lower in r.get("area", "").lower() or r.get("area", "").lower() in area_lower
    ]
    return {"reports": filtered_reports}
