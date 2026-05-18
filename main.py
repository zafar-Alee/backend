"""
CIRO — Crisis Intelligence & Response Orchestrator
====================================================
FastAPI entry point for the CIRO backend system.
Handles incoming crisis reports, runs the 5-agent pipeline,
and returns structured response data to the Flutter mobile app.

AISeekho2026 Antigravity Hackathon — Challenge 3
"""

import asyncio
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import configuration and middleware
from config import settings, validate_environment, print_startup_banner
from middleware import CIROMiddleware, rate_limiter, request_cache, performance_monitor

# Validate environment at startup
try:
    print_startup_banner()
except RuntimeError as e:
    print(f"Configuration error: {e}")
    exit(1)

# ---------------------------------------------------------------------------
# App Initialization
# ---------------------------------------------------------------------------
app = FastAPI(
    title="CIRO — Crisis Intelligence & Response Orchestrator",
    description=(
        "Agentic AI system that detects urban crises in Pakistani cities, "
        "analyzes severity, allocates resources, and simulates response actions."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS — Security: Use configured origins (NOT wildcard in production)
# ---------------------------------------------------------------------------
cors_allow_list = [
    origin.strip() 
    for origin in settings.cors_origins.split(",") 
    if origin.strip()
]

# Allow localhost for development, but use explicit list in production
if settings.production_mode and "*" in cors_allow_list:
    print("[WARNING] Wildcard CORS not allowed in production mode!")
    cors_allow_list = [
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Production Middleware (Rate Limiting, Caching, Logging)
# ---------------------------------------------------------------------------
app.add_middleware(CIROMiddleware, rate_limiter=rate_limiter, cache=request_cache)


# ---------------------------------------------------------------------------
# Global Exception Handler — catches GeminiUnavailableError from ANY endpoint
# ---------------------------------------------------------------------------
from starlette.requests import Request
from starlette.responses import JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch unhandled exceptions globally.
    GeminiUnavailableError -> 503 (AI service down)
    Everything else -> 500
    """
    # Import here to avoid circular imports at module level
    from utils.gemini_client import GeminiUnavailableError

    if isinstance(exc, HTTPException):
        raise exc  # Let FastAPI handle its own HTTPExceptions

    if isinstance(exc, GeminiUnavailableError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "status": "ai_unavailable",
                    "error": str(exc),
                    "message": "Gemini AI is currently unavailable. Check your API key or quota.",
                }
            },
        )

    # Generic 500
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "status": "error",
                "error": str(exc),
                "message": "Internal server error.",
            }
        },
    )

# ---------------------------------------------------------------------------
# Import & Include Mock API Routers
# ---------------------------------------------------------------------------
from mock_api.weather_router import router as weather_router
from mock_api.traffic_router import router as traffic_router
from mock_api.social_router import router as social_router
from mock_api.sensor_router import router as sensor_router
from auth import router as auth_router

app.include_router(weather_router, prefix="/mock", tags=["Mock Data"])
app.include_router(traffic_router, prefix="/mock", tags=["Mock Data"])
app.include_router(social_router, prefix="/mock", tags=["Mock Data"])
app.include_router(sensor_router, prefix="/mock", tags=["Mock Data"])
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])



# ═════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK & MONITORING ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["Monitoring"], summary="Health check endpoint")
async def health_check():
    """
    Simple health check endpoint for load balancers and monitoring systems.
    Returns 200 OK if service is running.
    """
    return {
        "status": "healthy",
        "service": "CIRO",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/system-info", tags=["Monitoring"], summary="System info and readiness")
async def system_info():
    """
    Detailed system state including API availability, database status,
    configuration, and performance metrics.
    """
    from utils.firebase_client import FirebaseClient

    fb = FirebaseClient()
    firebase_ready = fb.is_connected()
    gemini_ready = bool(settings.gemini_api_key)

    apis_available = {
        "gemini": gemini_ready,
        "openweather": bool(settings.openweather_api_key),
        "tomtom": bool(settings.tomtom_api_key),
        "firebase": firebase_ready,
    }

    status = validate_environment()

    return {
        "service": "CIRO",
        "status": "operational" if all(apis_available.values()) else "degraded",
        "environment": status["environment"],
        "mode": status["mode"],
        "dependencies": apis_available,
        "configuration": {
            "rate_limiting": settings.rate_limit_enabled,
            "caching": settings.cache_enabled,
            "detailed_logging": settings.detailed_logging,
            "production_mode": settings.production_mode,
        },
        "warnings": status["warnings"],
        "errors": status["errors"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/metrics", tags=["Monitoring"], summary="Performance metrics")
async def get_metrics():
    """
    Get application performance metrics including request counts,
    error rates, response times, and per-endpoint statistics.
    """
    if not settings.metrics_enabled:
        return {"error": "Metrics collection is disabled"}

    stats = performance_monitor.get_stats()

    return {
        "service": "CIRO",
        "metrics": stats,
        "rate_limiter": {
            "enabled": settings.rate_limit_enabled,
            "limit_per_minute": settings.rate_limit_per_minute,
        },
        "cache": {
            "enabled": settings.cache_enabled,
            "ttl_seconds": settings.cache_ttl_seconds,
            "items_cached": len(request_cache.cache),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/cache/clear", tags=["Monitoring"], summary="Clear request cache")
async def clear_cache():
    """Clear the in-memory request cache."""
    if not settings.cache_enabled:
        return {"warning": "Cache is disabled"}

    size_before = len(request_cache.cache)
    request_cache.clear()

    return {
        "status": "success",
        "items_cleared": size_before,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN CRISIS ANALYSIS ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

from agents.signal_collector import SignalCollector
from agents.crisis_detector import CrisisDetector
from agents.situation_analyzer import SituationAnalyzer
from agents.action_planner import ActionPlanner
from agents.executor import Executor

from pydantic import BaseModel, Field

from models.signal_models import AnalyzeRequest
from models.action_models import AnalyzeResponse, SimulationResult
from models.crisis_models import SeverityLevel


# ---------------------------------------------------------------------------
# Multi-Crisis Request / Response Models
# ---------------------------------------------------------------------------
class CrisisInput(BaseModel):
    """Single crisis input within a multi-crisis request."""
    text: str
    location: Optional[str] = None
    include_mock_signals: bool = True
    scenario: Optional[str] = None


class MultiCrisisRequest(BaseModel):
    """Request body for POST /analyze-multi."""
    crises: list[CrisisInput] = Field(
        ..., min_length=1, max_length=5,
        description="List of simultaneous crisis reports (max 5)",
    )


class MultiCrisisResponse(BaseModel):
    """Response for POST /analyze-multi with resource trade-offs."""
    incidents: list[AnalyzeResponse] = Field(default_factory=list)
    resource_trade_offs: list[str] = Field(default_factory=list)
    total_processing_time_ms: int = 0

from utils.gemini_client import GeminiClient, GeminiUnavailableError
from utils.firebase_client import FirebaseClient
from utils.logger import AgentLogger

_gemini_client = GeminiClient()

# ---------------------------------------------------------------------------
# Root Redirect
# ---------------------------------------------------------------------------
@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    """Redirect root to API docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


# ---------------------------------------------------------------------------
# Main Analysis Endpoint — Full 5-Agent Pipeline
# ---------------------------------------------------------------------------
@app.post("/analyze", tags=["Crisis Pipeline"], response_model=AnalyzeResponse)
async def analyze_crisis(request: AnalyzeRequest):
    """
    Main endpoint — receives crisis text from Flutter app,
    runs the full 5-agent pipeline, and returns structured response.

    Expected request body:
    {
        "text": "G-10 mein pani bhar gaya, gaariyan phans gayi hain",
        "location": "G-10, Islamabad",
        "include_mock_signals": true,
        "scenario": "flood"
    }
    """

    # ------------------------------------------------------------------
    # Step 1: Generate IDs
    # ------------------------------------------------------------------
    incident_id = f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    trace_id = f"TRACE-{incident_id}"

    # ------------------------------------------------------------------
    # Step 2: Initialize logger
    # ------------------------------------------------------------------
    logger = AgentLogger(trace_id, incident_id)

    # ------------------------------------------------------------------
    # Step 3: Initialize agents & utils
    # ------------------------------------------------------------------
    gemini = _gemini_client
    firebase = FirebaseClient()

    signal_collector = SignalCollector(gemini)
    crisis_detector = CrisisDetector(gemini)
    situation_analyzer = SituationAnalyzer(gemini)
    action_planner = ActionPlanner(gemini)
    executor = Executor(gemini)

    try:
        # ------------------------------------------------------------------
        # Step 4: Run the 5-agent pipeline with timing
        # ------------------------------------------------------------------
        t_start = time.time()

        # Agent 1: Signal Collection
        signals = await signal_collector.collect(request, logger)

        # Agent 2: Crisis Detection
        crisis = await crisis_detector.detect(signals, logger)

        # Agent 3: Situation Analysis
        crisis = await situation_analyzer.analyze(crisis, signals, logger)

        # Agent 4: Action Planning
        actions, messages = await action_planner.plan(crisis, logger)

        # Agent 5: Execution & Simulation
        simulation = await executor.execute(
            incident_id, crisis, actions, logger, messages
        )

        processing_time = int((time.time() - t_start) * 1000)

        # ------------------------------------------------------------------
        # Step 5: Save to Firebase
        # ------------------------------------------------------------------
        firebase.save_incident(incident_id, {
            "incident_id": incident_id,
            "crisis_type": crisis.type.value,
            "location": crisis.location,
            "severity": crisis.severity.value,
            "confidence": crisis.confidence,
            "affected_population": crisis.affected_population,
            "processing_time_ms": processing_time,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "RESPONSE_ACTIVE",
        })

        firebase.save_agent_trace(trace_id, logger.get_trace_data())

        # ------------------------------------------------------------------
        # Step 6: Build & return AnalyzeResponse
        # ------------------------------------------------------------------
        response = AnalyzeResponse(
            incident_id=incident_id,
            status="success",
            processing_time_ms=processing_time,
            crisis=crisis,
            signals_used=signals.signals,
            actions=actions,
            stakeholder_messages=messages,
            simulation=simulation,
            agent_trace_id=trace_id,
        )

        return response

    except GeminiUnavailableError as e:
        # ------------------------------------------------------------------
        # Gemini AI unavailable — return 503 with clear message
        # ------------------------------------------------------------------
        print(f"[CIRO] Gemini unavailable: {e}")

        try:
            firebase.save_agent_trace(trace_id, {
                **logger.get_trace_data(),
                "error": str(e),
                "error_type": "GEMINI_UNAVAILABLE",
            })
        except Exception:
            pass

        raise HTTPException(
            status_code=503,
            detail={
                "status": "ai_unavailable",
                "incident_id": incident_id,
                "error": str(e),
                "message": "Gemini AI is currently unavailable. Check your API key or quota.",
                "trace_id": trace_id,
            },
        )

    except Exception as e:
        # ------------------------------------------------------------------
        # Generic pipeline error — save partial trace, return 500
        # ------------------------------------------------------------------
        error_detail = traceback.format_exc()
        print(f"[CIRO] Pipeline error: {error_detail}")

        try:
            firebase.save_agent_trace(trace_id, {
                **logger.get_trace_data(),
                "error": str(e),
                "error_detail": error_detail,
            })
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "incident_id": incident_id,
                "error": str(e),
                "message": "Pipeline failed -- partial trace saved.",
                "trace_id": trace_id,
            },
        )


# ---------------------------------------------------------------------------
# Incident Endpoints
# ---------------------------------------------------------------------------
@app.get("/incidents", tags=["Incidents"])
async def get_all_incidents():
    """Retrieve all incidents from Firebase."""
    firebase = FirebaseClient()
    incidents = firebase.get_all_incidents()
    return {"incidents": incidents, "total": len(incidents)}


@app.get("/incidents/{incident_id}", tags=["Incidents"])
async def get_incident(incident_id: str):
    """Retrieve a specific incident by ID."""
    firebase = FirebaseClient()
    incident = firebase.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return incident


# ---------------------------------------------------------------------------
# System State Endpoint
# ---------------------------------------------------------------------------
@app.get("/system-state", tags=["System"])
async def get_system_state():
    """Get current before/after system state from Firebase."""
    firebase = FirebaseClient()
    
    if firebase.use_mock:
        return {
            "before": firebase._mock_store["system_state"]["before"],
            "after": firebase._mock_store["system_state"]["after"],
        }
        
    try:
        before_doc = firebase.db.collection("system_state").document("before").get()
        after_doc = firebase.db.collection("system_state").document("after").get()
        return {
            "before": before_doc.to_dict() if before_doc.exists else {},
            "after": after_doc.to_dict() if after_doc.exists else {},
        }
    except Exception as e:
        return {"error": str(e), "before": {}, "after": {}}


# ---------------------------------------------------------------------------
# Reset Endpoint
# ---------------------------------------------------------------------------
@app.post("/reset", tags=["System"])
async def reset_state():
    """Reset system state for demo purposes."""
    firebase = FirebaseClient()
    firebase.reset_state()
    return {"status": "reset_complete", "message": "System state cleared."}


# ---------------------------------------------------------------------------
# Trace Logs Endpoint
# ---------------------------------------------------------------------------
@app.get("/logs/{trace_id}", tags=["Logging"])
async def get_agent_logs(trace_id: str):
    """Retrieve agent trace logs for a specific trace ID."""
    import json
    from pathlib import Path

    trace_path = Path(__file__).parent / "logs" / "agent_traces" / f"{trace_id}.json"

    if not trace_path.exists():
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")

    with open(trace_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Multi-Crisis Endpoint — Simultaneous Crisis Handling
# ---------------------------------------------------------------------------

# Severity ordering for priority allocation
_SEVERITY_ORDER = {
    SeverityLevel.CRITICAL: 0,
    SeverityLevel.HIGH: 1,
    SeverityLevel.MEDIUM: 2,
    SeverityLevel.LOW: 3,
}


@app.post("/analyze-multi", tags=["Crisis Pipeline"], response_model=MultiCrisisResponse)
async def analyze_multi_crisis(request: MultiCrisisRequest):
    """
    Multi-crisis endpoint: processes 2+ crises simultaneously.

    Runs Agents 1-3 in parallel, then allocates shared resources
    by severity priority before running Agents 4-5 for each crisis.

    Returns combined response with resource trade-off explanations.
    """
    t_start = time.time()
    gemini = _gemini_client
    firebase = FirebaseClient()

    # ------------------------------------------------------------------
    # Phase 1: Run Agents 1-3 in PARALLEL for all crises
    # ------------------------------------------------------------------
    async def run_agents_1_to_3(crisis_input: CrisisInput, index: int):
        """Run signal collection, detection, and analysis for one crisis."""
        incident_id = f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}-C{index + 1}"
        trace_id = f"TRACE-{incident_id}"
        logger = AgentLogger(trace_id, incident_id)

        analyze_req = AnalyzeRequest(
            text=crisis_input.text,
            location=crisis_input.location,
            include_mock_signals=crisis_input.include_mock_signals,
            scenario=crisis_input.scenario,
        )

        collector = SignalCollector(gemini)
        detector = CrisisDetector(gemini)
        analyzer = SituationAnalyzer(gemini)

        signals = await collector.collect(analyze_req, logger)
        crisis = await detector.detect(signals, logger)
        crisis = await analyzer.analyze(crisis, signals, logger)

        return {
            "incident_id": incident_id,
            "trace_id": trace_id,
            "logger": logger,
            "signals": signals,
            "crisis": crisis,
        }

    # Run all crises through agents 1-3 concurrently
    phase1_results = await asyncio.gather(
        *[run_agents_1_to_3(ci, i) for i, ci in enumerate(request.crises)]
    )

    # ------------------------------------------------------------------
    # Phase 2: Sort by severity and allocate resources
    # ------------------------------------------------------------------
    # Sort by severity (CRITICAL first)
    sorted_results = sorted(
        phase1_results,
        key=lambda r: _SEVERITY_ORDER.get(r["crisis"].severity, 99),
    )

    # Master resource pool (copy from ActionPlanner defaults)
    resource_pool = {
        "rescue_vehicles": 3,
        "ambulances": 2,
        "police_units": 4,
        "water_tankers": 1,
        "field_teams": 2,
    }
    trade_offs: list[str] = []

    # Build per-crisis resource allocations
    crisis_allocations: list[dict[str, int]] = []

    for result in sorted_results:
        crisis = result["crisis"]
        alloc = _allocate_from_pool(crisis, resource_pool, trade_offs)
        crisis_allocations.append(alloc)

    # ------------------------------------------------------------------
    # Phase 3: Run Agents 4-5 for each crisis (with allocated resources)
    # ------------------------------------------------------------------
    final_responses: list[AnalyzeResponse] = []

    for idx, result in enumerate(sorted_results):
        incident_id = result["incident_id"]
        trace_id = result["trace_id"]
        logger = result["logger"]
        signals = result["signals"]
        crisis = result["crisis"]
        allocated = crisis_allocations[idx]

        # Determine other active crises for the planner's awareness
        other_crises = [
            r["crisis"] for r in sorted_results if r["incident_id"] != incident_id
        ]

        planner = ActionPlanner(gemini)
        executor = Executor(gemini)

        actions, messages = await planner.plan(
            crisis, logger, other_active_crises=other_crises
        )

        # Override action resources with our centrally-allocated amounts
        for action in actions:
            for res_name in list(action.resources_allocated.keys()):
                if res_name in allocated:
                    action.resources_allocated[res_name] = allocated.get(res_name, 0)

        simulation = await executor.execute(
            incident_id, crisis, actions, logger, messages
        )

        processing_time = int((time.time() - t_start) * 1000)

        # Save to Firebase
        firebase.save_incident(incident_id, {
            "incident_id": incident_id,
            "crisis_type": crisis.type.value,
            "location": crisis.location,
            "severity": crisis.severity.value,
            "confidence": crisis.confidence,
            "affected_population": crisis.affected_population,
            "processing_time_ms": processing_time,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "RESPONSE_ACTIVE",
            "multi_crisis": True,
        })
        firebase.save_agent_trace(trace_id, logger.get_trace_data())

        response = AnalyzeResponse(
            incident_id=incident_id,
            status="success",
            processing_time_ms=processing_time,
            crisis=crisis,
            signals_used=signals.signals,
            actions=actions,
            stakeholder_messages=messages,
            simulation=simulation,
            agent_trace_id=trace_id,
        )
        final_responses.append(response)

    total_time = int((time.time() - t_start) * 1000)

    return MultiCrisisResponse(
        incidents=final_responses,
        resource_trade_offs=trade_offs,
        total_processing_time_ms=total_time,
    )


def _allocate_from_pool(
    crisis,
    pool: dict[str, int],
    trade_offs: list[str],
) -> dict[str, int]:
    """
    Allocate resources from the shared pool for one crisis.

    Modifies `pool` in-place (decrements available resources).
    Appends trade-off messages to `trade_offs` when resources are limited.

    Args:
        crisis: CrisisClassification for this crisis.
        pool: Mutable dict of remaining resource counts.
        trade_offs: Mutable list of trade-off explanation strings.

    Returns:
        Dict of resource_name -> allocated_count for this crisis.
    """
    from models.crisis_models import CrisisType

    # Desired allocation per crisis type
    desired: dict[str, int] = {}
    if crisis.type == CrisisType.URBAN_FLOODING:
        desired = {"rescue_vehicles": 2, "police_units": 2, "water_tankers": 1}
    elif crisis.type == CrisisType.HEATWAVE:
        desired = {"ambulances": 1, "police_units": 2}
    elif crisis.type == CrisisType.ROAD_ACCIDENT:
        desired = {"ambulances": 1, "rescue_vehicles": 1, "police_units": 2}
    elif crisis.type == CrisisType.INFRASTRUCTURE_FAILURE:
        desired = {"field_teams": 1, "police_units": 1}
    elif crisis.type == CrisisType.POWER_OUTAGE:
        desired = {"field_teams": 1, "police_units": 1}

    allocated: dict[str, int] = {}
    location = crisis.location
    severity = crisis.severity.value
    crisis_label = crisis.type.value.replace("_", " ").lower()

    for res_name, wanted in desired.items():
        available = pool.get(res_name, 0)
        given = min(wanted, available)
        allocated[res_name] = given
        pool[res_name] = available - given

        if given < wanted:
            short = wanted - given
            trade_offs.append(
                f"{given} of {wanted} {res_name.replace('_', ' ')} allocated to "
                f"{location} ({severity} severity {crisis_label}); "
                f"{short} unavailable due to multi-crisis resource sharing"
            )
        else:
            trade_offs.append(
                f"{given} {res_name.replace('_', ' ')} allocated to "
                f"{location} ({severity} severity {crisis_label})"
            )

    return allocated


# ---------------------------------------------------------------------------
# Run Server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
