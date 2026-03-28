"""
AuthBridge Sanitization Test
Verifies regex logic for patient_id security.
"""

import asyncio
import re

def test_sanitization_logic():
    print("\n" + "="*70)
    print("  AUTHBRIDGE SANITIZATION AUDIT")
    print("="*70)
    
    # The regex from main.py
    pattern = r'^[a-zA-Z0-9_.-]+$'
    
    test_cases = [
        # Standard IDs
        ("592506", True),
        ("synthetic-nsclc-003", True),
        ("patient.123", True),
        ("patient_id_456", True),
        
        # Malicious / Invalid IDs
        ("patient; drop table", False),
        ("patient/../../etc/passwd", False),
        ("patient id with spaces", False),
        ("patient<script>", False),
        ("patient&whoami", False),
        ("patient|rm -rf", False),
        ("patient\0", False)
    ]
    
    passed = 0
    failed = 0
    
    for pid, expected in test_cases:
        is_valid = bool(re.match(pattern, pid))
        status = "✅ PASS" if is_valid == expected else "❌ FAIL"
        
        if is_valid == expected:
            passed += 1
        else:
            failed += 1
            
        print(f"  ID: {pid:<30} | Valid: {str(is_valid):<5} | Expected: {str(expected):<5} | {status}")

    print("="*70)
    print(f"  TOTAL: {len(test_cases)} | PASSED: {passed} | FAILED: {failed}")
    print("="*70 + "\n")
    
    return failed == 0

if __name__ == "__main__":
    success = test_sanitization_logic()
    if not success:
        exit(1)
