# Site sandbox: the simulated IOS beamline

The happi database that the configuration service loads when it runs against the **simulated**
IOS IOCs of
[`ios-profile-collection`](https://github.com/NSLS-II-IOS/ios-profile-collection) (`sim/`).

It is generated from [`../ios`](../ios) by `make_happi_db.py`, with the changes in
`overrides.json`. **Where `sites/ios` and the profile collection disagree, the profile wins**:
it is what runs at the beamline, and the simulated IOCs serve what its classes ask for.
`sites/ios` was made before the simulation existed.

| File | What it is |
| --- | --- |
| `overrides.json` | The differences, each with its reason. The only file to edit. |
| `make_happi_db.py` | Writes the two generated files. `--check` fails when they are out of date. |
| `happi_db.json`, `ios_devs.py` | Generated and committed. The service loads them when its database is empty. |

The files are generated **once, when the inputs change**, and committed. Nothing is merged when
the service starts.

## What differs from `sites/ios`

* `ios_devs.py`: the SPECS cam PV `TOTAL_POINTS_ITERTION_RBV` has the spelling that the profile
  requests (a typo in the profile, served by the simulation).
* Five devices the profile has and `sites/ios` lacks: `dm1_gv2_open`, `dm1_gv2_close`,
  `bt_gv1_open`, `bt_gv1_close`, `kb_vert`.

## Checking against the profile

From a clone of `ios-profile-collection` (branch with `sim/check_happi.py`), in its `qs-sim` pixi
environment:

```bash
python sim/check_happi.py --happi PATH/TO/ophyd-service/integration/happi/sites/ios-sim/happi_db.json
```

It lists devices whose PV sets differ from the profile's and the PVs of the registry that the
simulated IOC does not serve. Known, and the same as the simulation's own gaps: the Vortex (290
PVs), the SPECS camera (36), the KB mirror (19) and four valves (4); the simulation answers for
them only with `IOS_SIM_FALLBACK=1`. The Xspress3 shows 45 extra `C1SCA` PVs that the offline
walk of the profile does not reach; the simulation serves all of them.

## Using it

```text
CONFIG_LOAD_STRATEGY=happi
CONFIG_PROFILE_PATH=/profile        # this directory, mounted read-only
PYTHONPATH=/profile                 # so that ios_devs is importable
```

`ios_devs.Xspress3IOS` is built with `nslsii`. The community image does not have it: build the
configuration service with `--build-arg EXTRA_PIP_PACKAGES=nslsii==0.11.8` (without it the `xs3`
entry cannot load).
