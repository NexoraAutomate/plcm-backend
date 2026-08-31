"""
Seed workflow manual-testing demo data (users, entity list, configs, inventory).

Usage (from plcm-backend with venv active and DATABASE_URL set):
  python scripts/seed_workflow_demo.py
  python scripts/seed_workflow_demo.py --dry-run
  python scripts/seed_workflow_demo.py --configs-only
  python scripts/seed_workflow_demo.py --inventory-only

Fixtures live under fixtures/workflow-demo/.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

# Allow `python scripts/seed_workflow_demo.py` from repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import (  # noqa: E402
    ensure_default_admin,
    initialize_roles_and_permissions,
    sync_roles_and_permissions,
)
from app.database import engine  # noqa: E402
from app.domain.workflow_status import ItemStatus  # noqa: E402
from app.models.tables import Hierarchy, HierarchyConfiguration, Inventory, InventoryInstance, Status, User  # noqa: E402
from app.services.hierarchy_config_service import create_configuration  # noqa: E402
from app.services.inventory_service import (  # noqa: E402
    create_inventory_instance,
    find_inventory_group,
    sync_inventory_quantity,
)
from app.services.schema_bootstrap import ensure_user_management_schema  # noqa: E402
from app.services.workflow_demo_users import (  # noqa: E402
    WORKFLOW_DEMO_USERS,
    ensure_workflow_demo_users,
)
from app.services.workflow_foundation_seed import ensure_workflow_statuses  # noqa: E402

FIXTURES = ROOT / "fixtures" / "workflow-demo"
ENTITY_LIST_PATH = FIXTURES / "entity_list.json"
CONFIGS_PATH = FIXTURES / "hierarchy_configs.json"
INVENTORY_CSV_PATH = FIXTURES / "inventory_demo.csv"


def _item_status_id(session: Session, name: str) -> int:
    row = session.exec(
        select(Status).where(
            Status.status_name == name,
            Status.status_type == "inventory",
        )
    ).first()
    if not row or row.id is None:
        raise SystemExit(
            f"Inventory status '{name}' is not seeded — start the API once or run "
            "ensure_workflow_statuses first."
        )
    return int(row.id)


def seed_entity_list(session: Session, *, dry_run: bool) -> tuple[int, int]:
    payload = json.loads(ENTITY_LIST_PATH.read_text(encoding="utf-8"))
    created = 0
    skipped = 0
    for entry in payload:
        name = str(entry["name"]).strip()
        level = str(entry["hierarchy_type"]).strip().lower()
        existing = session.exec(
            select(Hierarchy).where(
                Hierarchy.hierarchy_type == level,
                Hierarchy.name == name,
            )
        ).first()
        if existing:
            skipped += 1
            continue
        if dry_run:
            created += 1
            continue
        session.add(
            Hierarchy(
                name=name,
                hierarchy_type=level,
                description=entry.get("description"),
                abbreviation=entry.get("abbreviation"),
                parent_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        created += 1
    if not dry_run and created:
        session.commit()
    return created, skipped


def seed_configs(session: Session, *, dry_run: bool) -> tuple[int, int]:
    configs = json.loads(CONFIGS_PATH.read_text(encoding="utf-8"))
    created = 0
    skipped = 0
    for payload in configs:
        code = str(payload["code"]).strip()
        existing = session.exec(
            select(HierarchyConfiguration).where(HierarchyConfiguration.code == code)
        ).first()
        if existing:
            skipped += 1
            continue
        if dry_run:
            created += 1
            continue
        create_configuration(session, payload)
        created += 1
    return created, skipped


def _existing_serials(session: Session, inventory_id: int) -> set[str]:
    rows = session.exec(
        select(InventoryInstance).where(InventoryInstance.inventory_id == inventory_id)
    ).all()
    return {
        (r.serial_number or "").strip().lower()
        for r in rows
        if (r.serial_number or "").strip()
    }


def seed_inventory(session: Session, *, dry_run: bool) -> tuple[int, int, int]:
    """Returns (groups_created, instances_created, instances_skipped)."""
    available_id = _item_status_id(session, ItemStatus.AVAILABLE.value)
    groups_created = 0
    instances_created = 0
    instances_skipped = 0
    touched_group_ids: set[int] = set()

    with INVENTORY_CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("name") or "").strip()
            inventory_type = (row.get("inventory_type") or "").strip().lower()
            part_number = (row.get("part_number") or "").strip() or None
            serial_number = (row.get("serial_number") or "").strip() or None
            location = (row.get("location") or "").strip() or "WH-DEMO"
            description = (row.get("description") or "").strip() or None
            quantity_raw = (row.get("quantity") or "").strip()
            quantity = int(quantity_raw) if quantity_raw else 0

            if not name or not inventory_type:
                continue

            group = find_inventory_group(
                session,
                name=name,
                inventory_type=inventory_type,
                part_number=part_number,
            )

            if group is None:
                if dry_run:
                    groups_created += 1
                    instances_created += max(quantity, 1 if serial_number else 0)
                    continue
                group = Inventory(
                    name=name,
                    inventory_type=inventory_type,
                    part_number=part_number,
                    quantity=0,
                    description=description,
                    location=location,
                    status_id=available_id,
                    added_date=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(group)
                session.flush()
                groups_created += 1
            elif not serial_number:
                instances_skipped += 1
                continue

            if group is not None and group.id is not None:
                touched_group_ids.add(int(group.id))

            unit_count = max(quantity, 1 if serial_number else 0)
            existing = _existing_serials(session, int(group.id))
            for index in range(unit_count):
                unit_serial = serial_number
                if unit_serial and unit_count > 1:
                    unit_serial = f"{unit_serial}-{index + 1:04d}"
                if unit_serial and unit_serial.lower() in existing:
                    instances_skipped += 1
                    continue
                if dry_run:
                    instances_created += 1
                    continue
                create_inventory_instance(
                    session,
                    group,
                    serial_number=unit_serial,
                    status_id=available_id,
                    location=location,
                )
                instances_created += 1

    if not dry_run:
        for gid in touched_group_ids:
            inv = session.get(Inventory, gid)
            if inv:
                sync_inventory_quantity(session, inv)
        session.commit()

    return groups_created, instances_created, instances_skipped


def _print_users(session: Session) -> None:
    print("\nDemo accounts:")
    print(f"  {'username':<12}  {'password':<20}  role")
    print(f"  {'admin':<12}  {'password@82768243':<20}  Admin")
    for entry in WORKFLOW_DEMO_USERS:
        user = session.exec(
            select(User).where(User.username == entry["username"])
        ).first()
        status = "ok" if user else "MISSING"
        print(
            f"  {entry['username']:<12}  {entry['password']:<20}  "
            f"{entry['role']} [{status}]"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed workflow demo data for manual testing")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing")
    parser.add_argument("--configs-only", action="store_true", help="Seed entity list + configs only")
    parser.add_argument("--inventory-only", action="store_true", help="Seed inventory CSV only")
    args = parser.parse_args()

    if args.configs_only and args.inventory_only:
        raise SystemExit("Choose at most one of --configs-only / --inventory-only")

    for path in (ENTITY_LIST_PATH, CONFIGS_PATH, INVENTORY_CSV_PATH):
        if not path.is_file():
            raise SystemExit(f"Missing fixture: {path}")

    do_users = not args.configs_only and not args.inventory_only
    do_configs = not args.inventory_only
    do_inventory = not args.configs_only

    ensure_user_management_schema()

    with Session(engine) as session:
        if not args.dry_run:
            initialize_roles_and_permissions(session)
            sync_roles_and_permissions(session)
            ensure_default_admin(session)
            ensure_workflow_statuses(session)

        print(f"Fixture dir: {FIXTURES}")
        print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")

        if do_users:
            if args.dry_run:
                missing = 0
                for entry in WORKFLOW_DEMO_USERS:
                    if not session.exec(
                        select(User).where(User.username == entry["username"])
                    ).first():
                        missing += 1
                print(f"Users: would create {missing} missing demo user(s)")
            else:
                n = ensure_workflow_demo_users(session, force=True)
                print(f"Users: created {n} demo user(s)")

        if do_configs:
            ec, es = seed_entity_list(session, dry_run=args.dry_run)
            print(f"Entity list: created={ec} skipped={es}")
            cc, cs = seed_configs(session, dry_run=args.dry_run)
            print(f"Configs: created={cc} skipped={cs}")

        if do_inventory:
            gc, ic, isk = seed_inventory(session, dry_run=args.dry_run)
            print(
                f"Inventory: groups_created={gc} instances_created={ic} "
                f"instances_skipped={isk}"
            )

        _print_users(session)
        print("\nDone. See docs/workflow-specs/MANUAL_TESTING_GUIDE.md in plcm-frontend.")


if __name__ == "__main__":
    main()
