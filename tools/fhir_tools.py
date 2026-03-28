"""
AuthBridge FHIR Tools
Fetches comprehensive clinical context from a FHIR R4 server.
Uses HAPI FHIR public sandbox by default (synthetic data only).
Optimized with asyncio.gather for parallel performance.
"""

import httpx
import logging
import asyncio
from typing import Optional, List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

HAPI_FHIR_BASE = "https://hapi.fhir.org/baseR4"
FHIR_TIMEOUT = 20.0


def _safe_get_coding(resource: Dict[str, Any], field: Optional[str] = None, subfield: str = "display") -> str:
    """Safely extract the first coding value from a FHIR CodeableConcept."""
    try:
        data = resource.get(field, {}) if field else resource
        if not isinstance(data, dict):
            return ""
        codings = data.get("coding", [])
        if not codings or not isinstance(codings, list):
            return ""
        return codings[0].get(subfield, "") or ""
    except (IndexError, AttributeError):
        return ""


def _safe_get_text(resource: Dict[str, Any], field: Optional[str] = None) -> str:
    """Safely extract .text from a CodeableConcept, falling back to display."""
    try:
        data = resource.get(field, {}) if field else resource
        if not isinstance(data, dict):
            return ""
        text = data.get("text", "")
        if text:
            return text
        return _safe_get_coding(resource, field)
    except AttributeError:
        return ""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True
)
async def _fhir_get(client: httpx.AsyncClient, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Make a FHIR GET request and return entries safely with retries."""
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json().get("entry", [])
    except Exception as e:
        # Tenacity will catch the raised error (if any) and retry.
        # If it finally fails after all attempts, we log and return empty.
        logger.warning(f"FHIR request finally failed for {path} after retries: {e}")
        return []


async def fetch_patient_context(patient_id: str, fhir_base_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches a comprehensive clinical snapshot for a patient.
    Parallelized with asyncio.gather for production performance.
    """
    base = fhir_base_url or HAPI_FHIR_BASE
    result = {
        "patient_id": patient_id,
        "patient_info": {},
        "conditions": [],
        "active_medications": [],
        "medication_history": [],
        "observations": [],
        "procedures": [],
        "allergies": [],
        "fetch_errors": []
    }

    async with httpx.AsyncClient(timeout=FHIR_TIMEOUT, base_url=base) as client:
        # Step 1: Patient demographics (must be first or could be parallel)
        try:
            r = await client.get(f"Patient/{patient_id}")
            if r.status_code == 200:
                pt = r.json()
                name_list = pt.get("name", [])
                name = name_list[0] if name_list else {}
                given = " ".join(name.get("given", []))
                family = name.get("family", "")
                result["patient_info"] = {
                    "id": patient_id,
                    "name": f"{given} {family}".strip() or "Unknown",
                    "dob": pt.get("birthDate", "Unknown"),
                    "gender": pt.get("gender", "Unknown"),
                    "active": pt.get("active", True)
                }
        except Exception as e:
            result["fetch_errors"].append(f"Patient demographics: {str(e)}")

        # Step 2: Parallel fetches for clinical resources
        tasks = [
            _fhir_get(client, "Condition", {"patient": patient_id, "clinical-status": "active", "_count": 30, "_sort": "-recorded-date"}),
            _fhir_get(client, "MedicationRequest", {"patient": patient_id, "status": "active", "_count": 30, "_sort": "-authoredon"}),
            _fhir_get(client, "MedicationStatement", {"patient": patient_id, "_count": 40, "_sort": "-effective"}),
            _fhir_get(client, "Observation", {"patient": patient_id, "_count": 50, "_sort": "-date", "status": "final,amended,corrected"}),
            _fhir_get(client, "Procedure", {"patient": patient_id, "_count": 25, "_sort": "-date"}),
            _fhir_get(client, "AllergyIntolerance", {"patient": patient_id, "_count": 20, "clinical-status": "active"})
        ]

        # Use gather to run all clinical queries in parallel
        clinical_data = await asyncio.gather(*tasks, return_exceptions=True)

        # Parse Conditions
        if not isinstance(clinical_data[0], Exception):
            result["conditions"] = [
                {
                    "code": _safe_get_coding(e["resource"], "code", "code"),
                    "display": _safe_get_text(e["resource"], "code"),
                    "system": _safe_get_coding(e["resource"], "code", "system"),
                    "clinical_status": _safe_get_coding(e["resource"].get("clinicalStatus", {}), None, "code"),
                    "onset": e["resource"].get("onsetDateTime", e["resource"].get("recordedDate", "Unknown")),
                    "note": e["resource"].get("note", [{}])[0].get("text", "") if e["resource"].get("note") else ""
                }
                for e in clinical_data[0] if "resource" in e
            ]

        # Parse Medication Requests
        if not isinstance(clinical_data[1], Exception):
            result["active_medications"] = [
                {
                    "name": _safe_get_text(e["resource"], "medicationCodeableConcept"),
                    "rxnorm_code": _safe_get_coding(e["resource"], "medicationCodeableConcept", "code"),
                    "status": e["resource"].get("status", ""),
                    "intent": e["resource"].get("intent", ""),
                    "authored_on": e["resource"].get("authoredOn", ""),
                    "dosage": e["resource"].get("dosageInstruction", [{}])[0].get("text", "") if e["resource"].get("dosageInstruction") else "",
                    "reason": _safe_get_text(e["resource"].get("reasonCode", [{}])[0] if e["resource"].get("reasonCode") else {})
                }
                for e in clinical_data[1] if "resource" in e
            ]

        # Parse Medication History
        if not isinstance(clinical_data[2], Exception):
            result["medication_history"] = [
                {
                    "name": _safe_get_text(e["resource"], "medicationCodeableConcept"),
                    "rxnorm_code": _safe_get_coding(e["resource"], "medicationCodeableConcept", "code"),
                    "status": e["resource"].get("status", ""),
                    "effective_start": e["resource"].get("effectivePeriod", {}).get("start", e["resource"].get("effectiveDateTime", "Unknown")),
                    "effective_end": e["resource"].get("effectivePeriod", {}).get("end", ""),
                    "reason_stopped": e["resource"].get("statusReason", [{}])[0].get("text", "") if e["resource"].get("statusReason") else "",
                    "note": e["resource"].get("note", [{}])[0].get("text", "") if e["resource"].get("note") else ""
                }
                for e in clinical_data[2] if "resource" in e
            ]

        # Parse Observations
        if not isinstance(clinical_data[3], Exception):
            result["observations"] = [
                {
                    "name": _safe_get_text(e["resource"], "code"),
                    "loinc_code": _safe_get_coding(e["resource"], "code", "code"),
                    "value": (
                        e["resource"].get("valueQuantity", {}).get("value")
                        or e["resource"].get("valueString")
                        or e["resource"].get("valueCodeableConcept", {}).get("text", "")
                    ),
                    "unit": e["resource"].get("valueQuantity", {}).get("unit", ""),
                    "interpretation": _safe_get_coding(e["resource"].get("interpretation", [{}])[0], None, "code"),
                    "date": e["resource"].get("effectiveDateTime", ""),
                    "status": e["resource"].get("status", "")
                }
                for e in clinical_data[3] if "resource" in e
            ]

        # Parse Procedures
        if not isinstance(clinical_data[4], Exception):
            result["procedures"] = [
                {
                    "name": _safe_get_text(e["resource"], "code"),
                    "cpt_code": _safe_get_coding(e["resource"], "code", "code"),
                    "status": e["resource"].get("status", ""),
                    "date": e["resource"].get("performedDateTime", e["resource"].get("performedPeriod", {}).get("start", "Unknown")),
                    "outcome": e["resource"].get("outcome", {}).get("text", "") or _safe_get_text(e["resource"].get("outcome", {}))
                }
                for e in clinical_data[4] if "resource" in e
            ]

        # Parse Allergies
        if not isinstance(clinical_data[5], Exception):
            result["allergies"] = [
                {
                    "substance": _safe_get_text(e["resource"], "code"),
                    "type": e["resource"].get("type", ""),
                    "category": e["resource"].get("category", []),
                    "criticality": e["resource"].get("criticality", ""),
                    "reaction": e["resource"].get("reaction", [{}])[0].get("manifestation", [{}])[0].get("text", "") if e["resource"].get("reaction") else ""
                }
                for e in clinical_data[5] if "resource" in e
            ]

    return result
