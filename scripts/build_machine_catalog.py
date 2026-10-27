#!/usr/bin/env python3
"""Validate an authorized machine feed and publish the compact app catalog."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def text(value: object, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--attribution", required=True)
    parser.add_argument("--license", required=True)
    args = parser.parse_args()
    for value, maximum in ((args.source, 200), (args.attribution, 300), (args.license, 80)):
        if not text(value, maximum):
            raise ValueError("source, attribution and license must be provided")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = payload.get("machines") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) > 30_000:
        raise ValueError("machines must be an array with at most 30,000 entries")

    machines: list[dict[str, object]] = []
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each machine must be an object")
        required = {"id": 160, "name": 160, "reading": 200, "manufacturer": 120}
        if any(not text(row.get(key), maximum) for key, maximum in required.items()):
            raise ValueError("machine has an invalid required text field")
        if str(row["id"]) in ids:
            raise ValueError(f"duplicate machine id: {row['id']}")
        ids.add(str(row["id"]))
        if row.get("kind") not in {"pachinko", "pachislot"}:
            raise ValueError("kind must be pachinko or pachislot")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or len(aliases) > 30 or any(not text(alias, 160) for alias in aliases):
            raise ValueError("aliases are invalid")
        released = row.get("releasedOn")
        if released is not None:
            dt.date.fromisoformat(str(released))
        model = row.get("modelName")
        if model is not None and not text(model, 200):
            raise ValueError("modelName is invalid")
        machine = {key: row[key] for key in ("id", "name", "reading", "manufacturer", "kind", "releasedOn", "modelName") if key in row}
        machine["aliases"] = aliases
        machines.append(machine)

    machines.sort(key=lambda machine: (str(machine.get("releasedOn", "")), str(machine["reading"])), reverse=True)
    output = {
        "version": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": args.source,
        "attribution": args.attribution,
        "license": args.license,
        "machines": machines,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
