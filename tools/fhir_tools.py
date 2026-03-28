"""
AuthBridge FHIR Tools
Fetches comprehensive clinical context from a FHIR R4 server.
Uses HAPI FHIR public sandbox by default (synthetic data only).
"""

import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

HAPI_FHIR_BASE = "https://hapi.fhir.org/baseR4"
FHIR_TIMEOUT = 20.0


def _safe_get_coding(resource: dict, field: Optional[str] = None, subfield: str = "display") -> str:
    """Safely extract the first coding value from a FHIR CodeableConcept."""
    try:
        data = resource.get(field, {}) if field else resource
        codings = data.get("coding", [{}])
        return codings[0].get(subfield, "") if codings else ""
    except (IndexError, AttributeError):
        return ""


def _safe_get_text(resource: dict, field: Optional[str] = None) -> str:
    """Safely extract .text from a CodeableConcept."""
    try:
        data = resource.get(field, {}) if field else resource
        return data.get("text", "") or _safe_get_coding(resource, field)
    except AttributeError:
        return ""


async def _fhir_get(client: httpx.AsyncClient, path: str, params: dict) -> list:
    """Make a FHIR GET request and return entries safely."""
    try:
        response = await client.get(f"/{path}", params=params)
        response.raise_for_status()
        return response.json().get("entry", [])
    except Exception as e:
        logger.warning(f"FHIR request failed for {path}: {e}")
        return []


async def fetch_patient_context(patient_id: str, fhir_base_url: Optional[str] = None) -> dict:
    """
    Fetches a comprehensive clinical snapshot for a patient from the FHIR server.

    Retrieves: active conditions, active medications (MedicationRequest),
    medication history (MedicationStatement), recent observations (labs/vitals),
    procedures, allergies, and basic patient demographics.

    Args:
        patient_id: The FHIR patient resource ID
        fhir_base_url: Optional override for the FHIR server base URL

    Returns:
        dict with keys: patient_info, conditions, active_medications,
        medication_history, observations, procedures, allergies, fetch_errors
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

        # Patient demographics
        try:
            r = await client.get(f"/Patient/{patient_id}")
            if r.status_code == 200:
                pt = r.json()
                name = pt.get("name", [{}])[0]
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

        # Active conditions (ICD-10 coded)
        try:
            entries = await _fhir_get(client, "Condition", {
                "patient": patient_id,
                "clinical-status": "active",
                "_count": 30,
                "_sort": "-recorded-date"
            })
            result["conditions"] = [
                {
                    "code": _safe_get_coding(e["resource"], "code", "code"),
                    "display": _safe_get_text(e["resource"], "code"),
                    "system": _safe_get_coding(e["resource"], "code", "system"),
                    "clinical_status": e["resource"].get("clinicalStatus", {}).get("coding", [{}])[0].get("code", ""),
                    "onset": e["resource"].get("onsetDateTime", e["resource"].get("recordedDate", "Unknown")),
                    "note": e["resource"].get("note", [{}])[0].get("text", "") if e["resource"].get("note") else ""
                }
                for e in entries if "resource" in e
            ]
        except Exception as e:
            result["fetch_errors"].append(f"Conditions: {str(e)}")

        # Active medication requests (current prescriptions)
        try:
            entries = await _fhir_get(client, "MedicationRequest", {
                "patient": patient_id,
                "status": "active",
                "_count": 30,
                "_sort": "-authoredon"
            })
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
                for e in entries if "resource" in e
            ]
        except Exception as e:
            result["fetch_errors"].append(f"Active medications: {str(e)}")

        # Medication history (all past medications including stopped/completed)
        try:
            entries = await _fhir_get(client, "MedicationStatement", {
                "patient": patient_id,
                "_count": 40,
                "_sort": "-effective"
            })
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
                for e in entries if "resource" in e
            ]
        except Exception as e:
            result["fetch_errors"].append(f"Medication history: {str(e)}")

        # Recent observations (labs, vitals, scores)
        try:
            entries = await _fhir_get(client, "Observation", {
                "patient": patient_id,
                "_count": 40,
                "_sort": "-date",
                "status": "final,amended,corrected"
            })
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
                    "interpretation": e["resource"].get("interpretation", [{}])[0].get("coding", [{}])[0].get("code", "") if e["resource"].get("interpretation") else "",
                    "date": e["resource"].get("effectiveDateTime", ""),
                    "status": e["resource"].get("status", "")
                }
                for e in entries if "resource" in e
            ]
        except Exception as e:
            result["fetch_errors"].append(f"Observations: {str(e)}")

        # Procedures
        try:
            entries = await _fhir_get(client, "Procedure", {
                "patient": patient_id,
                "_count": 25,
                "_sort": "-date"
            })
            result["procedures"] = [
                {
                    "name": _safe_get_text(e["resource"], "code"),
                    "cpt_code": _safe_get_coding(e["resource"], "code", "code"),
                    "status": e["resource"].get("status", ""),
                    "date": e["resource"].get("performedDateTime", e["resource"].get("performedPeriod", {}).get("start", "Unknown")),
                    "outcome": e["resource"].get("outcome", {}).get("text", "") or _safe_get_text(e["resource"].get("outcome", {}))
                }
                for e in entries if "resource" in e
            ]
        except Exception as e:
            result["fetch_errors"].append(f"Procedures: {str(e)}")

        # Allergies and intolerances
        try:
            entries = await _fhir_get(client, "AllergyIntolerance", {
                "patient": patient_id,
                "_count": 20,
                "clinical-status": "active"
            })
            result["allergies"] = [
                {
                    "substance": _safe_get_text(e["resource"], "code"),
                    "type": e["resource"].get("type", ""),
                    "category": e["resource"].get("category", []),
                    "criticality": e["resource"].get("criticality", ""),
                    "reaction": e["resource"].get("reaction", [{}])[0].get("manifestation", [{}])[0].get("text", "") if e["resource"].get("reaction") else ""
                }
                for e in entries if "resource" in e
            ]
        except Exception as e:
            result["fetch_errors"].append(f"Allergies: {str(e)}")

    return result
