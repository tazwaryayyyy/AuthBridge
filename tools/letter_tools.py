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
from tenacity import retry, stop_after_attempt, wait_exponential
from tools.criteria_tools import build_evidence_citations, format_evidence_trail, get_async_client

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
async def _llm_call(messages, max_tokens=1500, temperature=0.1):
    return await get_async_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )


def _trim_patient_context(patient_context: dict, max_meds=5, max_obs=5, max_procs=5) -> dict:
    """Create a smaller version of the patient context for LLM prompts."""
    trimmed = {
        "patient_info": patient_context.get("patient_info", {}),
        "conditions": patient_context.get("conditions", [])[:3],
        "active_medications": patient_context.get("active_medications", [])[:3],
        "medication_history": patient_context.get("medication_history", [])[:max_meds],
        "observations": patient_context.get("observations", [])[:max_obs],
        "procedures": patient_context.get("procedures", [])[:max_procs],
        "allergies": patient_context.get("allergies", [])[:3],
        "fetch_errors": patient_context.get("fetch_errors", [])
    }
    return trimmed


async def _simulate_payer_denial_agent(letter_text: str, pa_criteria: dict) -> dict:
    """
    Adversarial agent that simulates a payer's Medical Director.
    Tries to find loopholes or missing information to justify a DENIAL.
    """
    prompt = f"""You are an adversarial Payer Denial Agent (Medical Director at an insurance company).
Your ONLY goal is to find loopholes, missing information, or weak clinical arguments in this PA letter to justify a DENIAL.

== PA CRITERIA MUST MEET ==
{json.dumps(pa_criteria.get('required_criteria', []), indent=2)}
{json.dumps(pa_criteria.get('step_therapy_required', []), indent=2)}

== PA LETTER SUBMITTED ==
{letter_text}

Analyze the letter strictly against the criteria.
Return ONLY valid JSON:
{{
  "decision": "<APPROVE|DENY>",
  "denial_reason": "<Provide specific critique if DENY, explaining exactly what is missing>",
  "missing_elements": ["<list of missing or weak arguments>"]
}}"""
    
    try:
        response = await _llm_call(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Adversarial Denial Agent failed: {e}")
        return {"decision": "APPROVE", "denial_reason": "", "missing_elements": []}


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
    evidence_trail_str = "\n".join(evidence_trail[:5]) if evidence_trail else "See patient record"

    trimmed_context = _trim_patient_context(patient_context)

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

CRITICAL: DO NOT invent, hallucinate, or assume any clinical data. You MUST strictly use ONLY the provided FHIR EVIDENCE TRAIL and CLINICAL ANALYSIS. If data is missing, state it is not documented.

No markdown in output. 450-550 words."""

    try:
        response = await _llm_call(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1400
        )
        letter_text = response.choices[0].message.content.strip()

        # Adversarial Debate Loop
        adversarial_iterations = 0
        max_iterations = 2
        
        while adversarial_iterations < max_iterations:
            denial_result = await _simulate_payer_denial_agent(letter_text, pa_criteria)
            if denial_result.get("decision") == "APPROVE":
                logger.info(f"Adversarial Agent approved the letter after {adversarial_iterations} revisions.")
                break
                
            adversarial_iterations += 1
            logger.info(f"Adversarial Denial (Iteration {adversarial_iterations}): {denial_result.get('denial_reason')}")
            
            rewrite_prompt = prompt + f"""
            
== CRITIQUE FROM PAYER DENIAL AGENT ==
The payer rejected the previous draft for the following reasons:
{denial_result.get('denial_reason')}
Missing elements: {', '.join(denial_result.get('missing_elements', []))}

Rewrite the letter to specifically address and neutralize these objections using the provided FHIR evidence. 
Ensure you do not invent evidence; use only the provided FHIR trail and clinical summary.
"""
            try:
                response = await _llm_call(
                    messages=[{"role": "user", "content": rewrite_prompt}],
                    temperature=0.2,
                    max_tokens=1400
                )
                letter_text = response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Failed to rewrite letter during adversarial debate: {e}")
                break

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
            "word_count": len(letter_text.split()),
            "adversarial_revisions": adversarial_iterations
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
    trimmed_context = _trim_patient_context(patient_context)
    citations = build_evidence_citations(trimmed_context)
    evidence_trail = format_evidence_trail(citations)
    evidence_trail_str = "\n".join(evidence_trail[:5]) if evidence_trail else "See patient record"

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
        response = await _llm_call(
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

async def verify_pa_letter(
    letter: str,
    patient_context: dict,
    match_result: dict
) -> dict:
    """
    Audits the generated PA letter against the FHIR evidence trail.
    Flags any claim in the letter that cannot be traced to a source resource.
    Implements the Verifier/Observer pattern for hallucination prevention.
    """
    evidence_trail = match_result.get("fhir_evidence_trail", [])
    
    prompt = f"""You are a clinical auditor reviewing an AI-generated PA letter 
for accuracy and hallucination risk.

FHIR EVIDENCE AVAILABLE:
{chr(10).join(evidence_trail)}

LETTER TO AUDIT:
{letter}

For every clinical claim in the letter, determine if it is supported by FHIR evidence.
Calculate confidence scores:
- If claim maps directly to a FHIR resource → 0.95-1.0 confidence
- If claim is inferred from clinical notes → 0.5-0.7 confidence
- If claim has no supporting evidence → 0.0-0.3 confidence

Return ONLY valid JSON:
{{
  "verified_claims_with_confidence": [
    {{"claim": "<claim>", "confidence": <0.0-1.0>, "evidence": "<FHIR resource>"}}
  ],
  "unverified_claims": [
    {{"claim": "<claim>", "confidence": <0.0-1.0>, "reason": "No FHIR support found"}}
  ],
  "hallucination_risk": "<LOW|MEDIUM|HIGH>",
  "overall_verdict": "<VERIFIED|NEEDS_REVIEW|REJECT>",
  "auditor_notes": "<1-2 sentence summary>"
}}"""

    response = await _llm_call(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=800
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse verify_pa_letter JSON: {raw[:100]}")
        return {
            "verified_claims": [],
            "unverified_claims": [],
            "hallucination_risk": "HIGH",
            "overall_verdict": "ERROR",
            "auditor_notes": "LLM output formatting error."
        }


async def generate_patient_summary(
    drug_name: str,
    match_result: dict,
    patient_context: dict,
    pa_criteria: dict
) -> dict:
    """
    Generates a plain-language PA status summary for the patient.
    No clinical jargon, no ICD codes. Designed for patient portal delivery.
    Based on Dr. Proctor's CHIPPER app philosophy at CHOP.
    """
    score = match_result.get("score", 0)
    recommendation = match_result.get("recommendation", "NEEDS_REVIEW")
    is_urgent = match_result.get("urgency", {}).get("is_urgent", False)
    patient_name = patient_context.get("patient_info", {}).get("name", "you")
    
    prompt = f"""You are a patient liaison writing a simple, warm explanation 
of a prior authorization request for a patient. No medical jargon. No ICD codes.
Write like you are talking to a friend.

Drug requested: {drug_name}
Condition: {pa_criteria.get('indication_matched', 'your condition')}
PA score: {score}/100
Recommendation: {recommendation}
Urgent: {is_urgent}
Missing documentation: {match_result.get('missing_criteria', [])}

Write a 3-4 sentence patient summary covering:
1. What was submitted to insurance and why
2. What the likely outcome is
3. What the next step is and roughly how long it takes
4. What they should do if they have questions

Keep it under 80 words. Warm, reassuring, clear. No bullet points.
Return ONLY valid JSON:
{{
  "summary": "<plain language summary>",
  "next_step": "<one clear action for the patient>",
  "expected_timeline": "<plain language timeline>",
  "contact_note": "Contact your doctor's office if you have questions or if you haven't heard back within the expected timeframe."
}}"""

    response = await _llm_call(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=400
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse patient_summary JSON: {raw[:100]}")
        return {
            "summary": "We encountered an error generating your plain language summary. Your clinical notes are being processed.",
            "next_step": "None",
            "expected_timeline": "Unknown",
            "contact_note": "Contact your doctor's office if you have questions."
        }
