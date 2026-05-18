"""
Firebase Client
=================
Centralized wrapper for all Firebase Firestore operations.
Every agent MUST use this client — no direct SDK calls elsewhere.

Implements a Singleton pattern so that the Admin SDK is only initialized once.
If credentials are not found, it falls back to an in-memory mock store
to ensure the pipeline never crashes during testing/demo.
"""

import os
from typing import Any, Optional

from dotenv import load_dotenv

# Load .env from project root
load_dotenv()


class FirebaseClient:
    """
    Singleton client for Firebase Firestore operations.

    Manages:
    - incidents/          — Crisis records
    - system_state/       — Before/after state snapshots
    - emergency_tickets/  — Dispatch tickets
    - agent_traces/       — Agent execution logs
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseClient, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize Firebase Admin SDK (runs only once per process)."""
        if self._initialized:
            return

        self.project_id = os.getenv("FIREBASE_PROJECT_ID", "")
        self.creds_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "./firebase_credentials.json")
        self.db = None
        self.use_mock = False

        # In-memory store for fallback/testing
        self._mock_store: dict[str, dict] = {
            "incidents": {},
            "system_state": {"before": {}, "after": {}},
            "emergency_tickets": {},
            "agent_traces": {},
        }

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            # Check if app is already initialized
            if not firebase_admin._apps:
                # Option 1: JSON string from env variable (for cloud deployment)
                creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
                if creds_json:
                    import json
                    cred_dict = json.loads(creds_json)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                    self.db = firestore.client()
                    print("[FirebaseClient] Initialized from FIREBASE_CREDENTIALS_JSON env var.")
                elif os.path.exists(self.creds_path):
                    # Option 2: File path
                    cred = credentials.Certificate(self.creds_path)
                    firebase_admin.initialize_app(cred)
                    self.db = firestore.client()
                    print("[FirebaseClient] Initialized successfully with credentials file.")
                else:
                    self.use_mock = True
                    print(
                        f"[FirebaseClient] WARNING: Credentials not found at {self.creds_path}.\n"
                        "  => Falling back to IN-MEMORY mock store.\n"
                        "  => Set FIREBASE_CREDENTIALS_JSON env var or add credentials file."
                    )
            else:
                self.db = firestore.client()

            FirebaseClient._initialized = True

        except ImportError:
            self.use_mock = True
            print(
                "[FirebaseClient] ERROR: firebase-admin package not installed.\n"
                "  => Run: pip install firebase-admin\n"
                "  => Falling back to IN-MEMORY mock store."
            )
            FirebaseClient._initialized = True
        except Exception as e:
            self.use_mock = True
            print(f"[FirebaseClient] ERROR initializing Firebase: {e}\n  => Falling back to mock store.")
            FirebaseClient._initialized = True

    # ------------------------------------------------------------------
    # Connection Check
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Check if Firebase is connected (not using mock store)."""
        return self.db is not None and not self.use_mock

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    def save_incident(self, incident_id: str, data: dict) -> bool:
        """
        Save or update an incident record.

        Args:
            incident_id: Unique identifier.
            data: Incident data dictionary.

        Returns:
            True if successful, False otherwise.
        """
        try:
            if self.use_mock:
                self._mock_store["incidents"][incident_id] = data
                return True

            self.db.collection("incidents").document(incident_id).set(data, merge=True)
            return True
        except Exception as e:
            print(f"[FirebaseClient] Failed to save incident {incident_id}: {e}")
            return False

    def update_system_state(self, state_type: str, data: dict) -> bool:
        """
        Save a system state snapshot.

        Args:
            state_type: 'before' or 'after'.
            data: State snapshot dictionary.

        Returns:
            True if successful, False otherwise.
        """
        if state_type not in ("before", "after"):
            print(f"[FirebaseClient] Invalid state_type: {state_type}. Must be 'before' or 'after'.")
            return False

        try:
            if self.use_mock:
                self._mock_store["system_state"][state_type] = data
                return True

            self.db.collection("system_state").document(state_type).set(data)
            return True
        except Exception as e:
            print(f"[FirebaseClient] Failed to update system state '{state_type}': {e}")
            return False

    def save_emergency_ticket(self, ticket_id: str, data: dict) -> bool:
        """Save a generated emergency ticket."""
        try:
            if self.use_mock:
                self._mock_store["emergency_tickets"][ticket_id] = data
                return True

            self.db.collection("emergency_tickets").document(ticket_id).set(data)
            return True
        except Exception as e:
            print(f"[FirebaseClient] Failed to save emergency ticket {ticket_id}: {e}")
            return False

    def save_agent_trace(self, trace_id: str, data: dict) -> bool:
        """Save the full agent execution trace log to Firebase."""
        try:
            if self.use_mock:
                self._mock_store["agent_traces"][trace_id] = data
                return True

            self.db.collection("agent_traces").document(trace_id).set(data)
            return True
        except Exception as e:
            print(f"[FirebaseClient] Failed to save agent trace {trace_id}: {e}")
            return False

    def find_alerts(self, location: str, crisis_type: str) -> list[str]:
        """
        Find previous alert IDs for a given location and crisis type.
        Used for retracting false alarms.
        """
        matched_alerts = []
        loc_lower = location.lower()
        
        try:
            if self.use_mock:
                for inc_id, inc_data in self._mock_store["incidents"].items():
                    if inc_data.get("crisis_type") == crisis_type:
                        inc_loc = inc_data.get("location", "").lower()
                        if loc_lower in inc_loc or inc_loc in loc_lower:
                            # Check for alerts sent
                            latest_alert = inc_data.get("latest_alert")
                            if latest_alert and latest_alert.get("status") == "SENT":
                                matched_alerts.append(latest_alert.get("alert_id"))
                return matched_alerts
            else:
                # Real Firestore query (simplified for hackathon)
                docs = self.db.collection("incidents").where("crisis_type", "==", crisis_type).stream()
                for doc in docs:
                    inc_data = doc.to_dict()
                    inc_loc = inc_data.get("location", "").lower()
                    if loc_lower in inc_loc or inc_loc in loc_lower:
                        latest_alert = inc_data.get("latest_alert")
                        if latest_alert and latest_alert.get("status") == "SENT":
                            matched_alerts.append(latest_alert.get("alert_id"))
                return matched_alerts
        except Exception as e:
            print(f"[FirebaseClient] Failed to find alerts: {e}")
            return []

    # ------------------------------------------------------------------
    # Read Operations
    # ------------------------------------------------------------------

    def get_all_incidents(self) -> list[dict]:
        """
        Retrieve all incidents.

        Returns:
            List of incident dictionaries.
        """
        try:
            if self.use_mock:
                return list(self._mock_store["incidents"].values())

            docs = self.db.collection("incidents").stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"[FirebaseClient] Failed to get all incidents: {e}")
            return []

    def get_incident(self, incident_id: str) -> Optional[dict]:
        """
        Retrieve a specific incident by ID.

        Returns:
            Incident dictionary or None if not found.
        """
        try:
            if self.use_mock:
                return self._mock_store["incidents"].get(incident_id)

            doc = self.db.collection("incidents").document(incident_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            print(f"[FirebaseClient] Failed to get incident {incident_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Administrative
    # ------------------------------------------------------------------

    def reset_state(self) -> bool:
        """
        Clear the system_state and emergency_tickets collections.
        Used for resetting the system before a new demo scenario.

        Returns:
            True if successful, False otherwise.
        """
        try:
            if self.use_mock:
                self._mock_store["system_state"] = {"before": {}, "after": {}}
                self._mock_store["emergency_tickets"] = {}
                print("[FirebaseClient] In-memory mock state reset.")
                return True

            # In Firestore, deleting a collection requires deleting all docs inside it.
            for doc in self.db.collection("system_state").stream():
                doc.reference.delete()
            for doc in self.db.collection("emergency_tickets").stream():
                doc.reference.delete()

            print("[FirebaseClient] Firestore system state reset.")
            return True
        except Exception as e:
            print(f"[FirebaseClient] Failed to reset state: {e}")
            return False
