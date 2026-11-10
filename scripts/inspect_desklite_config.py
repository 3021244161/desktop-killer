"""Read-only decoder for 360 DesktopLite's DTFenceData.dtf layout.

This is an inspection script, not a configuration editor. The observed format is
a recursive TLV stream: one ASCII tag, a uint32 little-endian byte length, then
the payload. It refuses incomplete records and unknown scalar encodings.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct


@dataclass
class Node:
    tag: str
    offset: int
    size: int
    value: object


def parse_tlv(data: bytes, start: int = 0, end: int | None = None, depth: int = 0) -> list[Node]:
    end = len(data) if end is None else end
    if depth > 16:
        raise ValueError("excessive DTF nesting")
    nodes = []
    cursor = start
    while cursor < end:
        if end - cursor < 5:
            raise ValueError(f"truncated TLV header at {cursor}")
        tag = chr(data[cursor])
        size = struct.unpack_from("<I", data, cursor + 1)[0]
        payload = cursor + 5
        limit = payload + size
        if limit > end:
            raise ValueError(f"truncated TLV payload at {cursor}")
        if tag == "S":
            value = parse_tlv(data, payload, limit, depth + 1)
        elif tag == "s":
            value = data[payload:limit].decode("utf-16le", errors="strict")
        elif tag in ("d", "B") and size == 4:
            value = struct.unpack_from("<i", data, payload)[0]
        else:
            raise ValueError(f"unrecognized TLV {tag!r}/{size} at {cursor}")
        nodes.append(Node(tag, cursor, size, value))
        cursor = limit
    return nodes


def decode_layout(path: Path) -> dict:
    """Return explicit stored fields; do not invent physical coordinates."""
    data = path.read_bytes()
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("unexpectedly large DTF layout")
    groups = []
    for node in parse_tlv(data):
        if node.tag != "S":
            raise ValueError("expected top-level group container")
        fields: list[Node] = node.value
        scalars = [field.value for field in fields if field.tag != "S"]
        if len(scalars) < 7:
            raise ValueError("incomplete group header")
        items = []
        for item_node in fields:
            if item_node.tag != "S":
                continue
            item = item_node.value
            signature = "".join(field.tag for field in item)
            if signature != "dddssddsdddB":
                raise ValueError(f"unknown icon structure {signature!r} at {item_node.offset}")
            values = [field.value for field in item]
            items.append({
                "id": values[0], "parent_id": values[1],
                "file_size_stored": values[2], "path": values[3], "name": values[4],
                "slot": values[9], "alternate_slot": values[10],
                "extra_string": values[7], "flags_stored": [values[8], values[11]],
                "offset": item_node.offset,
            })
        is_desktop = isinstance(scalars[1], str) and scalars[1].lower().startswith("\\\\.\\display")
        groups.append({
            "id": scalars[0], "name": scalars[1], "is_desktop": is_desktop,
            "stored_tblr": scalars[2:6], "stored_scale_percent": scalars[6],
            "tail_scalars": scalars[7:],
            "last_four_layout_values": scalars[-4:],
            "items": items,
        })
    return {"source": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "format": "TLV: ASCII tag + uint32le byte count; S container, s UTF-16LE, d/B int32le",
            "groups": groups}


def main() -> None:
    default = Path(os.environ["APPDATA"]) / "360Desktoplite" / "DTFence" / "DTFenceData.dtf"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=default)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = decode_layout(args.source)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"bytes": result["bytes"], "sha256": result["sha256"], "groups": [
        {key: group[key] for key in ("id", "name", "is_desktop", "stored_tblr",
                                    "stored_scale_percent", "last_four_layout_values")}
        | {"item_count": len(group["items"]),
           "positioned_items": sum(bool(item["name"]) and item["slot"] >= 0 for item in group["items"])}
        for group in result["groups"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
