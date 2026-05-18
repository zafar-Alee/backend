"""
Signal Models
===============
Pydantic v2 models for input data shapes — raw signals from
weather, traffic, social media, sensors, and field reports.

Used by:
- Agent 1 (SignalCollector) — output
- Agent 2 (CrisisDetector) — input
- POST /analyze — request body
"""

from enum import Enum
from typing import Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SignalSource(str, Enum):
    """Enumeration of all data sources that can produce crisis signals."""

    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    WEATHER_API = "WEATHER_API"
    TRAFFIC_API = "TRAFFIC_API"
    SENSOR = "SENSOR"
    FIELD_REPORT = "FIELD_REPORT"


# ---------------------------------------------------------------------------
# Core Signal Model
# ---------------------------------------------------------------------------
class Signal(BaseModel):
    """
    A single crisis signal collected from any source.

    Attributes:
        source: Origin of the signal (social media, weather API, etc.)
        text: Raw text or description of the signal.
        credibility: Confidence in the signal's reliability (0.0 to 1.0).
        timestamp: When the signal was generated or received.
        location: Geographic area or address the signal refers to.
        metadata: Additional key-value data specific to the source.
    """

    source: SignalSource = Field(
        ...,
        description="Origin of the signal",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Raw text or description of the signal",
    )
    credibility: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in signal reliability (0.0 to 1.0)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the signal was generated or received",
    )
    location: Optional[str] = Field(
        default=None,
        description="Geographic area or address the signal refers to",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional source-specific key-value data",
    )

    @field_validator("credibility")
    @classmethod
    def validate_credibility(cls, v: float) -> float:
        """Ensure credibility is rounded to 2 decimal places."""
        return round(v, 2)

    @field_validator("text")
    @classmethod
    def validate_text_not_empty(cls, v: str) -> str:
        """Strip whitespace and ensure text is not blank."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Signal text cannot be empty or whitespace-only")
        return stripped


# ---------------------------------------------------------------------------
# Signal Collection (Agent 1 Output)
# ---------------------------------------------------------------------------
class SignalCollection(BaseModel):
    """
    Aggregated output from the Signal Collector agent.
    Contains all signals gathered from multiple sources for an area.

    Attributes:
        signals: List of individual signals collected.
        area: The geographic area being analyzed.
        total_count: Total number of signals in the collection.
        collection_time_ms: Time taken to collect all signals (milliseconds).
    """

    signals: list[Signal] = Field(
        default_factory=list,
        description="List of individual signals collected",
    )
    area: str = Field(
        ...,
        min_length=1,
        description="The geographic area being analyzed",
    )
    total_count: int = Field(
        default=0,
        ge=0,
        description="Total number of signals in the collection",
    )
    collection_time_ms: int = Field(
        default=0,
        ge=0,
        description="Time taken to collect all signals (milliseconds)",
    )

    @field_validator("total_count", mode="before")
    @classmethod
    def auto_count(cls, v, info):
        """If total_count is 0 or not set, derive from signals list length."""
        # Allow explicit override; auto-count handled in model_post_init
        return v

    def model_post_init(self, __context) -> None:
        """Auto-set total_count from signals list if not explicitly provided."""
        if self.total_count == 0 and self.signals:
            self.total_count = len(self.signals)


# ---------------------------------------------------------------------------
# Analyze Request (Flutter → Backend)
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    """
    Request body for the POST /analyze endpoint.
    Sent by the Flutter app to trigger the full agent pipeline.

    Attributes:
        text: Raw crisis report text (can be Roman Urdu or English).
        location: Optional explicit location. If omitted, Agent 1 extracts it.
        include_mock_signals: Whether to call mock API endpoints for signals.
        scenario: Optional scenario hint for demo purposes (flood, heatwave, etc.)
    """

    text: str = Field(
        ...,
        min_length=3,
        description="Raw crisis report text (Roman Urdu or English)",
        examples=["G-10 mein pani bhar gaya, gaariyan phans gayi hain"],
    )
    location: Optional[str] = Field(
        default=None,
        description="Explicit location. If omitted, extracted by Agent 1",
        examples=["G-10, Islamabad"],
    )
    include_mock_signals: bool = Field(
        default=True,
        description="Whether to call mock API endpoints for additional signals",
    )
    scenario: Optional[str] = Field(
        default=None,
        description="Scenario hint for demo: 'flood', 'heatwave', 'false_positive'",
        examples=["flood", "heatwave", "false_positive"],
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Strip whitespace and ensure meaningful input."""
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError(
                "Crisis report text must be at least 3 characters long"
            )
        return stripped
