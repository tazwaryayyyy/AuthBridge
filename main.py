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
from typing import Optional, Dict, Any
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
    # Input Sanitization: allow alphanumeric, hyphen, dot, underscore
    if not re.match(r'^[a-zA-Z0-9_.-]+$', patient_id):
        logger.warning(f"Invalid patient_id format rejected: {patient_id}")
        raise ValueError("Invalid patient_id format. Only alphanumeric, hyphen, dot, and underscore are allowed.")

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
    result = await _draft_appeal_letter(
        drug_name, denial_reason, pa_criteria, patient_context,
        prescriber_name, prescriber_npi, prescriber_specialty,
        prescriber_phone, practice_name, denial_date, reference_number
    )
    return result


# ─── Server Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse, HTMLResponse

    port = int(os.environ.get("PORT", 10000))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting AuthBridge MCP Server on {host}:{port}")

    # Initialize SSE transport
    sse = SseServerTransport("/messages/")

    async def health(request):
        return JSONResponse({"status": "ok", "service": "authbridge", "mcp": "sse"})

    async def index(request):
        html_content = """
        <html>
            <head>
                <title>AuthBridge MCP Server</title>
                <style>
                    body { font-family: -apple-system, system-ui, sans-serif; background: #0f172a; color: white; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                    .card { background: #1e293b; padding: 2rem; border-radius: 1rem; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); text-align: center; border: 1px solid #334155; max-width: 500px; }
                    h1 { color: #38bdf8; margin-top: 0; }
                    code { background: #0f172a; padding: 0.2rem 0.5rem; border-radius: 0.25rem; color: #f472b6; }
                    .status { display: inline-block; width: 10px; height: 10px; background: #22c55e; border-radius: 50%; margin-right: 0.5rem; }
                    .links { margin-top: 1.5rem; display: flex; gap: 1rem; justify-content: center; }
                    a { color: #38bdf8; text-decoration: none; font-size: 0.9rem; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>AuthBridge MCP</h1>
                    <p><span class="status"></span> Server is live and ready.</p>
                    <p>Transport: <code>SSE</code></p>
                    <p>Endpoint: <code>/sse</code></p>
                    <div class="links">
                        <a href="/health">Health Check</a>
                        <a href="https://github.com/tazwaryayyyy/AuthBridge">Documentation</a>
                    </div>
                </div>
            </body>
        </html>
        """
        return HTMLResponse(html_content)

    async def handle_sse(request):
        # Correctly wire FastMCP's internal server to the SSE transport
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options()
            )

    starlette_app = Starlette(
        routes=[
            Route("/", endpoint=index),
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    logger.info(f"AuthBridge MCP listening at http://{host}:{port}/sse")
    uvicorn.run(starlette_app, host=host, port=port)
