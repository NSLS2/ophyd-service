# Load Profile Collections

The service loads device definitions from beamline profile collections. Three formats are supported, and the service can auto-detect which one to use.

## Auto-detection

Point to a profile directory without specifying the format:

```bash
CONFIG_PROFILE_PATH=/path/to/profile bluesky-configuration-service
```

Detection order (first match wins):

1. `happi_db.json` found → **happi**
2. `configs/devices.yml` found → **bits**

## Happi format (LCLS/SLAC)

A JSON database with device class paths and constructor arguments.

Directory structure:

```
profile/
└── happi_db.json
```

Example `happi_db.json`:

```json
{
  "sample_x": {
    "device_class": "ophyd.EpicsMotor",
    "args": ["BL01:SAMPLE:X"],
    "kwargs": {"name": "sample_x"},
    "active": true,
    "beamline": "BL01",
    "functional_group": "motors"
  }
}
```

Load explicitly:

```bash
CONFIG_PROFILE_PATH=/path/to/profile CONFIG_LOAD_STRATEGY=happi bluesky-configuration-service
```

Entries may carry an optional advisory `framework` tag (`"ophyd-sync"` or
`"ophyd-async"`); it is stored on the instantiation spec and consumed by
direct_control, which verifies it against the imported class. Any other value
fails the load.

The `happi_db.json` need not be hand-written: the queueserver worker can
generate one from device constructor calls captured while its startup code
runs (`start-re-manager --existing-devices-happi <dir>` or
`qserver-list-plans-devices --happi-devices ON`). Pointing
`CONFIG_PROFILE_PATH` at that output directory seeds the registry from the
beamline's real startup profile; entries the capture could not make portable
arrive with `active: false` and an explanatory `documentation` note, and are
skipped at load.

## BITS format (BCDA-APS)

YAML-based device definitions with labels and an optional instrument config.

Directory structure:

```
profile/
└── configs/
    ├── devices.yml
    └── iconfig.yml    # optional
```

Example `devices.yml`:

```yaml
ophyd.EpicsMotor:
  - name: sample_x
    prefix: "BL01:SAMPLE:X"
    labels: ["motors", "sample-stage"]

ophyd.EpicsScaler:
  - name: det1
    prefix: "BL01:DET1:"
    labels: ["detectors"]
```

Load explicitly:

```bash
CONFIG_PROFILE_PATH=/path/to/profile CONFIG_LOAD_STRATEGY=bits bluesky-configuration-service
```

## Empty (devices via CRUD API)

For profiles that use IPython startup scripts, the service starts with an
empty device registry. Devices are registered at runtime via the CRUD API,
typically by the Experiment Execution Service (SVC-001) which executes the
startup scripts and syncs discovered devices.

```bash
CONFIG_LOAD_STRATEGY=empty bluesky-configuration-service
```

## First run vs. subsequent runs

On the first startup with a profile, the service:

1. Loads devices from the profile collection
2. Seeds them into the PostgreSQL database
3. Marks the database as seeded

On subsequent startups, the service loads directly from the database. The profile collection is not re-read. This means runtime changes (creates, updates, deletes) persist across restarts.

To force a re-read from the profile, use the reset endpoint:

```bash
curl -X POST http://localhost:8004/api/v1/registry/reset
```

This erases all runtime changes and re-seeds from the profile.
