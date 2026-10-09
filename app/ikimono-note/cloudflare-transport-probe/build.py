"""Bind the measured local Worker to the exact serialization source."""
import hashlib
import json
from pathlib import Path

here = Path(__file__).resolve().parent
digest = hashlib.sha256((here / "worker.mjs").read_bytes()).hexdigest()
wrapper_digest = hashlib.sha256((here / "remote.mjs").read_bytes()).hexdigest()
native_digest = hashlib.sha256((here.parent / "worker_transport.mjs").read_bytes()).hexdigest()
template_bytes = (here / "fixtures/template.json").read_bytes()
template = json.loads(template_bytes)
parts = template["contents"][0]["parts"]
if len(parts) != 2 or parts[0] != {"inline_data": {"mime_type": "image/jpeg", "data": ""}} or not isinstance(parts[1].get("text"), str):
    raise ValueError("Unexpected authoritative synthetic template")
template["contents"][0]["parts"] = [parts[1]]
(here / "_digest.mjs").write_text("export default '" + digest + "';\nexport const wrapperDigest = '" + wrapper_digest
    + "';\nexport const nativeDigest = '" + native_digest + "';\nexport const templateDigest = '"
    + hashlib.sha256(template_bytes).hexdigest() + "';\nexport const checkedTemplate = "
    + json.dumps(template, ensure_ascii=False, separators=(",", ":")) + ";\n")
print(digest)
