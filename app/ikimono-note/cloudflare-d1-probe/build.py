"""Copy only the production storage modules, never settings or credentials."""
from pathlib import Path
import shutil

here = Path(__file__).resolve().parent
for name in ("auth.py", "shares.py", "d1_store.py"):
    shutil.copyfile(here.parent / name, here / "src" / name)
print("Copied three allowlisted storage modules")
