"""Start a throwaway server (temp DB, port 8765), run the jsdom E2E checks, then stop it.
Needs: Node 18+, and `npm install` once inside tests/e2e."""
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
tmp = tempfile.mkdtemp()
env = {**os.environ, "METRICBRIDGE_DB": str(Path(tmp) / "e2e.db")}
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--port", str(PORT)], cwd=ROOT, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        sys.exit("Server did not start")
    sys.exit(subprocess.call(["node", "dashboard.e2e.js"], cwd=ROOT / "tests" / "e2e",
                             env={**os.environ, "BASE_URL": f"http://127.0.0.1:{PORT}"}))
finally:
    srv.terminate()
