"""
AuthBridge Demo Test Script
Runs the complete PA workflow end-to-end using synthetic patient data.

Scenarios:
  humira   — Crohn's disease, standard review
  ozempic  — Type 2 Diabetes, standard review
  keytruda — NSCLC, URGENT (CMS-0057-F 72-hour escalation)
  orilissa — Endometriosis (women's health module)

Usage:
    python tests/test_demo.py
    python tests/test_demo.py --scenario keytruda --show-appeal
    python tests/test_demo.py --scenario orilissa
"""

import asyncio
import json
import argparse
import sys
import os
from pathlib import Path
from datetime import date

# Fix import path
sys.path.insert(0, str(Path(__file__).parent.parent))

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
                "display": "Crohn's disease of small intestine, moderate-to-severe",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2019-03-15",
                "note": "Confirmed by colonoscopy. Harvey-Bradshaw Index 11."
            }
        ],
        "active_medications": [
            {
                "name": "Mesalamine 1.6g delayed-release tablets",
                "rxnorm_code": "795516",
                "status": "active",
                "intent": "order",
                "authored_on": "2022-11-15",
                "dosage": "1.6g three times daily",
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
                "note": "Two courses failed. Relapsed within 4 weeks of each taper."
            },
            {
                "name": "Azathioprine 150mg oral tablet",
                "rxnorm_code": "1310149",
                "status": "stopped",
                "effective_start": "2020-09-15",
                "effective_end": "2022-10-01",
                "reason_stopped": "Inadequate therapeutic response after 2 years. HBI remained 8-10 throughout.",
                "note": "Maximum dose achieved. Liver enzymes stable."
            },
            {
                "name": "Methotrexate 25mg subcutaneous weekly",
                "rxnorm_code": "105586",
                "status": "stopped",
                "effective_start": "2022-10-10",
                "effective_end": "2023-02-28",
                "reason_stopped": "Hepatotoxicity — ALT 3x ULN at 16 weeks. Discontinued per gastroenterology.",
                "note": "5 months trial at full therapeutic dose."
            }
        ],
        "observations": [
            {"name": "C-Reactive Protein", "loinc_code": "1988-5", "value": 18.7, "unit": "mg/L", "interpretation": "H", "date": "2025-12-10", "status": "final"},
            {"name": "Tuberculin skin test (TST)", "loinc_code": "11475-1", "value": "Negative", "unit": "", "interpretation": "N", "date": "2025-11-28", "status": "final"},
            {"name": "Hepatitis B surface antigen", "loinc_code": "5196-1", "value": "Negative", "unit": "", "interpretation": "N", "date": "2025-11-28", "status": "final"},
            {"name": "Harvey-Bradshaw Index (HBI)", "loinc_code": "89242-9", "value": 11, "unit": "score", "interpretation": "H", "date": "2025-12-05", "status": "final"},
            {"name": "Fecal calprotectin", "loinc_code": "27925-7", "value": 842, "unit": "ug/g", "interpretation": "H", "date": "2025-12-05", "status": "final"}
        ],
        "procedures": [
            {"name": "Colonoscopy with biopsy", "cpt_code": "45380", "status": "completed", "date": "2019-03-15", "outcome": "Moderate-to-severe ileocolonic Crohn's disease. Multiple ulcerations in terminal ileum."},
            {"name": "CT enterography", "cpt_code": "74178", "status": "completed", "date": "2025-10-22", "outcome": "Active transmural inflammation of terminal ileum with mesenteric stranding."}
        ],
        "allergies": [{"substance": "Penicillin", "type": "allergy", "category": ["medication"], "criticality": "high", "reaction": "anaphylaxis"}],
        "fetch_errors": []
    },
    "keytruda": {
        "patient_id": "synthetic-nsclc-003",
        "patient_info": {
            "id": "synthetic-nsclc-003",
            "name": "Robert Chen",
            "dob": "1959-11-22",
            "gender": "male",
            "active": True
        },
        "conditions": [
            {
                "code": "C34.10",
                "display": "Malignant neoplasm of upper lobe, bronchus or lung, unspecified side",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2025-10-05",
                "note": "Stage IIIB NSCLC. PD-L1 TPS 72%. EGFR negative. ALK negative."
            }
        ],
        "active_medications": [
            {"name": "Dexamethasone 4mg oral tablet", "rxnorm_code": "197590", "status": "active", "intent": "order", "authored_on": "2025-10-10", "dosage": "4mg twice daily", "reason": "Supportive care — lung cancer"}
        ],
        "medication_history": [],
        "observations": [
            {"name": "PD-L1 Tumor Proportion Score", "loinc_code": "85319-2", "value": 72, "unit": "%", "interpretation": "H", "date": "2025-10-12", "status": "final"},
            {"name": "EGFR mutation status", "loinc_code": "53037-8", "value": "Wildtype (negative)", "unit": "", "interpretation": "N", "date": "2025-10-12", "status": "final"},
            {"name": "ALK rearrangement status", "loinc_code": "72518-4", "value": "Negative", "unit": "", "interpretation": "N", "date": "2025-10-12", "status": "final"},
            {"name": "ECOG Performance Status", "loinc_code": "89243-7", "value": 1, "unit": "score", "interpretation": "N", "date": "2025-10-08", "status": "final"}
        ],
        "procedures": [
            {"name": "CT-guided core needle biopsy of lung mass", "cpt_code": "32405", "status": "completed", "date": "2025-10-05", "outcome": "Non-small cell lung carcinoma, adenocarcinoma type. PD-L1 72%."},
            {"name": "PET-CT scan", "cpt_code": "78816", "status": "completed", "date": "2025-10-08", "outcome": "Stage IIIB disease. No distant metastases identified."}
        ],
        "allergies": [],
        "fetch_errors": []
    },
    "orilissa": {
        "patient_id": "synthetic-endo-004",
        "patient_info": {
            "id": "synthetic-endo-004",
            "name": "Maya Patel",
            "dob": "1991-06-14",
            "gender": "female",
            "active": True
        },
        "conditions": [
            {
                "code": "N80.1",
                "display": "Endometriosis of ovary",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2022-04-10",
                "note": "Confirmed by laparoscopy. Stage III endometriosis. Bilateral ovarian endometriomas."
            },
            {
                "code": "N80.3",
                "display": "Endometriosis of pelvic peritoneum",
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "clinical_status": "active",
                "onset": "2022-04-10",
                "note": "Identified during diagnostic laparoscopy."
            }
        ],
        "active_medications": [
            {"name": "Ibuprofen 800mg oral tablet", "rxnorm_code": "197805", "status": "active", "intent": "order", "authored_on": "2023-01-10", "dosage": "800mg three times daily with food", "reason": "Endometriosis-associated pelvic pain — inadequate control"}
        ],
        "medication_history": [
            {
                "name": "Norethindrone 5mg oral tablet",
                "rxnorm_code": "861005",
                "status": "stopped",
                "effective_start": "2022-06-01",
                "effective_end": "2022-12-15",
                "reason_stopped": "Inadequate pain control. NRS pain score remained 7/10 throughout. Breakthrough bleeding requiring discontinuation.",
                "note": "6 months trial at therapeutic dose."
            },
            {
                "name": "Combined oral contraceptive (ethinyl estradiol/levonorgestrel)",
                "rxnorm_code": "748856",
                "status": "stopped",
                "effective_start": "2021-03-01",
                "effective_end": "2022-03-01",
                "reason_stopped": "Inadequate dysmenorrhea control. Pain NRS 6-8/10 despite 12 months of continuous use.",
                "note": "Continuous dosing regimen attempted."
            }
        ],
        "observations": [
            {"name": "Pelvic pain NRS score (dysmenorrhea)", "loinc_code": "72514-3", "value": 8, "unit": "/10", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Non-menstrual pelvic pain NRS score", "loinc_code": "72514-3", "value": 6, "unit": "/10", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Bone mineral density (DEXA) — lumbar spine", "loinc_code": "24701-5", "value": -0.8, "unit": "T-score", "interpretation": "N", "date": "2025-11-15", "status": "final"}
        ],
        "observations": [
            {"name": "Pelvic pain NRS score (dysmenorrhea)", "loinc_code": "72514-3", "value": 8, "unit": "/10", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Non-menstrual pelvic pain NRS score", "loinc_code": "72514-3", "value": 6, "unit": "/10", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Bone mineral density (DEXA) — lumbar spine", "loinc_code": "24701-5", "value": -0.8, "unit": "T-score", "interpretation": "N", "date": "2025-11-15", "status": "final"}
        ],
        "procedures": [
            {"name": "Diagnostic and operative laparoscopy", "cpt_code": "49320", "status": "completed", "date": "2022-04-10", "outcome": "Stage III endometriosis confirmed. Bilateral endometriomas excised. Deep infiltrating endometriosis of pelvic peritoneum identified."}
        ],
        "allergies": [],
        "fetch_errors": []
    },
    "ozempic": {
        "patient_id": "synthetic-t2dm-002",
        "patient_info": {"id": "synthetic-t2dm-002", "name": "Marcus Johnson", "dob": "1965-09-03", "gender": "male", "active": True},
        "conditions": [
            {"code": "E11.65", "display": "Type 2 diabetes mellitus with hyperglycemia", "system": "http://hl7.org/fhir/sid/icd-10-cm", "clinical_status": "active", "onset": "2018-06-10", "note": "Inadequately controlled despite maximum dose metformin."}
        ],
        "active_medications": [
            {"name": "Metformin 1000mg tablet", "rxnorm_code": "861009", "status": "active", "intent": "order", "authored_on": "2018-07-01", "dosage": "1000mg twice daily — maximum tolerated dose", "reason": "Type 2 Diabetes"}
        ],
        "medication_history": [
            {"name": "Metformin 500mg tablet", "rxnorm_code": "861004", "status": "stopped", "effective_start": "2018-07-01", "effective_end": "2019-01-15", "reason_stopped": "Dose titrated upward", "note": "Titrated to max 2000mg/day"}
        ],
        "observations": [
            {"name": "Hemoglobin A1c", "loinc_code": "4548-4", "value": 8.9, "unit": "%", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Body Mass Index", "loinc_code": "39156-5", "value": 34.2, "unit": "kg/m2", "interpretation": "H", "date": "2025-12-01", "status": "final"},
            {"name": "Estimated Glomerular Filtration Rate", "loinc_code": "33914-3", "value": 52, "unit": "mL/min/1.73m2", "interpretation": "L", "date": "2025-12-01", "status": "final"}
        ],
        "procedures": [],
        "allergies": [],
        "fetch_errors": []
    }
}

DRUG_MAP = {
    "humira": ("adalimumab", "Crohn's disease"),
    "keytruda": ("pembrolizumab", "Non-small cell lung cancer"),
    "orilissa": ("elagolix", "endometriosis"),
    "ozempic": ("semaglutide", "Type 2 Diabetes")
}

PRESCRIBER = {
    "humira": {"name": "Dr. Elena Petrov, MD", "npi": "1234567890", "specialty": "Gastroenterology", "phone": "(555) 867-5309", "practice": "Regional Medical Center — Gastroenterology Division"},
    "keytruda": {"name": "Dr. James Nakamura, MD", "npi": "9876543210", "specialty": "Oncology / Hematology-Oncology", "phone": "(555) 234-5678", "practice": "Regional Cancer Center — Thoracic Oncology"},
    "orilissa": {"name": "Dr. Priya Sharma, MD", "npi": "5556781234", "specialty": "Gynecology / Reproductive Endocrinology", "phone": "(555) 345-6789", "practice": "Women's Health Associates"},
    "ozempic": {"name": "Dr. Michael Torres, MD", "npi": "4443219876", "specialty": "Endocrinology", "phone": "(555) 456-7890", "practice": "Diabetes & Endocrinology Center"}
}


def print_header(text):
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}")


def print_section(title):
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


async def run_pa_workflow(scenario: str = "humira", show_appeal: bool = False):
    from tools.criteria_tools import lookup_pa_criteria, score_clinical_match
    from tools.letter_tools import draft_pa_letter, draft_appeal_letter

    drug_name, indication = DRUG_MAP.get(scenario, ("adalimumab", None))
    patient_data = SYNTHETIC_PATIENTS.get(scenario, SYNTHETIC_PATIENTS["humira"])
    prescriber = PRESCRIBER.get(scenario, PRESCRIBER["humira"])

    print_header(f"AUTHBRIDGE — PRIOR AUTHORIZATION WORKFLOW")
    print(f"\n  Scenario  : {scenario.upper()}")
    print(f"  Patient   : {patient_data['patient_info']['name']}")
    print(f"  Drug      : {drug_name.capitalize()}")
    print(f"  Date      : {date.today().strftime('%B %d, %Y')}")

    # STEP 1
    print_header("STEP 1 OF 4 — FHIR Patient Context")
    print("\n  [Using synthetic patient data]")
    patient_context = patient_data
    pt = patient_context["patient_info"]
    print(f"\n  ✓ Patient  : {pt['name']} | DOB: {pt['dob']} | Gender: {pt['gender']}")
    print(f"  ✓ Conditions      : {len(patient_context['conditions'])}")
    print(f"  ✓ Active meds     : {len(patient_context['active_medications'])}")
    print(f"  ✓ Med history     : {len(patient_context['medication_history'])} entries")
    print(f"  ✓ Observations    : {len(patient_context['observations'])} (labs/vitals)")
    print(f"  ✓ Procedures      : {len(patient_context['procedures'])}")

    # STEP 2
    print_header("STEP 2 OF 4 — PA Criteria Lookup")
    print(f"\n  Looking up criteria for: {drug_name}...")
    pa_criteria = await lookup_pa_criteria(drug_name, indication)
    print(f"\n  ✓ Drug      : {pa_criteria.get('drug_name')}")
    print(f"  ✓ Class     : {pa_criteria.get('drug_class')}")
    print(f"  ✓ Indication: {pa_criteria.get('indication_matched')}")
    print(f"  ✓ Criteria  : {len(pa_criteria.get('required_criteria', []))} items")
    print(f"  ✓ Guideline : {pa_criteria.get('clinical_guideline', 'N/A')}")

    # STEP 3
    print_header("STEP 3 OF 4 — Clinical Evidence Scoring")
    print(f"\n  Analyzing patient record against PA criteria...")
    match_result = await score_clinical_match(patient_context, pa_criteria)

    score = match_result.get("score", 0)
    recommendation = match_result.get("recommendation", "UNKNOWN")
    urgency = match_result.get("urgency", {})
    is_urgent = urgency.get("is_urgent", False)

    rec_map = {
        "APPROVE": "✅ APPROVE", "LIKELY_APPROVE": "✅ LIKELY APPROVE",
        "NEEDS_MORE_INFO": "⚠️  NEEDS MORE INFO", "LIKELY_DENY": "❌ LIKELY DENY",
        "DENY": "❌ DENY", "ERROR": "⚠️  ERROR"
    }

    print(f"\n  {'━' * 54}")
    print(f"  MATCH SCORE       :  {score}/100")
    print(f"  RECOMMENDATION    :  {rec_map.get(recommendation, recommendation)}")
    print(f"  EVIDENCE STRENGTH :  {match_result.get('evidence_strength', 'UNKNOWN')}")
    if is_urgent:
        print(f"\n  🚨 CMS-0057-F URGENT ESCALATION")
        print(f"  {urgency.get('urgency_reason', '')}")
        print(f"  {urgency.get('cms_timeline', '')}")
    print(f"  {'━' * 54}")

    print_section("Criteria Met:")
    for item in match_result.get("matched_criteria", []):
        print(f"  ✓ {item}")

    if match_result.get("missing_criteria"):
        print_section("Missing / Incomplete:")
        for item in match_result.get("missing_criteria", []):
            print(f"  ✗ {item}")

    print_section("Step Therapy Evidence:")
    for item in match_result.get("step_therapy_evidence", []):
        print(f"  ✓ {item}")
    for item in match_result.get("missing_step_therapy", []):
        print(f"  ✗ MISSING: {item}")

    # FHIR Evidence Trail — the structured decision brief
    print_section("FHIR Evidence Trail (Physician Verification):")
    for line in match_result.get("fhir_evidence_trail", [])[:10]:
        print(f"  {line}")

    if match_result.get("flags"):
        print_section("Clinical Flags:")
        for flag in match_result.get("flags", []):
            print(f"  ⚠  {flag}")

    print_section("Clinical Summary:")
    print(f"  {match_result.get('clinical_summary', '')}")

    # STEP 4
    print_header("STEP 4 OF 4 — PA Letter Generation")
    print(f"\n  Drafting clinical justification letter...")

    letter_result = await draft_pa_letter(
        drug_name=pa_criteria.get("drug_name", drug_name),
        pa_criteria=pa_criteria,
        match_result=match_result,
        patient_context=patient_context,
        prescriber_name=prescriber["name"],
        prescriber_npi=prescriber["npi"],
        prescriber_specialty=prescriber["specialty"],
        prescriber_phone=prescriber["phone"],
        practice_name=prescriber["practice"]
    )

    if letter_result.get("success"):
        print(f"\n  ✓ Letter generated : {letter_result.get('word_count')} words")
        print(f"  ✓ Urgency flag     : {'🚨 YES — CMS-0057-F 72-hour expedited review' if letter_result.get('is_urgent') else 'No — standard review'}")
        print_section("━━ PRIOR AUTHORIZATION LETTER ━━")
        print()
        print(letter_result.get("letter", ""))
        print()
        print(f"  {'━' * 68}")
    else:
        print(f"\n  ✗ Letter failed: {letter_result.get('error')}")

    # Optional appeal
    appeal_result = {}
    if show_appeal:
        print_header("BONUS: APPEAL LETTER GENERATION")
        denial = "Insufficient documentation of step therapy failure. Authorization denied per plan formulary requirements."
        print(f"\n  Simulated denial: \"{denial}\"")
        print(f"\n  Drafting formal appeal...")

        appeal_result = await draft_appeal_letter(
            drug_name=pa_criteria.get("drug_name", drug_name),
            denial_reason=denial,
            pa_criteria=pa_criteria,
            patient_context=patient_context,
            prescriber_name=prescriber["name"],
            prescriber_npi=prescriber["npi"],
            prescriber_specialty=prescriber["specialty"],
            prescriber_phone=prescriber["phone"],
            practice_name=prescriber["practice"],
            denial_date=date.today().strftime("%B %d, %Y"),
            reference_number="PA-2026-0042891"
        )

        if appeal_result.get("success"):
            print(f"\n  ✓ Appeal generated : {appeal_result.get('word_count')} words")
            print(f"\n  Key arguments:")
            for arg in appeal_result.get("key_arguments", []):
                print(f"    → {arg}")
            print_section("━━ FORMAL APPEAL LETTER ━━")
            print()
            print(appeal_result.get("appeal_letter", ""))
            print()

    print_header("AUTHBRIDGE WORKFLOW COMPLETE")
    print(f"""
  Summary:
  ─────────────────────────────────────────────
  Patient         : {patient_data['patient_info']['name']}
  Drug            : {pa_criteria.get('drug_name', drug_name)}
  Match Score     : {match_result.get('score', 0)}/100
  Recommendation  : {match_result.get('recommendation', 'UNKNOWN')}
  Urgency         : {'🚨 CMS-0057-F URGENT — 72h review' if is_urgent else 'Standard — 7 days'}
  Letter Status   : {'✓ Generated' if letter_result.get('success') else '✗ Failed'}
  {'Appeal Letter  : ✓ Generated' if show_appeal and appeal_result.get('success') else ''}
  FHIR Citations  : {len(match_result.get('fhir_evidence_trail', []))} traceable evidence points

  AuthBridge turned a multi-hour PA task into seconds.
  ─────────────────────────────────────────────
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AuthBridge Demo Test")
    parser.add_argument("--scenario", choices=["humira", "ozempic", "keytruda", "orilissa"], default="humira")
    parser.add_argument("--show-appeal", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    if not os.environ.get("GITHUB_TOKEN"):
        print("\n⚠️  ERROR: GITHUB_TOKEN not set.")
        print("   Copy .env.example to .env and add your GitHub token.")
        print("   Get one at: github.com/settings/tokens (Models: Read-only)\n")
        sys.exit(1)

    asyncio.run(run_pa_workflow(scenario=args.scenario, show_appeal=args.show_appeal))
