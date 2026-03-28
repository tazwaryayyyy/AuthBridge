"""
AuthBridge Letter Tools
Drafts clinical PA justification letters and appeal letters.
Includes CMS-0057-F urgency headers and FHIR evidence trail integration.
Updated for non-blocking AsyncOpenAI performance.
"""

import json
import os
import re
import logging
import asyncio
from datetime import date
from typing import Optional, Dict, Any
from openai import AsyncOpenAI
from tools.criteria_tools import build_evidence_citations, format_evidence_trail, get_async_client

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


async def draft_pa_letter(
    drug_name: str,
    pa_criteria: dict,
    match_result: dict,
    patient_context: dict,
    prescriber_name: Optional[str] = None,
    prescriber_npi: Optional[str] = None,
    prescriber_specialty: Optional[str] = None,
    prescriber_phone: Optional[str] = None,
    practice_name: Optional[str] = None
) -> dict:
    """
    Drafts a complete payer-ready PA justification letter.
    Uses AsyncOpenAI for non-blocking clinical drafting.
    """
    today = date.today().strftime("%B %d, %Y")
    patient_info = patient_context.get("patient_info", {})
    patient_name = patient_info.get("name", "Patient")
    patient_dob = patient_info.get("dob", "See records")
    patient_id_display = patient_context.get("patient_id", "See records")

    prescriber_block = prescriber_name or "Attending Physician"
    prescriber_details = ""
    if prescriber_npi:
        prescriber_details += f"\nNPI: {prescriber_npi}"
    if prescriber_specialty:
        prescriber_details += f"\nSpecialty: {prescriber_specialty}"
    if practice_name:
        prescriber_details += f"\nPractice: {practice_name}"
    if prescriber_phone:
        prescriber_details += f"\nDirect: {prescriber_phone} (available for peer-to-peer review)"

    urgency = match_result.get("urgency", {})
    is_urgent = urgency.get("is_urgent", False)
    urgency_reason = urgency.get("urgency_reason", "")
    cms_timeline = urgency.get("cms_timeline", "")

    evidence_trail = match_result.get("fhir_evidence_trail", [])
    evidence_trail_str = "\n".join(evidence_trail[:12]) if evidence_trail else "See patient record"

    prompt = f"""You are a physician writing a Prior Authorization justification letter.
Write with authority, precision, and strictly grounded clinical facts.

== PARAMETERS ==
Date: {today}
Patient Name: {patient_name}
Date of Birth: {patient_dob}
Patient ID: {patient_id_display}
Prescriber: {prescriber_block}{prescriber_details}

Drug: {drug_name}
Indication: {pa_criteria.get('indication_matched', 'Inadequately controlled condition')}
ICD-10: {', '.join(pa_criteria.get('icd10_codes', [])[:4])}

{'== CMS-0057-F EXPEDITED REVIEW ==' if is_urgent else ''}
{'Urgency: ' + urgency_reason if is_urgent else ''}

== FHIR EVIDENCE TRAIL ==
{evidence_trail_str}

== CLINICAL ANALYSIS ==
Score: {match_result.get('score', 0)}/100
Criteria met: {json.dumps(match_result.get('matched_criteria', []), indent=2)}
Step therapy evidence: {json.dumps(match_result.get('step_therapy_evidence', []), indent=2)}
Summary: {match_result.get('clinical_summary', '')}

== WRITING INSTRUCTIONS ==
{'START WITH: URGENT PRIOR AUTHORIZATION — CMS-0057-F EXPEDITED RESPONSE REQUIRED' if is_urgent else ''}

Write a 5-paragraph justification letter:
1. Patient & request identification.
2. Comprehensive treatment history (step therapy failures).
3. Specific clinical necessity based on FHIR evidence (labs, scores).
4. Alignment with {pa_criteria.get('clinical_guideline', 'clinical guidelines')}.
5. Closing medical necessity and prescriber contact.

No markdown in output. 450-550 words."""

    try:
        client = get_async_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1400
        )
        letter_text = response.choices[0].message.content.strip()

        return {
            "success": True,
            "letter": letter_text,
            "drug": drug_name,
            "patient": patient_name,
            "score": match_result.get("score", 0),
            "is_urgent": is_urgent,
            "urgency_reason": urgency_reason,
            "cms_timeline": cms_timeline,
            "fhir_evidence_trail": evidence_trail,
            "word_count": len(letter_text.split())
        }
    except Exception as e:
        logger.error(f"PA letter generation failed: {e}")
        return {"success": False, "error": str(e), "drug": drug_name, "patient": patient_name}


async def draft_appeal_letter(
    drug_name: str,
    denial_reason: str,
    pa_criteria: dict,
    patient_context: dict,
    prescriber_name: Optional[str] = None,
    prescriber_npi: Optional[str] = None,
    prescriber_specialty: Optional[str] = None,
    prescriber_phone: Optional[str] = None,
    practice_name: Optional[str] = None,
    denial_date: Optional[str] = None,
    reference_number: Optional[str] = None
) -> dict:
    """
    Drafts a formal PA appeal letter contesting a payer denial.
    Uses AsyncOpenAI.
    """
    today = date.today().strftime("%B %d, %Y")
    patient_info = patient_context.get("patient_info", {})
    patient_name = patient_info.get("name", "Patient")
    patient_dob = patient_info.get("dob", "See medical record")

    prescriber_block = prescriber_name or "Attending Physician"
    prescriber_details = ""
    if prescriber_npi:
        prescriber_details += f"\nNPI: {prescriber_npi}"
    if prescriber_specialty:
        prescriber_details += f"\nSpecialty: {prescriber_specialty}"
    if prescriber_phone:
        prescriber_details += f"\nDirect Line: {prescriber_phone}"
    if practice_name:
        prescriber_details += f"\nPractice: {practice_name}"

    ref_block = ""
    if reference_number: ref_block = f"\nPA Reference: {reference_number}"
    if denial_date: ref_block += f"\nDenial Date: {denial_date}"

    # Extract citations dynamically if not provided
    citations = build_evidence_citations(patient_context)
    evidence_trail = format_evidence_trail(citations)
    evidence_trail_str = "\n".join(evidence_trail[:10]) if evidence_trail else "See patient record"

    prompt = f"""You are a board-certified physician writing a formal appeal letter for {drug_name}.
Payer's denial: "{denial_reason}"

== PARAMETERS ==
Date: {today}
Patient: {patient_name}, DOB: {patient_dob}
Prescriber: {prescriber_block}{prescriber_details}
{ref_block}

== FHIR EVIDENCE TRAIL ==
{evidence_trail_str}

== WRITING INSTRUCTIONS ==
Write a 6-paragraph firm appeal letter:
1. Formal notice of appeal.
2. Clinical rebuttal of "{denial_reason}" using specific FHIR evidence.
3. Patient-specific clinical necessity and risk assessment.
4. Alignment with {pa_criteria.get('clinical_guideline', 'standard of care')}.
5. Patient safety risk from delay/denial.
6. Demand for peer-to-peer review within 24 hours.

No markdown. 500-650 words."""

    try:
        client = get_async_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=1600
        )
        appeal_text = response.choices[0].message.content.strip()

        return {
            "success": True,
            "appeal_letter": appeal_text,
            "drug": drug_name,
            "patient": patient_name,
            "denial_reason": denial_reason,
            "fhir_evidence_trail": evidence_trail,
            "word_count": len(appeal_text.split()),
            "peer_to_peer_requested": True
        }
    except Exception as e:
        logger.error(f"Appeal letter generation failed: {e}")
        return {"success": False, "error": str(e), "drug": drug_name, "patient": patient_name, "denial_reason": denial_reason}
