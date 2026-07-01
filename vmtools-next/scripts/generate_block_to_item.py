#!/usr/bin/env python3
"""Generate BLOCK_TO_ITEM mapping from superwy's list.csv.

Reads list.csv (minecraft,item_id,en_us,zh_cn) and generates a Python
dict mapping block_state -> item_id for litematica_parser.py.

Usage:
    python scripts/generate_block_to_item.py

Output: Prints the BLOCK_TO_ITEM dict to stdout, which can be pasted
        into litematica_parser.py.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def main():
    # Find list.csv relative to this script
    script_dir = Path(__file__).resolve().parent
    csv_path = script_dir.parent.parent / "superwy-master" / "list.csv"

    if not csv_path.exists():
        print(f"Error: list.csv not found at {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Read CSV and build mapping
    mapping: dict[str, str] = {}

    # Default mappings for special blocks
    special_mappings = {
        "minecraft:air": "minecraft:air",
        "minecraft:water": "minecraft:water_bucket",
        "minecraft:lava": "minecraft:lava_bucket",
        "minecraft:bedrock": "minecraft:bedrock",
    }
    mapping.update(special_mappings)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)  # Skip header

        for row in reader:
            if len(row) < 1:
                continue
            item_id = row[0].strip()
            if not item_id or item_id.startswith("@"):
                continue  # Skip empty lines and category headers

            # Add minecraft: prefix if not present
            if not item_id.startswith("minecraft:"):
                full_id = f"minecraft:{item_id}"
            else:
                full_id = item_id

            # For blocks, the block ID and item ID are usually the same
            mapping[full_id] = full_id

    # Generate Python dict to file
    output_path = script_dir / "block_to_item_output.py"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Block -> Item mapping (auto-generated from superwy list.csv)\n")
        f.write(f"# Total: {len(mapping)} entries\n")
        f.write("BLOCK_TO_ITEM = {\n")

        # Sort by key for consistent output
        for key in sorted(mapping.keys()):
            value = mapping[key]
            f.write(f'    "{key}": "{value}",\n')

        f.write("}\n")

    print(f"Generated {len(mapping)} entries to {output_path}")


if __name__ == "__main__":
    main()
