"""
AuthBridge MCP Server
The Prior Authorization Liberation Agent

An open-standards MCP server that automates healthcare prior authorization
using FHIR R4 patient data, structured payer criteria, and LLM-powered
clinical reasoning.

Built for: Agents Assemble — Healthcare AI Endgame Challenge 2026
Platform: Prompt Opinion (app.promptopinion.ai)
Standards: MCP + A2A + FHIR R4 + SHARP
"""

import os
import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("authbridge")

# Import tool implementations
from tools.fhir_tools import fetch_patient_context as _fetch_patient_context
from tools.criteria_tools import lookup_pa_criteria as _lookup_pa_criteria
from tools.criteria_tools import score_clinical_match as _score_clinical_match
from tools.letter_tools import draft_pa_letter as _draft_pa_letter
from tools.letter_tools import draft_appeal_letter as _draft_appeal_letter

# ─── Initialize FastMCP Server ───────────────────────────────────────────────

mcp = FastMCP(
    name="authbridge",
    instructions="""
You are AuthBridge, a specialized clinical prior authorization assistant.
You have access to 5 clinical tools that work together to automate PA workflows.

STANDARD PA WORKFLOW:
1. fetch_patient_context — Read the patient's FHIR clinical record
2. lookup_pa_criteria — Get the payer's PA requirements for the drug
3. score_clinical_match — Analyze how well the patient's record matches criteria
4. draft_pa_letter — Generate the complete PA justification letter

APPEAL WORKFLOW (when PA is denied):
1. fetch_patient_context — Refresh the patient's clinical record
2. lookup_pa_criteria — Get PA criteria for the denied drug
3. draft_appeal_letter — Generate a formal appeal with the denial reason

Always run the workflow in sequence. Present findings clearly before sharing letters.
Flag any missing criteria and recommend what additional documentation is needed.
Use synthetic/de-identified data only — never process real PHI.
"""
)

# ─── Tool Registrations ───────────────────────────────────────────────────────

@mcp.tool()
async def fetch_patient_context(
    patient_id: str,
    fhir_base_url: Optional[str] = None
) -> dict:
    """
    Fetches a comprehensive clinical snapshot for a patient from a FHIR R4 server.

    Retrieves and structures: active conditions (ICD-10 coded), active medication
    prescriptions (MedicationRequest), full medication history (MedicationStatement),
    recent lab results and vital signs (Observation), procedures, and allergies.

    This is always the first step in the AuthBridge PA workflow. The output is
    passed directly to score_clinical_match and the letter drafting tools.

    Args:
        patient_id: FHIR Patient resource ID (e.g., "592506" for HAPI FHIR sandbox)
        fhir_base_url: Optional FHIR server base URL. Defaults to HAPI FHIR public
                       sandbox (https://hapi.fhir.org/baseR4). Use a custom URL
                       for organization-specific FHIR servers.

    Returns:
        Structured dict with patient_info, conditions, active_medications,
        medication_history, observations, procedures, allergies, fetch_errors.
    """
    logger.info(f"Fetching FHIR context for patient: {patient_id}")
    result = await _fetch_patient_context(patient_id, fhir_base_url)
    logger.info(f"Fetched: {len(result['conditions'])} conditions, "
                f"{len(result['active_medications'])} active meds, "
                f"{len(result['medication_history'])} med history, "
                f"{len(result['observations'])} observations")
    return result


@mcp.tool()
async def lookup_pa_criteria(
    drug_name: str,
    indication: Optional[str] = None
) -> dict:
    """
    Looks up prior authorization clinical criteria for a given drug.

    Searches the AuthBridge criteria database by generic name, brand name,
    or drug class. Covers 12 major therapeutic drugs with realistic, guideline-based
    PA criteria including required documentation, step therapy requirements,
    relevant ICD-10 codes, and applicable clinical guidelines.

    If the drug is not in the database, generates synthetic criteria using LLM
    reasoning based on publicly documented clinical guidelines.

    Args:
        drug_name: Generic or brand name (e.g., "adalimumab", "Humira", "Ozempic")
        indication: Optional specific indication to filter (e.g., "Crohn's disease")
                    Useful when a drug has multiple indications with different criteria.

    Returns:
        Dict with: found, drug_name, drug_class, indication_matched, icd10_codes,
        required_criteria, step_therapy_required, clinical_guideline, typical_payers.
    """
    logger.info(f"Looking up PA criteria for: {drug_name} | Indication: {indication}")
    result = await _lookup_pa_criteria(drug_name, indication)
    logger.info(f"PA criteria found: {result.get('found')} | "
                f"Drug: {result.get('drug_name')} | "
                f"Indication: {result.get('indication_matched', 'N/A')}")
    return result


@mcp.tool()
async def score_clinical_match(
    patient_context: dict,
    pa_criteria: dict
) -> dict:
    """
    Analyzes and scores how well a patient's FHIR clinical record matches PA criteria.

    Uses LLM clinical reasoning to evaluate each required criterion against the
    patient's documented conditions, medication history, lab results, and procedures.
    Identifies matched evidence, missing documentation, step therapy completion,
    and clinical safety flags.

    This is the core intelligence of AuthBridge — it bridges the gap between
    structured FHIR data and the narrative reasoning required for PA decisions.

    Args:
        patient_context: Output from fetch_patient_context
        pa_criteria: Output from lookup_pa_criteria

    Returns:
        Dict with: score (0-100), recommendation (APPROVE/LIKELY_APPROVE/
        NEEDS_MORE_INFO/LIKELY_DENY/DENY), matched_criteria, missing_criteria,
        step_therapy_evidence, missing_step_therapy, flags, clinical_summary,
        evidence_strength, recommended_additional_docs.
    """
    patient_name = patient_context.get("patient_info", {}).get("name", "Unknown")
    drug = pa_criteria.get("drug_name", "Unknown")
    logger.info(f"Scoring PA match: {patient_name} → {drug}")
    result = await _score_clinical_match(patient_context, pa_criteria)
    logger.info(f"Score: {result.get('score')}/100 | "
                f"Recommendation: {result.get('recommendation')} | "
                f"Matched: {len(result.get('matched_criteria', []))} criteria | "
                f"Missing: {len(result.get('missing_criteria', []))} criteria")
    return result


@mcp.tool()
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

    Generates a formal 5-paragraph clinical letter grounded in the patient's FHIR
    data and PA criteria. The letter documents diagnosis, prior treatment failures,
    clinical necessity, guideline alignment, and prescriber availability for
    peer-to-peer review. Automatically detects urgent cases and requests expedited review.

    This tool does NOT invent clinical data — every claim in the letter traces
    back to the patient_context and match_result provided.

    Args:
        drug_name: Name of drug requiring PA
        pa_criteria: Output from lookup_pa_criteria
        match_result: Output from score_clinical_match
        patient_context: Output from fetch_patient_context
        prescriber_name: Full name of prescribing physician (optional)
        prescriber_npi: Prescriber's NPI number (optional)
        prescriber_specialty: Medical specialty (optional)
        prescriber_phone: Direct phone for peer-to-peer review (optional)
        practice_name: Health system or practice name (optional)

    Returns:
        Dict with: success, letter (full text), score, recommendation,
        evidence_strength, missing_criteria, recommended_additional_docs,
        is_urgent, word_count.
    """
    logger.info(f"Drafting PA letter for: {patient_context.get('patient_info', {}).get('name', 'Unknown')} → {drug_name}")
    result = await _draft_pa_letter(
        drug_name, pa_criteria, match_result, patient_context,
        prescriber_name, prescriber_npi, prescriber_specialty,
        prescriber_phone, practice_name
    )
    logger.info(f"PA letter drafted: {result.get('word_count', 0)} words | "
                f"Success: {result.get('success')} | "
                f"Urgent: {result.get('is_urgent')}")
    return result


@mcp.tool()
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
    Drafts a formal Prior Authorization appeal letter contesting a payer denial.

    Generates a firm 6-paragraph appeal letter that rebuts the specific denial
    reason, argues clinical necessity with evidence from the patient's FHIR record,
    cites relevant clinical guidelines, quantifies patient safety risk from
    continued denial, and formally demands peer-to-peer physician review.

    Designed to maximize appeal approval rate through authoritative clinical
    language, specific evidence citations, and escalation language.

    Args:
        drug_name: Name of the drug that was denied
        denial_reason: The exact denial reason from the payer's letter
        pa_criteria: Output from lookup_pa_criteria
        patient_context: Output from fetch_patient_context
        prescriber_name: Full name of prescribing physician (optional)
        prescriber_npi: Prescriber's NPI number (optional)
        prescriber_specialty: Medical specialty (optional)
        prescriber_phone: Direct phone for peer-to-peer review (optional)
        practice_name: Health system or practice name (optional)
        denial_date: Date of payer's denial letter (optional)
        reference_number: Payer's PA reference number (optional)

    Returns:
        Dict with: success, appeal_letter (full text), key_arguments,
        peer_to_peer_requested, word_count.
    """
    logger.info(f"Drafting appeal for: {patient_context.get('patient_info', {}).get('name', 'Unknown')} "
                f"→ {drug_name} | Denial: {denial_reason[:60]}...")
    result = await _draft_appeal_letter(
        drug_name, denial_reason, pa_criteria, patient_context,
        prescriber_name, prescriber_npi, prescriber_specialty,
        prescriber_phone, practice_name, denial_date, reference_number
    )
    logger.info(f"Appeal drafted: {result.get('word_count', 0)} words | Success: {result.get('success')}")
    return result


# ─── Server Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse

    port = int(os.environ.get("PORT", 10000))

    logger.info(f"Starting AuthBridge MCP Server on 0.0.0.0:{port}")

    sse = SseServerTransport("/messages/")

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options()
            )

    starlette_app = Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    uvicorn.run(starlette_app, host="0.0.0.0", port=port)
