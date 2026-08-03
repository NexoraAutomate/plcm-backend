"""
Seed realistic FaultyEntity repair timelines so executive MTTR / MTBF
gauges and month-over-month trends have data.

Usage (from plcm-backend with venv active):
  python scripts/seed_reliability_metrics.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.database import engine
from app.models.base import CaseStatus, EntityType, FaultType, FaultyEntityStatus
from app.models.tables import FaultyEntity, MaintenanceCase, Project
from app.services.dashboard_service import DashboardFilters, _build_reliability


def _utc(year: int, month: int, day: int, hour: int = 10) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def main() -> None:
    with Session(engine) as session:
        project = session.exec(select(Project).order_by(Project.id).limit(1)).first()
        if not project:
            raise SystemExit("No projects found — create a project before seeding.")

        # Normalize any prior micro-duration resolved faults so they do not skew MTTR.
        existing_resolved = session.exec(
            select(FaultyEntity).where(FaultyEntity.resolved_at.isnot(None))
        ).all()
        for fe in existing_resolved:
            if fe.identified_at and fe.resolved_at:
                duration_h = (_as_utc(fe.resolved_at) - _as_utc(fe.identified_at)).total_seconds() / 3600.0
                if duration_h < 1.0:
                    # Stretch to a realistic ~20h repair anchored on identified_at
                    fe.resolved_at = _as_utc(fe.identified_at) + timedelta(hours=20.0)
                    if fe.status != FaultyEntityStatus.RESOLVED:
                        fe.status = FaultyEntityStatus.RESOLVED

        # Avoid duplicate seed runs
        already = session.exec(
            select(MaintenanceCase).where(MaintenanceCase.case_number.like("MC-SEED-REL-%"))
        ).first()
        if already:
            session.commit()
            rel = _build_reliability(session, DashboardFilters())
            print("Seed cases already present — normalized micro-repairs only.")
            print(f"MTTR: {rel.mttr.value} {rel.mttr.unit} (change_value={rel.mttr.change_value})")
            print(f"MTBF: {rel.mtbf.value} {rel.mtbf.unit} (change_value={rel.mtbf.change_value})")
            return

        # Specs: (identified_at, repair_hours, fault_type)
        specs: list[tuple[datetime, float, FaultType]] = [
            (_utc(2026, 1, 8), 22.0, FaultType.HARDWARE),
            (_utc(2026, 2, 12), 19.5, FaultType.SOFTWARE),
            (_utc(2026, 3, 5), 25.0, FaultType.ELECTRICAL),
            (_utc(2026, 3, 28), 17.0, FaultType.MECHANICAL),
            (_utc(2026, 4, 20), 21.0, FaultType.HARDWARE),
            (_utc(2026, 5, 15), 18.0, FaultType.SOFTWARE),
            (_utc(2026, 6, 3), 24.0, FaultType.HARDWARE),
            (_utc(2026, 6, 11), 20.5, FaultType.ELECTRICAL),
            (_utc(2026, 6, 18), 22.0, FaultType.SOFTWARE),
            (_utc(2026, 6, 25), 19.0, FaultType.MECHANICAL),
            (_utc(2026, 7, 2), 18.0, FaultType.HARDWARE),
            (_utc(2026, 7, 9), 16.5, FaultType.SOFTWARE),
            (_utc(2026, 7, 14), 19.0, FaultType.ELECTRICAL),
            (_utc(2026, 7, 21), 17.5, FaultType.MECHANICAL),
            (_utc(2026, 7, 27), 18.5, FaultType.HARDWARE),
        ]

        created = 0
        for i, (identified_at, repair_hours, fault_type) in enumerate(specs, start=1):
            resolved_at = identified_at + timedelta(hours=repair_hours)
            case = MaintenanceCase(
                case_number=f"MC-SEED-REL-{i:03d}",
                project_id=project.id,
                description=f"Seeded reliability event #{i} for executive dashboard metrics",
                status=CaseStatus.RESOLVED,
                reported_at=identified_at,
                resolved_at=resolved_at,
                project_name=project.name,
            )
            session.add(case)
            session.flush()

            fe = FaultyEntity(
                case_id=case.id,
                entity_type=EntityType.MODULE,
                entity_id=project.id,
                entity_name=f"Seed Module {i}",
                fault_type=fault_type,
                fault_description=f"Seeded fault for MTTR/MTBF demo ({repair_hours}h repair)",
                status=FaultyEntityStatus.RESOLVED,
                identified_at=identified_at,
                resolved_at=resolved_at,
            )
            session.add(fe)
            created += 1

        session.commit()

        rel = _build_reliability(session, DashboardFilters())
        print(f"Seeded {created} resolved faulty entities on project id={project.id} ({project.name})")
        print(f"MTTR: {rel.mttr.value} {rel.mttr.unit} (change_value={rel.mttr.change_value})")
        print(f"MTBF: {rel.mtbf.value} {rel.mtbf.unit} (change_value={rel.mtbf.change_value})")


if __name__ == "__main__":
    main()
