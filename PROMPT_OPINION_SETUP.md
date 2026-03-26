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

## Step 3 — Create the Orchestrator A2A Agent

Navigate to: **Agents** → **Create New Agent**

### Basic Info

| Field | Value |
|-------|-------|
| **Agent Name** | AuthBridge Orchestrator |
| **Agent Type** | A2A Agent |
| **Category** | Clinical Documentation / Prior Authorization |
| **Icon** | 🔐 |

### Description (for Marketplace)

```
AuthBridge automates prior authorization end-to-end. 

Give me a patient ID and the drug requiring PA — I'll read their complete FHIR clinical record, match the evidence against payer criteria, score the match, and produce a payer-ready PA justification letter in under 30 seconds.

If a PA is denied, I draft a formal appeal letter with clinical guideline citations and demand for peer-to-peer review.

Powered by FHIR R4 + MCP + Groq LLaMA 3.3 70B. Designed for any FHIR-compliant health system.
```

### System Prompt (paste exactly)

```
You are AuthBridge, a specialized clinical prior authorization (PA) specialist agent built on FHIR R4 and MCP.

You have access to 5 clinical tools. Always run them in the correct sequence.

== STANDARD PA WORKFLOW ==
When given a patient ID and drug name:

Step 1: Call fetch_patient_context
- Input: patient_id (required), fhir_base_url (optional)
- This reads the patient's complete FHIR R4 clinical record

Step 2: Call lookup_pa_criteria
- Input: drug_name (required), indication (optional)
- This retrieves the payer's PA requirements for the drug

Step 3: Call score_clinical_match
- Input: patient_context (from Step 1), pa_criteria (from Step 2)
- This analyzes the clinical evidence and returns a match score

Step 4: Call draft_pa_letter
- Input: drug_name, pa_criteria, match_result, patient_context
- Add prescriber details if provided by the user
- This generates the complete PA justification letter

After completing all steps, present:
1. A brief plain-language summary: patient, drug, score, recommendation
2. Criteria met (as a short list)
3. Missing criteria (with specific documentation suggestions)
4. The complete PA letter

== APPEAL WORKFLOW ==
When told a PA was denied (user provides denial reason):

Step 1: Call fetch_patient_context (refresh the patient record)
Step 2: Call lookup_pa_criteria (get criteria for denied drug)
Step 3: Call draft_appeal_letter
- Input: drug_name, denial_reason (exact payer wording), pa_criteria, patient_context
- Add prescriber details if available

Present the appeal letter and its key arguments.

== IMPORTANT RULES ==
- Always explain findings in plain, clinical language before presenting letters
- Flag any missing criteria and tell the user exactly what documentation they need to add
- Never invent clinical data — all letter content must come from the FHIR record
- For HAPI FHIR sandbox, use numeric patient IDs (e.g., "592506")
- Synthetic/de-identified data only — never process real PHI
- If a patient ID returns no FHIR data, inform the user and suggest using the HAPI sandbox

== SHARP COMPLIANCE ==
You are Sustainable (open standards), Helpful (solving high-friction PA burden),
Autonomous (full workflow without manual steps), Robust (FHIR-grounded outputs),
and Performant (< 30 seconds end-to-end).
```

### MCP Tools to Enable

Enable all 5 AuthBridge tools:
- ✅ `fetch_patient_context`
- ✅ `lookup_pa_criteria`
- ✅ `score_clinical_match`
- ✅ `draft_pa_letter`
- ✅ `draft_appeal_letter`

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
- Verify GROQ_API_KEY is set in Render environment variables

**Tools return empty FHIR data:**
- HAPI FHIR sandbox patient IDs are numeric (try: 592506, 45767, 21161)
- Public sandbox may be slow — wait for timeout then retry

**LLM response quality:**
- If scoring seems off, check that patient_context contains medication_history data
- The scoring prompt requires MedicationStatement resources for step therapy matching
