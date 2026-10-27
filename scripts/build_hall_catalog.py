"""Build the Shimazu nationwide hall catalog from P-Lens ODbL JSONL data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


MINIMUM_HALL_COUNT = 3_000
MAXIMUM_TEXT_LENGTH = 200


def read_json_lines(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record must be an object")
            records.append(value)
    return records


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned if 0 < len(cleaned) <= MAXIMUM_TEXT_LENGTH else None


def catalog_entry(record: dict[str, Any]) -> dict[str, Any]:
    hall_id = optional_text(record.get("id"))
    name = optional_text(record.get("name"))
    reading = optional_text(record.get("reading"))
    prefecture = optional_text(record.get("prefecture"))
    checked = optional_text(record.get("checked"))
    if not all((hall_id, name, reading, prefecture, checked)):
        raise ValueError(f"Required hall field is missing: {record.get('id', '<unknown>')}")

    entry: dict[str, Any] = {
        "id": hall_id,
        "name": name,
        "reading": reading,
        "prefecture": prefecture,
        "checked": checked,
    }
    keywords = record.get("keywords")
    if isinstance(keywords, list):
        cleaned_keywords = [text for value in keywords if (text := optional_text(value))]
        if cleaned_keywords:
            entry["keywords"] = cleaned_keywords
    for field in ("branchReading", "address", "officialName", "officialUrl"):
        if text := optional_text(record.get(field)):
            entry[field] = text
    for field in ("lat", "lon"):
        value = record.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            entry[field] = value
    return entry


def build(placed_path: Path, unplaced_path: Path, output_path: Path) -> int:
    entries_by_id: dict[str, dict[str, Any]] = {}
    for record in read_json_lines(placed_path) + read_json_lines(unplaced_path):
        entry = catalog_entry(record)
        hall_id = entry["id"]
        if hall_id in entries_by_id:
            raise ValueError(f"Duplicate hall id: {hall_id}")
        entries_by_id[hall_id] = entry

    halls = sorted(
        entries_by_id.values(),
        key=lambda hall: (hall["prefecture"], hall["reading"], hall["name"], hall["id"]),
    )
    if len(halls) < MINIMUM_HALL_COUNT:
        raise RuntimeError(
            f"Only {len(halls)} halls found; refusing to replace the catalog"
        )

    catalog = {
        "version": 2,
        "generatedAt": dt.datetime.now(dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": "P-Lens parlors",
        "sourceUrl": "https://github.com/p-lens/p-lens-parlors",
        "license": "ODbL-1.0",
        "licenseUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
        "attribution": "© P-Lens contributors, © OpenStreetMap contributors",
        "halls": halls,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return len(halls)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("placed", type=Path)
    parser.add_argument("unplaced", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Wrote {build(args.placed, args.unplaced, args.output)} halls")
