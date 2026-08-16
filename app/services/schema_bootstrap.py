"""Ensure newly added columns exist when create_all cannot alter tables."""

from __future__ import annotations

from sqlalchemy import text

from app.database import engine


USER_COLUMN_DDL = [
    ("updated_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_login_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_logout_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_activity_at", "TIMESTAMP WITH TIME ZONE"),
    ("failed_login_count", "INTEGER DEFAULT 0 NOT NULL"),
    ("locked_until", "TIMESTAMP WITH TIME ZONE"),
    ("created_by_id", "INTEGER"),
    ("avatar_url", "VARCHAR"),
    ("password_changed_at", "TIMESTAMP WITH TIME ZONE"),
    ("password_history", "TEXT"),
]

STATUS_COLUMN_DDL = [
    ("color", "VARCHAR"),
]

PROJECT_COLUMN_DDL = [
    ("hierarchy_config_id", "INTEGER"),
    ("hierarchy_config_version", "INTEGER"),
    ("product_type", "VARCHAR(64)"),
    ("flight_count", "INTEGER"),
    ("sdls_per_flight", "INTEGER"),
    ("assigned_hm_id", "INTEGER"),
    ("created_by_id", "INTEGER"),
    ("approved_by_id", "INTEGER"),
    ("approved_at", "TIMESTAMP WITH TIME ZONE"),
    ("successor_project_id", "INTEGER"),
    ("predecessor_project_id", "INTEGER"),
]

SYSTEM_COLUMN_DDL = [
    ("sdls_id", "INTEGER"),
]

FLIGHT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS flight (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(64),
    sequence INTEGER NOT NULL DEFAULT 1,
    description VARCHAR,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    status_id INTEGER REFERENCES status(id),
    created_at TIMESTAMP WITH TIME ZONE
)
"""

SDLS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS sdls (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(64),
    sequence INTEGER NOT NULL DEFAULT 1,
    description VARCHAR,
    product_type VARCHAR(64),
    flight_id INTEGER NOT NULL REFERENCES flight(id) ON DELETE CASCADE,
    status_id INTEGER REFERENCES status(id),
    created_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_RESERVATION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryreservation (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    flight_id INTEGER NOT NULL REFERENCES flight(id),
    sdls_id INTEGER NOT NULL REFERENCES sdls(id),
    target_entity_type VARCHAR(32) NOT NULL,
    target_entity_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    inventory_instance_id INTEGER REFERENCES inventoryinstance(id),
    reserved_by_user_id INTEGER NOT NULL REFERENCES "user"(id),
    reserved_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_reminder_at TIMESTAMP WITH TIME ZONE,
    extension_count INTEGER NOT NULL DEFAULT 0,
    part_number VARCHAR(128),
    serial_number VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    released_at TIMESTAMP WITH TIME ZONE,
    released_by_user_id INTEGER REFERENCES "user"(id),
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_SHORTAGE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryshortage (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    flight_id INTEGER NOT NULL REFERENCES flight(id),
    sdls_id INTEGER NOT NULL REFERENCES sdls(id),
    target_entity_type VARCHAR(32) NOT NULL,
    target_entity_id INTEGER NOT NULL,
    inventory_id INTEGER REFERENCES inventory(id),
    part_number VARCHAR(128),
    qty_short INTEGER NOT NULL DEFAULT 1,
    qty_original INTEGER NOT NULL DEFAULT 1,
    lru_name VARCHAR(255),
    requested_by_user_id INTEGER NOT NULL REFERENCES "user"(id),
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    last_notified_at TIMESTAMP WITH TIME ZONE,
    fulfilled_reservation_id INTEGER REFERENCES inventoryreservation(id),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancelled_by_user_id INTEGER REFERENCES "user"(id),
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_SHORTAGE_NOTICE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryshortagenotice (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    shortage_id INTEGER NOT NULL REFERENCES inventoryshortage(id) ON DELETE CASCADE,
    notice_type VARCHAR(32) NOT NULL,
    part_number VARCHAR(128),
    qty INTEGER NOT NULL DEFAULT 1,
    flight_code VARCHAR(64),
    flight_name VARCHAR(255),
    sdls_code VARCHAR(64),
    sdls_name VARCHAR(255),
    lru_name VARCHAR(255),
    project_id INTEGER,
    project_name VARCHAR(255),
    message VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_RESERVATION_EXPIRY_NOTICE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryreservationexpirynotice (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    reservation_id INTEGER NOT NULL REFERENCES inventoryreservation(id) ON DELETE CASCADE,
    notice_type VARCHAR(32) NOT NULL,
    part_number VARCHAR(128),
    serial_number VARCHAR(128),
    flight_code VARCHAR(64),
    flight_name VARCHAR(255),
    sdls_code VARCHAR(64),
    sdls_name VARCHAR(255),
    inventory_name VARCHAR(255),
    project_id INTEGER,
    project_name VARCHAR(255),
    message VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE
)
"""

ISSUANCE_COLUMN_DDL = [
    ("return_requested_at", "TIMESTAMP WITH TIME ZONE"),
    ("signature_type", "VARCHAR(32)"),
    ("signature_payload", "TEXT"),
    ("item_request_id", "INTEGER"),
    ("reservation_id", "INTEGER"),
    ("project_id", "INTEGER"),
    ("flight_id", "INTEGER"),
    ("sdls_id", "INTEGER"),
    ("item_lifecycle_status", "VARCHAR(64)"),
    ("test_result", "VARCHAR(16)"),
    ("test_recorded_at", "TIMESTAMP WITH TIME ZONE"),
    ("test_recorded_by_id", "INTEGER"),
    ("complete_reported_at", "TIMESTAMP WITH TIME ZONE"),
    ("complete_reported_by_id", "INTEGER"),
    ("verified_at", "TIMESTAMP WITH TIME ZONE"),
    ("verified_by_id", "INTEGER"),
    ("defect_pending", "BOOLEAN DEFAULT FALSE"),
]

HIERARCHY_ASSIGN_DEVELOPER_DDL = [
    ("assigned_developer_id", "INTEGER"),
]

RETURN_NOTICE_COLUMN_DDL = [
    ("decision", "VARCHAR DEFAULT 'pending'"),
    ("decided_at", "TIMESTAMP WITH TIME ZONE"),
    ("decided_by_id", "INTEGER"),
    ("decision_notes", "VARCHAR"),
    ("request_notes", "VARCHAR"),
]

ISSUANCE_EVENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryissuanceevent (
    id SERIAL PRIMARY KEY,
    issuance_id INTEGER NOT NULL REFERENCES inventoryissuance(id),
    inventory_id INTEGER REFERENCES inventory(id),
    inventory_instance_id INTEGER,
    event_type VARCHAR NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    actor_user_id INTEGER,
    actor_name VARCHAR,
    installer_user_id INTEGER,
    installer_name VARCHAR,
    notes VARCHAR,
    part_number VARCHAR,
    serial_number VARCHAR,
    inventory_name VARCHAR,
    inventory_type VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE
)
"""

INSTALLER_NOTICE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryinstallernotice (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    notice_type VARCHAR NOT NULL,
    issuance_id INTEGER REFERENCES inventoryissuance(id),
    inventory_id INTEGER REFERENCES inventory(id),
    inventory_name VARCHAR,
    part_number VARCHAR,
    serial_number VARCHAR,
    message VARCHAR,
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_REWORK_CASE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryreworkcase (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    flight_id INTEGER REFERENCES flight(id),
    sdls_id INTEGER REFERENCES sdls(id),
    target_entity_type VARCHAR(32) NOT NULL,
    target_entity_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    original_instance_id INTEGER REFERENCES inventoryinstance(id),
    current_instance_id INTEGER REFERENCES inventoryinstance(id),
    current_issuance_id INTEGER REFERENCES inventoryissuance(id),
    assigned_developer_id INTEGER REFERENCES "user"(id),
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    stage VARCHAR(32) NOT NULL DEFAULT 'failed',
    attempt_count INTEGER NOT NULL DEFAULT 1,
    disposition VARCHAR(32),
    repaired_at TIMESTAMP WITH TIME ZONE,
    repaired_by_id INTEGER REFERENCES "user"(id),
    opened_at TIMESTAMP WITH TIME ZONE NOT NULL,
    opened_by_id INTEGER REFERENCES "user"(id),
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by_id INTEGER REFERENCES "user"(id),
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_RECALL_TASK_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryrecalltask (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    flight_id INTEGER REFERENCES flight(id),
    sdls_id INTEGER REFERENCES sdls(id),
    target_entity_type VARCHAR(32),
    target_entity_id INTEGER,
    inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    inventory_instance_id INTEGER REFERENCES inventoryinstance(id),
    issuance_id INTEGER REFERENCES inventoryissuance(id),
    assigned_developer_id INTEGER REFERENCES "user"(id),
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    stage VARCHAR(32) NOT NULL DEFAULT 'requested',
    disposition VARCHAR(32),
    forced_return BOOLEAN NOT NULL DEFAULT FALSE,
    forced_by_id INTEGER REFERENCES "user"(id),
    opened_at TIMESTAMP WITH TIME ZONE NOT NULL,
    opened_by_id INTEGER REFERENCES "user"(id),
    returned_at TIMESTAMP WITH TIME ZONE,
    returned_by_id INTEGER REFERENCES "user"(id),
    inspected_at TIMESTAMP WITH TIME ZONE,
    inspected_by_id INTEGER REFERENCES "user"(id),
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by_id INTEGER REFERENCES "user"(id),
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
)
"""

CONFIG_CHANGE_REQUEST_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS configchangerequest (
    id SERIAL PRIMARY KEY,
    source_project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    target_hierarchy_config_id INTEGER REFERENCES hierarchyconfiguration(id),
    target_product_type VARCHAR(64),
    target_flight_count INTEGER,
    target_sdls_per_flight INTEGER,
    reason_remarks VARCHAR,
    status VARCHAR(32) NOT NULL DEFAULT 'REQUESTED',
    successor_project_id INTEGER REFERENCES project(id),
    requested_by_id INTEGER REFERENCES "user"(id),
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL,
    submitted_by_id INTEGER REFERENCES "user"(id),
    submitted_at TIMESTAMP WITH TIME ZONE,
    approved_by_id INTEGER REFERENCES "user"(id),
    approved_at TIMESTAMP WITH TIME ZONE,
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
)
"""

INVENTORY_ITEM_REQUEST_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS inventoryitemrequest (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    flight_id INTEGER NOT NULL REFERENCES flight(id),
    sdls_id INTEGER NOT NULL REFERENCES sdls(id),
    target_entity_type VARCHAR(32) NOT NULL,
    target_entity_id INTEGER NOT NULL,
    assigned_developer_id INTEGER NOT NULL REFERENCES "user"(id),
    requested_by_user_id INTEGER NOT NULL REFERENCES "user"(id),
    inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    inventory_instance_id INTEGER REFERENCES inventoryinstance(id),
    reservation_id INTEGER NOT NULL REFERENCES inventoryreservation(id),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL,
    issued_at TIMESTAMP WITH TIME ZONE,
    issued_issuance_id INTEGER REFERENCES inventoryissuance(id),
    notes VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
)
"""


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
            LIMIT 1
            """
        ),
        {"table": table, "column": column},
    ).first()
    return row is not None


def _add_columns_if_missing(table: str, columns: list[tuple[str, str]]) -> None:
    with engine.begin() as conn:
        for name, ddl in columns:
            conn.execute(
                text(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS {name} {ddl}
                    """
                )
            )


def ensure_user_management_schema() -> None:
    """Idempotent column bootstrap for environments that skip Alembic."""
    _add_columns_if_missing('"user"', USER_COLUMN_DDL)
    _add_columns_if_missing("status", STATUS_COLUMN_DDL)
    _add_columns_if_missing("project", PROJECT_COLUMN_DDL)
    _add_columns_if_missing("inventoryissuance", ISSUANCE_COLUMN_DDL)
    _add_columns_if_missing(
        "hierarchy",
        [("abbreviation", "VARCHAR")],
    )
    _add_columns_if_missing(
        "appdefinitions",
        [
            ("abbrev_system", "VARCHAR DEFAULT 'SYS'"),
            ("abbrev_subsystem", "VARCHAR DEFAULT 'SUB'"),
            ("abbrev_module", "VARCHAR DEFAULT 'MOD'"),
            ("abbrev_unit", "VARCHAR DEFAULT 'UNIT'"),
            ("abbrev_component", "VARCHAR DEFAULT 'COMP'"),
            ("part_template_system", "VARCHAR"),
            ("serial_template_system", "VARCHAR"),
            ("part_template_subsystem", "VARCHAR"),
            ("serial_template_subsystem", "VARCHAR"),
            ("part_template_module", "VARCHAR"),
            ("serial_template_module", "VARCHAR"),
            ("part_template_unit", "VARCHAR"),
            ("serial_template_unit", "VARCHAR"),
            ("part_template_component", "VARCHAR"),
            ("serial_template_component", "VARCHAR"),
        ],
    )

    with engine.begin() as conn:
        conn.execute(text(FLIGHT_TABLE_DDL))
        conn.execute(text(SDLS_TABLE_DDL))
        # Ensure ON DELETE CASCADE even if tables were first created by create_all
        conn.execute(
            text(
                """
                ALTER TABLE flight DROP CONSTRAINT IF EXISTS flight_project_id_fkey
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE flight
                ADD CONSTRAINT flight_project_id_fkey
                FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE sdls DROP CONSTRAINT IF EXISTS sdls_flight_id_fkey
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE sdls
                ADD CONSTRAINT sdls_flight_id_fkey
                FOREIGN KEY (flight_id) REFERENCES flight(id) ON DELETE CASCADE
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_flight_project_id
                ON flight (project_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_sdls_flight_id
                ON sdls (flight_id)
                """
            )
        )
        conn.execute(text(INVENTORY_RESERVATION_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreservation_project_id
                ON inventoryreservation (project_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreservation_status
                ON inventoryreservation (status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreservation_instance_id
                ON inventoryreservation (inventory_instance_id)
                """
            )
        )
        conn.execute(text(INVENTORY_SHORTAGE_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryshortage_part_status
                ON inventoryshortage (part_number, status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryshortage_requested_at
                ON inventoryshortage (requested_at)
                """
            )
        )
        conn.execute(text(INVENTORY_SHORTAGE_NOTICE_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryshortagenotice_user_id
                ON inventoryshortagenotice (user_id)
                """
            )
        )
        conn.execute(text(INVENTORY_RESERVATION_EXPIRY_NOTICE_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreservationexpirynotice_user_id
                ON inventoryreservationexpirynotice (user_id)
                """
            )
        )

    _add_columns_if_missing("system", SYSTEM_COLUMN_DDL)
    _add_columns_if_missing("system", HIERARCHY_ASSIGN_DEVELOPER_DDL)
    _add_columns_if_missing("subsystem", HIERARCHY_ASSIGN_DEVELOPER_DDL)
    _add_columns_if_missing("module", HIERARCHY_ASSIGN_DEVELOPER_DDL)
    _add_columns_if_missing("unit", HIERARCHY_ASSIGN_DEVELOPER_DDL)
    _add_columns_if_missing("component", HIERARCHY_ASSIGN_DEVELOPER_DDL)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_system_sdls_id
                ON system (sdls_id)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE system DROP CONSTRAINT IF EXISTS system_sdls_id_fkey
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'system_sdls_id_fkey'
                    ) THEN
                        ALTER TABLE system
                        ADD CONSTRAINT system_sdls_id_fkey
                        FOREIGN KEY (sdls_id) REFERENCES sdls(id) ON DELETE SET NULL;
                    END IF;
                END $$;
                """
            )
        )

    with engine.begin() as conn:
        had_decision = _column_exists(conn, "inventoryreturnnotice", "decision")
        for name, ddl in RETURN_NOTICE_COLUMN_DDL:
            conn.execute(
                text(
                    f"""
                    ALTER TABLE inventoryreturnnotice
                    ADD COLUMN IF NOT EXISTS {name} {ddl}
                    """
                )
            )
        # First-time add: existing notices are already finalized returns.
        if not had_decision:
            conn.execute(
                text(
                    """
                    UPDATE inventoryreturnnotice
                    SET decision = 'accepted'
                    WHERE decision IS NULL OR decision = 'pending'
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE inventoryreturnnotice
                    SET decision = 'accepted'
                    WHERE decision IS NULL
                    """
                )
            )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreturnnotice_decision
                ON inventoryreturnnotice (decision)
                """
            )
        )
        conn.execute(text(ISSUANCE_EVENT_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryissuanceevent_issuance_id
                ON inventoryissuanceevent (issuance_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryissuanceevent_event_type
                ON inventoryissuanceevent (event_type)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryissuanceevent_serial_number
                ON inventoryissuanceevent (serial_number)
                """
            )
        )
        conn.execute(text(INSTALLER_NOTICE_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryinstallernotice_user_id
                ON inventoryinstallernotice (user_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryinstallernotice_notice_type
                ON inventoryinstallernotice (notice_type)
                """
            )
        )
        conn.execute(text(INVENTORY_ITEM_REQUEST_TABLE_DDL))
        conn.execute(text(INVENTORY_REWORK_CASE_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreworkcase_status
                ON inventoryreworkcase (status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreworkcase_entity
                ON inventoryreworkcase (target_entity_type, target_entity_id)
                """
            )
        )
        conn.execute(text(INVENTORY_RECALL_TASK_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryrecalltask_status
                ON inventoryrecalltask (status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryrecalltask_project
                ON inventoryrecalltask (project_id)
                """
            )
        )
        conn.execute(text(CONFIG_CHANGE_REQUEST_TABLE_DDL))
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_configchangerequest_status
                ON configchangerequest (status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_configchangerequest_source
                ON configchangerequest (source_project_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryitemrequest_status
                ON inventoryitemrequest (status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryitemrequest_developer
                ON inventoryitemrequest (assigned_developer_id)
                """
            )
        )
