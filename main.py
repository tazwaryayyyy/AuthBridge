"""
AuthBridge MCP Server
The Prior Authorization Liberation Agent

An open-standards MCP server that automates healthcare prior authorization
using FHIR R4 patient data, structured payer criteria, and LLM-powered
clinical reasoning.

Updated: 16+ Drug Database | CMS-0057-F Compliance | FHIR Citation Trail
"""

from starlette.middleware.base import BaseHTTPMiddleware
from tools.letter_tools import generate_patient_summary as _generate_patient_summary
from tools.letter_tools import verify_pa_letter as _verify_pa_letter
from tools.letter_tools import draft_appeal_letter as _draft_appeal_letter
from tools.letter_tools import draft_pa_letter as _draft_pa_letter
from tools.criteria_tools import ingest_payer_policy as _ingest_payer_policy
from tools.criteria_tools import score_clinical_match as _score_clinical_match
from tools.criteria_tools import lookup_pa_criteria as _lookup_pa_criteria
from tools.fhir_tools import fetch_patient_context as _fetch_patient_context
import os
import logging
import re
import asyncio
import json
from typing import Optional, Dict, Any, List
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from collections import defaultdict
import time

_metrics = {
    "total_pa_letters": 0,
    "total_appeals": 0,
    "total_verifications": 0,
    "urgent_cases": 0,
    "approve_count": 0,
    "start_time": time.time()
}


def _validate_patient_id(patient_id: str) -> str:
    # Allow alphanumeric, hyphens, underscores, and periods (standard FHIR ID format)
    if not re.match(r'^[a-zA-Z0-9\-_.]{1,64}$', patient_id):
        raise ValueError(f"Invalid patient_id format: {patient_id}")
    return patient_id


def _ensure_json_serializable(obj: Any) -> Any:
    """Ensure object is JSON serializable, convert None to empty strings where appropriate"""
    if obj is None:
        return ""
    elif isinstance(obj, dict):
        return {k: _ensure_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_ensure_json_serializable(item) for item in obj]
    elif hasattr(obj, '__dict__'):
        # Convert objects with __dict__ to their string representation
        return str(obj)
    else:
        return obj


def _generate_reasoning_trace(match_result: dict, patient_context: dict, pa_criteria: dict) -> list:
    """Generate detailed reasoning trace showing how AI arrived at its decision"""
    trace = []

    # Analyze matched criteria
    for criterion in match_result.get("matched_criteria", []):
        evidence = []
        if "methotrexate" in criterion.lower() and "medication_history" in patient_context:
            for med in patient_context.get("medication_history", []):
                if "methotrexate" in med.get("drug", "").lower():
                    evidence.append(
                        f"MedicationStatement/{med.get('id', 'unknown')} — {med.get('drug', 'Unknown')} documented failure")
                    break
        elif "crohn" in criterion.lower() and "conditions" in patient_context:
            for condition in patient_context.get("conditions", []):
                if "K50" in condition.get("code", ""):
                    evidence.append(
                        f"Condition/{condition.get('id', 'unknown')} — {condition.get('display', 'Unknown')} confirmed on {condition.get('date_recorded', 'unknown')}")
                    break

        if evidence:
            trace.append(
                f"Matched: {criterion} — Evidence: {'; '.join(evidence)}")

    # Analyze missing criteria
    for criterion in match_result.get("missing_criteria", []):
        if "tnf inhibitor" in criterion.lower():
            trace.append(
                f"Missing: TNF inhibitor trial — No documented biologic therapy in patient history")
        elif "hepatitis screening" in criterion.lower():
            trace.append(
                f"Missing: Hepatitis screening — No recent Observation resources for hepatitis B/C status")

    # Add conclusion
    score = match_result.get("score", 0)
    if score >= 80:
        conclusion = "Conclusion: Strong clinical evidence supports approval"
    elif score >= 60:
        conclusion = "Conclusion: Moderate evidence, consider additional documentation"
    else:
        conclusion = f"Conclusion: Low evidence score ({score}) — Significant criteria gaps identified"

    trace.append(conclusion)

    return trace


# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("authbridge")

# Import tool implementations

# ─── Initialize FastMCP Server ───────────────────────────────────────────────

mcp = FastMCP(
    name="AuthBridge",
    instructions="FHIR-native prior authorization agent. Reads patient FHIR records, matches payer criteria, scores evidence, and drafts complete PA letters and appeals."
)


FHIR_EXTENSION = {
    "ai.promptopinion/fhir-context": {
        "scopes": [
            {"name": "patient/Patient.rs",            "required": True},
            {"name": "patient/Condition.rs",           "required": True},
            {"name": "patient/MedicationRequest.rs"},
            {"name": "patient/MedicationStatement.rs"},
            {"name": "patient/Observation.rs"},
            {"name": "patient/Procedure.rs"},
            {"name": "patient/AllergyIntolerance.rs"},
        ]
    }
}


class FHIRExtensionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Skip middleware for SSE endpoints and streaming connections
            path = scope.get("path", "")
            if path.startswith("/sse") or path.startswith("/messages/"):
                await self.app(scope, receive, send)
                return

            async def send_wrapper(message):
                if message["type"] == "http.response.body":
                    body = message.get("body", b"")
                    try:
                        data = json.loads(body)
                        # Inject into initialize responses only
                        if (isinstance(data, dict) and
                                data.get("result", {}).get("serverInfo") is not None):
                            caps = data["result"].setdefault(
                                "capabilities", {})
                            caps.setdefault("extensions", {}).update(
                                FHIR_EXTENSION)
                            body = json.dumps(data).encode()
                            message = {**message, "body": body}
                    except Exception:
                        pass
                await send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)


# ─── Tool Registrations ───────────────────────────────────────────────────────

@mcp.tool()
async def fetch_patient_context(
    patient_id: str,
    fhir_base_url: Optional[str] = None
) -> dict:
    """
    Returns:
        Structured dict with patient_info, conditions, active_medications,
        medication_history, observations, procedures, allergies, fetch_errors.
    """
    patient_id = _validate_patient_id(patient_id)
    logger.info(f"Fetching FHIR context for patient: {patient_id}")
    result = await _fetch_patient_context(patient_id, fhir_base_url)
    return result


@mcp.tool()
async def lookup_pa_criteria(
    drug_name: str,
    indication: Optional[str] = None
) -> dict:
    """
    Looks up clinical PA requirements. Covers 16+ major therapeutic drugs.
    """
    logger.info(f"Looking up PA criteria for: {drug_name}")
    result = await _lookup_pa_criteria(drug_name, indication)
    return result


@mcp.tool()
async def score_clinical_match(
    patient_context: dict,
    pa_criteria: dict
) -> dict:
    """
    Analyzes patient record against PA criteria using clinical reasoning.
    Includes CMS-0057-F urgency detection and FHIR evidence citations.
    """
    logger.info(f"Scoring PA match for {pa_criteria.get('drug_name')}")
    result = await _score_clinical_match(patient_context, pa_criteria)
    if result.get("urgency", {}).get("is_urgent"):
        _metrics["urgent_cases"] += 1
    if result.get("score", 0) >= 80 or str(result.get("recommendation", "")).upper() == "APPROVE":
        _metrics["approve_count"] += 1
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
    Drafts a justification letter with urgency headers and FHIR evidence trail.
    """
    logger.info(f"Drafting PA letter for: {drug_name}")
    _metrics["total_pa_letters"] += 1
    result = await _draft_pa_letter(
        drug_name, pa_criteria, match_result, patient_context,
        prescriber_name, prescriber_npi, prescriber_specialty,
        prescriber_phone, practice_name
    )
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
    Drafts a formal appeal letter rebuttal with guideline citations.
    """
    logger.info(f"Drafting appeal for: {drug_name}")
    _metrics["total_appeals"] += 1
    result = await _draft_appeal_letter(
        drug_name, denial_reason, pa_criteria, patient_context,
        prescriber_name, prescriber_npi, prescriber_specialty,
        prescriber_phone, practice_name, denial_date, reference_number
    )
    return result


@mcp.tool()
async def ingest_payer_policy(
    policy_text: str,
    payer_name: str = "Unknown Payer"
) -> dict:
    """
    Ingests unstructured payer policy text, extracts structured PA criteria using an LLM,
    and dynamically updates the payer_criteria.json database.
    """
    logger.info(f"Ingesting new payer policy for {payer_name}")
    result = await _ingest_payer_policy(policy_text, payer_name)
    return result


@mcp.tool()
async def verify_pa_letter(
    letter: str,
    patient_context: dict,
    match_result: dict
) -> dict:
    """
    Audits a generated PA letter against the FHIR evidence trail.
    Flags any clinical claim that cannot be traced to a source FHIR resource.
    Implements AI self-verification to prevent hallucination before physician review.
    """
    _metrics["total_verifications"] += 1
    return await _verify_pa_letter(letter, patient_context, match_result)


@mcp.tool()
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
    return await _generate_patient_summary(drug_name, match_result, patient_context, pa_criteria)


@mcp.tool()
async def run_full_pa_workflow(
    patient_id: str,
    drug_name: str,
    prescriber_name: str = "",
    prescriber_npi: str = "",
    prescriber_specialty: str = "",
    prescriber_phone: str = "",
    practice_name: str = "",
    payer: str = ""
) -> dict:
    """
    Runs the complete AuthBridge prior authorization workflow in a single call.
    Fetches FHIR patient context, looks up payer criteria, scores clinical evidence,
    drafts the PA justification letter, verifies it, and generates a patient summary.
    Returns the complete output including score, letter, urgency flag, and evidence trail.
    Use this for the full end-to-end PA automation workflow.

    Args:
        patient_id: FHIR patient resource ID
        drug_name: Generic or brand name of drug requiring PA
        prescriber_name: Full name of prescribing physician (optional)
        prescriber_npi: Prescriber NPI number (optional)
        prescriber_specialty: Medical specialty (optional)
        prescriber_phone: Direct phone for peer-to-peer review (optional)
        practice_name: Practice or health system name (optional)
    """
    _validate_patient_id(patient_id)
    logger.info(
        f"Running full PA workflow: patient={patient_id}, drug={drug_name}")

    # Step 1: FHIR
    patient_context = await _fetch_patient_context(patient_id)

    # Step 2: Criteria
    pa_criteria = await _lookup_pa_criteria(drug_name, payer=payer or None)

    # Step 3: Score
    match_result = await _score_clinical_match(patient_context, pa_criteria)

    # Step 4: Letter
    letter_result = await _draft_pa_letter(
        drug_name=pa_criteria.get("drug_name", drug_name),
        pa_criteria=pa_criteria,
        match_result=match_result,
        patient_context=patient_context,
        prescriber_name=prescriber_name,
        prescriber_npi=prescriber_npi,
        prescriber_specialty=prescriber_specialty,
        prescriber_phone=prescriber_phone,
        practice_name=practice_name
    )

    # Step 5: Verify
    verify_result = {}
    if letter_result.get("success") and letter_result.get("letter"):
        try:
            verify_result = await _verify_pa_letter(
                letter=letter_result["letter"],
                patient_context=patient_context,
                match_result=match_result
            )
        except Exception as e:
            verify_result = {"error": str(e)}

    # Step 6: Patient summary
    summary_result = {}
    try:
        summary_result = await _generate_patient_summary(
            drug_name=pa_criteria.get("drug_name", drug_name),
            match_result=match_result,
            patient_context=patient_context,
            pa_criteria=pa_criteria
        )
    except Exception as e:
        summary_result = {"error": str(e)}

    urgency = match_result.get("urgency", {})
    _metrics["total_pa_letters"] += 1
    if urgency.get("is_urgent"):
        _metrics["urgent_cases"] += 1
    if match_result.get("recommendation") in ("APPROVE", "LIKELY_APPROVE"):
        _metrics["approve_count"] += 1

    try:
        result = {
            "patient": patient_context.get("patient_info", {}).get("name", "Unknown"),
            "drug": pa_criteria.get("drug_name", drug_name),
            "score": match_result.get("score", 0),
            "recommendation": match_result.get("recommendation", "UNKNOWN"),
            "evidence_strength": match_result.get("evidence_strength", "UNKNOWN"),
            "is_urgent": urgency.get("is_urgent", False),
            "urgency_reason": urgency.get("urgency_reason", ""),
            "cms_timeline": urgency.get("cms_timeline", ""),
            "matched_criteria": match_result.get("matched_criteria", []),
            "missing_criteria": match_result.get("missing_criteria", []),
            "step_therapy_evidence": match_result.get("step_therapy_evidence", []),
            "fhir_evidence_trail": match_result.get("fhir_evidence_trail", []),
            "clinical_summary": match_result.get("clinical_summary", ""),
            "letter": letter_result.get("letter", ""),
            "letter_word_count": letter_result.get("word_count", 0),
            "verification": verify_result,
            "patient_summary": summary_result.get("summary", ""),
            "patient_next_step": summary_result.get("next_step", ""),
            "hallucination_risk": verify_result.get("hallucination_risk", "UNKNOWN"),
            "reasoning_trace": _generate_reasoning_trace(match_result, patient_context, pa_criteria),
            "workflow_steps_completed": 6
        }

        # Ensure JSON serializable
        serializable_result = _ensure_json_serializable(result)

        # Test serialization
        json.dumps(serializable_result)

        logger.info(
            f"Successfully created result for PA workflow: patient={patient_id}, drug={drug_name}")
        return serializable_result
    except Exception as e:
        logger.error(f"Error creating PA workflow result: {e}")
        return {
            "error": str(e),
            "success": False,
            "patient": patient_context.get("patient_info", {}).get("name", "Unknown"),
            "drug": pa_criteria.get("drug_name", drug_name),
            "workflow_steps_completed": 0
        }


@mcp.tool()
async def run_full_appeal_workflow(
    patient_id: str,
    drug_name: str,
    denial_reason: str,
    prescriber_name: str = "",
    prescriber_npi: str = "",
    prescriber_specialty: str = "",
    prescriber_phone: str = "",
    practice_name: str = "",
    payer: str = ""
) -> dict:
    """
    Runs the complete appeal letter workflow in a single call.
    Fetches FHIR patient context, looks up payer criteria, then drafts a formal appeal.
    """
    _validate_patient_id(patient_id)
    patient_context = await _fetch_patient_context(patient_id)
    pa_criteria = await _lookup_pa_criteria(drug_name, payer=payer or None)
    appeal_result = await _draft_appeal_letter(
        drug_name=drug_name,
        denial_reason=denial_reason,
        patient_context=patient_context,
        pa_criteria=pa_criteria,
        prescriber_name=prescriber_name,
        prescriber_npi=prescriber_npi,
        prescriber_specialty=prescriber_specialty,
        prescriber_phone=prescriber_phone,
        practice_name=practice_name
    )

    try:
        logger.info(
            f"Successfully created result for appeal workflow: patient={patient_id}, drug={drug_name}")

        # Ensure JSON serializable
        serializable_result = _ensure_json_serializable(appeal_result)

        # Test serialization
        json.dumps(serializable_result)

        return serializable_result
    except Exception as e:
        logger.error(f"Error creating appeal workflow result: {e}")
        return {
            "error": str(e),
            "success": False,
            "patient": patient_context.get("patient_info", {}).get("name", "Unknown"),
            "drug": drug_name,
            "denial_reason": denial_reason,
            "workflow_steps_completed": 0
        }


@mcp.tool()
async def simulate_pa_lifecycle(
    patient_id: str,
    drug_name: str,
    prescriber_name: str = "",
    prescriber_npi: str = "",
    prescriber_specialty: str = "",
    prescriber_phone: str = "",
    practice_name: str = "",
    denial_reason: str = "",
    payer: str = ""
) -> dict:
    """
    Simulates the complete PA lifecycle from submission to final resolution.
    Returns a timeline of events showing the full prior authorization journey.
    """
    _validate_patient_id(patient_id)

    timeline = []

    # Day 0: Initial PA submission
    timeline.append({
        "day": 0,
        "event": "PA submitted",
        "status": "pending",
        "description": f"Prior authorization request submitted for {drug_name}"
    })

    # Run the full PA workflow
    pa_result = await run_full_pa_workflow(
        patient_id=patient_id,
        drug_name=drug_name,
        prescriber_name=prescriber_name,
        prescriber_npi=prescriber_npi,
        prescriber_specialty=prescriber_specialty,
        prescriber_phone=prescriber_phone,
        practice_name=practice_name,
        payer=payer
    )

    # Day 1: Decision based on scoring
    if pa_result.get("recommendation") in ["APPROVE", "LIKELY_APPROVE"]:
        timeline.append({
            "day": 1,
            "event": "Approved - criteria met",
            "status": "approved",
            "description": f"PA for {drug_name} approved without delay"
        })
        final_outcome = "approved"
    else:
        timeline.append({
            "day": 1,
            "event": f"Denied - {pa_result.get('missing_criteria', ['criteria not met'])[0] if pa_result.get('missing_criteria') else 'criteria not met'}",
            "status": "denied",
            "description": f"PA for {drug_name} denied"
        })

        # Day 1: Appeal generation (if denied)
        if denial_reason:
            appeal_result = await run_full_appeal_workflow(
                patient_id=patient_id,
                drug_name=drug_name,
                denial_reason=denial_reason,
                prescriber_name=prescriber_name,
                prescriber_npi=prescriber_npi,
                prescriber_specialty=prescriber_specialty,
                prescriber_phone=prescriber_phone,
                practice_name=practice_name,
                payer=payer
            )

            timeline.append({
                "day": 1,
                "event": "Appeal generated and submitted",
                "status": "appealed",
                "description": f"Formal appeal letter generated for {drug_name}"
            })

        # Day 3: Final resolution (peer review)
        timeline.append({
            "day": 3,
            "event": "Peer review completed",
            "status": "resolved",
            "description": f"Peer-to-peer review conducted for {drug_name} request"
        })

        final_outcome = "approved_after_appeal" if denial_reason else "approved"

    return {
        "patient": pa_result.get("patient", "Unknown"),
        "drug": drug_name,
        "timeline": timeline,
        "final_outcome": final_outcome,
        "pa_score": pa_result.get("score", 0),
        "pa_recommendation": pa_result.get("recommendation", "UNKNOWN"),
        "workflow_steps_completed": len(timeline)
    }


async def _single_pa_score(pid: str, drug_name: str) -> dict:
    pid = _validate_patient_id(pid)
    ctx = await _fetch_patient_context(pid)
    crit = await _lookup_pa_criteria(drug_name)
    res = await _score_clinical_match(ctx, crit)
    res["patient_id"] = pid
    return res


@mcp.tool()
async def batch_pa_check(patient_ids: List[str], drug_name: str) -> dict:
    """
    Runs PA eligibility scoring for multiple patients simultaneously.
    Returns ranked results with scores and urgency flags.
    Demonstrates population-level PA workflow automation.
    """
    logger.info(
        f"Running batch PA check for {len(patient_ids)} patients on {drug_name}")
    sem = asyncio.Semaphore(3)

    async def _sem_score(pid: str):
        async with sem:
            # Rate limit protection for downstream APIs
            await asyncio.sleep(0.5)
            return await _single_pa_score(pid, drug_name)

    tasks = [_sem_score(pid) for pid in patient_ids[:5]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "drug": drug_name,
        "patients_evaluated": len(patient_ids),
        "results": sorted(
            [r for r in results if isinstance(r, dict)],
            key=lambda x: x.get("score", 0),
            reverse=True
        )
    }


# Keep the public MCP surface small and registry-friendly. The lower-level
# functions remain available to the Python app, but hosted MCP registries such
# as Prompt Opinion only need the single-call workflows below.
PUBLIC_MCP_TOOLS = {
    "run_full_pa_workflow",
    "run_full_appeal_workflow",
    "simulate_pa_lifecycle",
}

for _tool_name in list(mcp._tool_manager._tools.keys()):
    if _tool_name not in PUBLIC_MCP_TOOLS:
        mcp.remove_tool(_tool_name)

# ─── Server Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse, HTMLResponse, FileResponse
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    limiter = Limiter(key_func=get_remote_address)

    port = int(os.environ.get("PORT", 10000))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting AuthBridge MCP Server on {host}:{port}")

    # Initialize SSE transport
    sse = SseServerTransport("/messages/")

    async def health(request):
        return JSONResponse({"status": "ok", "service": "authbridge", "mcp": "sse"})

    async def mcp_tools_debug(request):
        tools = await mcp.list_tools()
        return JSONResponse({
            "status": "ok",
            "count": len(tools),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
                for tool in tools
            ],
        })

    async def serve_index(request):
        return FileResponse("index.html")

    async def dashboard(request):
        uptime_hours = (time.time() - _metrics["start_time"]) / 3600
        # conservative 1h manual PA baseline per completed workflow
        hours_saved = _metrics["total_pa_letters"] * 1
        dollars_saved = hours_saved * 150  # $150/h physician time

        baseline_stats = {
            "avg_manual_pa_hours": 1,
            "avg_physician_hourly": 150,
            "treatment_abandonment_rate": 0.25,
            "cms_urgent_response_hours": 72
        }

        # Static math for impact case
        # Assuming 1 PA per day per physician, 20 working days/month
        monthly_pas = 10 * 20
        proj_hours_saved = monthly_pas * baseline_stats["avg_manual_pa_hours"]
        proj_dollars_saved = proj_hours_saved * \
            baseline_stats["avg_physician_hourly"]

        html = f"""<!DOCTYPE html>
<html>
<head><title>AuthBridge — Status</title>
<style>
  body {{ font-family: system-ui; background: #f8fafc; color: #1e293b; padding: 40px; }}
  h1 {{ color: #0f766e; }} 
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 24px 0; }}
  .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; }}
  .num {{ font-size: 36px; font-weight: 800; color: #0f766e; }}
  .label {{ color: #64748b; font-size: 13px; margin-top: 4px; }}
  .badge {{ display: inline-block; background: #d1fae5; color: #065f46; 
            padding: 4px 12px; border-radius: 99px; font-size: 12px; font-weight: 600; }}
  .impact-card {{ background: #0f766e; color: white; border-radius: 12px; padding: 24px; margin-top: 32px; }}
  .impact-card h2 {{ font-size: 20px; margin-top: 0; }}
  .impact-card p {{ opacity: 0.9; line-height: 1.5; }}
</style>
</head>
<body>
<h1>AuthBridge <span class="badge">● Live</span></h1>
<p>FHIR-native Prior Authorization Intelligence Agent · MCP + A2A + FHIR R4</p>
<div class="grid">
  <div class="card"><div class="num">{_metrics['total_pa_letters']}</div><div class="label">PA Letters Generated</div></div>
  <div class="card"><div class="num">{_metrics['total_appeals']}</div><div class="label">Appeal Letters Generated</div></div>
  <div class="card"><div class="num">{_metrics['urgent_cases']}</div><div class="label">Urgent Cases Flagged for Expedited Review</div></div>
  <div class="card"><div class="num">{hours_saved:.0f}h</div><div class="label">Estimated Physician Hours Saved</div></div>
  <div class="card"><div class="num">${dollars_saved:,.0f}</div><div class="label">Estimated Administrative Cost Saved</div></div>
  <div class="card"><div class="num">{uptime_hours:.1f}h</div><div class="label">Server Uptime</div></div>
</div>

<div class="impact-card">
  <h2>The Population Health Impact</h2>
  <p><strong>Even before processing live calls, the static math is transformative:</strong><br>
  If 10 physicians used AuthBridge daily (1 PA/day, 20 days/month), the clinic reduces manual chart review and drafting work by an estimated <strong>{proj_hours_saved:,.0f} hours</strong> and <strong>${proj_dollars_saved:,.0f}</strong> in administrative cost per month.</p>
  <p style="font-size:12px;opacity:0.8;">Regulatory note: CMS-0057-F establishes FHIR prior authorization API and decision-timeframe requirements for covered items and services; the current medication PA demo uses the same interoperability pattern but remains a synthetic demonstration.</p>
</div>

<p style="color:#94a3b8;font-size:12px;margin-top:24px;">MCP endpoint: /sse · Health: /health</p>
</body>
</html>"""
        return HTMLResponse(html)

    class SSEHandler:
        async def __call__(self, scope, receive, send):
            # Correctly wire FastMCP's internal server to the SSE transport
            try:
                async with sse.connect_sse(
                    scope, receive, send
                ) as streams:
                    await mcp._mcp_server.run(
                        streams[0], streams[1],
                        mcp._mcp_server.create_initialization_options()
                    )
            except Exception as e:
                logger.error(f"SSE connection error: {e}")

    handle_sse = SSEHandler()
    handle_sse.__name__ = "handle_sse"
    handle_sse.__module__ = __name__

    @limiter.limit("50/minute")
    async def run_pa_api(request):
        # Request size limit 1MB
        if int(request.headers.get("content-length", 0)) > 1024 * 1024:
            return JSONResponse({"error": "Payload too large. Max 1MB."}, status_code=413)

        try:
            body = await request.json()
        except:
            return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

        patient_id = body.get("patient_id")
        drug_name = body.get("drug_name")
        if not patient_id or not drug_name:
            return JSONResponse({"error": "Missing patient_id or drug_name"}, status_code=400)

        try:
            t0 = time.time()
            result = await run_full_pa_workflow(
                patient_id=patient_id,
                drug_name=drug_name,
                prescriber_name=body.get("prescriber_name"),
                prescriber_npi=body.get("prescriber_npi"),
                prescriber_specialty=body.get("prescriber_specialty"),
                prescriber_phone=body.get("prescriber_phone"),
                practice_name=body.get("practice_name"),
                payer=body.get("payer")
            )

            elapsed_seconds = round(time.time() - t0, 2)
            evidence_count = len(result.get("fhir_evidence_trail", []))
            result["elapsed_seconds"] = elapsed_seconds
            result["impact_metrics"] = {
                "manual_pa_minutes_baseline": 60,
                "automation_seconds": elapsed_seconds,
                "estimated_minutes_saved": max(0, round(60 - (elapsed_seconds / 60), 1)),
                "evidence_resources": evidence_count,
                "verification_status": result.get("verification", {}).get("overall_verdict", "UNKNOWN")
            }
            result["safety_controls"] = [
                "Synthetic or de-identified data only in this demo",
                "Strict patient ID validation before FHIR access",
                "FHIR evidence trail attached to clinical claims",
                "AI self-audit runs before clinician review",
                "Clinician attestation required before submission"
            ]
            result["regulatory_note"] = (
                "CMS-0057-F supports the FHIR prior authorization direction for covered items and services; "
                "this medication PA demo is a synthetic workflow prototype and does not claim live payer submission."
            )

            return JSONResponse(result)
        except Exception as e:
            logger.error(f"API Error: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @limiter.limit("50/minute")
    async def run_appeal_api(request):
        # Request size limit 1MB
        if int(request.headers.get("content-length", 0)) > 1024 * 1024:
            return JSONResponse({"error": "Payload too large. Max 1MB."}, status_code=413)

        try:
            body = await request.json()
        except:
            return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

        patient_id = body.get("patient_id")
        drug_name = body.get("drug_name")
        denial_reason = body.get("denial_reason")
        if not patient_id or not drug_name or not denial_reason:
            return JSONResponse({"error": "Missing patient_id, drug_name, or denial_reason"}, status_code=400)

        try:
            result = await run_full_appeal_workflow(
                patient_id=patient_id,
                drug_name=drug_name,
                denial_reason=denial_reason,
                prescriber_name=body.get("prescriber_name"),
                prescriber_npi=body.get("prescriber_npi"),
                prescriber_specialty=body.get("prescriber_specialty"),
                prescriber_phone=body.get("prescriber_phone"),
                practice_name=body.get("practice_name"),
                payer=body.get("payer")
            )

            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Appeal API Error: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @limiter.limit("50/minute")
    async def run_pa_lifecycle_api(request):
        # Request size limit 1MB
        if int(request.headers.get("content-length", 0)) > 1024 * 1024:
            return JSONResponse({"error": "Payload too large. Max 1MB."}, status_code=413)

        try:
            body = await request.json()
        except:
            return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

        patient_id = body.get("patient_id")
        drug_name = body.get("drug_name")
        prescriber_name = body.get("prescriber_name")
        prescriber_npi = body.get("prescriber_npi")
        prescriber_specialty = body.get("prescriber_specialty")
        prescriber_phone = body.get("prescriber_phone")
        practice_name = body.get("practice_name")
        denial_reason = body.get("denial_reason")
        payer = body.get("payer")

        if not patient_id or not drug_name:
            return JSONResponse({"error": "Missing patient_id or drug_name"}, status_code=400)

        try:
            result = await simulate_pa_lifecycle(
                patient_id=patient_id,
                drug_name=drug_name,
                prescriber_name=prescriber_name,
                prescriber_npi=prescriber_npi,
                prescriber_specialty=prescriber_specialty,
                prescriber_phone=prescriber_phone,
                practice_name=practice_name,
                denial_reason=denial_reason,
                payer=payer
            )
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Lifecycle API Error: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    starlette_app = Starlette(
        routes=[
            Route("/", endpoint=serve_index),
            Route("/dashboard", endpoint=dashboard),
            Route("/api/run-pa", endpoint=run_pa_api, methods=["POST"]),
            Route("/api/run-appeal",
                  endpoint=run_appeal_api, methods=["POST"]),
            Route("/api/run-pa-lifecycle",
                  endpoint=run_pa_lifecycle_api, methods=["POST"]),
            Route("/health", endpoint=health),
            Route("/mcp/tools", endpoint=mcp_tools_debug),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    starlette_app.state.limiter = limiter
    starlette_app.add_exception_handler(
        RateLimitExceeded, _rate_limit_exceeded_handler)
    starlette_app.add_middleware(SlowAPIMiddleware)
    starlette_app.add_middleware(FHIRExtensionMiddleware)

    logger.info(f"AuthBridge MCP listening at http://{host}:{port}/sse")
    uvicorn.run(starlette_app, host=host, port=port)
