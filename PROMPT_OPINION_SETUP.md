# AuthBridge — Prompt Opinion Configuration Guide

Step-by-step instructions to register AuthBridge in the Prompt Opinion platform.

---

## Step 1 — Deploy the MCP Server

Deploy to Render first (see README.md). Your MCP server URL will be:
```
https://authbridge-mcp.onrender.com
```

The server exposes an SSE endpoint at:
```
https://authbridge-mcp.onrender.com/sse
```

---

## Step 2 — Register MCP Server on Prompt Opinion

1. Log in at **app.promptopinion.ai**
2. Navigate to: **Tools** → **MCP Servers** → **Register New Server**
3. Fill in:

| Field | Value |
|-------|-------|
| **Name** | AuthBridge |
| **Server URL** | `https://authbridge-mcp.onrender.com/sse` |
| **Transport** | SSE |
| **Description** | FHIR-native prior authorization intelligence agent. Reads patient FHIR records, matches payer criteria, scores clinical evidence, and drafts complete PA justification and appeal letters. |
| **Tags** | `prior-authorization`, `FHIR`, `medication`, `clinical-documentation`, `PA`, `biologic` |

4. Click **Test Connection** — all 5 tools should appear
5. Click **Save & Publish**

---

## Step 3 — Multi-Agent Configuration (A2A)

**Recommended: Use Unified Workflow Tools for Better Reliability**

Instead of multi-agent orchestration, configure a single agent that uses the unified workflow tools:

### Primary AuthBridge Agent
- **Type**: Single Agent (Recommended)
- **Name**: AuthBridge Orchestrator
- **Description**: AuthBridge automates prior authorization end-to-end using FHIR records...
- **System prompt**: 
```
You are AuthBridge, a prior authorization specialist agent.

For ALL prior authorization requests, call run_full_pa_workflow with:
- patient_id: the patient's FHIR ID
- drug_name: the drug requiring PA
- prescriber details if provided

This single tool runs all 6 steps automatically and returns the complete output.

For ALL appeal letter requests, call run_full_appeal_workflow with:
- patient_id: the patient's FHIR ID
- drug_name: the drug requiring PA
- denial_reason: the specific denial reason from the payer
- prescriber details if provided

After PA workflow returns, present to the clinician:
1. Score and recommendation
2. Urgency flag (if CMS-0057-F 72-hour review applies)
3. Matched and missing criteria
4. The complete PA letter
5. Verification result (hallucination risk)
6. Patient summary

After appeal workflow returns, present the complete appeal letter.

Never call fetch_patient_context, lookup_pa_criteria, score_clinical_match, draft_pa_letter, or draft_appeal_letter 
individually — always use the unified workflow tools.
```
- **Tools**: Enable `run_full_pa_workflow` and `run_full_appeal_workflow` only.

### Alternative: Legacy Multi-Agent Setup
If you prefer multi-agent orchestration, you can still use the original 4-agent setup:

### Agent 1: PA Detector
- **Tools**: `fetch_patient_context`, `lookup_pa_criteria`
- **System prompt**: "You fetch the patient's FHIR record and retrieve payer PA criteria for the requested drug. Return both as structured data for the Evidence Compiler."

### Agent 2: Evidence Compiler
- **Tools**: `score_clinical_match`, `verify_pa_letter`
- **System prompt**: "You score the clinical evidence match and run the verifier audit. Return the match result with urgency assessment and FHIR evidence trail."

### Agent 3: Letter Drafter
- **Tools**: `draft_pa_letter`, `generate_patient_summary`
- **System prompt**: "You draft the PA justification letter and generate the plain-language patient summary. Include CMS-0057-F urgency header when indicated."

### Agent 4: Appeal Agent
- **Tools**: `draft_appeal_letter`
- **System prompt**: "You draft formal appeal letters contesting PA denials. Demand peer-to-peer review within 24 hours."

### Orchestrator Agent
- **Type**: A2A Agent
- **Name**: AuthBridge Orchestrator
- **Description**: AuthBridge automates prior authorization end-to-end using FHIR records...
- **System prompt**: "You are the AuthBridge Orchestrator. Route standard PA requests through PA Detector -> Evidence Compiler -> Letter Drafter. Route denial appeals to PA Detector -> Appeal Agent."
- **Tools**: Enable the 4 agents above as tools.

### SHARP Context Settings
| Setting | Value |
|---------|-------|
| Enable SHARP Context | ✅ Yes |
| Patient ID Propagation | ✅ Yes |
| FHIR Token Handling | ✅ Yes (if available) |

---

## Step 4 — Test in Prompt Opinion

Once the agent is configured, test with:

**Test 1 — Standard PA Workflow:**
```
Patient ID: [HAPI FHIR patient ID] needs prior authorization for Adalimumab (Humira) for Crohn's disease.
Prescriber: Dr. Elena Petrov, MD, Gastroenterology, NPI 1234567890, phone 555-867-5309
```

**Test 2 — Ozempic Scenario:**
```
I need to request PA for Semaglutide (Ozempic) for patient [ID] with Type 2 Diabetes. HbA1c is 8.9% and they've been on metformin 1000mg twice daily for 2 years.
```

**Test 3 — Appeal Workflow:**
```
The PA for Humira was denied for patient [ID]. Denial reason: "Insufficient step therapy documentation." Please draft an appeal.
```

---

## Step 5 — Publish to Marketplace

1. Navigate to your agent settings
2. Click **Publish to Marketplace**
3. Set visibility to **Public**
4. Add categories: `Prior Authorization`, `Clinical Documentation`, `FHIR`
5. Add the demo video URL (YouTube) once recorded
6. Click **Publish**

---

## Step 6 — Verify Marketplace Discovery

1. Go to **Marketplace**
2. Search: "prior authorization" or "AuthBridge"
3. Confirm agent appears and is invokable
4. Test invoke from marketplace UI

✅ You're now ready to submit to Devpost.

---

## Troubleshooting

**MCP server connection fails:**
- Check Render deploy logs
- Wait 30-60 seconds if Render cold-starts the free tier
- Verify GITHUB_TOKEN is set in Render environment variables

**Tools return empty FHIR data:**
- HAPI FHIR sandbox patient IDs are numeric (try: 592506, 45767, 21161)
- Public sandbox may be slow — wait for timeout then retry

**LLM response quality:**
- If scoring seems off, check that patient_context contains medication_history data
- The scoring prompt requires MedicationStatement resources for step therapy matching
