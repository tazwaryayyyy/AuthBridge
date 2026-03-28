"""
AuthBridge Demo Test Script
Runs the complete PA workflow end-to-end using a synthetic patient scenario.

SCENARIO: Sarah Thompson — Moderate-to-severe Crohn's disease
Drug requested: Adalimumab (Humira)
Expected outcome: ~85-95/100 score, LIKELY_APPROVE

Usage:
    python test_demo.py
    python test_demo.py --scenario ozempic
    python test_demo.py --scenario keytruda
    python test_demo.py --show-appeal
"""

import asyncio
import json
import argparse
import sys
from datetime import date
from pathlib import Path

# Add project root to path for tool imports
sys.path.append(str(Path(__file__).parent.parent))

# ─── Synthetic Patient Data ───────────────────────────────────────────────────
# These simulate what you'd get from fetch_patient_context on a real FHIR server.
# In the actual demo, real FHIR calls to HAPI FHIR populate this data.

SYNTHETIC_PATIENTS = {
    "humira": {
        "patient_id": "synthetic-crohns-001",
        "patient_info": {
            "id": "synthetic-crohns-001",
            "name": "Sarah Thompson",
            "dob": "1978-04-12",
            "gender": "female",
            "active": True
        },
        "conditions": [
            {
                "code": "K50.90",
                "display": "Crohn's disease of small intestine without complications",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2019-03-15",
                "note": "Moderate-to-severe disease confirmed by colonoscopy March 2019. Harvey-Bradshaw Index 12."
            },
            {
                "code": "K52.9",
                "display": "Noninfective gastroenteritis and colitis, unspecified",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2019-01-20",
                "note": "Presenting symptom prior to Crohn's diagnosis"
            }
        ],
        "active_medications": [
            {
                "name": "Mesalamine 1.6g delayed-release tablets",
                "rxnorm_code": "795516",
                "status": "active",
                "intent": "order",
                "authored_on": "2022-11-15",
                "dosage": "1.6g three times daily with meals",
                "reason": "Crohn's disease maintenance"
            }
        ],
        "medication_history": [
            {
                "name": "Prednisone 40mg oral tablet",
                "rxnorm_code": "312615",
                "status": "stopped",
                "effective_start": "2019-04-01",
                "effective_end": "2020-08-30",
                "reason_stopped": "Inadequate disease control and significant side effects: weight gain, mood lability, adrenal suppression",
                "note": "Attempted two courses. Disease relapsed within 4 weeks of each taper."
            },
            {
                "name": "Azathioprine 150mg oral tablet",
                "rxnorm_code": "1310149",
                "status": "stopped",
                "effective_start": "2020-09-15",
                "effective_end": "2022-10-01",
                "reason_stopped": "Inadequate therapeutic response after 2 years. HBI remained 8-10 throughout. TPMT activity normal.",
                "note": "Maximum dose achieved. Liver enzymes monitored — remained stable."
            },
            {
                "name": "Methotrexate 25mg subcutaneous weekly",
                "rxnorm_code": "105586",
                "status": "stopped",
                "effective_start": "2022-10-10",
                "effective_end": "2023-02-28",
                "reason_stopped": "Persistent nausea and hepatotoxicity (ALT 3x ULN at 16 weeks). Discontinued per gastroenterology recommendation.",
                "note": "5 months trial at full therapeutic dose."
            }
        ],
        "observations": [
            {
                "name": "Hemoglobin A1c",
                "loinc_code": "4548-4",
                "value": 5.4,
                "unit": "%",
                "interpretation": "N",
                "date": "2025-11-20",
                "status": "final"
            },
            {
                "name": "C-Reactive Protein",
                "loinc_code": "1988-5",
                "value": 18.7,
                "unit": "mg/L",
                "interpretation": "H",
                "date": "2025-12-10",
                "status": "final"
            },
            {
                "name": "Tuberculin skin test (TST)",
                "loinc_code": "11475-1",
                "value": "Negative",
                "unit": "",
                "interpretation": "N",
                "date": "2025-11-28",
                "status": "final"
            },
            {
                "name": "Hepatitis B surface antigen",
                "loinc_code": "5196-1",
                "value": "Negative",
                "unit": "",
                "interpretation": "N",
                "date": "2025-11-28",
                "status": "final"
            },
            {
                "name": "Harvey-Bradshaw Index (HBI)",
                "loinc_code": "89242-9",
                "value": 11,
                "unit": "score",
                "interpretation": "H",
                "date": "2025-12-05",
                "status": "final"
            },
            {
                "name": "Fecal calprotectin",
                "loinc_code": "27925-7",
                "value": 842,
                "unit": "ug/g",
                "interpretation": "H",
                "date": "2025-12-05",
                "status": "final"
            }
        ],
        "procedures": [
            {
                "name": "Colonoscopy with biopsy",
                "cpt_code": "45380",
                "status": "completed",
                "date": "2019-03-15",
                "outcome": "Moderate-to-severe ileocolonic Crohn's disease confirmed. Multiple ulcerations observed in terminal ileum and ascending colon."
            },
            {
                "name": "CT enterography",
                "cpt_code": "74178",
                "status": "completed",
                "date": "2025-10-22",
                "outcome": "Active transmural inflammation of terminal ileum with thickening and mesenteric stranding consistent with active Crohn's disease."
            }
        ],
        "allergies": [
            {
                "substance": "Penicillin",
                "type": "allergy",
                "category": ["medication"],
                "criticality": "high",
                "reaction": "anaphylaxis"
            }
        ],
        "fetch_errors": []
    },
    "ozempic": {
        "patient_id": "synthetic-t2dm-002",
        "patient_info": {
            "id": "synthetic-t2dm-002",
            "name": "Marcus Johnson",
            "dob": "1965-09-03",
            "gender": "male",
            "active": True
        },
        "conditions": [
            {
                "code": "E11.65",
                "display": "Type 2 diabetes mellitus with hyperglycemia",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2018-06-10",
                "note": "Inadequately controlled T2DM. HbA1c persistently elevated despite maximum dose metformin."
            },
            {
                "code": "E11.69",
                "display": "Type 2 diabetes mellitus with other specified complication",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2020-01-15",
                "note": "Early diabetic nephropathy"
            }
        ],
        "active_medications": [
            {
                "name": "Metformin 1000mg tablet",
                "rxnorm_code": "861009",
                "status": "active",
                "intent": "order",
                "authored_on": "2018-07-01",
                "dosage": "1000mg twice daily with meals — maximum tolerated dose",
                "reason": "Type 2 Diabetes Mellitus"
            },
            {
                "name": "Atorvastatin 40mg oral tablet",
                "rxnorm_code": "617310",
                "status": "active",
                "intent": "order",
                "authored_on": "2020-03-10",
                "dosage": "40mg once daily at bedtime",
                "reason": "Dyslipidemia"
            }
        ],
        "medication_history": [
            {
                "name": "Metformin 500mg tablet",
                "rxnorm_code": "861004",
                "status": "stopped",
                "effective_start": "2018-07-01",
                "effective_end": "2019-01-15",
                "reason_stopped": "Dose titrated upward due to inadequate glycemic control",
                "note": "Started at 500mg, titrated to maximum 2000mg/day over 6 months"
            }
        ],
        "observations": [
            {
                "name": "Hemoglobin A1c",
                "loinc_code": "4548-4",
                "value": 8.9,
                "unit": "%",
                "interpretation": "H",
                "date": "2025-12-01",
                "status": "final"
            },
            {
                "name": "Body Mass Index",
                "loinc_code": "39156-5",
                "value": 34.2,
                "unit": "kg/m2",
                "interpretation": "H",
                "date": "2025-12-01",
                "status": "final"
            },
            {
                "name": "Estimated Glomerular Filtration Rate",
                "loinc_code": "33914-3",
                "value": 52,
                "unit": "mL/min/1.73m2",
                "interpretation": "L",
                "date": "2025-12-01",
                "status": "final"
            }
        ],
        "procedures": [],
        "allergies": [],
        "fetch_errors": []
    }
}

# ─── Prescriber Info (Synthetic) ──────────────────────────────────────────────

PRESCRIBER = {
    "name": "Dr. Elena Petrov, MD",
    "npi": "1234567890",
    "specialty": "Gastroenterology",
    "phone": "(555) 867-5309",
    "practice": "Regional Medical Center — Gastroenterology Division"
}


def print_header(text: str, char: str = "═"):
    width = 70
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


def print_section(title: str, content: str):
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")
    print(content)


async def run_pa_workflow(scenario: str = "humira", show_appeal: bool = False):
    """Run the complete AuthBridge PA workflow for a synthetic patient."""

    # Import tool functions directly for demo (bypasses MCP protocol layer)
    from tools.fhir_tools import fetch_patient_context
    from tools.criteria_tools import lookup_pa_criteria, score_clinical_match
    from tools.letter_tools import draft_pa_letter, draft_appeal_letter

    drug_map = {
        "humira": ("adalimumab", "Crohn's disease"),
        "ozempic": ("semaglutide", "Type 2 Diabetes"),
        "keytruda": ("pembrolizumab", "Non-small cell lung cancer")
    }

    drug_name, indication = drug_map.get(scenario, ("adalimumab", None))
    patient_data = SYNTHETIC_PATIENTS.get(scenario, SYNTHETIC_PATIENTS["humira"])

    print_header(f"AUTHBRIDGE — PRIOR AUTHORIZATION WORKFLOW")
    print(f"\n  Scenario : {scenario.upper()}")
    print(f"  Patient  : {patient_data['patient_info']['name']}")
    print(f"  Drug     : {drug_name.capitalize()}")
    print(f"  Date     : {date.today().strftime('%B %d, %Y')}")

    # ── STEP 1: Patient Context ───────────────────────────────────────────────
    print_header("STEP 1 OF 4 — FHIR Patient Context", "─")
    print("\n  [Simulating FHIR fetch — using synthetic patient data]")

    # Use synthetic data directly for demo (no network needed)
    patient_context = patient_data
    pt = patient_context["patient_info"]
    print(f"\n  ✓ Patient: {pt['name']} | DOB: {pt['dob']} | Gender: {pt['gender']}")
    print(f"  ✓ Active conditions: {len(patient_context['conditions'])}")
    print(f"  ✓ Active medications: {len(patient_context['active_medications'])}")
    print(f"  ✓ Medication history: {len(patient_context['medication_history'])} entries")
    print(f"  ✓ Observations: {len(patient_context['observations'])} (labs/vitals)")
    print(f"  ✓ Procedures: {len(patient_context['procedures'])}")

    # ── STEP 2: PA Criteria Lookup ────────────────────────────────────────────
    print_header("STEP 2 OF 4 — PA Criteria Lookup", "─")
    print(f"\n  Looking up PA criteria for: {drug_name}...")
    pa_criteria = await lookup_pa_criteria(drug_name, indication)

    print(f"\n  ✓ Drug: {pa_criteria.get('drug_name')}")
    print(f"  ✓ Class: {pa_criteria.get('drug_class')}")
    print(f"  ✓ Indication: {pa_criteria.get('indication_matched')}")
    print(f"  ✓ Required criteria: {len(pa_criteria.get('required_criteria', []))} items")
    print(f"  ✓ Step therapy required: {len(pa_criteria.get('step_therapy_required', []))} drugs")
    print(f"  ✓ Guideline: {pa_criteria.get('clinical_guideline', 'N/A')}")

    print_section("Required PA Criteria:", "")
    for i, criterion in enumerate(pa_criteria.get("required_criteria", []), 1):
        print(f"  {i}. {criterion}")

    print_section("Step Therapy Required:", "")
    step_therapy = pa_criteria.get("step_therapy_required", [])
    if step_therapy:
        for drug in step_therapy:
            print(f"  → {drug}")
    else:
        print("  None required")

    # ── STEP 3: Clinical Match Scoring ────────────────────────────────────────
    print_header("STEP 3 OF 4 — Clinical Evidence Scoring", "─")
    print(f"\n  Analyzing patient record against PA criteria...")
    print(f"  [Calling OpenAI GPT-4o-mini for clinical reasoning...]")

    match_result = await score_clinical_match(patient_context, pa_criteria)

    score = match_result.get("score", 0)
    recommendation = match_result.get("recommendation", "UNKNOWN")
    evidence_strength = match_result.get("evidence_strength", "UNKNOWN")

    # Color coding in terminal
    rec_symbol = {
        "APPROVE": "✅ APPROVE",
        "LIKELY_APPROVE": "✅ LIKELY APPROVE",
        "NEEDS_MORE_INFO": "⚠️  NEEDS MORE INFO",
        "LIKELY_DENY": "❌ LIKELY DENY",
        "DENY": "❌ DENY",
        "ERROR": "⚠️  ERROR"
    }.get(recommendation, recommendation)

    print(f"\n  {'━' * 50}")
    print(f"  MATCH SCORE     :  {score}/100")
    print(f"  RECOMMENDATION  :  {rec_symbol}")
    print(f"  EVIDENCE STRENGTH: {evidence_strength}")
    print(f"  {'━' * 50}")

    print_section("Criteria Met:", "")
    for item in match_result.get("matched_criteria", []):
        print(f"  ✓ {item}")

    if match_result.get("missing_criteria"):
        print_section("Missing / Incomplete:", "")
        for item in match_result.get("missing_criteria", []):
            print(f"  ✗ {item}")

    print_section("Step Therapy Evidence:", "")
    for item in match_result.get("step_therapy_evidence", []):
        print(f"  ✓ {item}")
    if match_result.get("missing_step_therapy"):
        for item in match_result.get("missing_step_therapy", []):
            print(f"  ✗ MISSING: {item}")

    if match_result.get("flags"):
        print_section("Clinical Flags:", "")
        for flag in match_result.get("flags", []):
            print(f"  ⚠  {flag}")

    print_section("Clinical Summary:", "")
    print(f"  {match_result.get('clinical_summary', '')}")

    # ── STEP 4: Draft PA Letter ───────────────────────────────────────────────
    print_header("STEP 4 OF 4 — PA Letter Generation", "─")
    print(f"\n  Drafting clinical justification letter...")

    letter_result = await draft_pa_letter(
        drug_name=pa_criteria.get("drug_name", drug_name),
        pa_criteria=pa_criteria,
        match_result=match_result,
        patient_context=patient_context,
        prescriber_name=PRESCRIBER["name"],
        prescriber_npi=PRESCRIBER["npi"],
        prescriber_specialty=PRESCRIBER["specialty"],
        prescriber_phone=PRESCRIBER["phone"],
        practice_name=PRESCRIBER["practice"]
    )

    if letter_result.get("success"):
        print(f"\n  ✓ Letter generated: {letter_result.get('word_count')} words")
        print(f"  ✓ Urgency flag: {'YES — Expedited review requested' if letter_result.get('is_urgent') else 'No'}")

        print_section("━━ PRIOR AUTHORIZATION LETTER ━━", "")
        print()
        print(letter_result.get("letter", ""))
        print()
        print(f"  {'━' * 68}")
    else:
        print(f"\n  ✗ Letter generation failed: {letter_result.get('error')}")

    # ── Optional: Appeal Letter ───────────────────────────────────────────────
    if show_appeal:
        print_header("BONUS: APPEAL LETTER GENERATION", "─")
        simulated_denial = "Insufficient documentation of step therapy failure. Prior authorization denied per plan formulary step therapy requirements."
        print(f"\n  Simulated denial: \"{simulated_denial}\"")
        print(f"\n  Drafting formal appeal...")

        appeal_result = await draft_appeal_letter(
            drug_name=pa_criteria.get("drug_name", drug_name),
            denial_reason=simulated_denial,
            pa_criteria=pa_criteria,
            patient_context=patient_context,
            prescriber_name=PRESCRIBER["name"],
            prescriber_npi=PRESCRIBER["npi"],
            prescriber_specialty=PRESCRIBER["specialty"],
            prescriber_phone=PRESCRIBER["phone"],
            practice_name=PRESCRIBER["practice"],
            denial_date=date.today().strftime("%B %d, %Y"),
            reference_number="PA-2025-0042891"
        )

        if appeal_result.get("success"):
            print(f"\n  ✓ Appeal generated: {appeal_result.get('word_count')} words")
            print(f"\n  Key arguments:")
            for arg in appeal_result.get("key_arguments", []):
                print(f"    → {arg}")

            print_section("━━ FORMAL APPEAL LETTER ━━", "")
            print()
            print(appeal_result.get("appeal_letter", ""))
            print()
            print(f"  {'━' * 68}")
        else:
            print(f"\n  ✗ Appeal generation failed: {appeal_result.get('error')}")

    appeal_status = ""
    if show_appeal:
        appeal_status = f"  Appeal Letter : {'✓ Generated' if appeal_result.get('success') else '✗ Failed'}"

    print_header("AUTHBRIDGE WORKFLOW COMPLETE")
    print(f"""
  Summary:
  ─────────────────────────────────────────────
  Patient       : {patient_data['patient_info']['name']}
  Drug          : {pa_criteria.get('drug_name', drug_name)}
  Match Score   : {match_result.get('score', 0)}/100
  Recommendation: {match_result.get('recommendation', 'UNKNOWN')}
  Letter Status : {'✓ Generated' if letter_result.get('success') else '✗ Failed'}
{appeal_status}
  Total tools called: {4 + (2 if show_appeal else 0)}
  AuthBridge turned a multi-hour PA task into seconds.
  ─────────────────────────────────────────────
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AuthBridge Demo Test")
    parser.add_argument(
        "--scenario",
        choices=["humira", "ozempic", "keytruda"],
        default="humira",
        help="Which synthetic patient scenario to run"
    )
    parser.add_argument(
        "--show-appeal",
        action="store_true",
        help="Also demonstrate the appeal letter workflow"
    )
    args = parser.parse_args()

    # Check for GITHUB_TOKEN
    import os
    from dotenv import load_dotenv
    load_dotenv()

    if not os.environ.get("GITHUB_TOKEN"):
        print("\n⚠️  ERROR: GITHUB_TOKEN not set.")
        print("   Copy .env.example to .env and add your GitHub Token.")
        print("   Get a token at: https://github.com/settings/tokens\n")
        sys.exit(1)

    asyncio.run(run_pa_workflow(
        scenario=args.scenario,
        show_appeal=args.show_appeal
    ))
