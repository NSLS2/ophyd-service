"""Stamp the sentinel simulation identity into RE.md (one-shot, idempotent).

RE.md is a RedisJSONDict over the pod's TLS redis (what nslsii.configure_base
uses); every key lands in every run's start document. Run on each bring-up so
no simulated run can carry a real-looking identity. Mirrors reproduce.sh's
seed_sim_md.
"""

import os

from nslsii import open_redis_client
from redis_json_dict import RedisJSONDict

md = RedisJSONDict(redis_client=open_redis_client(redis_ssl=True), prefix="")
sentinel = {
    "proposal_id": os.environ.get("SIM_PROPOSAL_ID", "000000"),
    "data_session": os.environ.get("SIM_DATA_SESSION", "pass-000000"),
    "PI": "SIMULATED",
    "cycle": "0000-0",
    "endstation": "SIMULATED",
    "proposal_type": "SIMULATED",
    "simulated_beamline": True,
}
md.update(sentinel)
print("RE.md sentinel:", {k: md[k] for k in sentinel})
