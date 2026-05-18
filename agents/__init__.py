"""
CIRO Agents Package
====================
Contains the 5 agentic AI classes that form the crisis response pipeline:
1. SignalCollector — ingests text + calls mock API endpoints
2. CrisisDetector — cross-references signals, calculates confidence
3. SituationAnalyzer — severity, population, duration via Gemini
4. ActionPlanner — generates actions, allocates resources
5. Executor — simulates actions, saves state to Firebase
"""
