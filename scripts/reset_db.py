"""Delete the local demo database; it is re-created and re-seeded on next server start."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.db import db_path
p = db_path()
p.unlink(missing_ok=True)
print(f"Removed {p}. It will be re-seeded on next start.")
