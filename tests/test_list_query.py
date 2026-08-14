from app.models.tables import Customer, Order, Project
from app.services.list_query import (
    combine_where,
    eq_if_set,
    inventory_search_where,
    inventory_stock_where,
    text_search,
)


def test_text_search_ignores_blank():
    assert text_search(Project, None, "name") is None
    assert text_search(Project, "   ", "name") is None


def test_text_search_builds_or_clause():
    clause = text_search(Project, "alpha", "name", "description", "product_type")
    assert clause is not None


def test_eq_if_set():
    assert eq_if_set(Project, "status_id", None) is None
    assert eq_if_set(Project, "status_id", 4) is not None
    assert eq_if_set(Project, "missing_field", 1) is None


def test_combine_where_skips_none():
    name = text_search(Customer, "acme", "name")
    status = eq_if_set(Customer, "status_id", None)
    combined = combine_where(name, status)
    assert combined is not None


def test_order_and_inventory_search_helpers():
    assert text_search(Order, "PO-1", "order_number", "title") is not None
    assert inventory_search_where("") is None
    assert inventory_search_where("SN-100") is not None
    assert inventory_stock_where("all") is None
    assert inventory_stock_where("reserved") is not None
    assert inventory_stock_where("available") is not None
    assert inventory_stock_where("out_of_stock") is not None
    assert inventory_stock_where("unknown") is None
