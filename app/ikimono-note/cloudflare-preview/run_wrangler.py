"""Use existing OAuth securely when automatic credential discovery fails."""
import os
from pathlib import Path
import subprocess
import sys
import tomllib

config = tomllib.loads((Path.home() / '.config/.wrangler/config/default.toml').read_text())
environment = {**os.environ, 'CLOUDFLARE_API_TOKEN': config['oauth_token'],
               'CLOUDFLARE_ACCOUNT_ID': '559cfb7fb4d4ff05a7bbcfc75ec739a4',
               'WRANGLER_SEND_METRICS': 'false'}
node = '/home/ats030/.nvm/versions/node/v24.19.0/bin/node'
wrangler = '/home/ats030/.npm/_npx/32026684e21afda6/node_modules/wrangler/bin/wrangler.js'
result = subprocess.run([node, wrangler, *sys.argv[1:]], env=environment)
sys.exit(result.returncode)
