"""Bind the measured local Worker to the exact serialization source."""
import hashlib
from pathlib import Path

here = Path(__file__).resolve().parent
digest = hashlib.sha256((here / "worker.mjs").read_bytes()).hexdigest()
wrapper_digest = hashlib.sha256((here / "remote.mjs").read_bytes()).hexdigest()
(here / "_digest.mjs").write_text("export default '" + digest + "';\nexport const wrapperDigest = '" + wrapper_digest + "';\n")
print(digest)
