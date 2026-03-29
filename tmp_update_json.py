import json
import os

path = r'c:\Users\MSI\Desktop\AuthBridge\data\payer_criteria.json'
with open(path, 'r') as f:
    data = json.load(f)

for drug, d_data in data.items():
    for ind in d_data.get('indications', []):
        weights = {}
        crits = ind.get('required_criteria', [])
        for i, c in enumerate(crits):
            if i < 2:
                weights[c] = 'CRITICAL'
            elif i < 4:
                weights[c] = 'HIGH'
            else:
                weights[c] = 'MEDIUM'
        ind['criteria_weights'] = weights

# Manually set Humira Crohn's to match the example completely
humira_crohns_weights = {
  "Diagnosis of moderate-to-severe Crohn's disease confirmed by endoscopy, colonoscopy, or imaging (CT/MRI enterography)": "CRITICAL",
  "Failure, intolerance, or contraindication to at least one conventional therapy (corticosteroids such as prednisone, AND at least one immunomodulator: azathioprine, 6-mercaptopurine, or methotrexate)": "CRITICAL",
  "Negative tuberculosis test (TST or IGRA) within 6 months prior to initiation": "HIGH",
  "Hepatitis B surface antigen screening completed and documented": "HIGH",
  "Patient is not currently pregnant or breastfeeding (or risk/benefit discussed and documented)": "MEDIUM"
}

if 'adalimumab_humira' in data:
    data['adalimumab_humira']['indications'][0]['criteria_weights'] = humira_crohns_weights

with open(path, 'w') as f:
    json.dump(data, f, indent=2)

print('Updated JSON')
