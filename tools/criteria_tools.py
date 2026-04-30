"""
AuthBridge Criteria Tools
Looks up payer PA criteria and scores clinical evidence match using LLM reasoning.
Includes urgency detection (CMS-0057-F 72-hour rule) and FHIR evidence citations.
Updated to use AsyncOpenAI for non-blocking clinical reasoning.
"""

import json
import os
import logging
import re
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None
_criteria_db: Optional[dict] = None

def get_async_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN environment variable not set")
        _client = AsyncOpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=token
        )
    return _client

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
async def _llm_call(messages, max_tokens=1500, temperature=0.1):
    return await get_async_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )


def _load_criteria() -> dict:
    global _criteria_db
    if _criteria_db is None:
        criteria_path = Path(__file__).parent.parent / "data" / "payer_criteria.json"
        with open(criteria_path, "r") as f:
            _criteria_db = json.load(f)
    return _criteria_db


def _fuzzy_match_drug(drug_name: str, criteria_db: dict) -> Optional[tuple]:
    query = drug_name.lower().strip()
    query_clean = re.sub(r'\s*\(.*?\)', '', query).strip()

    for key, drug_data in criteria_db.items():
        if query_clean in key or key in query_clean:
            return key, drug_data
        if query_clean in drug_data["drug_name"].lower() or drug_data["drug_name"].lower() in query_clean:
            return key, drug_data
        for brand in drug_data.get("brand_names", []):
            if query_clean in brand or brand in query_clean:
                return key, drug_data
    return None


def detect_urgency(patient_context: dict, drug_name: str, pa_criteria: dict) -> dict:
    """
    Detects whether a PA qualifies for CMS-0057-F expedited 72-hour review.
    Urgent cases: oncology drugs, high-acuity biologics, conditions where
    treatment delay causes irreversible harm.
    """
    urgent_drug_keywords = [
        "pembrolizumab", "keytruda", "nivolumab", "opdivo", "atezolizumab",
        "bevacizumab", "avastin", "trastuzumab", "herceptin", "rituximab",
        "natalizumab", "tysabri", "ocrelizumab", "ocrevus", "checkpoint",
        "immunotherapy", "elagolix", "orilissa", "leuprolide", "lupron",
        "biologic", "chemotherapy", "immunosuppressant"
    ]
    urgent_condition_keywords = [
        "cancer", "malignancy", "carcinoma", "lymphoma", "leukemia", "tumor",
        "metastatic", "nsclc", "lung cancer", "breast cancer", "ovarian",
        "cervical", "endometrial", "multiple sclerosis", "organ failure",
        "transplant", "sepsis", "pulmonary hypertension", "als",
        "endometriosis", "stage 3", "stage 4", "stage iii", "stage iv",
        "active flare", "severe", "life-threatening"
    ]

    drug_lower = drug_name.lower()
    drug_class_lower = pa_criteria.get("drug_class", "").lower()
    indication_lower = pa_criteria.get("indication_matched", "").lower()

    is_urgent = False
    urgency_reason = ""

    for kw in urgent_drug_keywords:
        if kw in drug_lower or kw in drug_class_lower:
            is_urgent = True
            urgency_reason = f"High-acuity clinical profile: {drug_name}"
            break

    if not is_urgent:
        for kw in urgent_condition_keywords:
            if kw in indication_lower:
                is_urgent = True
                urgency_reason = f"Direct risk from delay: {pa_criteria.get('indication_matched', '')}"
                break

    if not is_urgent:
        for condition in patient_context.get("conditions", []):
            display = condition.get("display", "").lower()
            code = condition.get("code", "")
            for kw in urgent_condition_keywords:
                if kw in display:
                    is_urgent = True
                    urgency_reason = f"Active high-acuity condition: {condition.get('display', '')}"
                    break
            if code.startswith("C") and len(code) >= 3:
                is_urgent = True
                urgency_reason = f"Documented active malignancy: {condition.get('display', code)}"
            if is_urgent:
                break

    return {
        "is_urgent": is_urgent,
        "urgency_reason": urgency_reason if is_urgent else "Standard review criteria apply",
        "cms_timeline": "72-hour payer response required — CMS-0057-F expedited review" if is_urgent else "7 calendar days — standard review per CMS-0057-F",
        "cms_rule": "CMS Interoperability and Prior Authorization Final Rule (CMS-0057-F)"
    }


def build_evidence_citations(patient_context: dict) -> list:
    """
    Builds a structured FHIR evidence citation trail.
    Publicly exported for use in letter generation.
    """
    citations = []

    # Conditions
    for condition in patient_context.get("conditions", []):
        if condition.get("display"):
            citations.append({
                "type": "Condition",
                "resource": f"Condition/{condition.get('code', 'unknown')}",
                "description": condition.get("display", ""),
                "date": condition.get("onset", "unknown"),
                "relevance": "Direct diagnostic confirmation"
            })

    # Medications (Active)
    for med in patient_context.get("active_medications", []):
        if med.get("name"):
            citations.append({
                "type": "MedicationRequest",
                "resource": f"MedicationRequest/{med.get('rxnorm_code', 'unknown')}",
                "description": med.get("name", ""),
                "date": med.get("authored_on", "unknown"),
                "relevance": "Active management"
            })

    # Medication History (Step Therapy)
    for med in patient_context.get("medication_history", []):
        if med.get("name") and med.get("status") in ["stopped", "completed", "on-hold"]:
            citations.append({
                "type": "MedicationStatement",
                "resource": f"MedicationStatement/{med.get('rxnorm_code', 'unknown')}",
                "description": f"{med.get('name', '')} — {med.get('status', '')}",
                "date": f"{med.get('effective_start', '?')} to {med.get('effective_end', 'present')}",
                "relevance": f"Step therapy failure: {med.get('reason_stopped', 'discontinued')}"
            })

    # Observations
    priority_keywords = [
        "hba1c", "crp", "tb", "hepatitis", "creatinine", "egfr", "bmi",
        "calprotectin", "hbi", "pdl1", "egfr", "alk", "ecog", "lvef",
        "easi", "pasi", "das28", "joint", "bone", "dexa"
    ]
    for obs in patient_context.get("observations", []):
        name = obs.get("name", "").lower()
        if any(kw in name for kw in priority_keywords):
            citations.append({
                "type": "Observation",
                "resource": f"Observation/{obs.get('loinc_code', 'unknown')}",
                "description": f"{obs.get('name', '')}: {obs.get('value', '')} {obs.get('unit', '')}".strip(),
                "date": obs.get("date", "unknown"),
                "relevance": "Supporting clinical metric"
            })

    # Procedures
    for proc in patient_context.get("procedures", []):
        if proc.get("name"):
            citations.append({
                "type": "Procedure",
                "resource": f"Procedure/{proc.get('cpt_code', 'unknown')}",
                "description": f"{proc.get('name', '')} — {proc.get('outcome', '')}",
                "date": proc.get("date", "unknown"),
                "relevance": "Procedure-based confirmation"
            })

    return citations


def format_evidence_trail(citations: list) -> list:
    """Formats citations as readable strings for display."""
    trail = []
    for c in citations:
        line = f"→ {c['type']}/{c.get('resource', 'unknown')} — {c['description']}"
        if c.get("date") and c["date"] not in ("unknown", "? to present"):
            line += f" — {c['date']}"
        if c.get("relevance"):
            line += f" [{c['relevance']}]"
        trail.append(line)
    return trail


def _trim_patient_context(patient_context: dict, max_meds=5, max_obs=5, max_procs=5) -> dict:
    """Create a smaller version of the patient context for LLM prompts."""
    trimmed = {
        "patient_info": patient_context.get("patient_info", {}),
        "conditions": patient_context.get("conditions", [])[:3],  # limit to 3 conditions
        "active_medications": patient_context.get("active_medications", [])[:3],
        "medication_history": patient_context.get("medication_history", [])[:max_meds],
        "observations": patient_context.get("observations", [])[:max_obs],
        "procedures": patient_context.get("procedures", [])[:max_procs],
        "allergies": patient_context.get("allergies", [])[:3],
        "fetch_errors": patient_context.get("fetch_errors", [])
    }
    return trimmed


async def lookup_pa_criteria(drug_name: str, indication: Optional[str] = None, payer: Optional[str] = None) -> dict:
    criteria_db = _load_criteria()
    match = _fuzzy_match_drug(drug_name, criteria_db)

    if match:
        key, drug_data = match
        indications = drug_data.get("indications", [])
        matched_indication = indications[0]

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
            "source": "authbridge_criteria_database",
            "criteria_weights": matched_indication.get("criteria_weights", {})
        }

    logger.info(f"Drug '{drug_name}' not in database — generating via LLM")
    client = get_async_client()

    payer_instruction = f"The criteria must be specific to payer: {payer}." if payer else ""
    typical_payers_str = f'"{payer}"' if payer else '"Aetna", "BCBS"'

    prompt = f"""You are a clinical pharmacist. Generate realistic SYNTHETIC PA criteria for '{drug_name}'.
{payer_instruction}
Return ONLY valid JSON:
{{
  "drug_name": "{drug_name}",
  "drug_class": "<pharmacological class>",
  "indication_matched": "<primary indication>",
  "icd10_codes": ["<ICD-10 codes>"],
  "required_criteria": ["<4-6 PA criteria>"],
  "step_therapy_required": ["<drugs required first>"],
  "supporting_fhir_resources": ["Condition", "Observation"],
  "clinical_guideline": "<relevant guideline>",
  "typical_payers": [{typical_payers_str}]
}}"""

    try:
        response = await _llm_call(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        try:
            generated = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM criteria JSON: {raw[:100]}")
            return {"found": False, "drug_name": drug_name, "error": "JSON parse error", "required_criteria": [], "source": "error"}
            
        generated["found"] = False
        generated["drug_key"] = drug_name.lower().replace(" ", "_")
        generated["source"] = "llm_generated_synthetic"
        return generated
    except Exception as e:
        logger.error(f"LLM criteria generation failed: {e}")
        return {"found": False, "drug_name": drug_name, "error": str(e), "required_criteria": [], "source": "error"}


async def score_clinical_match(patient_context: dict, pa_criteria: dict) -> dict:
    """
    Scores how well a patient's FHIR record matches payer PA criteria.
    Uses AsyncOpenAI for non-blocking clinical reasoning.
    """
    drug_name = pa_criteria.get("drug_name", "Unknown")
    urgency = detect_urgency(patient_context, drug_name, pa_criteria)
    evidence_citations = build_evidence_citations(patient_context)

    # Stringify context for LLM
    trimmed_context = _trim_patient_context(patient_context)

    def _json_summary(items, limit=15):
        return json.dumps(items[:limit], indent=2)

    conditions_str = _json_summary([f"{c['display']} ({c['code']})" for c in trimmed_context.get("conditions", [])])
    active_meds_str = _json_summary([f"{m['name']} ({m['rxnorm_code']})" for m in trimmed_context.get("active_medications", [])])
    med_history_str = _json_summary([f"{m['name']} — {m['status']} — {m.get('reason_stopped', '')}" for m in trimmed_context.get("medication_history", [])])
    obs_str = _json_summary([f"{o['name']}: {o['value']} {o['unit']}" for o in trimmed_context.get("observations", [])])
    procedures_str = _json_summary([f"{p['name']} — {p.get('outcome', '')}" for p in trimmed_context.get("procedures", [])])
    allergies_str = _json_summary([f"{a['substance']} ({a['criticality']})" for a in trimmed_context.get("allergies", [])])
    notes_str = json.dumps(patient_context.get("clinical_notes", [])[:5], indent=2)
    
    criteria_weights_str = json.dumps(pa_criteria.get("criteria_weights", {}), indent=2)

    # Check for data quality issues
    data_quality_warnings = []
    if "data_quality" in patient_context:
        for issue in patient_context.get("data_quality", []):
            data_quality_warnings.append(f"Data quality issue: {issue}")
    
    # Check for uncertain criteria
    uncertain_criteria = []
    criteria_list = pa_criteria.get("required_criteria", [])
    for criterion in criteria_list:
        # Simple heuristic: if criterion mentions multiple drugs or complex conditions, mark as uncertain
        if any(term in criterion.lower() for term in ["or", "either", "multiple", "combination"]):
            uncertain_criteria.append(criterion)
    
    # Add data quality and uncertainty to context for LLM
    trimmed_context = _trim_patient_context(patient_context)
    if data_quality_warnings:
        trimmed_context["data_quality_warnings"] = data_quality_warnings
    if uncertain_criteria:
        trimmed_context["uncertain_criteria"] = uncertain_criteria

    prompt = f"""You are a clinical reviewer. Analyze if the patient meets PA criteria for {drug_name}.

== PA CRITERIA ==
{json.dumps(pa_criteria.get('required_criteria', []), indent=2)}
Step therapy: {json.dumps(pa_criteria.get('step_therapy_required', []), indent=2)}

Criteria weights (CRITICAL items failing = automatic DENY, HIGH items failing = LIKELY_DENY):
{criteria_weights_str}

Apply these weights when calculating score. A CRITICAL criterion not met 
capsizes score at 40. A HIGH criterion not met reduces score by 15 points each.

== PATIENT FHIR SNAPSHOT ==
Conditions: {conditions_str}
Active Meds: {active_meds_str}
History: {med_history_str}
Observations: {obs_str}
Procedures: {procedures_str}
Allergies: {allergies_str}
Clinical notes (unstructured): look for evidence of failed treatments, adverse reactions, or symptom descriptions that support criteria even if not in discrete fields.

Data Quality Warnings: {json.dumps(data_quality_warnings, indent=2)}
Uncertain Criteria: {json.dumps(uncertain_criteria, indent=2)}

Return ONLY valid JSON:
{{
  "score": <0-100>,
  "recommendation": "<APPROVE|DENY|NEEDS_INFO>",
  "matched_criteria": ["<met criteria>"],
  "missing_criteria": ["<missing criteria>"],
  "step_therapy_evidence": ["<drug> — <outcome>"],
  "missing_step_therapy": ["<required drug not found>"],
  "flags": ["<clinical safety flags>"],
  "clinical_summary": "<3 sentence narrative>",
  "evidence_strength": "<STRONG|MODERATE|WEAK>",
  "recommended_additional_docs": ["<specific requests>"]
}}"""

    try:
        response = await _llm_call(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM scoring JSON: {raw[:100]}")
            result = {
                "score": 0, 
                "recommendation": "ERROR", 
                "matched_criteria": [],
                "missing_criteria": [],
                "step_therapy_evidence": [],
                "flags": [],
                "clinical_summary": "LLM Parsing Failure"
            }

        result["urgency"] = urgency
        result["evidence_citations"] = evidence_citations
        result["fhir_evidence_trail"] = format_evidence_trail(evidence_citations)
        result["uncertain_criteria"] = uncertain_criteria

        return result

    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        return {
            "score": 0, "recommendation": "ERROR", "error": str(e),
            "urgency": urgency, "evidence_citations": evidence_citations,
            "fhir_evidence_trail": format_evidence_trail(evidence_citations)
        }

async def ingest_payer_policy(policy_text: str, payer_name: str = "Unknown Payer") -> dict:
    """
    Ingests unstructured payer policy text, extracts structured PA criteria using an LLM,
    and dynamically updates the payer_criteria.json database.
    This demonstrates real-world scalability and dynamic rules engine updates.
    """
    global _criteria_db
    logger.info(f"Ingesting new payer policy for {payer_name}...")
    
    prompt = f"""You are a clinical pharmacoeconomics specialist. 
Extract the Prior Authorization criteria from the following unstructured policy text.
Payer: {payer_name}

POLICY TEXT:
{policy_text[:4000]}

Return ONLY valid JSON in the following format:
{{
  "drug_name": "extracted generic or brand name",
  "drug_class": "extracted class",
  "indication_matched": "primary indication this policy applies to",
  "icd10_codes": ["array of ICD-10 codes if mentioned"],
  "required_criteria": ["array of 4-6 specific clinical requirements"],
  "step_therapy_required": ["array of drugs that must be tried and failed first"],
  "supporting_fhir_resources": ["Condition", "Observation", "MedicationStatement"],
  "clinical_guideline": "any mentioned guideline or simply the payer policy name",
  "typical_payers": ["{payer_name}"],
  "criteria_weights": {{
     "example critical requirement": "CRITICAL",
     "example high requirement": "HIGH"
  }}
}}"""

    try:
        response = await _llm_call(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        
        extracted_data = json.loads(raw)
        
        # Add to local DB
        drug_name = extracted_data.get("drug_name", "Unknown_Drug")
        drug_key = drug_name.lower().replace(" ", "_")
        
        # Load current DB
        criteria_path = Path(__file__).parent.parent / "data" / "payer_criteria.json"
        
        try:
            with open(criteria_path, "r") as f:
                db = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            db = {}
            
        # Update DB
        if drug_key in db:
            # Append indication if it exists
            db[drug_key]["indications"].append(extracted_data)
        else:
            db[drug_key] = {
                "drug_name": drug_name,
                "drug_class": extracted_data.get("drug_class", ""),
                "brand_names": [drug_name],
                "indications": [extracted_data]
            }
            
        try:
            # Save back to file
            with open(criteria_path, "w") as f:
                json.dump(db, f, indent=2)
                
            # Invalidate cache
            _criteria_db = db
        except Exception as file_err:
            logger.warning(f"Could not persist criteria to disk (read-only FS?): {file_err}")
            # Still update the in-memory cache so it works for this session
            _criteria_db = db
            
        return {
            "success": True,
            "message": f"Successfully ingested policy for {drug_name}",
            "extracted_criteria_count": len(extracted_data.get("required_criteria", [])),
            "step_therapy_count": len(extracted_data.get("step_therapy_required", [])),
            "drug_key": drug_key
        }
        
    except Exception as e:
        logger.error(f"Failed to ingest payer policy: {e}")
        return {
            "success": False,
            "error": str(e)
        }

