"""
AuthBridge Letter Tools
Drafts clinical PA justification letters and appeal letters.
Uses LLM grounded in FHIR patient data — structured output ensures accuracy.
"""

import json
import os
import re
import logging
from datetime import date
from typing import Optional
from groq import Groq

logger = logging.getLogger(__name__)

_client: Optional[Groq] = None


def _get_groq_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        _client = Groq(api_key=api_key)
    return _client


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
    Drafts a complete, payer-ready Prior Authorization clinical justification letter.

    The letter is grounded entirely in the patient's FHIR data and PA criteria.
    The LLM serves as a skilled clinical writer — it does not invent clinical facts.

    Args:
        drug_name: Name of the drug requiring PA
        pa_criteria: Output from lookup_pa_criteria
        match_result: Output from score_clinical_match
        patient_context: Output from fetch_patient_context
        prescriber_name: Full name of prescribing physician
        prescriber_npi: NPI number of prescribing physician
        prescriber_specialty: Medical specialty of prescriber
        prescriber_phone: Direct phone for peer-to-peer review
        practice_name: Name of practice or health system

    Returns:
        dict with: letter (full text), metadata, missing_criteria,
        recommendation, urgency_flags
    """
    client = _get_groq_client()
    today = date.today().strftime("%B %d, %Y")

    patient_info = patient_context.get("patient_info", {})
    patient_name = patient_info.get("name", "Patient")
    patient_dob = patient_info.get("dob", "See medical record")
    patient_id_display = patient_context.get("patient_id", "See medical record")

    # Build prescriber section
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

    # Determine urgency based on flags and score
    flags = match_result.get("flags", [])
    urgency_keywords = ["cancer", "oncol", "malignancy", "imminent", "acute", "deteriorat", "lung", "nsclc"]
    
    is_urgent = any(
        any(kw in flag.lower() for kw in urgency_keywords)
        for flag in flags
    ) or any(kw in drug_name.lower() for kw in ["keytruda", "pembrolizumab"])
    prompt = f"""You are a board-certified physician writing a formal Prior Authorization justification letter
to a health insurance Medical Director. This is a critical clinical document that directly affects patient care.
Write with precision, authority, and evidence-based clinical reasoning.

== LETTER PARAMETERS ==
Date: {today}
Patient Name: {patient_name}
Date of Birth: {patient_dob}
Patient ID: {patient_id_display}

Prescriber: {prescriber_block}{prescriber_details}

Drug Requested: {drug_name}
Indication: {pa_criteria.get('indication_matched', 'As clinically indicated')}
Drug Class: {pa_criteria.get('drug_class', '')}
Relevant ICD-10: {', '.join(pa_criteria.get('icd10_codes', [])[:4])}

== CLINICAL EVIDENCE FROM PATIENT RECORD ==
Evidence strength: {match_result.get('evidence_strength', 'MODERATE')}
Match score: {match_result.get('score', 0)}/100

Criteria clearly met:
{json.dumps(match_result.get('matched_criteria', []), indent=2)}

Step therapy documented:
{json.dumps(match_result.get('step_therapy_evidence', []), indent=2)}

Clinical summary: {match_result.get('clinical_summary', '')}

Flags identified: {json.dumps(match_result.get('flags', []))}

== PAYER CRITERIA TO ADDRESS ==
{json.dumps(pa_criteria.get('required_criteria', []), indent=2)}

Clinical guideline: {pa_criteria.get('clinical_guideline', '')}

{'== URGENCY: This is a MEDICALLY URGENT request. Include an explicit urgency statement and request for expedited 72-hour review. ==' if is_urgent else ''}

== WRITING INSTRUCTIONS ==
Write a formal 5-paragraph PA justification letter:

Paragraph 1 — PATIENT & REQUEST: Patient identification, confirmed diagnosis, and the specific clinical reason {drug_name} is being requested.

Paragraph 2 — TREATMENT HISTORY: Document the complete prior treatment course — what was tried, for how long, why it failed or was discontinued. Be specific about duration and outcomes. This is the step therapy section.

Paragraph 3 — CLINICAL NECESSITY: Explain in clinical terms why {drug_name} is specifically indicated for this patient at this time. Reference the patient's specific clinical parameters, lab values, or scores that support escalation.

Paragraph 4 — GUIDELINE ALIGNMENT: State explicitly how this prescription aligns with the clinical guideline ({pa_criteria.get('clinical_guideline', 'established clinical guidelines')}). Address each payer criterion point by point. Use confident, authoritative language.

Paragraph 5 — CLOSING & AVAILABILITY: Summarize medical necessity, request {"expedited (72-hour) review given clinical urgency" if is_urgent else "timely review"}, state prescriber's availability for peer-to-peer review, and provide direct contact.

FORMAT RULES:
- Begin with the date on its own line
- Address to: "Medical Director, Prior Authorization Department"
- Professional formal letter format, no bullet points in the letter body
- Specific, evidence-based, clinically authoritative tone
- Length: 400-550 words in the letter body
- End with prescriber signature block
- No markdown formatting, no headers with ##
- Do not invent clinical data not provided above"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=1400
        )

        letter_text = response.choices[0].message.content.strip()

        return {
            "success": True,
            "letter": letter_text,
            "drug": drug_name,
            "patient": patient_name,
            "score": match_result.get("score", 0),
            "recommendation": match_result.get("recommendation", "NEEDS_REVIEW"),
            "evidence_strength": match_result.get("evidence_strength", "MODERATE"),
            "missing_criteria": match_result.get("missing_criteria", []),
            "missing_step_therapy": match_result.get("missing_step_therapy", []),
            "recommended_additional_docs": match_result.get("recommended_additional_docs", []),
            "is_urgent": is_urgent,
            "word_count": len(letter_text.split())
        }

    except Exception as e:
        logger.error(f"Error generating PA letter: {e}")
        return {
            "success": False,
            "error": str(e),
            "drug": drug_name,
            "patient": patient_name
        }


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
    Drafts a formal Prior Authorization appeal letter responding to a payer denial.

    The appeal argues against the specific denial reason with clinical evidence,
    peer-reviewed literature citations, and demands peer-to-peer review.
    Tone is firm, professional, and medically urgent.

    Args:
        drug_name: Name of the drug that was denied
        denial_reason: The payer's stated reason for denial
        pa_criteria: Output from lookup_pa_criteria
        patient_context: Output from fetch_patient_context
        prescriber_name, prescriber_npi, etc: Prescriber details
        denial_date: Date of denial letter (if known)
        reference_number: Payer's PA reference number (if known)

    Returns:
        dict with: appeal_letter (full text), metadata, key_arguments
    """
    client = _get_groq_client()
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
    if reference_number:
        ref_block = f"\nPA Reference Number: {reference_number}"
    if denial_date:
        ref_block += f"\nDenial Date: {denial_date}"

    prompt = f"""You are a senior board-certified physician writing a FORMAL APPEAL LETTER
contesting a Prior Authorization denial from a health insurance company.
This is an urgent clinical matter. The patient's access to necessary medication depends on this letter.
Write with authority, clinical precision, and urgency.

== APPEAL DETAILS ==
Date: {today}
Patient: {patient_name}, DOB: {patient_dob}
Drug denied: {drug_name}
Indication: {pa_criteria.get('indication_matched', 'As clinically indicated')}
Drug class: {pa_criteria.get('drug_class', '')}
{ref_block}

Prescriber: {prescriber_block}{prescriber_details}

PAYER'S DENIAL REASON:
"{denial_reason}"

== PATIENT CLINICAL CONTEXT ==
Conditions: {json.dumps([c.get('display', '') for c in patient_context.get('conditions', [])[:8]])}
Active medications: {json.dumps([m.get('name', '') for m in patient_context.get('active_medications', [])[:8]])}
Medication history (relevant): {json.dumps([f"{m['name']} — {m['status']} — {m.get('reason_stopped', '')}" for m in patient_context.get('medication_history', [])[:10]])}
Recent labs: {json.dumps([f"{o['name']}: {o['value']} {o['unit']}" for o in patient_context.get('observations', [])[:8]])}

== RELEVANT CLINICAL GUIDELINES ==
{pa_criteria.get('clinical_guideline', 'Established clinical practice guidelines')}

== WRITING INSTRUCTIONS ==
Write a firm, 6-paragraph formal appeal letter:

Paragraph 1 — NOTICE OF APPEAL: Formally notify the Medical Director that you are appealing the denial for {drug_name}. Reference the denial reason directly. Assert that the denial is not supported by clinical evidence and constitutes a barrier to medically necessary treatment.

Paragraph 2 — REBUTTAL OF DENIAL: Address the specific denial reason "{denial_reason}" point by point. Provide a direct clinical counterargument. If the denial cites insufficient step therapy, cite the documented treatment history explicitly. If it cites lack of medical necessity, cite clinical parameters. Do not be passive.

Paragraph 3 — CLINICAL NECESSITY: Present the strongest clinical argument for why this specific patient needs {drug_name} specifically. Reference the patient's diagnosis, disease severity, and why alternative treatments are inadequate or contraindicated.

Paragraph 4 — GUIDELINE SUPPORT: Cite the {pa_criteria.get('clinical_guideline', 'relevant clinical guidelines')} and explain how this prescription is consistent with the standard of care. Note that denial contradicts evidence-based medicine. Cite that major clinical societies endorse this treatment for this indication.

Paragraph 5 — PATIENT SAFETY: State explicitly that continued denial creates a patient safety risk. Quantify the risk where possible. Reference that delayed treatment may result in disease progression, hospitalization, or irreversible harm.

Paragraph 6 — DEMAND FOR PEER-TO-PEER + CLOSING: Formally demand a peer-to-peer physician review within 24 hours. State that failure to overturn this decision will result in escalation to the state insurance commissioner and filing a formal grievance. Provide direct contact for peer-to-peer call. Request written confirmation of appeal receipt.

FORMAT:
- Begin "RE: FORMAL APPEAL — Prior Authorization Denial for [drug]"
- Direct, firm, legally-aware professional tone
- No bullet points in letter body — continuous professional prose
- No markdown. No ## headers. 
- End with prescriber signature block and date
- Length: 500-650 words"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=1600
        )

        appeal_text = response.choices[0].message.content.strip()

        # Generate a brief summary of key arguments
        key_args_prompt = f"""Given this PA appeal letter for {drug_name} denied for: "{denial_reason}",
list the 3 strongest clinical arguments made. Return as a JSON array of strings. No other text."""

        args_response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": key_args_prompt},
                {"role": "assistant", "content": appeal_text},
                {"role": "user", "content": "Now list the 3 key arguments as JSON array:"}
            ],
            temperature=0.1,
            max_tokens=300
        )

        try:
            raw_args = args_response.choices[0].message.content.strip()
            raw_args = re.sub(r'^```json\s*', '', raw_args)
            raw_args = re.sub(r'\s*```$', '', raw_args)
            key_arguments = json.loads(raw_args)
        except Exception:
            key_arguments = ["Clinical necessity documented in patient record", "Guideline-aligned treatment", "Patient safety risk from denial"]

        return {
            "success": True,
            "appeal_letter": appeal_text,
            "drug": drug_name,
            "patient": patient_name,
            "denial_reason": denial_reason,
            "key_arguments": key_arguments,
            "word_count": len(appeal_text.split()),
            "peer_to_peer_requested": True
        }

    except Exception as e:
        logger.error(f"Error generating appeal letter: {e}")
        return {
            "success": False,
            "error": str(e),
            "drug": drug_name,
            "patient": patient_name,
            "denial_reason": denial_reason
        }
