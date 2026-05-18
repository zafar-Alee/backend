"""
Agent 2 — Crisis Detector
============================
Cross-references collected signals, applies credibility-weighted scoring,
classifies the crisis type, and calculates a confidence score.

Pipeline position: SECOND — receives from SignalCollector (Agent 1),
feeds into SituationAnalyzer (Agent 3).

Dependencies:
    - GeminiClient (utils/gemini_client.py)
    - AgentLogger  (utils/logger.py)
    - httpx        (for checking field reports)
"""

import json
import os
import time
from typing import Any

import httpx

from models.signal_models import Signal, SignalCollection
from models.crisis_models import CrisisClassification, CrisisType, SeverityLevel
from utils.gemini_client import GeminiClient
from utils.logger import AgentLogger


# Base URL for mock endpoints (same server)
_MOCK_BASE_URL = f"http://localhost:{os.getenv('PORT', '8000')}"

# ---------------------------------------------------------------------------
# Keyword → CrisisType mapping
# ---------------------------------------------------------------------------
_CRISIS_KEYWORDS: dict[CrisisType, list[str]] = {
    CrisisType.URBAN_FLOODING: [
        "flood", "flooding", "pani", "baarish", "barish", "rain",
        "water level", "waterlogging", "bhar gaya", "doob",
    ],
    CrisisType.HEATWAVE: [
        "heat", "heatwave", "garmi", "temperature", "heatstroke",
        "behosh", "loo", "sunstroke", "hot",
    ],
    CrisisType.ROAD_ACCIDENT: [
        "accident", "hadsa", "crash", "collision", "overturned",
        "takkar", "injured", "zakhmi",
    ],
    CrisisType.INFRASTRUCTURE_FAILURE: [
        "water main", "pipe", "burst", "infrastructure", "broken",
        "collapse", "toot", "sewage", "gas leak",
    ],
    CrisisType.POWER_OUTAGE: [
        "power", "bijli", "blackout", "outage", "electricity",
        "load shedding", "transformer",
    ],
}


class CrisisDetector:
    """
    Agent 2: Detects and classifies crises from collected signals.

    Takes a SignalCollection from Agent 1, cross-references signals
    using keyword matching and credibility weighting, calls Gemini for
    classification, computes a confidence score, and checks for
    conflicting signals (false positive detection).
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        """
        Initialize the Crisis Detector.

        Args:
            gemini_client: Shared GeminiClient instance for classification.
        """
        self.gemini = gemini_client

    async def detect(
        self,
        signals: SignalCollection,
        logger: AgentLogger,
    ) -> CrisisClassification:
        """
        Detect and classify a crisis from collected signals.

        Steps:
            1. Keyword-based crisis type scoring
            2. Gemini-based classification
            3. Confidence calculation (multi-factor formula)
            4. Field report conflict check
            5. Edge case: low confidence handling
            6. Log and return

        Args:
            signals: SignalCollection from Agent 1.
            logger: AgentLogger instance for this pipeline run.

        Returns:
            CrisisClassification with type, confidence, severity, and reasoning.
        """
        start_ms = _now_ms()

        # ------------------------------------------------------------------
        # Step 1: Keyword-based source credibility analysis
        # ------------------------------------------------------------------
        all_text = " ".join(s.text.lower() for s in signals.signals)
        type_scores: dict[CrisisType, float] = {}

        for crisis_type, keywords in _CRISIS_KEYWORDS.items():
            score = 0.0
            matching_signals = 0
            for signal in signals.signals:
                sig_text = signal.text.lower()
                # Check if any keyword matches this signal
                if any(kw in sig_text for kw in keywords):
                    # Weight by credibility — official sources count more
                    score += signal.credibility
                    matching_signals += 1
            if matching_signals > 0:
                type_scores[crisis_type] = score

        # Determine best keyword-matched crisis type
        if type_scores:
            keyword_crisis_type = max(type_scores, key=type_scores.get)
            keyword_score = type_scores[keyword_crisis_type]
        else:
            keyword_crisis_type = CrisisType.FALSE_ALARM
            keyword_score = 0.0

        # ------------------------------------------------------------------
        # Step 2: Gemini-based classification
        # ------------------------------------------------------------------
        gemini_result = self._classify_with_gemini(signals)

        gemini_crisis_type_str = gemini_result.get("crisis_type", "")
        gemini_confidence = float(gemini_result.get("confidence", 0.5))
        gemini_severity = gemini_result.get("severity_hint", "MEDIUM")
        gemini_reasoning = gemini_result.get("reasoning", "")

        # Try to map Gemini's crisis type string to enum
        gemini_crisis_type = _parse_crisis_type(gemini_crisis_type_str)

        # Prioritize Gemini's classification. If Gemini failed or is FALSE_ALARM, 
        # fallback to the keyword-based classification (unless keyword is also FALSE_ALARM).
        if gemini_crisis_type and gemini_crisis_type != CrisisType.FALSE_ALARM:
            detected_type = gemini_crisis_type
        else:
            detected_type = keyword_crisis_type

        # ------------------------------------------------------------------
        # Step 3: Confidence calculation (multi-factor formula)
        # ------------------------------------------------------------------
        total_sources = max(len(signals.signals), 1)
        matching_sources = sum(
            1 for s in signals.signals
            if any(kw in s.text.lower() for kw in _CRISIS_KEYWORDS.get(detected_type, []))
        )

        avg_credibility = (
            sum(s.credibility for s in signals.signals) / total_sources
            if signals.signals else 0.0
        )

        base_confidence = (matching_sources / total_sources) * 0.5
        credibility_bonus = avg_credibility * 0.2
        gemini_bonus = gemini_confidence * 0.3

        final_confidence = round(
            min(base_confidence + credibility_bonus + gemini_bonus, 1.0), 2
        )

        # ------------------------------------------------------------------
        # Step 4: Check for conflicting signals (field reports)
        # ------------------------------------------------------------------
        conflicting_signals = False
        conflict_reason = ""

        try:
            field_reports = await _fetch_field_reports(signals.area)
            if field_reports:
                for report in field_reports:
                    if report.get("is_false_alarm", False):
                        conflicting_signals = True
                        conflict_reason = report.get("report", "Field report contradicts crisis")
                        # Lower confidence
                        final_confidence = round(max(final_confidence - 0.25, 0.0), 2)
                        # Reclassify to infrastructure failure if confidence < 0.5
                        if final_confidence < 0.5:
                            detected_type = CrisisType.INFRASTRUCTURE_FAILURE
                        break
        except Exception as e:
            # Field report check is optional — don't crash
            print(f"[CrisisDetector] Field report check failed: {e}")

        # ------------------------------------------------------------------
        # Step 5: Build reasoning
        # ------------------------------------------------------------------
        reasoning_parts = []

        if gemini_reasoning:
            reasoning_parts.append(gemini_reasoning)
        else:
            reasoning_parts.append(
                f"{matching_sources}/{total_sources} sources confirm "
                f"{detected_type.value.lower().replace('_', ' ')} pattern."
            )

        if conflicting_signals:
            reasoning_parts.append(
                f"CONFLICT: Field report contradicts — '{conflict_reason}'. "
                f"Confidence reduced by 0.25."
            )

        # ------------------------------------------------------------------
        # Step 6: Edge case — low confidence
        # ------------------------------------------------------------------
        severity = _parse_severity(gemini_severity)

        if final_confidence < 0.4:
            severity = SeverityLevel.LOW
            reasoning_parts.append(
                "Low confidence — verification recommended."
            )

        reasoning = " ".join(reasoning_parts)

        # ------------------------------------------------------------------
        # Step 7: Build result
        # ------------------------------------------------------------------
        elapsed_ms = _now_ms() - start_ms

        classification = CrisisClassification(
            type=detected_type,
            location=signals.area,
            severity=severity,
            confidence=final_confidence,
            affected_population=0,       # Agent 3 fills this
            affected_radius_km=0.0,      # Agent 3 fills this
            expected_duration_hours=0.0,  # Agent 3 fills this
            reasoning=reasoning,
            conflicting_signals=conflicting_signals,
        )

        # ------------------------------------------------------------------
        # Step 8: Log agent step
        # ------------------------------------------------------------------
        logger.log_agent_step(
            agent_name="agent_2_crisis_detector",
            step="Crisis Detection",
            input_data=f"{len(signals.signals)} signals from {signals.area}",
            output_data=(
                f"{detected_type.value} detected with {final_confidence} confidence"
            ),
            duration_ms=elapsed_ms,
            extra_data={
                "signals_analyzed": len(signals.signals),
                "confidence_score": final_confidence,
                "crisis_type": detected_type.value,
                "severity": severity.value,
                "conflicting_signals": conflicting_signals,
                "reasoning": reasoning,
                "keyword_scores": {k.value: round(v, 2) for k, v in type_scores.items()},
                "gemini_classification": gemini_result,
            },
        )

        return classification

    # ------------------------------------------------------------------
    # Private: Gemini Classification
    # ------------------------------------------------------------------

    def _classify_with_gemini(self, signals: SignalCollection) -> dict:
        """
        Use Gemini to classify the crisis from all signal texts.

        Args:
            signals: The full signal collection.

        Returns:
            Dict with crisis_type, confidence, severity_hint, reasoning.
        """
        # Build signal summary for the prompt
        signal_lines = []
        for i, sig in enumerate(signals.signals, 1):
            signal_lines.append(
                f"  {i}. [{sig.source.value}] (credibility={sig.credibility}): {sig.text}"
            )
        signals_text = "\n".join(signal_lines)

        system_instruction = (
            "You are a crisis classification AI for Pakistani urban areas. "
            "You analyze multiple data signals to determine if a crisis is occurring, "
            "its type, and confidence level. You understand Roman Urdu, English, and Urdu."
        )

        prompt = f"""Analyze these {len(signals.signals)} signals from {signals.area} and classify the crisis.

SIGNALS:
{signals_text}

Based on these signals, determine:
1. What type of crisis is occurring?
2. How confident are you (0.0 to 1.0)?
3. What is the severity hint?
4. What is your reasoning?

Return ONLY a valid JSON object:
{{
    "crisis_type": "one of: URBAN_FLOODING, HEATWAVE, ROAD_ACCIDENT, INFRASTRUCTURE_FAILURE, POWER_OUTAGE, FALSE_ALARM",
    "confidence": 0.91,
    "severity_hint": "one of: LOW, MEDIUM, HIGH, CRITICAL",
    "reasoning": "explanation of classification",
    "affected_area_description": "brief description of affected area"
}}

Return ONLY the JSON object, no markdown, no explanation."""

        try:
            response_text = self.gemini.analyze_text(prompt, system_instruction)
            return self.gemini._parse_json_response(response_text)
        except Exception as e:
            print(f"[CrisisDetector] Gemini classification failed: {e}. Using Keyword Heuristic Fallback.")
            return {}


# ===========================================================================
# Module-level helpers
# ===========================================================================

async def _fetch_field_reports(area: str) -> list[dict]:
    """Fetch mock field reports for the specified area."""
    try:
        async with httpx.AsyncClient(
            base_url=_MOCK_BASE_URL, timeout=5.0
        ) as client:
            resp = await client.get(f"/mock/field-report?area={area}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("reports", [])
    except Exception:
        return []


def _parse_crisis_type(type_str: str) -> CrisisType | None:
    """
    Parse a crisis type string into a CrisisType enum.

    Args:
        type_str: String like 'URBAN_FLOODING' or 'urban flooding'.

    Returns:
        CrisisType enum member or None if not recognized.
    """
    if not type_str:
        return None

    normalized = type_str.upper().strip().replace(" ", "_")
    try:
        return CrisisType(normalized)
    except ValueError:
        return None


def _parse_crisis_type_from_text(text: str) -> CrisisType | None:
    """
    Infer a crisis type from free-form text (e.g., a field report).

    Args:
        text: Free-form text to analyze.

    Returns:
        Best-matching CrisisType or None.
    """
    text_lower = text.lower()
    for crisis_type, keywords in _CRISIS_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return crisis_type
    return None


def _parse_severity(severity_str: str) -> SeverityLevel:
    """
    Parse a severity string into a SeverityLevel enum.

    Args:
        severity_str: String like 'HIGH' or 'high'.

    Returns:
        SeverityLevel enum member. Defaults to MEDIUM.
    """
    if not severity_str:
        return SeverityLevel.MEDIUM

    normalized = severity_str.upper().strip()
    try:
        return SeverityLevel(normalized)
    except ValueError:
        return SeverityLevel.MEDIUM


def _normalize_for_match(area: str) -> str:
    """
    Normalize an area string for fuzzy matching.

    Strips dashes, spaces, commas so that 'g10', 'G-10', and
    'G-10, Islamabad' all contain the common substring 'g10'.

    Args:
        area: Raw area string.

    Returns:
        Lowercased string with special chars removed.
    """
    return area.lower().replace("-", "").replace(" ", "").replace(",", "")


def _now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.time() * 1000)
