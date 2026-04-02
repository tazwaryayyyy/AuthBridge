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

import copy

logger = logging.getLogger(__name__)

HAPI_FHIR_BASE = "https://hapi.fhir.org/baseR4"
FHIR_TIMEOUT = 20.0

# Pre-canned synthetic patient data for demo/testing reliability
SYNTHETIC_PATIENTS = {
    "synthetic-crohns-001": {
        "patient_id": "synthetic-crohns-001",
        "patient_info": {
            "id": "synthetic-crohns-001",
            "name": "Sarah Thompson",
            "dob": "1978-04-12",
            "gender": "female",
            "active": True
        },
        "conditions": [
            {
                "code": "K50.90",
                "display": "Crohn's disease of small intestine, moderate-to-severe",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2019-03-15",
                "note": "Confirmed by colonoscopy. Harvey-Bradshaw Index 11."
            }
        ],
        "active_medications": [
            {
                "name": "Mesalamine 1.6g delayed-release tablets",
                "rxnorm_code": "795516",
                "status": "active",
                "intent": "order",
                "authored_on": "2022-11-15",
                "dosage": "1.6g three times daily",
                "reason": "Crohn's disease maintenance"
            }
        ],
        "medication_history": [
            {
                "name": "Prednisone 40mg oral tablet",
                "rxnorm_code": "312615",
                "status": "stopped",
                "effective_start": "2019-04-01",
                "effective_end": "2020-08-30",
                "reason_stopped": "Inadequate disease control and significant side effects: weight gain, mood lability, adrenal suppression",
                "note": "Two courses failed. Relapsed within 4 weeks of each taper."
            },
            {
                "name": "Azathioprine 150mg oral tablet",
                "rxnorm_code": "1310149",
                "status": "stopped",
                "effective_start": "2020-09-15",
                "effective_end": "2022-10-01",
                "reason_stopped": "Inadequate therapeutic response after 2 years. HBI remained 8-10 throughout.",
                "note": "Maximum dose achieved. Liver enzymes stable."
            },
            {
                "name": "Methotrexate 25mg subcutaneous weekly",
                "rxnorm_code": "105586",
                "status": "stopped",
                "effective_start": "2022-10-10",
                "effective_end": "2023-02-28",
                "reason_stopped": "Hepatotoxicity — ALT 3x ULN at 16 weeks. Discontinued per gastroenterology.",
                "note": "5 months trial at full therapeutic dose."
            }
        ],
        "observations": [
            {"name": "C-Reactive Protein", "loinc_code": "1988-5", "value": 18.7, "unit": "mg/L", "interpretation": "H", "date": "2025-12-10", "status": "final"},
            {"name": "Tuberculin skin test (TST)", "loinc_code": "11475-1", "value": "Negative", "unit": "", "interpretation": "N", "date": "2025-11-28", "status": "final"},
            {"name": "Hepatitis B surface antigen", "loinc_code": "5196-1", "value": "Negative", "unit": "", "interpretation": "N", "date": "2025-11-28", "status": "final"},
            {"name": "Harvey-Bradshaw Index (HBI)", "loinc_code": "89242-9", "value": 11, "unit": "score", "interpretation": "H", "date": "2025-12-05", "status": "final"},
            {"name": "Fecal calprotectin", "loinc_code": "27925-7", "value": 842, "unit": "ug/g", "interpretation": "H", "date": "2025-12-05", "status": "final"}
        ],
        "procedures": [
            {"name": "Colonoscopy with biopsy", "cpt_code": "45380", "status": "completed", "date": "2019-03-15", "outcome": "Moderate-to-severe ileocolonic Crohn's disease. Multiple ulcerations in terminal ileum."},
            {"name": "CT enterography", "cpt_code": "74178", "status": "completed", "date": "2025-10-22", "outcome": "Active transmural inflammation of terminal ileum with mesenteric stranding."}
        ],
        "allergies": [{"substance": "Penicillin", "type": "allergy", "category": ["medication"], "criticality": "high", "reaction": "anaphylaxis"}],
        "clinical_notes": [],
        "fetch_errors": []
    },
    "synthetic-nsclc-003": {
        "patient_id": "synthetic-nsclc-003",
        "patient_info": {
            "id": "synthetic-nsclc-003",
            "name": "Robert Chen",
            "dob": "1959-11-22",
            "gender": "male",
            "active": True
        },
        "conditions": [
            {
                "code": "C34.10",
                "display": "Malignant neoplasm of upper lobe, bronchus or lung, unspecified side",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2025-10-05",
                "note": "Stage IIIB NSCLC. PD-L1 TPS 72%. EGFR negative. ALK negative."
            }
        ],
        "active_medications": [
            {"name": "Dexamethasone 4mg oral tablet", "rxnorm_code": "197590", "status": "active", "intent": "order", "authored_on": "2025-10-10", "dosage": "4mg twice daily", "reason": "Supportive care — lung cancer"}
        ],
        "medication_history": [],
        "observations": [
            {"name": "PD-L1 Tumor Proportion Score", "loinc_code": "85319-2", "value": 72, "unit": "%", "interpretation": "H", "date": "2025-10-12", "status": "final"},
            {"name": "EGFR mutation status", "loinc_code": "53037-8", "value": "Wildtype (negative)", "unit": "", "interpretation": "N", "date": "2025-10-12", "status": "final"},
            {"name": "ALK rearrangement status", "loinc_code": "72518-4", "value": "Negative", "unit": "", "interpretation": "N", "date": "2025-10-12", "status": "final"},
            {"name": "ECOG Performance Status", "loinc_code": "89243-7", "value": 1, "unit": "score", "interpretation": "N", "date": "2025-10-08", "status": "final"}
        ],
        "procedures": [
            {"name": "CT-guided core needle biopsy of lung mass", "cpt_code": "32405", "status": "completed", "date": "2025-10-05", "outcome": "Non-small cell lung carcinoma, adenocarcinoma type. PD-L1 72%."},
            {"name": "PET-CT scan", "cpt_code": "78816", "status": "completed", "date": "2025-10-08", "outcome": "Stage IIIB disease. No distant metastases identified."}
        ],
        "allergies": [],
        "clinical_notes": [],
        "fetch_errors": []
    },
    "synthetic-endo-004": {
        "patient_id": "synthetic-endo-004",
        "patient_info": {
            "id": "synthetic-endo-004",
            "name": "Maya Patel",
            "dob": "1991-06-14",
            "gender": "female",
            "active": True
        },
        "conditions": [
            {
                "code": "N80.1",
                "display": "Endometriosis of ovary",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2022-04-10",
                "note": "Confirmed by laparoscopy. Stage III endometriosis. Bilateral ovarian endometriomas."
            },
            {
                "code": "N80.3",
                "display": "Endometriosis of pelvic peritoneum",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2022-04-10",
                "note": "Identified during diagnostic laparoscopy."
            }
        ],
        "active_medications": [
            {"name": "Ibuprofen 800mg oral tablet", "rxnorm_code": "197805", "status": "active", "intent": "order", "authored_on": "2023-01-10", "dosage": "800mg three times daily with food", "reason": "Endometriosis-associated pelvic pain — inadequate control"}
        ],
        "medication_history": [
            {
                "name": "Norethindrone 5mg oral tablet",
                "rxnorm_code": "861005",
                "status": "stopped",
                "effective_start": "2022-06-01",
                "effective_end": "2022-12-15",
                "reason_stopped": "Inadequate pain control. NRS pain score remained 7/10 throughout. Breakthrough bleeding requiring discontinuation.",
                "note": "6 months trial at therapeutic dose."
            },
            {
                "name": "Combined oral contraceptive (ethinyl estradiol/levonorgestrel)",
                "rxnorm_code": "748856",
                "status": "stopped",
                "effective_start": "2021-03-01",
                "effective_end": "2022-03-01",
                "reason_stopped": "Inadequate dysmenorrhea control. Pain NRS 6-8/10 despite 12 months of continuous use.",
                "note": "Continuous dosing regimen attempted."
            }
        ],
        "observations": [
            {"name": "Pelvic pain NRS score (dysmenorrhea)", "loinc_code": "72514-3", "value": 8, "unit": "/10", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Non-menstrual pelvic pain NRS score", "loinc_code": "72514-3", "value": 6, "unit": "/10", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Bone mineral density (DEXA) — lumbar spine", "loinc_code": "24701-5", "value": -0.8, "unit": "T-score", "interpretation": "N", "date": "2025-11-15", "status": "final"}
        ],
        "procedures": [
            {"name": "Diagnostic and operative laparoscopy", "cpt_code": "49320", "status": "completed", "date": "2022-04-10", "outcome": "Stage III endometriosis confirmed. Bilateral endometriomas excised. Deep infiltrating endometriosis of pelvic peritoneum identified."}
        ],
        "allergies": [],
        "clinical_notes": [],
        "fetch_errors": []
    },
    "synthetic-t2dm-002": {
        "patient_id": "synthetic-t2dm-002",
        "patient_info": {"id": "synthetic-t2dm-002", "name": "Marcus Johnson", "dob": "1965-09-03", "gender": "male", "active": True},
        "conditions": [
            {"code": "E11.65", "display": "Type 2 diabetes mellitus with hyperglycemia", "system": "http://hl7.org/fhir/sid/icd-10-cm", "clinical_status": "active", "onset": "2018-06-10", "note": "Inadequately controlled despite maximum dose metformin."}
        ],
        "active_medications": [
            {"name": "Metformin 1000mg tablet", "rxnorm_code": "861009", "status": "active", "intent": "order", "authored_on": "2018-07-01", "dosage": "1000mg twice daily — maximum tolerated dose", "reason": "Type 2 Diabetes"}
        ],
        "medication_history": [
            {"name": "Metformin 500mg tablet", "rxnorm_code": "861004", "status": "stopped", "effective_start": "2018-07-01", "effective_end": "2019-01-15", "reason_stopped": "Dose titrated upward", "note": "Titrated to max 2000mg/day"}
        ],
        "observations": [
            {"name": "Hemoglobin A1c", "loinc_code": "4548-4", "value": 8.9, "unit": "%", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Body Mass Index", "loinc_code": "39156-5", "value": 34.2, "unit": "kg/m2", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Estimated Glomerular Filtration Rate", "loinc_code": "33914-3", "value": 52, "unit": "mL/min/1.73m2", "interpretation": "L", "date": "2025-12-01", "status": "final"}
        ],
        "procedures": [],
        "allergies": [],
        "clinical_notes": [],
        "fetch_errors": []
    },
    "synthetic-messy-005": {
        "patient_id": "synthetic-messy-005",
        "patient_info": {
            "id": "synthetic-messy-005",
            "name": "Alex Chen",
            "dob": "1985-09-23",
            "gender": "male",
            "active": True
        },
        "conditions": [
            {
                "code": "K50.90",
                "display": "Crohn's disease",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2020-01-15"
            },
            {
                "code": "K52.9",
                "display": "Crohn's disease of large intestine", 
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2020-06-20"
            }
        ],
        "active_medications": [
            {
                "name": "Prednisone",
                "rxnorm_code": "7648",
                "status": "completed",
                "intent": "order",
                "authored_on": "2019-04-01",
                "dosage": "40mg",
                "reason": "Acute flare"
            }
        ],
        "medication_history": [
            {
                "drug": "Azathioprine",
                "status": "unknown",
                "date_range": "2019-2020"
            }
        ],
        "observations": [
            {
                "code": "18.7",
                "display": "CRP",
                "value": "18.7",
                "unit": "mg/L",
                "interpretation": "High",
                "date_recorded": "2023-03-15"
            }
        ],
        "data_quality": "messy",
        "quality_issues": [
            "Missing medication history for failed methotrexate trial",
            "Conflicting diagnosis codes for same condition",
            "Lab value out of expected range but ambiguous"
        ]
    }
}


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
    response = await client.get(path, params=params)
    response.raise_for_status()
    return response.json().get("entry", [])


async def fetch_patient_context(patient_id: str, fhir_base_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches a comprehensive clinical snapshot for a patient.
    Parallelized with asyncio.gather for production performance.
    """
    # Check for synthetic test IDs first (fallback for demo reliability)
    if patient_id in SYNTHETIC_PATIENTS:
        logger.info(f"Using synthetic fallback data for patient: {patient_id}")
        return copy.deepcopy(SYNTHETIC_PATIENTS[patient_id])

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
        "clinical_notes": [],
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
            _fhir_get(client, "AllergyIntolerance", {"patient": patient_id, "_count": 20, "clinical-status": "active"}),
            _fhir_get(client, "DocumentReference", {"patient": patient_id, "_count": 10, "_sort": "-date"})
        ]

        # Use gather to run all clinical queries in parallel
        clinical_data = await asyncio.gather(*tasks, return_exceptions=True)

        if isinstance(clinical_data[0], Exception):
            result["fetch_errors"].append(f"Conditions Error: {str(clinical_data[0])}")
        else:
            result["conditions"] = [
                {
                    "code": _safe_get_coding(e["resource"], "code", "code"),
                    "display": _safe_get_text(e["resource"], "code"),
                    "system": _safe_get_coding(e["resource"], "code", "system"),
                    "clinical_status": _safe_get_coding(e["resource"].get("clinicalStatus", {}), None, "code"),
                    "onset": e["resource"].get("onsetDateTime", e["resource"].get("recordedDate", "Unknown")),
                    "note": next(iter(e["resource"].get("note", [])), {}).get("text", "")
                }
                for e in clinical_data[0] if "resource" in e
            ]

        # Parse Medication Requests
        if isinstance(clinical_data[1], Exception):
            result["fetch_errors"].append(f"MedicationRequest Error: {str(clinical_data[1])}")
        else:
            result["active_medications"] = [
                {
                    "name": _safe_get_text(e["resource"], "medicationCodeableConcept"),
                    "rxnorm_code": _safe_get_coding(e["resource"], "medicationCodeableConcept", "code"),
                    "status": e["resource"].get("status", ""),
                    "intent": e["resource"].get("intent", ""),
                    "authored_on": e["resource"].get("authoredOn", ""),
                    "dosage": next(iter(e["resource"].get("dosageInstruction", [])), {}).get("text", ""),
                    "reason": _safe_get_text(next(iter(e["resource"].get("reasonCode", [])), {}))
                }
                for e in clinical_data[1] if "resource" in e
            ]

        # Parse Medication History
        if isinstance(clinical_data[2], Exception):
            result["fetch_errors"].append(f"MedicationStatement Error: {str(clinical_data[2])}")
        else:
            result["medication_history"] = [
                {
                    "name": _safe_get_text(e["resource"], "medicationCodeableConcept"),
                    "rxnorm_code": _safe_get_coding(e["resource"], "medicationCodeableConcept", "code"),
                    "status": e["resource"].get("status", ""),
                    "effective_start": e["resource"].get("effectivePeriod", {}).get("start", e["resource"].get("effectiveDateTime", "Unknown")),
                    "effective_end": e["resource"].get("effectivePeriod", {}).get("end", ""),
                    "reason_stopped": next(iter(e["resource"].get("statusReason", [])), {}).get("text", ""),
                    "note": next(iter(e["resource"].get("note", [])), {}).get("text", "")
                }
                for e in clinical_data[2] if "resource" in e
            ]

        # Parse Observations
        if isinstance(clinical_data[3], Exception):
            result["fetch_errors"].append(f"Observation Error: {str(clinical_data[3])}")
        else:
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
                    "interpretation": _safe_get_coding(next(iter(e["resource"].get("interpretation", [])), {}), None, "code"),
                    "date": e["resource"].get("effectiveDateTime", ""),
                    "status": e["resource"].get("status", "")
                }
                for e in clinical_data[3] if "resource" in e
            ]

        # Parse Procedures
        if isinstance(clinical_data[4], Exception):
            result["fetch_errors"].append(f"Procedure Error: {str(clinical_data[4])}")
        else:
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
        if isinstance(clinical_data[5], Exception):
            result["fetch_errors"].append(f"AllergyIntolerance Error: {str(clinical_data[5])}")
        else:
            result["allergies"] = [
                {
                    "substance": _safe_get_text(e["resource"], "code"),
                    "type": e["resource"].get("type", ""),
                    "category": e["resource"].get("category", []),
                    "criticality": e["resource"].get("criticality", ""),
                    "reaction": next(iter(next(iter(e["resource"].get("reaction", [])), {}).get("manifestation", [])), {}).get("text", "")
                }
                for e in clinical_data[5] if "resource" in e
            ]

        # Parse DocumentReference
        if len(clinical_data) > 6:
            if isinstance(clinical_data[6], Exception):
                result["fetch_errors"].append(f"DocumentReference Error: {str(clinical_data[6])}")
            else:
                result["clinical_notes"] = [
                    next(iter(e["resource"].get("content", [])), {}).get("attachment", {}).get("data", "")
                    for e in clinical_data[6] if "resource" in e
                ]

    return result
