"""Phase-1 correlation helper: diff two DP dumps to map DP ids to meaning.

Capture dumps in different states with::

    python tools/cli.py dump --save captures

then diff any two::

    python tools/correlate.py captures/dp_dump_A.json captures/dp_dump_B.json

Changed DPs between a known before/after (e.g. ride a known distance, or flip
one setting in the official app) are your candidates for that variable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str) -> dict[int, dict]:
    data = json.loads(Path(path).read_text())
    return {dp["id"]: dp for dp in data["datapoints"]}


def main(a: str, b: str) -> None:
    da, db = _load(a), _load(b)
    ids = sorted(set(da) | set(db))
    print(f"{'id':>3}  {'change':<8}  before -> after")
    print(f"{'-'*3}  {'-'*8}  {'-'*40}")
    for dp_id in ids:
        va, vb = da.get(dp_id), db.get(dp_id)
        if va is None:
            print(f"{dp_id:>3}  {'ADDED':<8}  -- -> {vb['value']!r} ({vb['type']})")
        elif vb is None:
            print(f"{dp_id:>3}  {'REMOVED':<8}  {va['value']!r} -> --")
        elif va["value"] != vb["value"]:
            print(f"{dp_id:>3}  {'CHANGED':<8}  {va['value']!r} -> {vb['value']!r} "
                  f"({va['type']})")
        else:
            print(f"{dp_id:>3}  {'same':<8}  {va['value']!r}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python tools/correlate.py <dump_a.json> <dump_b.json>")
    main(sys.argv[1], sys.argv[2])
