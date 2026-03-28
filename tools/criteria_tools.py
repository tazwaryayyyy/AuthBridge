"""
AuthBridge Criteria Tools
Looks up payer PA criteria and scores clinical evidence match using LLM reasoning.
"""

import json
import os
import logging
import re
from pathlib import Path
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

_client = None
_criteria_db = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=os.environ.get("GITHUB_TOKEN")
        )
    return _client


def _load_criteria() -> dict:
    global _criteria_db
    if _criteria_db is None:
        criteria_path = Path(__file__).parent.parent / "data" / "payer_criteria.json"
        with open(criteria_path, "r") as f:
            _criteria_db = json.load(f)
    return _criteria_db


def _fuzzy_match_drug(drug_name: str, criteria_db: dict) -> Optional[tuple[str, dict]]:
    """
    Attempts fuzzy matching of a drug name against the criteria database.
    Checks drug_key, drug_name field, and brand_names list.
    Returns (key, drug_data) if found, None otherwise.
    """
    query = drug_name.lower().strip()
    # Remove common suffixes
    query_clean = re.sub(r'\s*\(.*?\)', '', query).strip()

    for key, drug_data in criteria_db.items():
        # Check key
        if query_clean in key or key in query_clean:
            return key, drug_data
        # Check drug_name field
        if query_clean in drug_data["drug_name"].lower() or drug_data["drug_name"].lower() in query_clean:
            return key, drug_data
        # Check brand names
        for brand in drug_data.get("brand_names", []):
            if query_clean in brand or brand in query_clean:
                return key, drug_data

    return None


async def lookup_pa_criteria(drug_name: str, indication: Optional[str] = None) -> dict:
    """
    Looks up prior authorization clinical criteria for a given drug name.

    Searches the AuthBridge payer criteria database by drug name, brand name,
    or generic name. If not found, generates synthetic criteria using the LLM
    based on publicly documented clinical guidelines.

    Args:
        drug_name: Generic or brand name of the drug requiring PA
        indication: Optional specific indication to filter results

    Returns:
        dict with keys: found, drug_key, indication_matched, criteria_data, source
    """
    criteria_db = _load_criteria()
    match = _fuzzy_match_drug(drug_name, criteria_db)

    if match:
        key, drug_data = match
        indications = drug_data.get("indications", [])

        # If indication filter provided, try to match
        matched_indication = indications[0]  # default to first
        if indication and len(indications) > 1:
            indication_lower = indication.lower()
            for ind in indications:
                if any(word in ind["name"].lower() for word in indication_lower.split()):
                    matched_indication = ind
                    break

        return {
            "found": True,
            "drug_key": key,
            "drug_name": drug_data["drug_name"],
            "drug_class": drug_data.get("drug_class", ""),
            "indication_matched": matched_indication["name"],
            "icd10_codes": matched_indication.get("icd10_codes", []),
            "required_criteria": matched_indication.get("required_criteria", []),
            "step_therapy_required": matched_indication.get("step_therapy_required", []),
            "supporting_fhir_resources": matched_indication.get("supporting_fhir_resources", []),
            "clinical_guideline": matched_indication.get("clinical_guideline", ""),
            "typical_payers": matched_indication.get("typical_payers", []),
            "source": "authbridge_criteria_database"
        }

    # Fallback: LLM-generated synthetic criteria
    logger.info(f"Drug '{drug_name}' not in database — generating synthetic criteria via LLM")
    client = _get_client()

    prompt = f"""You are a clinical pharmacist and prior authorization specialist.
The drug '{drug_name}' was not found in the database.
Generate realistic but completely SYNTHETIC prior authorization criteria based on
publicly documented clinical guidelines for this drug class.

Return ONLY valid JSON (no markdown, no explanation) with this exact structure:
{{
  "drug_name": "<full generic + brand name>",
  "drug_class": "<pharmacological class>",
  "indication_matched": "<primary FDA-approved indication>",
  "icd10_codes": ["<list of relevant ICD-10 codes>"],
  "required_criteria": ["<list of 4-6 realistic PA criteria>"],
  "step_therapy_required": ["<list of drugs that must be tried first, if any>"],
  "supporting_fhir_resources": ["<list of FHIR R4 resource types needed>"],
  "clinical_guideline": "<name of relevant clinical guideline>",
  "typical_payers": ["UnitedHealthcare", "Aetna", "BCBS"]
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.15,
            max_tokens=800
        )
        raw = response.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        generated = json.loads(raw)
        generated["found"] = False
        generated["drug_key"] = drug_name.lower().replace(" ", "_")
        generated["source"] = "llm_generated_synthetic"
        return generated
    except Exception as e:
        return {
            "found": False,
            "drug_key": drug_name.lower(),
            "drug_name": drug_name,
            "error": f"Could not generate criteria: {str(e)}",
            "required_criteria": [],
            "step_therapy_required": [],
            "source": "error"
        }


async def score_clinical_match(patient_context: dict, pa_criteria: dict) -> dict:
    """
    Scores how well a patient's clinical FHIR record matches payer PA criteria.

    Uses LLM reasoning to analyze each criterion against available clinical evidence.
    Returns a structured match report with score, matched criteria, missing criteria,
    and a clinical summary suitable for inclusion in a PA letter.

    Args:
        patient_context: Output from fetch_patient_context
        pa_criteria: Output from lookup_pa_criteria

    Returns:
        dict with: score (0-100), recommendation, matched_criteria, missing_criteria,
        step_therapy_evidence, missing_step_therapy, flags, clinical_summary
    """

    # Build a clean, concise representation of patient data for the prompt
    conditions_str = json.dumps([
        f"{c['display']} ({c['code']}) — onset {c['onset']}"
        for c in patient_context.get("conditions", [])[:15]
    ], indent=2)

    active_meds_str = json.dumps([
        f"{m['name']} ({m['rxnorm_code']}) — since {m['authored_on']}"
        for m in patient_context.get("active_medications", [])[:15]
    ], indent=2)

    med_history_str = json.dumps([
        f"{m['name']} — status: {m['status']} — {m['effective_start']} to {m['effective_end'] or 'present'} — stopped: {m.get('reason_stopped', 'not documented')}"
        for m in patient_context.get("medication_history", [])[:20]
    ], indent=2)

    obs_str = json.dumps([
        f"{o['name']}: {o['value']} {o['unit']} (date: {o['date']})"
        for o in patient_context.get("observations", [])[:20]
    ], indent=2)

    procedures_str = json.dumps([
        f"{p['name']} — status: {p['status']} — date: {p['date']}"
        for p in patient_context.get("procedures", [])[:10]
    ], indent=2)

    allergies_str = json.dumps([
        f"{a['substance']} ({a['criticality']})"
        for a in patient_context.get("allergies", [])[:10]
    ], indent=2)

    prompt = f"""You are a senior clinical pharmacist conducting a prior authorization review for a health insurance company.

== PRIOR AUTHORIZATION REQUEST ==
Drug: {pa_criteria.get('drug_name', 'Unknown')}
Indication: {pa_criteria.get('indication_matched', 'Unknown')}
Drug class: {pa_criteria.get('drug_class', '')}

Required PA criteria:
{json.dumps(pa_criteria.get('required_criteria', []), indent=2)}

Step therapy drugs required (patient must have tried these first):
{json.dumps(pa_criteria.get('step_therapy_required', []), indent=2)}

Relevant clinical guidelines: {pa_criteria.get('clinical_guideline', 'N/A')}

== PATIENT CLINICAL RECORD ==
Patient: {patient_context.get('patient_info', {}).get('name', 'Unknown')}
DOB: {patient_context.get('patient_info', {}).get('dob', 'Unknown')}
Gender: {patient_context.get('patient_info', {}).get('gender', 'Unknown')}

Active Conditions:
{conditions_str}

Active Medications (current prescriptions):
{active_meds_str}

Medication History (all past medications):
{med_history_str}

Recent Lab Results and Vitals:
{obs_str}

Procedures:
{procedures_str}

Known Allergies:
{allergies_str}

== INSTRUCTIONS ==
Analyze the patient's complete clinical record against each required criterion and step therapy requirement.
Be thorough — look for indirect evidence (e.g., a note about "failed methotrexate" counts as step therapy).
Consider generic AND brand name equivalents for step therapy drugs.

Return ONLY valid JSON with this exact structure:
{{
  "score": <integer 0-100 representing overall PA approval likelihood>,
  "recommendation": "<APPROVE|LIKELY_APPROVE|NEEDS_MORE_INFO|LIKELY_DENY|DENY>",
  "matched_criteria": [
    "<Each required criterion that is clearly documented in the patient record>"
  ],
  "missing_criteria": [
    "<Each required criterion with no supporting evidence in the record — include specific suggestion for what documentation is needed>"
  ],
  "step_therapy_evidence": [
    "<Step therapy drug name> — <evidence found: dates, status, outcome>"
  ],
  "missing_step_therapy": [
    "<Step therapy drug with no evidence in patient record>"
  ],
  "flags": [
    "<Any clinical safety flags, contraindications, or risk factors identified>"
  ],
  "clinical_summary": "<3-4 sentence clinical narrative summarizing the patient's case and why this drug is or isn't indicated>",
  "evidence_strength": "<STRONG|MODERATE|WEAK>",
  "recommended_additional_docs": [
    "<Specific additional documentation that would strengthen the PA request>"
  ]
}}"""

    client = _get_client()
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500
        )
        raw = response.choices[0].message.content.strip()
        # Robustly extract JSON from potential markdown blocks
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        result = json.loads(raw)
        return result
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error in score_clinical_match: {e}")
        return {
            "score": 0,
            "recommendation": "ERROR",
            "error": f"Failed to parse LLM response: {str(e)}",
            "matched_criteria": [],
            "missing_criteria": ["Unable to analyze — JSON parse error"],
            "step_therapy_evidence": [],
            "missing_step_therapy": [],
            "flags": ["Analysis failed — manual review required"],
            "clinical_summary": "Automated analysis failed. Manual clinical review required.",
            "evidence_strength": "WEAK",
            "recommended_additional_docs": []
        }
    except Exception as e:
        logger.error(f"Unexpected error in score_clinical_match: {e}")
        return {
            "score": 0,
            "recommendation": "ERROR",
            "error": str(e),
            "matched_criteria": [],
            "missing_criteria": [],
            "step_therapy_evidence": [],
            "missing_step_therapy": [],
            "flags": [],
            "clinical_summary": f"Analysis error: {str(e)}",
            "evidence_strength": "WEAK",
            "recommended_additional_docs": []
        }
