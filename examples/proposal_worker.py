"""Offline protocol example, not a real model or production pricing policy."""
import hashlib
import json
import sys

request = sys.stdin.buffer.read(262145)
if len(request) > 262144:
    sys.exit(2)
value = json.loads(request)
patches = [{'id': row['id'], 'unit_price_cents': row['pack_price_cents'] // row['units_per_pack']}
           for row in value['snapshot']['rows'] if row['unit_price_cents'] is None]
response = {'version': 1, 'request_digest': hashlib.sha256(request).hexdigest(),
            'plans': [{'id': 'offline-derived-repair', 'patches': patches}]}
sys.stdout.write(json.dumps(response))
