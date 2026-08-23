"""Inventory CSV / JSON import grouping: one catalog row per part number."""

from __future__ import annotations

from app.services.inventory_import_export import (
    parse_csv_groups,
    parse_json_groups,
    split_serial_numbers,
)


def test_split_serial_numbers_accepts_delimiters_and_json():
    assert split_serial_numbers("SN-1;SN-2 | SN-3") == ["SN-1", "SN-2", "SN-3"]
    assert split_serial_numbers('["SN-A","SN-B"]') == ["SN-A", "SN-B"]
    assert split_serial_numbers([" SN-1 ", "", "SN-2"]) == ["SN-1", "SN-2"]


def test_csv_duplicate_part_numbers_collapse_to_child_serials():
    text = (
        "name,inventory_type,part_number,serial_number,quantity,location\n"
        "SDLS,system,PN-0001,SN-0001-001,1,WH-A/Rack-01\n"
        "SDLS,system,PN-0001,SN-0001-002,1,WH-A/Rack-01\n"
        "SDLS,system,PN-0001,SN-0001-003,1,WH-A/Rack-01\n"
    )
    groups, errors = parse_csv_groups(text)
    assert errors == []
    assert len(groups) == 1
    group = groups[0]
    assert group.name == "SDLS"
    assert group.part_number == "PN-0001"
    assert [s.serial_number for s in group.serials] == [
        "SN-0001-001",
        "SN-0001-002",
        "SN-0001-003",
    ]


def test_csv_serial_numbers_column_is_one_row_per_part():
    text = (
        "name,inventory_type,part_number,serial_numbers,quantity,location\n"
        "System - DPU,subsystem,PN-0003,SN-0003-001;SN-0003-002;SN-0003-003,3,WH-A/Rack-03\n"
    )
    groups, errors = parse_csv_groups(text)
    assert errors == []
    assert len(groups) == 1
    assert [s.serial_number for s in groups[0].serials] == [
        "SN-0003-001",
        "SN-0003-002",
        "SN-0003-003",
    ]


def test_json_nested_instances_keep_parent_child_relationship():
    text = """
    {
      "version": 1,
      "items": [
        {
          "name": "SUM Card",
          "inventory_type": "unit",
          "part_number": "PN-0046",
          "location": "WH-A/Rack-06",
          "instances": [
            {"serial_number": "SN-0046-001", "location": "WH-A/Rack-06"},
            {"serial_number": "SN-0046-002", "location": "WH-B/Bin-01"}
          ]
        }
      ]
    }
    """
    groups, errors = parse_json_groups(text)
    assert errors == []
    assert len(groups) == 1
    group = groups[0]
    assert group.part_number == "PN-0046"
    assert [s.serial_number for s in group.serials] == ["SN-0046-001", "SN-0046-002"]
    assert group.serials[1].location == "WH-B/Bin-01"


def test_component_rows_do_not_create_serial_children():
    text = (
        "name,inventory_type,part_number,quantity,location\n"
        "Az Motor,component,PN-0059,8,WH-A/Rack-07\n"
        "Az Motor,component,PN-0059,2,WH-A/Rack-07\n"
    )
    groups, errors = parse_csv_groups(text)
    assert errors == []
    assert len(groups) == 1
    assert groups[0].quantity == 10
    assert groups[0].serials == []
