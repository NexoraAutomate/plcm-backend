"""Represent component stock as individual inventory instances."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t6u7v8w9x0"
down_revision: Union[str, None] = "s5t6u7v8w9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "inventory" not in tables or "inventoryinstance" not in tables:
        return

    # Convert legacy component quantity pools only when no unit rows exist.
    # Existing parent-level physical fields are copied to every generated unit.
    bind.execute(
        sa.text(
            """
            INSERT INTO inventoryinstance (
                inventory_id,
                serial_number,
                original_serial_number,
                configuration_item,
                status_id,
                holder_user_id,
                location,
                added_date,
                shelf_life_expires_at,
                picture_url,
                installation_date,
                installed_by_id,
                original_part_number,
                updated_at
            )
            SELECT
                inv.id,
                CASE
                    WHEN NULLIF(BTRIM(inv.serial_number), '') IS NULL
                        THEN 'UNIT-' || inv.id || '-' || LPAD(series.n::text, 4, '0')
                    WHEN COALESCE(inv.quantity, 0) = 1
                        THEN BTRIM(inv.serial_number)
                    ELSE BTRIM(inv.serial_number) || '-' || LPAD(series.n::text, 4, '0')
                END,
                CASE
                    WHEN NULLIF(BTRIM(inv.original_serial_number), '') IS NULL
                        THEN CASE
                            WHEN NULLIF(BTRIM(inv.serial_number), '') IS NULL
                                THEN 'UNIT-' || inv.id || '-' || LPAD(series.n::text, 4, '0')
                            WHEN COALESCE(inv.quantity, 0) = 1
                                THEN BTRIM(inv.serial_number)
                            ELSE BTRIM(inv.serial_number) || '-' || LPAD(series.n::text, 4, '0')
                        END
                    WHEN COALESCE(inv.quantity, 0) = 1
                        THEN BTRIM(inv.original_serial_number)
                    ELSE BTRIM(inv.original_serial_number) || '-' || LPAD(series.n::text, 4, '0')
                END,
                COALESCE(inv.configuration_item, inv.part_number, inv.name),
                inv.status_id,
                inv.holder_user_id,
                COALESCE(NULLIF(BTRIM(inv.location), ''), 'Warehouse'),
                inv.added_date,
                inv.shelf_life_expires_at,
                inv.picture_url,
                inv.installation_date,
                inv.installed_by_id,
                COALESCE(inv.original_part_number, inv.part_number),
                inv.updated_at
            FROM inventory AS inv
            CROSS JOIN LATERAL generate_series(
                1, GREATEST(COALESCE(inv.quantity, 0), 0)
            ) AS series(n)
            WHERE inv.inventory_type = 'component'
              AND COALESCE(inv.quantity, 0) > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM inventoryinstance AS existing
                  WHERE existing.inventory_id = inv.id
              )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE inventory AS inv
            SET quantity = (
                    SELECT COUNT(*)
                    FROM inventoryinstance AS inst
                    WHERE inst.inventory_id = inv.id
                ),
                serial_number = NULL,
                holder_user_id = NULL,
                location = NULL,
                shelf_life_expires_at = NULL,
                picture_url = NULL,
                installation_date = NULL,
                installed_by_id = NULL,
                original_part_number = NULL,
                original_serial_number = NULL
            WHERE inv.inventory_type = 'component'
              AND EXISTS (
                  SELECT 1
                  FROM inventoryinstance AS inst
                  WHERE inst.inventory_id = inv.id
              )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_inventoryinstance_inventory_serial_ci
            ON inventoryinstance (inventory_id, LOWER(serial_number))
            WHERE serial_number IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DROP INDEX IF EXISTS uq_inventoryinstance_inventory_serial_ci")
    )
