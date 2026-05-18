"""
Agent 4 — Action Planner
==========================
Allocates resources, generates tactical response actions, and uses Gemini
to draft targeted stakeholder messages based on the analyzed crisis.

Pipeline position: FOURTH — receives from SituationAnalyzer (Agent 3),
feeds into Executor (Agent 5).

Dependencies:
    - GeminiClient (utils/gemini_client.py)
    - AgentLogger  (utils/logger.py)
"""

import time
from typing import Any

from models.crisis_models import CrisisClassification, CrisisType
from models.action_models import ActionType, ResponseAction, StakeholderMessages
from utils.gemini_client import GeminiClient
from utils.logger import AgentLogger


class ActionPlanner:
    """
    Agent 4: Plans response actions and resource allocation.

    Uses predefined logic to allocate available resources and generate
    response actions based on the crisis type. Then uses Gemini to 
    draft contextual stakeholder messages (public, hospital, police, etc).
    """

    AVAILABLE_RESOURCES = {
        "rescue_vehicles": {"total": 3, "available": 3, "location": "G-6 Station"},
        "ambulances": {"total": 2, "available": 2, "location": "PIMS Hospital"},
        "police_units": {"total": 4, "available": 4, "location": "F-8 Station"},
        "water_tankers": {"total": 1, "available": 1, "location": "CDA Depot"},
        "field_teams": {"total": 2, "available": 2, "location": "Sector G-9"},
    }

    def __init__(self, gemini_client: GeminiClient) -> None:
        """
        Initialize the Action Planner.

        Args:
            gemini_client: Shared GeminiClient instance for messaging.
        """
        self.gemini = gemini_client

    async def plan(
        self,
        crisis: CrisisClassification,
        logger: AgentLogger,
        other_active_crises: list[Any] = None,
    ) -> tuple[list[ResponseAction], StakeholderMessages]:
        """
        Generate response actions and stakeholder messages.

        Steps:
            1. Allocate resources based on crisis type.
            2. Handle multi-crisis resource contention.
            3. Generate tactical response actions.
            4. Generate targeted stakeholder messages via Gemini.
            5. Log and return.

        Args:
            crisis: CrisisClassification from Agent 3.
            logger: AgentLogger instance for this pipeline run.
            other_active_crises: List of other active crises for resource contention.

        Returns:
            Tuple of (list of ResponseAction, StakeholderMessages).
        """
        start_ms = _now_ms()
        multi_crisis_mode = bool(other_active_crises)
        
        # ------------------------------------------------------------------
        # Step 1 & 2: Resource Allocation
        # ------------------------------------------------------------------
        # Base allocation dict
        allocated: dict[str, int] = {}
        
        if crisis.type == CrisisType.URBAN_FLOODING:
            allocated = {"rescue_vehicles": 2, "police_units": 2, "water_tankers": 1}
        elif crisis.type == CrisisType.HEATWAVE:
            allocated = {"ambulances": 1, "police_units": 1}
        elif crisis.type == CrisisType.ROAD_ACCIDENT:
            allocated = {"ambulances": 1, "rescue_vehicles": 1, "police_units": 2}
        elif crisis.type == CrisisType.INFRASTRUCTURE_FAILURE:
            allocated = {"field_teams": 1, "police_units": 1}
        elif crisis.type == CrisisType.POWER_OUTAGE:
            allocated = {"field_teams": 1, "police_units": 1}
        else: # FALSE_ALARM
            allocated = {}

        # If there are other crises, simulate splitting resources
        if multi_crisis_mode:
            for res_name, amount in allocated.items():
                if amount > 1:
                    allocated[res_name] = max(1, amount // 2)

        # ------------------------------------------------------------------
        # Step 3: Generate AI-Reasoned Response Actions via Gemini
        # ------------------------------------------------------------------
        actions = self._generate_actions_with_gemini(crisis, allocated)

        # ------------------------------------------------------------------
        # Step 4: Generate Stakeholder Messages via Gemini
        # ------------------------------------------------------------------
        if crisis.type != CrisisType.FALSE_ALARM:
            messages = self._generate_stakeholder_messages(crisis)
        else:
            messages = StakeholderMessages(
                public="No action required. The earlier report was a false alarm.",
                hospital="",
                traffic_police="Stand down from area.",
                utility="",
                media="Situation normal, false alarm reported.",
            )

        # ------------------------------------------------------------------
        # Step 5: Log Agent Step
        # ------------------------------------------------------------------
        elapsed_ms = _now_ms() - start_ms
        
        logger.log_agent_step(
            agent_name="agent_4_action_planner",
            step="Action Planning",
            input_data=f"{crisis.type.value} at {crisis.location} (Severity: {crisis.severity.value})",
            output_data=f"Generated {len(actions)} AI-reasoned actions and 5 stakeholder messages",
            duration_ms=elapsed_ms,
            extra_data={
                "crisis_type": crisis.type.value,
                "actions_generated": len(actions),
                "resources_allocated": allocated,
                "multi_crisis_mode": multi_crisis_mode,
                "stakeholder_messages_generated": 5 if crisis.type != CrisisType.FALSE_ALARM else 2,
            },
        )

        # ------------------------------------------------------------------
        # Step 6: Return
        # ------------------------------------------------------------------
        return actions, messages

    # ------------------------------------------------------------------
    # Private: Gemini Action Generation
    # ------------------------------------------------------------------

    def _generate_actions_with_gemini(
        self,
        crisis: CrisisClassification,
        allocated: dict,
    ) -> list["ResponseAction"]:
        """
        Use Gemini to reason about the crisis context and generate
        specific, location-aware response actions.

        Gemini is given the crisis type, severity, location, affected population,
        reasoning, and available resources — then asked to plan the response.
        Hardcoded fallback is used if Gemini is unavailable.
        """
        crisis_prefix = crisis.type.value[:3].upper()  # e.g. URB, HEA, ROA
        
        system_instruction = (
            "You are a senior crisis response coordinator in Pakistan's NDMA. "
            "You have deep knowledge of Islamabad's road network, hospitals, and emergency services. "
            "Generate specific, realistic, immediately actionable response actions for crises. "
            "Use real Pakistani emergency entity names (Rescue 1122, NDMA, PIMS, CDA, WASA, IESCO, Traffic Police)."
        )

        prompt = f"""A real crisis has been detected. Generate 3-4 specific, actionable response actions.

CRISIS DETAILS:
- Type: {crisis.type.value}
- Location: {crisis.location}
- Severity: {crisis.severity.value}
- Affected Population: {crisis.affected_population:,}
- Expected Duration: {crisis.expected_duration_hours} hours
- AI Reasoning: {crisis.reasoning[:300] if crisis.reasoning else 'N/A'}

AVAILABLE RESOURCES: {allocated}

You MUST return ONLY a valid JSON array of action objects. Each object must have:
- "type": one of [TRAFFIC_REROUTE, EMERGENCY_DISPATCH, PUBLIC_ALERT, HOSPITAL_PREP, UTILITY_ESCALATION, MEDIA_UPDATE]
- "description": a SPECIFIC action with real local road/hospital/entity names relevant to {crisis.location} in Islamabad, Pakistan
- "entity": the Pakistani entity responsible (Rescue 1122, Traffic Police, NDMA, PIMS Hospital, CDA, WASA, IESCO, etc.)
- "priority": integer 1-3 (1=most urgent)
- "estimated_impact": expected real-world outcome
- "resources": dict with resource names and counts from available resources

Return ONLY the JSON array, no markdown."""

        try:
            response_text = self.gemini.analyze_text(prompt, system_instruction)
            parsed = self.gemini._parse_json_response(response_text)
            
            # Handle both array and wrapped object responses
            if isinstance(parsed, dict) and "actions" in parsed:
                parsed = parsed["actions"]
            if not isinstance(parsed, list):
                raise ValueError("Gemini did not return a list of actions")

            actions = []
            for i, item in enumerate(parsed[:4], start=1):
                action_type_str = item.get("type", "PUBLIC_ALERT").upper()
                try:
                    action_type = ActionType(action_type_str)
                except ValueError:
                    action_type = ActionType.PUBLIC_ALERT

                actions.append(ResponseAction(
                    action_id=f"ACT-{crisis_prefix}-{i:03d}",
                    type=action_type,
                    description=item.get("description", f"Response action {i}"),
                    entity=item.get("entity", "NDMA"),
                    priority=max(1, min(int(item.get("priority", i)), 10)),
                    estimated_impact=item.get("estimated_impact", ""),
                    resources_allocated=item.get("resources", {}),
                ))

            print(f"[ActionPlanner] Gemini generated {len(actions)} AI-reasoned actions for {crisis.location}")
            return actions

        except Exception as e:
            print(f"[ActionPlanner] Gemini action generation failed: {e}. Using rule-based fallback.")
            return self._fallback_actions(crisis, allocated)

    def _fallback_actions(self, crisis: CrisisClassification, allocated: dict) -> list["ResponseAction"]:
        """Rule-based fallback if Gemini is unavailable."""
        prefix_map = {
            CrisisType.URBAN_FLOODING: "FLD",
            CrisisType.HEATWAVE: "HTW",
            CrisisType.ROAD_ACCIDENT: "ACC",
            CrisisType.INFRASTRUCTURE_FAILURE: "INF",
            CrisisType.POWER_OUTAGE: "PWR",
        }
        pfx = prefix_map.get(crisis.type, "GEN")
        loc = crisis.location

        if crisis.type == CrisisType.URBAN_FLOODING:
            return [
                ResponseAction(action_id=f"ACT-{pfx}-001", type=ActionType.TRAFFIC_REROUTE,
                    description=f"Reroute traffic away from flooded {loc}", entity="Traffic Police",
                    priority=1, estimated_impact="Reduce congestion", resources_allocated={"police_units": allocated.get("police_units", 2)}),
                ResponseAction(action_id=f"ACT-{pfx}-002", type=ActionType.EMERGENCY_DISPATCH,
                    description=f"Dispatch {allocated.get('rescue_vehicles', 2)} rescue vehicles to {loc}", entity="Rescue 1122",
                    priority=1, estimated_impact="Evacuate stranded citizens", resources_allocated={"rescue_vehicles": allocated.get("rescue_vehicles", 2)}),
                ResponseAction(action_id=f"ACT-{pfx}-003", type=ActionType.PUBLIC_ALERT,
                    description=f"SMS flood warning to {loc} residents", entity="NDMA",
                    priority=2, estimated_impact="Prevent casualties", resources_allocated={}),
                ResponseAction(action_id=f"ACT-{pfx}-004", type=ActionType.HOSPITAL_PREP,
                    description="Activate emergency protocol at PIMS Hospital", entity="PIMS Hospital",
                    priority=3, estimated_impact="Ensure trauma readiness", resources_allocated={}),
            ]
        elif crisis.type == CrisisType.HEATWAVE:
            return [
                ResponseAction(action_id=f"ACT-{pfx}-001", type=ActionType.PUBLIC_ALERT,
                    description=f"Heat emergency warning for {loc}", entity="NDMA",
                    priority=1, estimated_impact="Keep citizens indoors", resources_allocated={}),
                ResponseAction(action_id=f"ACT-{pfx}-002", type=ActionType.EMERGENCY_DISPATCH,
                    description="Deploy medical outreach teams", entity="Rescue 1122",
                    priority=1, estimated_impact="Treat heatstroke on-site", resources_allocated={"ambulances": allocated.get("ambulances", 1)}),
            ]
        else:
            return [
                ResponseAction(action_id=f"ACT-{pfx}-001", type=ActionType.PUBLIC_ALERT,
                    description=f"Emergency alert issued for {loc}", entity="NDMA",
                    priority=1, estimated_impact="Public awareness", resources_allocated={}),
                ResponseAction(action_id=f"ACT-{pfx}-002", type=ActionType.EMERGENCY_DISPATCH,
                    description=f"Emergency teams dispatched to {loc}", entity="Rescue 1122",
                    priority=1, estimated_impact="On-site response", resources_allocated={}),
            ]

    # ------------------------------------------------------------------
    # Private: Gemini Message Generation
    # ------------------------------------------------------------------

    def _generate_stakeholder_messages(self, crisis: CrisisClassification) -> StakeholderMessages:
        """
        Use Gemini to draft context-aware stakeholder messages.

        Args:
            crisis: Current crisis classification.

        Returns:
            StakeholderMessages populated via Gemini.
        """
        crisis_summary = (
            f"Type: {crisis.type.value}, Location: {crisis.location}, "
            f"Severity: {crisis.severity.value}, Affected Pop: {crisis.affected_population}, "
            f"Expected Duration: {crisis.expected_duration_hours}h"
        )
        
        system_instruction = (
            "You are a crisis communication expert for the NDMA in Pakistan. "
            "You write clear, urgent, and concise SMS-style alerts."
        )

        prompt = f"""Generate 5 targeted messages for this crisis:
{crisis_summary}

One each for: public, hospital, traffic_police, utility_company, media.
Keep each under 160 characters for SMS. Be specific about {crisis.location}.
Return as JSON.

Return ONLY a valid JSON object:
{{
    "public": "message here",
    "hospital": "message here",
    "traffic_police": "message here",
    "utility": "message here",
    "media": "message here"
}}

Return ONLY the JSON object, no markdown, no explanation."""

        default_messages = {
            "public": f"ALERT: {crisis.type.value.replace('_', ' ')} reported in {crisis.location}. Stay safe.",
            "hospital": f"PREP: Incoming casualties from {crisis.location} due to {crisis.type.value}.",
            "traffic_police": f"REROUTE: Avoid {crisis.location}. Heavy congestion expected.",
            "utility": f"DISPATCH: Immediate response required at {crisis.location}.",
            "media": f"UPDATE: {crisis.type.value} active in {crisis.location}. Emergency teams deployed.",
        }

        try:
            response_text = self.gemini.analyze_text(prompt, system_instruction)
            parsed = self.gemini._parse_json_response(response_text)
            
            return StakeholderMessages(
                public=parsed.get("public", default_messages["public"]),
                hospital=parsed.get("hospital", default_messages["hospital"]),
                traffic_police=parsed.get("traffic_police", default_messages["traffic_police"]),
                utility=parsed.get("utility", default_messages["utility"]),
                media=parsed.get("media", default_messages["media"]),
            )
        except Exception as e:
            from utils.gemini_client import GeminiUnavailableError
            if isinstance(e, GeminiUnavailableError):
                raise
            print(f"[ActionPlanner] Gemini message generation failed: {e}")
            return StakeholderMessages(**default_messages)


def _now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.time() * 1000)
