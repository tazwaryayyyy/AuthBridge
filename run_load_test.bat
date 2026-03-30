@echo off
setlocal
echo [AuthBridge] Starting server in background...
start /B python main.py

echo [AuthBridge] Waiting 5 seconds for server to initialize...
timeout /t 5 /nobreak > nul

echo [AuthBridge] Running concurrent load test (15 requests)...
python tests/test_load.py

echo [AuthBridge] Load test complete. 
echo [AuthBridge] Use 'taskkill /IM python.exe /F' if you need to manually stop the background server.
pause
endlocal
