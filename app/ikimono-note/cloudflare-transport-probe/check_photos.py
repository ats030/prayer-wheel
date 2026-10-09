"""Actual Workers strict base64/frame/JPEG rejection; synthetic, no AI."""
import base64
import json
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from check_public import HERE, ORIGIN, NoRedirect, credential

wire = (HERE / 'fixtures/wire-1.json').read_bytes()
payload = json.loads(wire)
encoded = payload['contents'][0]['parts'][0]['inline_data']['data']
assert encoded.endswith('='), 'Synthetic fixture must exercise strict unused bits'
alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
index = len(encoded) - (3 if encoded.endswith('==') else 2)
unused_bits = encoded[:index] + alphabet[alphabet.index(encoded[index]) ^ 1] + encoded[index + 1:]
assert base64.b64decode(unused_bits) == base64.b64decode(encoded)
bad = [unused_bits, encoded[:4] + '=' + encoded[5:], encoded[:4] + ' ' + encoded[5:], encoded + '=',
       base64.b64encode(base64.b64decode(encoded)[:-2] + b'xx').decode()]
requests = []
for photo in bad:
    value = json.loads(wire)
    value['contents'][0]['parts'][0]['inline_data']['data'] = photo
    requests.append(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
requests += [wire + b' ', wire.replace(b'"contents":', b'"contents":[],"contents":', 1),
             wire.replace(b'"data":', b'"data":"ignored","data":', 1)]
for body in requests:
    request = Request(ORIGIN + '/checked/1', data=body, method='POST', headers={
        'Authorization': credential, 'Content-Type': 'application/json', 'User-Agent': 'ikimono-photo-reject-check/1.0'})
    try:
        response = build_opener(NoRedirect).open(request, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == 400
        assert 'X-Preview-Isolate' not in response.headers
print('PASS: actual Workers strict unused bits/padding/characters/JPEG tail/noncanonical JSON/duplicate keys; no AI')
