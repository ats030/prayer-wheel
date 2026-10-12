"""Use the selected ~/.env API token, or the existing Wrangler OAuth store."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from cloudflare_credentials import deployment_environment

home = Path.home()
node = os.environ.get("TIMELINE_NODE") or str(home / ".nvm/versions/node/v24.19.0/bin/node")
wrangler = Path(os.environ.get("TIMELINE_WRANGLER") or str(
    home / ".npm/_npx/32026684e21afda6/node_modules/wrangler/bin/wrangler.js"))
if json.loads((wrangler.parent.parent / "package.json").read_text())["version"] != "4.149.0":
    sys.exit("Expected existing Wrangler 4.149.0; version changed")
if not Path(node).is_file():
    node = shutil.which("node")
args = sys.argv[1:]
use_oauth = args[:1] == ["--oauth"]
if use_oauth:
    args = args[1:]
try:
    env = deployment_environment(use_oauth=use_oauth)
except ValueError as exc:
    sys.exit(str(exc))
config = home / ".config/.wrangler/config"
legacy = home / ".wrangler/config"
if not env.get("CLOUDFLARE_API_TOKEN") and (config / "default.toml").is_file() and not legacy.exists():
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.symlink_to(config, target_is_directory=True)
sys.exit(subprocess.run([node, str(wrangler), *args],
    cwd=Path(__file__).resolve().parent / "cloudflare", env=env).returncode)
