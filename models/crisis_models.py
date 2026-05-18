"""
Crisis Models
===============
Pydantic v2 models for crisis detection and analysis outputs —
crisis type classification, severity levels, confidence scores,
and full situation reports.

Used by:
- Agent 2 (CrisisDetector) — output
- Agent 3 (SituationAnalyzer) — input/output
- POST /analyze — response body (nested)
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class CrisisType(str, Enum):
    """
    Classification of urban crisis types detected by the system.
    FALSE_ALARM is used when the system determines no real crisis exists
    (e.g., Scenario C — broken water main mistaken for a flood).
    """

    URBAN_FLOODING = "URBAN_FLOODING"
    HEATWAVE = "HEATWAVE"
    ROAD_ACCIDENT = "ROAD_ACCIDENT"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    POWER_OUTAGE = "POWER_OUTAGE"
    FALSE_ALARM = "FALSE_ALARM"


class SeverityLevel(str, Enum):
    """
    Severity grading for a detected crisis.
    Determines resource allocation priority and escalation paths.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Crisis Classification (Agent 2 + Agent 3 Output)
# ---------------------------------------------------------------------------
class CrisisClassification(BaseModel):
    """
    Full crisis classification and situation analysis result.
    Combines output from the Crisis Detector (Agent 2) and
    Situation Analyzer (Agent 3).

    Attributes:
        type: Classified crisis type.
        location: Geographic area of the crisis.
        severity: Severity grading (LOW → CRITICAL).
        confidence: Model confidence in the classification (0.0 to 1.0).
        affected_population: Estimated number of people affected.
        affected_radius_km: Estimated geographic radius of impact.
        expected_duration_hours: Predicted duration of the crisis.
        reasoning: Explanation of why this classification was made.
        conflicting_signals: Whether contradictory signals were detected.
    """

    type: CrisisType = Field(
        ...,
        description="Classified crisis type",
    )
    location: str = Field(
        ...,
        min_length=1,
        description="Geographic area of the crisis",
    )
    severity: SeverityLevel = Field(
        ...,
        description="Severity grading (LOW, MEDIUM, HIGH, CRITICAL)",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence in the classification (0.0 to 1.0)",
    )
    affected_population: int = Field(
        default=0,
        ge=0,
        description="Estimated number of people affected",
    )
    affected_radius_km: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated geographic radius of impact in kilometers",
    )
    expected_duration_hours: float = Field(
        default=0.0,
        ge=0.0,
        description="Predicted duration of the crisis in hours",
    )
    reasoning: str = Field(
        default="",
        description="Explanation of why this classification was made",
    )
    conflicting_signals: bool = Field(
        default=False,
        description="Whether contradictory signals were detected",
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Round confidence to 2 decimal places for consistency."""
        return round(v, 2)

    @field_validator("affected_radius_km")
    @classmethod
    def validate_radius(cls, v: float) -> float:
        """Round radius to 1 decimal place."""
        return round(v, 1)

    @field_validator("expected_duration_hours")
    @classmethod
    def validate_duration(cls, v: float) -> float:
        """Round duration to 1 decimal place."""
        return round(v, 1)
