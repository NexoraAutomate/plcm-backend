"""
Multiply existing inventory stock for manual / automated test cases.

One run adds 10× current quantity per catalog group:
  - Same part number / supplier original PN
  - Serial numbers continue from last used
  - Location defaults to Room R1 / Cabinet C1 / Rack R1
  - Unit + bulk quote cost = 10
  - No shelf life, no warranty

Usage (from plcm-backend with venv active and DATABASE_URL set):
  python scripts/seed_inventory_x10.py
  python scripts/seed_inventory_x10.py --dry-run
  python scripts/seed_inventory_x10.py --multiplier 5 --ids 1,2,3

Admin UI alternative: Settings → Test Data → Seed inventory stock
(or POST /api/inventory/seed-test-stock/ as Admin with confirm=\"SEED\").
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import engine  # noqa: E402
from app.services.inventory_stock_seed import (  # noqa: E402
    DEFAULT_CABINET,
    DEFAULT_MULTIPLIER,
    DEFAULT_RACK,
    DEFAULT_ROOM,
    DEFAULT_UNIT_COST,
    seed_inventory_stock_multiplier,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add multiplier × current qty to each inventory stock group"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing",
    )
    parser.add_argument(
        "--multiplier",
        type=int,
        default=DEFAULT_MULTIPLIER,
        help=f"Quantity multiplier (default {DEFAULT_MULTIPLIER})",
    )
    parser.add_argument(
        "--unit-cost",
        type=Decimal,
        default=DEFAULT_UNIT_COST,
        help=f"Unit / bulk quote cost (default {DEFAULT_UNIT_COST})",
    )
    parser.add_argument(
        "--room",
        default=DEFAULT_ROOM,
        help=f"Location room (default {DEFAULT_ROOM})",
    )
    parser.add_argument(
        "--cabinet",
        default=DEFAULT_CABINET,
        help=f"Location cabinet (default {DEFAULT_CABINET})",
    )
    parser.add_argument(
        "--rack",
        default=DEFAULT_RACK,
        help=f"Location rack (default {DEFAULT_RACK})",
    )
    parser.add_argument(
        "--ids",
        default="",
        help="Optional comma-separated inventory group ids to limit the seed",
    )
    args = parser.parse_args()

    if args.multiplier < 1:
        raise SystemExit("multiplier must be at least 1")

    inventory_ids = None
    raw_ids = (args.ids or "").strip()
    if raw_ids:
        try:
            inventory_ids = [int(part.strip()) for part in raw_ids.split(",") if part.strip()]
        except ValueError as exc:
            raise SystemExit(f"Invalid --ids value: {args.ids}") from exc

    with Session(engine) as session:
        result = seed_inventory_stock_multiplier(
            session,
            multiplier=args.multiplier,
            unit_cost=args.unit_cost,
            location_room=args.room,
            location_cabinet=args.cabinet,
            location_rack=args.rack,
            dry_run=args.dry_run,
            inventory_ids=inventory_ids,
        )
        if not args.dry_run:
            session.commit()

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"Mode: {mode}")
    print(f"Location: {result.location}")
    print(f"Unit / quote cost: {result.unit_cost}")
    print(
        f"Groups processed={result.groups_processed} "
        f"skipped={result.groups_skipped} "
        f"units_added={result.units_added}"
    )
    for group in result.groups:
        skip = f" skipped={group.skipped_reason}" if group.skipped_reason else ""
        print(
            f"  #{group.inventory_id} {group.name} "
            f"PN={group.part_number or '—'} "
            f"{group.previous_quantity} → {group.new_quantity} "
            f"(+{group.units_added}){skip}"
        )


if __name__ == "__main__":
    main()
