#!/usr/bin/env python3
"""Run the existing Wrangler with its existing OAuth; never print credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

home = Path.home()
node = os.environ.get('MIDOKORO_NODE') or str(home / '.nvm/versions/node/v24.19.0/bin/node')
wrangler = os.environ.get('MIDOKORO_WRANGLER') or str(home / '.npm/_npx/32026684e21afda6/node_modules/wrangler/bin/wrangler.js')
if not Path(node).is_file():
    node = shutil.which('node')
env = dict(os.environ, WRANGLER_SEND_METRICS='false')
env.setdefault('CLOUDFLARE_ACCOUNT_ID', '559cfb7fb4d4ff05a7bbcfc75ec739a4')
config = home / '.config/.wrangler/config'
legacy = home / '.wrangler/config'
if not env.get('CLOUDFLARE_API_TOKEN') and (config / 'default.toml').is_file() and not legacy.exists():
    # Wrangler prefers ~/.wrangler when its log directory exists. Point its
    # credential lookup at the existing store so its normal OAuth refresh works.
    # Never copy credentials or overwrite another profile.
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.symlink_to(config, target_is_directory=True)
sys.exit(subprocess.run([node, wrangler, *sys.argv[1:]], cwd=Path(__file__).resolve().parents[1] / 'cloudflare', env=env).returncode)
