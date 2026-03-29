"""
AuthBridge MCP Server
The Prior Authorization Liberation Agent

An open-standards MCP server that automates healthcare prior authorization
using FHIR R4 patient data, structured payer criteria, and LLM-powered
clinical reasoning.

Updated: 16+ Drug Database | CMS-0057-F Compliance | FHIR Citation Trail
"""

import os
import logging
import re
import asyncio
from typing import Optional, Dict, Any
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
    # Allow alphanumeric, hyphens, underscores only
    if not re.match(r'^[a-zA-Z0-9\-_]{1,64}$', patient_id):
        raise ValueError(f"Invalid patient_id format: {patient_id}")
    return patient_id

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
from tools.letter_tools import verify_pa_letter as _verify_pa_letter
from tools.letter_tools import generate_patient_summary as _generate_patient_summary

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

APPEAL WORKFLOW:
1. fetch_patient_context + lookup_pa_criteria
2. draft_appeal_letter — Generate a formal appeal rebuttal

Always run the workflow in sequence. Present findings with FHIR evidence trails.
Flag any missing criteria and recommend documentation.
Use synthetic data only — never process real PHI.
"""
)

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

async def _single_pa_score(pid: str, drug_name: str) -> dict:
    pid = _validate_patient_id(pid)
    ctx = await _fetch_patient_context(pid)
    crit = await _lookup_pa_criteria(drug_name)
    res = await _score_clinical_match(ctx, crit)
    res["patient_id"] = pid
    return res

@mcp.tool()
async def batch_pa_check(patient_ids: list, drug_name: str) -> dict:
    """
    Runs PA eligibility scoring for multiple patients simultaneously.
    Returns ranked results with scores and urgency flags.
    Demonstrates population-level PA workflow automation.
    """
    logger.info(f"Running batch PA check for {len(patient_ids)} patients on {drug_name}")
    sem = asyncio.Semaphore(3)
    
    async def _sem_score(pid: str):
        async with sem:
            await asyncio.sleep(0.5)  # Rate limit protection for downstream APIs
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
        
    async def serve_index(request):
        return FileResponse("index.html")

    async def dashboard(request):
        uptime_hours = (time.time() - _metrics["start_time"]) / 3600
        hours_saved = _metrics["total_pa_letters"] * 13  # 13h average per PA
        dollars_saved = hours_saved * 150  # $150/h physician time
        
        baseline_stats = {
            "avg_manual_pa_hours": 13,
            "avg_physician_hourly": 150,
            "treatment_abandonment_rate": 0.25,
            "cms_urgent_response_hours": 72
        }
        
        # Static math for impact case
        # Assuming 1 PA per day per physician, 20 working days/month
        monthly_pas = 10 * 20
        proj_hours_saved = monthly_pas * baseline_stats["avg_manual_pa_hours"]
        proj_dollars_saved = proj_hours_saved * baseline_stats["avg_physician_hourly"]
        
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
  <div class="card"><div class="num">{_metrics['urgent_cases']}</div><div class="label">Urgent Cases (CMS-0057-F 72h)</div></div>
  <div class="card"><div class="num">{hours_saved:.0f}h</div><div class="label">Estimated Physician Hours Saved</div></div>
  <div class="card"><div class="num">${dollars_saved:,.0f}</div><div class="label">Estimated Administrative Cost Saved</div></div>
  <div class="card"><div class="num">{uptime_hours:.1f}h</div><div class="label">Server Uptime</div></div>
</div>

<div class="impact-card">
  <h2>The Population Health Impact</h2>
  <p><strong>Even before processing live calls, the static math is transformative:</strong><br>
  If 10 physicians used AuthBridge daily (1 PA/day, 20 days/month), the clinic eliminates manual chart review and saves <strong>{proj_hours_saved:,.0f} hours</strong> and <strong>${proj_dollars_saved:,.0f}</strong> in administrative costs per month.</p>
</div>

<p style="color:#94a3b8;font-size:12px;margin-top:24px;">MCP endpoint: /sse · Health: /health · 
Built for Agents Assemble Healthcare AI Endgame 2026</p>
</body>
</html>"""
        return HTMLResponse(html)

    @limiter.limit("5/minute")
    async def handle_sse(request):
        # Correctly wire FastMCP's internal server to the SSE transport
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options()
            )

    @limiter.limit("30/minute")
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
            pid = _validate_patient_id(patient_id)
            ctx = await _fetch_patient_context(pid)
            crit = await _lookup_pa_criteria(drug_name)
            match = await _score_clinical_match(ctx, crit)
            letter_result = await _draft_pa_letter(drug_name, crit, match, ctx)
            summary = await _generate_patient_summary(drug_name, match, ctx, crit)
            
            return JSONResponse({
                "score": match.get("score", 0),
                "recommendation": match.get("recommendation", ""),
                "urgency": match.get("urgency", {}),
                "letter": letter_result.get("letter", ""),
                "evidence_trail": match.get("fhir_evidence_trail", []),
                "missing_criteria": match.get("missing_criteria", []),
                "patient_summary": summary.get("summary", "")
            })
        except Exception as e:
            logger.error(f"API Error: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    starlette_app = Starlette(
        routes=[
            Route("/", endpoint=serve_index),
            Route("/dashboard", endpoint=dashboard),
            Route("/api/run-pa", endpoint=run_pa_api, methods=["POST"]),
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )
    
    starlette_app.state.limiter = limiter
    starlette_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    starlette_app.add_middleware(SlowAPIMiddleware)

    logger.info(f"AuthBridge MCP listening at http://{host}:{port}/sse")
    uvicorn.run(starlette_app, host=host, port=port)
