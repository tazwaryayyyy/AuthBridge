# AuthBridge MCP Tools Reference

AuthBridge exposes 10 critical MCP tools designed specifically for Prior Authorization (PA) intelligence. These tools execute complete workflow from FHIR evidence extraction to generating CMS-compliant PA justification and appeal letters.

## How to Call These Tools via MCP Client

If you are using an A2A-compliant orchestrator (like Prompt Opinion) or a standard MCP Client (like Claude Desktop), connect to AuthBridge via its Server-Sent Events (SSE) transport wrapper.

**SSE Endpoint:** `http://localhost:10000/sse` (Local) or `https://<render-app>.onrender.com/sse` (Production)

Once connected, your client will automatically complete `list_tools` handshake to discover the definitions below, and can execute them via `call_tool` primitive.

---

## 🚀 **Unified Workflow Tools (Recommended)**

## 1. `run_full_pa_workflow`
**Description:** Runs the complete prior authorization workflow in a single call. Fetches FHIR patient context, looks up payer criteria, scores clinical evidence, drafts the PA justification letter, verifies it, and generates a patient summary. Returns the complete output including score, letter, urgency flag, and evidence trail.

**Input Schema:**
```json
{
  "patient_id": "string (Required: e.g., 'synthetic-crohns-001')",
  "drug_name": "string (Required: e.g., 'Adalimumab')",
  "prescriber_name": "string (Optional: Full name of prescribing physician)",
  "prescriber_npi": "string (Optional: Prescriber NPI number)",
  "prescriber_specialty": "string (Optional: Medical specialty)",
  "prescriber_phone": "string (Optional: Direct phone for peer-to-peer review)",
  "practice_name": "string (Optional: Practice or health system name)"
}
```

**Output Example:**
```json
{
  "patient": "Sarah Thompson",
  "drug": "Adalimumab",
  "score": 40,
  "recommendation": "DENY",
  "evidence_strength": "MODERATE",
  "is_urgent": true,
  "urgency_reason": "High-acuity clinical profile: Adalimumab (Humira)",
  "cms_timeline": "72-hour payer response required — CMS-0057-F expedited review",
  "matched_criteria": ["Confirmed diagnosis of moderate-to-severe Crohn's disease"],
  "missing_criteria": ["Failure, intolerance, or contraindication to at least one conventional therapy"],
  "fhir_evidence_trail": ["Condition/Condition/K50.90 — Crohn's disease — 2019-03-15"],
  "letter": "URGENT PRIOR AUTHORIZATION — CMS-0057-F EXPEDITED RESPONSE REQUIRED...",
  "verification": {"hallucination_risk": "LOW", "verified_claims": ["Diagnosis confirmed"]},
  "patient_summary": "We submitted a request to your insurance for Adalimumab...",
  "workflow_steps_completed": 6,
  "total": 10
}

---

## Author

Created by [Tazwar Ahnnaf Enan](https://x.com/TazwarEnan) | [X (Twitter)](https://x.com/TazwarEnan)

## License

MIT License — open for the entire healthcare AI ecosystem.

---

## 2. `run_full_appeal_workflow`
**Description:** Runs the complete appeal letter workflow in a single call. Fetches FHIR patient context, looks up payer criteria, and generates a formal appeal letter with clinical evidence and guideline citations.

**Input Schema:**
```json
{
  "patient_id": "string (Required: e.g., 'synthetic-crohns-001')",
  "drug_name": "string (Required: e.g., 'Adalimumab')",
  "denial_reason": "string (Required: Specific denial reason from payer)",
  "prescriber_name": "string (Optional: Full name of prescribing physician)",
  "prescriber_npi": "string (Optional: Prescriber NPI number)",
  "prescriber_specialty": "string (Optional: Medical specialty)",
  "prescriber_phone": "string (Optional: Direct phone for peer-to-peer review)",
  "practice_name": "string (Optional: Practice or health system name)"
}
```

**Output Example:**
```json
{
  "success": true,
  "appeal_letter": "[Your Practice Letterhead]...\nRe: Appeal for Denial of Adalimumab...",
  "drug": "Adalimumab",
  "patient": "Sarah Thompson",
  "denial_reason": "Failure to meet step therapy requirements",
  "fhir_evidence_trail": ["Condition/Condition/K50.90 — Crohn's disease — 2019-03-15"],
  "word_count": 559,
  "peer_to_peer_requested": true
}
```

---

## 🔧 **Individual Tools (Legacy/Internal Use)**

> **Note:** These tools are still available for granular control but are deprecated for direct use. The unified workflow tools above provide better reliability and complete automation.

## 3. `fetch_patient_context` ⚠️ *Legacy*
**Description:** Fetches a comprehensive clinical snapshot for a patient from a FHIR R4 server, aggregating 7 resources concurrently.
**Input Schema:**
```json
{
  "patient_id": "string (Required: e.g. '592506')",
  "fhir_base_url": "string (Optional: Defaults to HAPI FHIR)"
}
```
**Output Example:**
```json
{
  "patient_id": "592506",
  "patient_info": { "name": "Sarah Thompson" },
  "conditions": [{ "code": "K50.90", "display": "Crohn's Disease" }],
  "active_medications": [],
  "medication_history": [],
  "observations": [],
  "clinical_notes": ["Progress note detailing failure of prednisone..."]
}
```
**Error Responses:**
- `ValueError`: Triggered by strict sanitization if `patient_id` contains invalid characters.
- Non-breaking failures (e.g., FHIR 500) will log to `fetch_errors` inside the output object without crashing workflows.

---

## 4. `lookup_pa_criteria` ⚠️ *Legacy*
**Description:** Retrieves granular payer coverage requirements, contraindications, and step-therapy rules for a specified drug.
**Input Schema:**
```json
{
  "drug_name": "string (Required: e.g. 'Humira')",
  "indication": "string (Optional: Specific disease state)"
}
```
**Output Example:**
```json
{
  "drug_name": "Adalimumab (Humira)",
  "class": "TNF-alpha inhibitor",
  "required_criteria": [
    "Confirmed diagnosis of moderate-to-severe Crohn's disease",
    "Failure or intolerance to conventional therapy (corticosteroids)"
  ]
}
```
**Error Responses:**
- If the drug is rarely prescribed or not in the cached JSON database, the tool gracefully asks the LLM to generate synthetically accurate criteria on-the-fly.

---

## 5. `score_clinical_match` ⚠️ *Legacy*
**Description:** Analyzes the patient FHIR record against the PA criteria to yield an approval score and an exact evidence trail.
**Input Schema:**
```json
{
  "patient_context": "object (Output from fetch_patient_context)",
  "pa_criteria": "object (Output from lookup_pa_criteria)"
}
```
**Output Example:**
```json
{
  "score": 90,
  "recommendation": "APPROVE",
  "missing_criteria": ["Hepatitis B screening"],
  "urgency": { "is_urgent": false, "reason": "" },
  "fhir_evidence_trail": ["Diagnosis confirmed — Condition/82928"]
}
```
**Error Responses:**
- Context limits exceeded or LLM JSON parsing failures resulting in missing fields (fallback to `0` score gracefully).

---

## 6. `draft_pa_letter` ⚠️ *Legacy*
**Description:** Generates a formal, clinical-grade PA justification letter anchored strictly to the previously scored FHIR evidence.
**Input Schema:**
```json
{
  "drug_name": "string (Required)",
  "pa_criteria": "object (Required)",
  "match_result": "object (Required)",
  "patient_context": "object (Required)"
}
```
**Output Example:**
```json
{
  "status": "success",
  "letter": "December 26, 2025\n\nMedical Director...\nI respectfully request prior authorization for Adalimumab..."
}
```
**Error Responses:**
- Returns an abbreviated error within the JSON object if required matching/payload data is completely empty.

---

## 7. `draft_appeal_letter` ⚠️ *Legacy*
**Description:** Generates a formal, escalated appeal letter explicitly rebutting a specific denial reason while demanding a peer-to-peer review.
**Input Schema:**
```json
{
  "drug_name": "string (Required)",
  "denial_reason": "string (Required: e.g., 'Step therapy incomplete')",
  "pa_criteria": "object (Required)",
  "patient_context": "object (Required)"
}
```
**Output Example:**
```json
{
  "status": "success",
  "letter": "RE: FORMAL FIRST LEVEL APPEAL...\nThe denial states 'step therapy incomplete', however the FHIR record proves..."
}
```

---

## 8. `verify_pa_letter` ⚠️ *Legacy*
**Description:** Protects against LLM hallucinations by auditing the generated PA letter to mathematically verify that every clinical claim maps directly back to the original FHIR record.
**Input Schema:**
```json
{
  "letter": "string (Required)",
  "patient_context": "object (Required)",
  "match_result": "object (Required)"
}
```
**Output Example:**
```json
{
  "verified_claims": ["Condition present — confirmed: Condition/1234"],
  "unverified_claims": [],
  "hallucination_detected": false,
  "verification_summary": "All clinical citations in letter perfectly match the FHIR data."
}
```

---

## 9. `generate_patient_summary` ⚠️ *Legacy*
**Description:** Distills clinical approval hurdles into plain, compassionate language aimed at lowering patient anxiety in patient-portals.
**Input Schema:**
```json
{
  "drug_name": "string (Required)",
  "match_result": "object (Required)",
  "patient_context": "object (Required)",
  "pa_criteria": "object (Required)"
}
```
**Output Example:**
```json
{
  "status": "success",
  "summary": "We've submitted a request for Humira. Your insurance requires proof that you tried previous medications first, which we've gathered from your chart. You should hear back in 3 days."
}
```

---

## 10. `batch_pa_check` ⚠️ *Legacy*
**Description:** High-throughput population health endpoint that executes PA requirement scoring horizontally across multiple patient IDs at once.
**Input Schema:**
```json
{
  "patient_ids": "array (Required: e.g., ['101', '102'])",
  "drug_name": "string (Required: 'Humira')"
}
```
**Output Example:**
```json
{
  "drug": "Humira",
  "patients_evaluated": 2,
  "results": [
    { "patient_id": "101", "score": 95, "recommendation": "APPROVE" },
    { "patient_id": "102", "score": 40, "recommendation": "DENY" }
  ]
}
```
