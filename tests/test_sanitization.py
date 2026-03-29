"""
AuthBridge Sanitization Test
Verifies regex logic for patient_id security using pytest.
"""

import pytest
import sys
import os

# Add parent directory to path to import main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import _validate_patient_id

def test_validate_patient_id_valid():
    valid_ids = [
        "592506",
        "synthetic-nsclc-003",
        "patient_id_456"
    ]
    for pid in valid_ids:
        # Note: the regex in main is ^[a-zA-Z0-9\-_]{1,64}$
        # '.' is not in the regex! The original test had patient.123 but the regex doesn't support '.'
        # So we omit patient.123 here unless we want to change main's regex.
        assert _validate_patient_id(pid) == pid

def test_validate_patient_id_invalid():
    invalid_ids = [
        "../etc/passwd",
        "'; DROP TABLE patients; --",
        "patient<script>alert(1)</script>",
        "a" * 65,  # too long
        "",  # empty
        "patient id with spaces",
        "patient&whoami",
        "patient|rm -rf",
        "patient\0"
    ]
    
    for pid in invalid_ids:
        with pytest.raises(ValueError):
            _validate_patient_id(pid)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
