import json

from ck_agent.mock_data import User

RETRIEVE_KNOWLEDGE_TOOL = {
    "toolSpec": {
        "name": "retrieve_knowledge",
        "description": (
            "Search internal company documents (policies, FAQs, shipping info, company information) "
            "to answer user questions. Use this for any question about company policies, shipping, "
            "returns, or general company information."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query derived from the user's question",
                    }
                },
                "required": ["query"],
            }
        },
    }
}

CHECK_ORDER_STATUS_TOOL = {
    "toolSpec": {
        "name": "check_order_status",
        "description": (
            "Look up order information for a verified user. REQUIRES all three verification fields: "
            "email, last 4 digits of SSN, and date of birth in ISO format. Never call this tool "
            "until all three fields have been collected from the user."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "User email matching pattern @ck<digits>.com",
                    },
                    "ssn_last4": {
                        "type": "string",
                        "description": "Exactly 4 digits",
                    },
                    "dob_iso": {
                        "type": "string",
                        "description": "Date of birth in YYYY-MM-DD format",
                    },
                    "selected_order_id": {
                        "type": "string",
                        "description": (
                            "Optional. If the user has multiple orders and has chosen one, "
                            "pass the order ID here to get details for that specific order."
                        ),
                    },
                },
                "required": ["email", "ssn_last4", "dob_iso"],
            }
        },
    }
}

TOOL_CONFIG = {
    "tools": [RETRIEVE_KNOWLEDGE_TOOL, CHECK_ORDER_STATUS_TOOL]
}


def retrieve_knowledge(query: str) -> str:
    """Stub — replaced with Bedrock KB call in phase 05."""
    return f"[STUB: knowledge lookup for '{query}' — will be wired to Bedrock KB in phase 05]"


def check_order_status(
    email: str,
    ssn_last4: str,
    dob_iso: str,
    selected_order_id: str | None = None,
) -> dict:
    from ck_agent.verification import verify_user, parse_dob

    # Normalize DOB from any user-provided format to ISO YYYY-MM-DD
    dob_parsed = parse_dob(dob_iso)
    if not dob_parsed.ok:
        return {"verified": False, "reason": f"Could not understand date of birth: {dob_parsed.reason}"}
    dob_iso = dob_parsed.value

    result = verify_user(email=email, ssn_last4=ssn_last4, dob_iso=dob_iso)
    if not result.verified:
        return {"verified": False, "reason": result.reason}

    user: User = result.user
    orders = user.orders

    if len(orders) == 0:
        return {"verified": True, "orders": [], "message": "No orders found for this account."}

    if selected_order_id:
        matching = [o for o in orders if o.order_id == selected_order_id]
        if not matching:
            return {"verified": True, "error": f"Order {selected_order_id} not found for this user."}
        return {"verified": True, "order": matching[0].model_dump()}

    if len(orders) == 1:
        return {"verified": True, "order": orders[0].model_dump()}

    return {
        "verified": True,
        "multiple_orders_found": True,
        "action_required": "ask_user_to_select",
        "orders_summary": [
            {"order_id": o.order_id, "status": o.status, "items_summary": o.items_summary}
            for o in orders
        ],
    }


def dispatch_tool(name: str, arguments: dict) -> str:
    """Route a tool call to its implementation. Returns JSON-serializable result."""
    if name == "retrieve_knowledge":
        return retrieve_knowledge(**arguments)
    if name == "check_order_status":
        result = check_order_status(**arguments)
        return json.dumps(result)
    raise ValueError(f"Unknown tool: {name}")
