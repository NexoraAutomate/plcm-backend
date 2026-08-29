"""Unit coverage for opaque signed inventory label payloads."""

from app.domain.workflow_permissions import WORKFLOW_PERMISSION_NAMES
from app.services.inventory_label_service import parse_signed_payload, signed_payload


def test_signed_payload_round_trip():
    label_id = "7c1c90a8f9e64707b3db3fd3cc53f3e4"
    payload = signed_payload(label_id)

    assert parse_signed_payload(payload) == (label_id, True)


def test_signed_payload_rejects_tampering():
    label_id = "7c1c90a8f9e64707b3db3fd3cc53f3e4"
    payload = signed_payload(label_id)
    prefix, _, signature = payload.rpartition(".")

    assert parse_signed_payload(f"{prefix}x.{signature}") == (f"{label_id}x", False)
    assert parse_signed_payload(f"{prefix}.{signature[:-1]}x") == (label_id, False)
    assert parse_signed_payload("PLCM1.not-a-label.bad-signature") == (
        "not-a-label",
        False,
    )


def test_label_permissions_are_registered_for_workflow_roles():
    assert "inventory.label.generate" in WORKFLOW_PERMISSION_NAMES
    assert "inventory.label.print" in WORKFLOW_PERMISSION_NAMES
    assert "inventory.label.scan" in WORKFLOW_PERMISSION_NAMES
    assert "inventory.label.manage" in WORKFLOW_PERMISSION_NAMES
