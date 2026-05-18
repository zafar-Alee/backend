"""
Agent 1 — Signal Collector (Production-Ready)
================================================
Ingests raw crisis text, extracts location via Gemini, and calls mock API endpoints
to gather multi-source signals with credibility scores.

Pipeline position: FIRST — feeds into CrisisDetector (Agent 2).

Dependencies:
    - GeminiClient (utils/gemini_client.py)
    - AgentLogger  (utils/logger.py)
    - httpx        (async HTTP client)
"""

import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
import os

import httpx

from config import settings
from models.signal_models import AnalyzeRequest, Signal, SignalCollection, SignalSource
from utils.gemini_client import GeminiClient
from utils.logger import AgentLogger


# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_area(location: str) -> str:
    """Normalize location string to area code."""
    normalized = location.lower().replace("-", "").replace(",", "").strip().split()[0]
    return normalized


def _extract_city_for_weather(location: str) -> str:
    """Extract city name from location for weather API."""
    parts = location.split(",")
    if len(parts) > 1:
        return parts[1].strip()
    words = location.split()
    return words[-1] if words else location


def _get_mock_base_url() -> str:
    """Get mock API base URL from config."""
    host = os.getenv("HOST", settings.host)
    port = os.getenv("PORT", str(settings.port))
    return f"http://{host}:{port}"


def _now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.time() * 1000)


_MOCK_BASE_URL = _get_mock_base_url()


# ─────────────────────────────────────────────────────────────────────────────
# Signal Collector Class
# ─────────────────────────────────────────────────────────────────────────────

class SignalCollector:
    """Agent 1: Collects crisis signals from multiple sources."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        """Initialize with GeminiClient."""
        self.gemini = gemini_client

    async def collect(
        self,
        request: AnalyzeRequest,
        logger: AgentLogger,
    ) -> SignalCollection:
        """
        Collect signals from all available sources.
        
        Wraps collection with timeout to prevent hanging.
        """
        try:
            return await asyncio.wait_for(
                self._do_collect(request, logger),
                timeout=settings.signal_collection_timeout
            )
        except asyncio.TimeoutError:
            logger.log_agent_step(
                agent_name="agent_1_signal_collector",
                step="Signal Collection",
                input_data=request.text,
                output_data="TIMEOUT - Fallback to user signal only",
                duration_ms=settings.signal_collection_timeout * 1000,
                extra_data={"error": "Signal collection exceeded timeout"},
            )
            # Return minimal collection with user signal only
            return SignalCollection(
                signals=[Signal(
                    source=SignalSource.SOCIAL_MEDIA,
                    text=request.text,
                    credibility=0.65,
                    timestamp=datetime.now(timezone.utc),
                    location=request.location or "unknown",
                    metadata={"origin": "timeout_fallback"},
                )],
                area=request.location or "unknown",
                total_count=1,
                collection_time_ms=settings.signal_collection_timeout * 1000,
            )

    async def _do_collect(
        self,
        request: AnalyzeRequest,
        logger: AgentLogger,
    ) -> SignalCollection:
        """Internal collect method."""
        start_ms = _now_ms()
        signals: list[Signal] = []
        sources_checked: list[str] = []
        errors: list[str] = []
        weather_api_failed = False

        # Extract location
        detected_location = request.location or "islamabad"
        area_code = _normalize_area(detected_location)

        # Add user's signal
        signals.append(Signal(
            source=SignalSource.SOCIAL_MEDIA,
            text=request.text,
            credibility=0.65,
            timestamp=datetime.now(timezone.utc),
            location=detected_location,
            metadata={"origin": "user_input"},
        ))

        # Collect from APIs
        if request.include_mock_signals:
            try:
                async with httpx.AsyncClient(
                    base_url=_MOCK_BASE_URL,
                    timeout=float(settings.http_client_timeout),
                ) as client:
                    # Weather
                    try:
                        weather_resp = await client.get(
                            f"{_MOCK_BASE_URL}/mock/weather",
                            params={"city": _extract_city_for_weather(detected_location)}
                        )
                        if weather_resp.status_code == 200:
                            weather_data = weather_resp.json()
                            signals.append(Signal(
                                source=SignalSource.WEATHER_API,
                                text=f"Weather: {weather_data.get('condition', 'UNKNOWN')}",
                                credibility=0.85,
                                timestamp=datetime.now(timezone.utc),
                                location=detected_location,
                                metadata=weather_data,
                            ))
                    except Exception as e:
                        weather_api_failed = True
                        errors.append(f"Weather API failed: {e}")
                    
                    sources_checked.append("weather")

                    # Traffic
                    try:
                        traffic_resp = await client.get(
                            f"{_MOCK_BASE_URL}/mock/traffic",
                            params={"area": area_code}
                        )
                        if traffic_resp.status_code == 200:
                            traffic_data = traffic_resp.json()
                            signals.append(Signal(
                                source=SignalSource.TRAFFIC_API,
                                text=f"Traffic: congestion level {traffic_data.get('congestion_level', 0)}/10",
                                credibility=0.80,
                                timestamp=datetime.now(timezone.utc),
                                location=detected_location,
                                metadata=traffic_data,
                            ))
                    except Exception as e:
                        errors.append(f"Traffic API failed: {e}")
                    
                    sources_checked.append("traffic")

                    # Sensors
                    try:
                        sensor_resp = await client.get(
                            f"{_MOCK_BASE_URL}/mock/sensors",
                            params={"area": area_code}
                        )
                        if sensor_resp.status_code == 200:
                            sensor_data = sensor_resp.json()
                            signals.append(Signal(
                                source=SignalSource.SENSOR,
                                text=f"Sensors: water level {sensor_data.get('water_level_cm', 0)}cm",
                                credibility=0.88,
                                timestamp=datetime.now(timezone.utc),
                                location=detected_location,
                                metadata=sensor_data,
                            ))
                    except Exception as e:
                        errors.append(f"Sensor API failed: {e}")
                    
                    sources_checked.append("sensors")

            except Exception as e:
                errors.append(f"API collection failed: {e}")

        # Calculate weighted score
        weighted_score = round(
            sum(s.credibility for s in signals) / len(signals), 2
        ) if signals else 0.0

        # Log and return
        elapsed_ms = _now_ms() - start_ms
        
        logger.log_agent_step(
            agent_name="agent_1_signal_collector",
            step="Signal Collection",
            input_data=request.text,
            output_data=f"{len(signals)} signals collected",
            duration_ms=elapsed_ms,
            extra_data={
                "sources_checked": sources_checked,
                "signals_found": len(signals),
                "credibility_score": weighted_score,
                "errors": errors if errors else None,
            },
        )

        return SignalCollection(
            signals=signals,
            area=detected_location,
            total_count=len(signals),
            collection_time_ms=elapsed_ms,
        )
