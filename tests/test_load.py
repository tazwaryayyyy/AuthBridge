"""
AuthBridge Load & Smoke Test Script
Simulates concurrent PA requests to verify stability and throughput.
"""

import asyncio
import httpx
import time
import sys

BASE_URL = "http://localhost:10000/api/run-pa"
CONCURRENT_REQUESTS = 15

# Mix of valid payload scenarios based on demo scripts
PAYLOAD_MIX = [
    {"patient_id": "synthetic-crohns-001", "drug_name": "Humira"},
    {"patient_id": "592506", "drug_name": "Ozempic"},
    {"patient_id": "synthetic-nsclc-003", "drug_name": "Keytruda"},
    {"patient_id": "synthetic-crohns-001", "drug_name": "Stelara"}
]

async def send_pa_request(client: httpx.AsyncClient, payload: dict, req_id: int):
    start_time = time.time()
    try:
        response = await client.post(BASE_URL, json=payload, timeout=60.0)
        elapsed = time.time() - start_time
        if response.status_code == 200:
            return {"success": True, "time": elapsed, "payload": payload, "id": req_id}
        elif response.status_code == 429:
            return {"success": False, "time": elapsed, "error": f"HTTP 429: Rate Limit Exceeded", "id": req_id}
        else:
            return {"success": False, "time": elapsed, "error": f"HTTP {response.status_code}: {response.text}", "id": req_id}
    except Exception as e:
        elapsed = time.time() - start_time
        return {"success": False, "time": elapsed, "error": str(e), "id": req_id}

async def run_load_test():
    print("\n" + "=" * 60)
    print(f"  AUTHBRIDGE ASYNC LOAD TEST ({CONCURRENT_REQUESTS} requests)")
    print("=" * 60)
    
    # Configure limits to prevent socket exhaustion
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=20)
    tasks = []
    
    start_total = time.time()
    async with httpx.AsyncClient(limits=limits) as client:
        # Launch requests concurrently
        print("Launching concurrent requests...")
        for i in range(CONCURRENT_REQUESTS):
            payload = PAYLOAD_MIX[i % len(PAYLOAD_MIX)]
            tasks.append(send_pa_request(client, payload, i))
            
        results = await asyncio.gather(*tasks)
    
    total_time = time.time() - start_total
    
    success_count = sum(1 for r in results if r["success"])
    fail_count = CONCURRENT_REQUESTS - success_count
    
    print("\n[ RESULTS COMPILED ]\n")
    for r in results:
        status = "✅ PASS" if r["success"] else f"❌ FAIL ({r['error']})"
        print(f"Req #{r['id']:<3} | PID: {r.get('payload', {}).get('patient_id', 'N/A'):<22} | Time: {r['time']:.2f}s | {status}")
        
    avg_time = sum(r["time"] for r in results) / CONCURRENT_REQUESTS if CONCURRENT_REQUESTS else 0
    
    print("\n" + "=" * 60)
    print(f"  Total Wall Clock Time : {total_time:.2f} seconds")
    print(f"  Average Time / Req    : {avg_time:.2f} seconds")
    print(f"  Throughput (success)  : {success_count}/{CONCURRENT_REQUESTS} ({(success_count/CONCURRENT_REQUESTS)*100:.1f}%)")
    print("=" * 60 + "\n")
    
    # If the fail count includes 429s, that proves rate limiting works!
    # But if standard requests fail >10%, flag it.
    if fail_count > (CONCURRENT_REQUESTS * 0.1):
        print("FAILURE RATE > 10%. Note: If 429 Rate Limits triggered, this is expected behavior from slowapi protection.")
        
if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_load_test())
