import json
import pytest

from ck_agent.tools import TOOL_CONFIG, dispatch_tool, check_order_status
from ck_agent.mock_data import USERS


# ---------------------------------------------------------------------------
# Tool config shape
# ---------------------------------------------------------------------------

def test_tool_config_has_two_tools():
    assert "tools" in TOOL_CONFIG
    assert len(TOOL_CONFIG["tools"]) == 2


def test_tool_config_each_has_required_fields():
    for tool in TOOL_CONFIG["tools"]:
        assert "toolSpec" in tool
        spec = tool["toolSpec"]
        assert "name" in spec
        assert "description" in spec
        assert "inputSchema" in spec
        assert spec["inputSchema"]["json"]["type"] == "object"


def test_tool_names_are_known():
    names = {t["toolSpec"]["name"] for t in TOOL_CONFIG["tools"]}
    assert names == {"retrieve_knowledge", "check_order_status"}


# ---------------------------------------------------------------------------
# dispatch_tool
# ---------------------------------------------------------------------------

def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch_tool("not_a_tool", {})


def test_dispatch_check_order_status_returns_json_string():
    result = dispatch_tool(
        "check_order_status",
        {"email": "nobody@ck99.com", "ssn_last4": "0000", "dob_iso": "1990-01-01"},
    )
    parsed = json.loads(result)
    assert "verified" in parsed


# ---------------------------------------------------------------------------
# check_order_status — all 4 mock users
# ---------------------------------------------------------------------------

def test_alice_multi_order():
    """Alice has 3 orders — response should indicate multiple orders found."""
    alice = USERS["alice@ck1.com"]
    r = check_order_status(
        email="alice@ck1.com",
        ssn_last4=alice.ssn_full[-4:],
        dob_iso=alice.dob_iso,
    )
    assert r["verified"] is True
    assert r.get("multiple_orders_found") is True
    assert len(r["orders_summary"]) == 3


def test_alice_order_selection():
    """Selecting a specific order returns just that order's details."""
    alice = USERS["alice@ck1.com"]
    order_id = alice.orders[0].order_id
    r = check_order_status(
        email="alice@ck1.com",
        ssn_last4=alice.ssn_full[-4:],
        dob_iso=alice.dob_iso,
        selected_order_id=order_id,
    )
    assert r["verified"] is True
    assert r["order"]["order_id"] == order_id


def test_bob_single_order():
    """Bob has 1 order — returned directly without selection step."""
    bob = USERS["bob@ck2.com"]
    r = check_order_status(
        email="bob@ck2.com",
        ssn_last4=bob.ssn_full[-4:],
        dob_iso=bob.dob_iso,
    )
    assert r["verified"] is True
    assert "order" in r
    assert "multiple_orders_found" not in r


def test_carol_zero_orders():
    """Carol is a verified user with no orders."""
    carol = USERS["carol@ck123.com"]
    r = check_order_status(
        email="carol@ck123.com",
        ssn_last4=carol.ssn_full[-4:],
        dob_iso=carol.dob_iso,
    )
    assert r["verified"] is True
    assert r["orders"] == []


def test_unknown_email_not_verified():
    r = check_order_status(
        email="ghost@ck99.com",
        ssn_last4="1234",
        dob_iso="1990-01-01",
    )
    assert r["verified"] is False


def test_wrong_ssn_not_verified():
    alice = USERS["alice@ck1.com"]
    r = check_order_status(
        email="alice@ck1.com",
        ssn_last4="0000",
        dob_iso=alice.dob_iso,
    )
    assert r["verified"] is False


def test_invalid_order_id_returns_error():
    alice = USERS["alice@ck1.com"]
    r = check_order_status(
        email="alice@ck1.com",
        ssn_last4=alice.ssn_full[-4:],
        dob_iso=alice.dob_iso,
        selected_order_id="ORD-DOESNT-EXIST",
    )
    assert r["verified"] is True
    assert "error" in r
