"""
Agent 3 — Situation Analyzer
===============================
Enriches a CrisisClassification with detailed situation analysis:
affected population, geographic radius, expected duration, and
full reasoning — powered by Gemini LLM.

Pipeline position: THIRD — receives from CrisisDetector (Agent 2),
feeds into ActionPlanner (Agent 4).

Dependencies:
    - GeminiClient (utils/gemini_client.py)
    - AgentLogger  (utils/logger.py)
"""

import time
from typing import Any

from models.signal_models import SignalCollection
from models.crisis_models import CrisisClassification, CrisisType, SeverityLevel
from utils.gemini_client import GeminiClient
from utils.logger import AgentLogger


# ---------------------------------------------------------------------------
# Pakistani city context data (hardcoded for demo scenarios)
# ---------------------------------------------------------------------------
_AREA_CONTEXT: dict[str, dict[str, Any]] = {
    "g10": {
        "full_name": "G-10, Islamabad",
        "population_density": 8000,
        "vulnerable_zones": ["G-10/1", "G-10/4"],
        "nearby_hospitals": ["PIMS Hospital", "Shifa International"],
        "key_roads": ["Main Margalla Road", "G-10 Markaz Underpass"],
        "drainage_quality": "poor",
    },
    "f8": {
        "full_name": "F-8, Islamabad",
        "population_density": 12000,
        "vulnerable_zones": ["F-8 Markaz", "F-8/3"],
        "nearby_hospitals": ["PIMS Hospital", "Ali Medical Centre"],
        "key_roads": ["F-8 Markaz Road", "Faisal Avenue"],
        "drainage_quality": "moderate",
    },
    "i8": {
        "full_name": "I-8, Islamabad",
        "population_density": 6000,
        "vulnerable_zones": ["I-8 Markaz"],
        "nearby_hospitals": ["Quaid-e-Azam International Hospital"],
        "key_roads": ["I-8 Main Road"],
        "drainage_quality": "good",
    },
}

# ---------------------------------------------------------------------------
# Default estimates per crisis type (fallback when Gemini is unavailable)
# ---------------------------------------------------------------------------
_DEFAULTS: dict[CrisisType, dict[str, Any]] = {
    CrisisType.URBAN_FLOODING: {
        "affected_population": 10000,
        "affected_radius_km": 2.0,
        "expected_duration_hours": 4,
        "severity": "HIGH",
        "reasoning": (
            "Urban flooding in a densely populated sector with poor drainage. "
            "Multiple sources confirm waterlogging. Peak hour traffic multiplies impact."
        ),
    },
    CrisisType.HEATWAVE: {
        "affected_population": 50000,
        "affected_radius_km": 5.0,
        "expected_duration_hours": 8,
        "severity": "HIGH",
        "reasoning": (
            "Heatwave affecting a wide urban area. Vulnerable populations "
            "(elderly, outdoor workers) at high risk of heatstroke."
        ),
    },
    CrisisType.ROAD_ACCIDENT: {
        "affected_population": 500,
        "affected_radius_km": 0.5,
        "expected_duration_hours": 2,
        "severity": "MEDIUM",
        "reasoning": "Road accident causing localized traffic disruption and potential casualties.",
    },
    CrisisType.INFRASTRUCTURE_FAILURE: {
        "affected_population": 5000,
        "affected_radius_km": 1.0,
        "expected_duration_hours": 6,
        "severity": "MEDIUM",
        "reasoning": "Infrastructure failure (water main/pipe burst) affecting local water supply.",
    },
    CrisisType.POWER_OUTAGE: {
        "affected_population": 20000,
        "affected_radius_km": 3.0,
        "expected_duration_hours": 5,
        "severity": "MEDIUM",
        "reasoning": "Power outage affecting residential and commercial areas.",
    },
    CrisisType.FALSE_ALARM: {
        "affected_population": 0,
        "affected_radius_km": 0.0,
        "expected_duration_hours": 0,
        "severity": "LOW",
        "reasoning": "Signals do not confirm a genuine crisis. Likely a false alarm.",
    },
}


class SituationAnalyzer:
    """
    Agent 3: Enriches crisis classification with detailed situation analysis.

    Uses Gemini to estimate affected population, geographic radius,
    expected duration, and provides detailed reasoning. Falls back
    to sensible defaults per crisis type if Gemini is unavailable.
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        """
        Initialize the Situation Analyzer.

        Args:
            gemini_client: Shared GeminiClient instance for analysis.
        """
        self.gemini = gemini_client

    async def analyze(
        self,
        crisis: CrisisClassification,
        signals: SignalCollection,
        logger: AgentLogger,
    ) -> CrisisClassification:
        """
        Perform detailed situation analysis and enrich the crisis classification.

        Steps:
            1. Gather area context data
            2. Build and send Gemini prompt
            3. Parse response with validation
            4. Adjust population based on area density
            5. Determine final severity
            6. Log and return enriched classification

        Args:
            crisis: CrisisClassification from Agent 2.
            signals: SignalCollection from Agent 1 (for context).
            logger: AgentLogger instance for this pipeline run.

        Returns:
            Enriched CrisisClassification with population, radius,
            duration, and reasoning filled in.
        """
        start_ms = _now_ms()

        # ------------------------------------------------------------------
        # Step 1: Get area context
        # ------------------------------------------------------------------
        area_key = _normalize_area(crisis.location)
        area_ctx = _AREA_CONTEXT.get(area_key, {})

        # ------------------------------------------------------------------
        # Step 2: Call Gemini for detailed analysis
        # ------------------------------------------------------------------
        gemini_analysis = self._analyze_with_gemini(crisis, signals, area_ctx)

        # ------------------------------------------------------------------
        # Step 3: Extract and validate fields
        # ------------------------------------------------------------------
        defaults = _DEFAULTS.get(crisis.type, _DEFAULTS[CrisisType.URBAN_FLOODING])

        affected_population = _safe_int(
            gemini_analysis.get("affected_population"),
            defaults["affected_population"],
        )
        affected_radius_km = _safe_float(
            gemini_analysis.get("affected_radius_km"),
            defaults["affected_radius_km"],
        )
        expected_duration_hours = _safe_float(
            gemini_analysis.get("expected_duration_hours"),
            defaults["expected_duration_hours"],
        )
        reasoning = gemini_analysis.get("reasoning", "") or defaults["reasoning"]
        severity_hint = gemini_analysis.get("severity", defaults["severity"])

        # ------------------------------------------------------------------
        # Step 4: Adjust population based on area density
        # ------------------------------------------------------------------
        if area_ctx.get("population_density"):
            density = area_ctx["population_density"]
            density_adjusted = int(density * affected_radius_km * 1.5)
            # Use the larger of Gemini estimate or density-based estimate
            affected_population = max(affected_population, density_adjusted)

        # ------------------------------------------------------------------
        # Step 5: Determine final severity
        # ------------------------------------------------------------------
        # Use Gemini's severity if valid, otherwise keep Agent 2's severity
        final_severity = _parse_severity(severity_hint) if severity_hint else crisis.severity

        # Override severity based on confidence from Agent 2
        if crisis.conflicting_signals:
            # Don't escalate if there are conflicts
            if final_severity == SeverityLevel.CRITICAL:
                final_severity = SeverityLevel.HIGH
            reasoning += " Note: Conflicting signals detected — severity capped."

        # ------------------------------------------------------------------
        # Step 6: Build enriched classification
        # ------------------------------------------------------------------
        elapsed_ms = _now_ms() - start_ms

        enriched = CrisisClassification(
            type=crisis.type,
            location=crisis.location,
            severity=final_severity,
            confidence=crisis.confidence,
            affected_population=affected_population,
            affected_radius_km=affected_radius_km,
            expected_duration_hours=expected_duration_hours,
            reasoning=reasoning,
            conflicting_signals=crisis.conflicting_signals,
        )

        # ------------------------------------------------------------------
        # Step 7: Log agent step
        # ------------------------------------------------------------------
        logger.log_agent_step(
            agent_name="agent_3_situation_analyzer",
            step="Situation Analysis",
            input_data=f"{crisis.type.value} at {crisis.location} (confidence={crisis.confidence})",
            output_data=(
                f"Population={affected_population}, Radius={affected_radius_km}km, "
                f"Duration={expected_duration_hours}hrs, Severity={final_severity.value}"
            ),
            duration_ms=elapsed_ms,
            extra_data={
                "affected_population": affected_population,
                "affected_radius_km": affected_radius_km,
                "expected_duration_hours": expected_duration_hours,
                "severity": final_severity.value,
                "conflicting_signals": crisis.conflicting_signals,
                "area_context_used": bool(area_ctx),
                "gemini_analysis": gemini_analysis,
            },
        )

        return enriched

    # ------------------------------------------------------------------
    # Private: Gemini Analysis
    # ------------------------------------------------------------------

    def _analyze_with_gemini(
        self,
        crisis: CrisisClassification,
        signals: SignalCollection,
        area_ctx: dict,
    ) -> dict:
        """
        Build a detailed prompt and query Gemini for situation analysis.

        Args:
            crisis: Current crisis classification.
            signals: All collected signals.
            area_ctx: Local area context data (population density, etc.).

        Returns:
            Dict with analysis fields, or defaults on failure.
        """
        # Build signal summary
        signal_summary_lines = []
        for i, sig in enumerate(signals.signals[:10], 1):  # Cap at 10
            signal_summary_lines.append(
                f"  {i}. [{sig.source.value}] (cred={sig.credibility}): {sig.text[:100]}"
            )
        signal_summary = "\n".join(signal_summary_lines)

        # Build area context string
        area_info = ""
        if area_ctx:
            area_info = (
                f"\nAREA CONTEXT:\n"
                f"  Population density: {area_ctx.get('population_density', 'unknown')} per sq km\n"
                f"  Vulnerable zones: {', '.join(area_ctx.get('vulnerable_zones', []))}\n"
                f"  Nearby hospitals: {', '.join(area_ctx.get('nearby_hospitals', []))}\n"
                f"  Key roads: {', '.join(area_ctx.get('key_roads', []))}\n"
                f"  Drainage quality: {area_ctx.get('drainage_quality', 'unknown')}"
            )

        system_instruction = (
            "You are an expert crisis situation analyzer for Pakistani urban areas. "
            "You assess crisis severity by considering population density, infrastructure, "
            "weather patterns, and local geography. You provide precise numeric estimates."
        )

        prompt = f"""Analyze this crisis situation in detail.

CRISIS TYPE: {crisis.type.value}
LOCATION: {crisis.location}
CURRENT CONFIDENCE: {crisis.confidence}
CONFLICTING SIGNALS: {crisis.conflicting_signals}

SIGNALS ({len(signals.signals)} total):
{signal_summary}
{area_info}

Provide a detailed situation analysis. Consider:
- Population density and time of day
- Infrastructure vulnerability (drainage, roads)
- Historical patterns for this type of crisis in Islamabad
- Cascading effects (traffic, hospital capacity, utilities)

Return ONLY a valid JSON object:
{{
    "affected_population": 15000,
    "affected_radius_km": 2.5,
    "expected_duration_hours": 4.0,
    "severity": "one of: LOW, MEDIUM, HIGH, CRITICAL",
    "peak_impact_time": "one of: soon, 1-2 hours, 4+ hours",
    "spread_risk": "one of: low, medium, high",
    "reasoning": "one paragraph explaining the full situation assessment"
}}

Return ONLY the JSON object, no markdown, no explanation."""

        defaults = _DEFAULTS.get(crisis.type, _DEFAULTS[CrisisType.URBAN_FLOODING])

        try:
            response_text = self.gemini.analyze_text(prompt, system_instruction)
            return self.gemini._parse_json_response(response_text)
        except Exception as e:
            from utils.gemini_client import GeminiUnavailableError
            if isinstance(e, GeminiUnavailableError):
                raise
            print(f"[SituationAnalyzer] Gemini analysis failed: {e}")
            return defaults


# ===========================================================================
# Module-level helpers
# ===========================================================================

def _normalize_area(location: str) -> str:
    """
    Normalize a location string to match _AREA_CONTEXT keys.

    Args:
        location: Raw location (e.g., 'G-10, Islamabad').

    Returns:
        Normalized key (e.g., 'g10').
    """
    loc = location.lower().strip()
    if "g-10" in loc or "g10" in loc or "g 10" in loc:
        return "g10"
    if "f-8" in loc or "f8" in loc or "f 8" in loc:
        return "f8"
    if "i-8" in loc or "i8" in loc or "i 8" in loc:
        return "i8"
    return loc.replace("-", "").replace(" ", "").replace(",", "")


def _parse_severity(severity_str: str) -> SeverityLevel:
    """
    Parse a severity string into a SeverityLevel enum.

    Args:
        severity_str: String like 'HIGH'.

    Returns:
        SeverityLevel enum member. Defaults to MEDIUM.
    """
    if not severity_str:
        return SeverityLevel.MEDIUM
    try:
        return SeverityLevel(severity_str.upper().strip())
    except ValueError:
        return SeverityLevel.MEDIUM


def _safe_int(value: Any, default: int) -> int:
    """
    Safely convert a value to int, returning default on failure.

    Args:
        value: Value to convert.
        default: Fallback integer.

    Returns:
        Integer value.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    """
    Safely convert a value to float, returning default on failure.

    Args:
        value: Value to convert.
        default: Fallback float.

    Returns:
        Float value.
    """
    if value is None:
        return default
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return default


def _now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.time() * 1000)
