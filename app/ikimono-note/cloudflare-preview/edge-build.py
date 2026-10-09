"""Build existing reviewed Python payload, then bind the JS gateway to it."""
import ast
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
runpy.run_path(str(HERE / 'build.py'))
namespace = {}
exec((HERE / 'src/_resources.py').read_text(), namespace)
tree = ast.parse((HERE.parent / 'main.py').read_text())
assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'CONTENT_SECURITY_POLICY' for t in node.targets))
csp = '; '.join(ast.literal_eval(assignment.value.args[0])).replace("script-src 'self'", "script-src 'self' 'wasm-unsafe-eval'")
security = {'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Permissions-Policy': 'camera=(self), geolocation=(self)',
            'Cross-Origin-Opener-Policy': 'same-origin-allow-popups', 'Content-Security-Policy': csp}
digest = hashlib.sha256((namespace['BUNDLE_SHA256'] + '\0').encode()
                        + (HERE / 'edge.mjs').read_bytes() + (HERE.parent / 'worker_session.mjs').read_bytes()
                        + json.dumps(security, sort_keys=True).encode()).hexdigest()
(HERE / '_edge_policy.mjs').write_text('export const bundleDigest = ' + json.dumps(digest)
                                    + ';\nexport const pythonBundleDigest = ' + json.dumps(namespace['BUNDLE_SHA256'])
                                    + ';\nexport const securityHeaders = ' + json.dumps(security) + ';\n')
(HERE / 'edge-manifest.json').write_text(json.dumps({'bundle_sha256': digest,
    'python_bundle_sha256': namespace['BUNDLE_SHA256']}, indent=2) + '\n')
print('JS gateway bundle ' + digest)
