import asyncio
from pycoreconf import CORECONFModel
import cbor2 as cbor
model = CORECONFModel("coreconf-m2m@2026-03-08.sid")
cbor_data = bytes.fromhex("81a1158c551903fa000164572f6d321905fc551903fc0003626d6d00551903fa0000401905b4551903fb0001626b6d00551903fc0001636465671907f1551903fc0002636d2f7319066b551903fc0002636d2f731906ee551903fc0001636465671828551903fa00016464656743188e551903fc0003636b5061190444551903fb0002636b50611927c7551903fb0001632552481902ae")
db = model.create_datastore(cbor_data)
# Try getting keys
print("Type of db:", type(db))
js_db = db.to_json()
measurements = js_db.get("coreconf-m2m:measurements/measurement", [])
print(f"Number of measurements: {len(measurements)}")
if measurements:
    print("Keys of a measurement:", list(measurements[0].keys()))
EOF
./.venv/bin/python3 test_keys.py
