#!/usr/bin/env python3
"""Make the happi database of the simulated IOS beamline from the one of sites/ios.

    python make_happi_db.py            # write happi_db.json and ios_devs.py here
    python make_happi_db.py --check    # fail if the committed files are not what this makes

``sites/ios`` was made before the simulation existed. ``overrides.json`` lists where the IOS
profile collection disagrees with it; the profile wins. The result is committed: the
configuration service loads it when its database is empty, so nothing is merged when the
service starts. Run this again only when ``sites/ios`` or ``overrides.json`` changes, and run
``sim/check_happi.py`` of ios-profile-collection to see what still differs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "ios"


def build() -> dict[str, str]:
    overrides = json.loads((HERE / "overrides.json").read_text())
    database = json.loads((BASE / "happi_db.json").read_text())
    for name, spec in overrides["add_devices"].items():
        if name in database:
            raise SystemExit(f"{name} is in sites/ios already: drop it from overrides.json")
        database[name] = {
            "_id": name,
            "active": True,
            "documentation": f"Added for the simulation: {spec['reason']}",
            "args": ["{{prefix}}"],
            "kwargs": {"name": "{{name}}"},
            "type": "OphydItem",
            "device_class": spec["device_class"],
            "name": name,
            "prefix": spec["prefix"],
        }
    files = {"ios_devs.py": (BASE / "ios_devs.py").read_text()}
    for change in overrides["replace_text"]:
        text = files[change["file"]]
        if change["old"] not in text:
            raise SystemExit(f"{change['file']}: {change['old']!r} is not there any more: update overrides.json")
        files[change["file"]] = text.replace(change["old"], change["new"])
    files["happi_db.json"] = json.dumps(dict(sorted(database.items())), indent=2) + "\n"
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="do not write; fail on a difference")
    args = parser.parse_args()
    stale = []
    for name, content in build().items():
        path = HERE / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(name)
        else:
            path.write_text(content)
            print(f"wrote {path.relative_to(HERE.parent.parent.parent)}")
    if stale:
        print("out of date: " + ", ".join(stale) + " (run make_happi_db.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
