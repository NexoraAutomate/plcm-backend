"""
Seed maintenance-workflow demo roles + users (P0 foundations).

Creates/syncs:
  - Workflow roles ME / FSE / IE (plus existing PD / IM / …)
  - Legacy Maintenance role (notification target)
  - Demo users: demo-me, demo-fse, demo-ie, demo-maintenance, demo-pd, demo-im, …

Usage (from satlife-backend-main with venv active and DATABASE_URL set):
  python scripts/seed_maintenance_demo_users.py
  python scripts/seed_maintenance_demo_users.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import (  # noqa: E402
    ensure_default_admin,
    initialize_roles_and_permissions,
    sync_roles_and_permissions,
)
from app.database import engine  # noqa: E402
from app.domain.workflow_roles import WORKFLOW_ROLE_DB_NAMES, WorkflowRole  # noqa: E402
from app.models.tables import Role, User  # noqa: E402
from app.services.schema_bootstrap import ensure_user_management_schema  # noqa: E402
from app.services.workflow_demo_users import (  # noqa: E402
    WORKFLOW_DEMO_USERS,
    ensure_workflow_demo_users,
)
from app.services.workflow_foundation_seed import ensure_workflow_statuses  # noqa: E402

MAINTENANCE_ROLE_NAMES = (
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ME],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.FSE],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IE],
    "Maintenance",
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM],
)


def _print_status(session: Session) -> None:
    print("\nRoles (maintenance-relevant):")
    for name in MAINTENANCE_ROLE_NAMES:
        role = session.exec(select(Role).where(Role.name == name)).first()
        print(f"  {name:<24}  {'ok' if role else 'MISSING'}")

    print("\nDemo accounts:")
    print(f"  {'username':<18}  {'password':<20}  role")
    print(f"  {'admin':<18}  {'password@82768243':<20}  Admin")
    for entry in WORKFLOW_DEMO_USERS:
        user = session.exec(
            select(User).where(User.username == entry["username"])
        ).first()
        status = "ok" if user else "MISSING"
        print(
            f"  {entry['username']:<18}  {entry['password']:<20}  "
            f"{entry['role']} [{status}]"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed ME/FSE/IE (+ legacy Maintenance) roles and demo users"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report current state without writing",
    )
    args = parser.parse_args()

    ensure_user_management_schema()

    with Session(engine) as session:
        print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")

        if args.dry_run:
            _print_status(session)
            missing_users = sum(
                1
                for entry in WORKFLOW_DEMO_USERS
                if not session.exec(
                    select(User).where(User.username == entry["username"])
                ).first()
            )
            print(f"\nWould create up to {missing_users} missing demo user(s).")
            print("Re-run without --dry-run to sync roles and create users.")
            return

        initialize_roles_and_permissions(session)
        sync_roles_and_permissions(session)
        ensure_default_admin(session)
        ensure_workflow_statuses(session)

        created = ensure_workflow_demo_users(session, force=True)
        print(f"Users: created {created} demo user(s)")

        _print_status(session)
        print(
            "\nDone.\n"
            "Note: Occurrence Report + dual-track (Track A/B) UI is not fully "
            "implemented yet — use these accounts to exercise the live field-service "
            "maintenance path (onsite outcome, soft fix, replace -> IM return, warranty).\n"
            "See docs/specs/maintenance-occurrence-replacement/05-system-test-specification.md "
            "for the target ST scenarios once P1+ lands."
        )


if __name__ == "__main__":
    main()
