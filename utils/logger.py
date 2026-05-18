"""
Agent Trace Logger
====================
JSON-based logging system for Antigravity trace submission.
Saves structured agent execution logs to logs/agent_traces/.

Each pipeline run creates ONE trace file containing logs from all 5 agents.
The file is built incrementally — each agent appends its step log.

Log format matches the hackathon submission spec:
    {
        "trace_id": "TRACE-INC-2026-001",
        "incident_id": "INC-2026-001",
        "timestamp": "2026-05-20T14:32:00",
        "agents": {
            "agent_1_signal_collector": { ... },
            "agent_2_crisis_detector": { ... },
            ...
        },
        "total_duration_ms": 8340
    }
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Resolve the logs directory relative to this file's location
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent.parent
_TRACES_DIR = _BASE_DIR / "logs" / "agent_traces"


class AgentLogger:
    """
    Structured JSON logger for the CIRO agent pipeline.

    Creates and incrementally updates a single trace file per incident,
    appending each agent's step data as the pipeline progresses.

    Args:
        trace_id: Unique trace identifier (e.g., TRACE-INC-2026-001).
        incident_id: Associated incident identifier (e.g., INC-2026-001).
    """

    def __init__(self, trace_id: str, incident_id: str) -> None:
        """
        Initialize the logger and create the trace file skeleton.

        Args:
            trace_id: Unique trace identifier.
            incident_id: Associated incident identifier.
        """
        self.trace_id = trace_id
        self.incident_id = incident_id
        self.start_time = datetime.now(timezone.utc)
        self._traces_dir = _TRACES_DIR

        # Ensure the output directory exists
        self._traces_dir.mkdir(parents=True, exist_ok=True)

        # Path to this trace's JSON file
        self.trace_file = self._traces_dir / f"{trace_id}.json"

        # Initialize the trace structure
        self._trace_data: dict[str, Any] = {
            "trace_id": trace_id,
            "incident_id": incident_id,
            "timestamp": self.start_time.isoformat(),
            "agents": {},
            "total_duration_ms": 0,
        }

        # Write the initial skeleton
        self._save()

    # ------------------------------------------------------------------
    # Public Methods
    # ------------------------------------------------------------------

    def log_agent_step(
        self,
        agent_name: str,
        step: str,
        input_data: Any,
        output_data: Any,
        duration_ms: int,
        extra_data: Optional[dict] = None,
    ) -> None:
        """
        Log a single agent's execution step to the trace file.

        This appends the agent's data under the 'agents' key and
        accumulates the total pipeline duration.

        Args:
            agent_name: Agent key (e.g., 'agent_1_signal_collector').
            step: Human-readable step name (e.g., 'Signal Collection').
            input_data: What the agent received as input.
            output_data: What the agent produced as output.
            duration_ms: How long the agent took (milliseconds).
            extra_data: Optional additional key-value pairs to include.
        """
        agent_log: dict[str, Any] = {
            "step": step,
            "input": self._serialize(input_data),
            "output": self._serialize(output_data),
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Merge any extra data (e.g., sources_checked, signals_found)
        if extra_data:
            agent_log.update(extra_data)

        # Append to the agents dict
        self._trace_data["agents"][agent_name] = agent_log

        # Accumulate total duration
        self._trace_data["total_duration_ms"] += duration_ms

        # Persist to disk
        self._save()

    def get_trace_data(self) -> dict:
        """
        Return the current in-memory trace data.

        Returns:
            Dict containing the full trace structure.
        """
        return self._trace_data

    @staticmethod
    def get_trace(trace_id: str) -> Optional[dict]:
        """
        Read and return a trace file by its ID.

        Args:
            trace_id: The trace identifier to look up.

        Returns:
            Parsed dict from the JSON file, or None if not found.
        """
        trace_file = _TRACES_DIR / f"{trace_id}.json"
        if not trace_file.exists():
            return None

        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[AgentLogger] Error reading trace {trace_id}: {e}")
            return None

    @staticmethod
    def list_traces() -> list[str]:
        """
        List all available trace IDs in the traces directory.

        Returns:
            List of trace ID strings (filenames without .json extension).
        """
        if not _TRACES_DIR.exists():
            return []

        return [
            f.stem
            for f in _TRACES_DIR.glob("*.json")
            if f.is_file()
        ]

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Persist the current trace data to disk as formatted JSON."""
        try:
            with open(self.trace_file, "w", encoding="utf-8") as f:
                json.dump(self._trace_data, f, indent=2, ensure_ascii=False, default=str)
        except OSError as e:
            print(f"[AgentLogger] Error writing trace file: {e}")

    @staticmethod
    def _serialize(data: Any) -> Any:
        """
        Safely convert data to a JSON-serializable format.

        Handles Pydantic models, datetime objects, and other complex types.

        Args:
            data: Any data to serialize.

        Returns:
            JSON-safe representation of the data.
        """
        if data is None:
            return None
        if isinstance(data, str):
            return data
        if isinstance(data, (int, float, bool)):
            return data
        if isinstance(data, datetime):
            return data.isoformat()
        if isinstance(data, (list, tuple)):
            return [AgentLogger._serialize(item) for item in data]
        if isinstance(data, dict):
            return {str(k): AgentLogger._serialize(v) for k, v in data.items()}

        # Handle Pydantic models
        if hasattr(data, "model_dump"):
            return data.model_dump()

        # Fallback: convert to string
        return str(data)
