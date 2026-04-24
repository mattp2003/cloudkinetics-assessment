# Phase 02 — Mock Data & Tool Definitions

## Prerequisites

- [ ] Phase 01 complete
- [ ] `src/ck_agent/` directory exists

## Goal

Mock user/order data and two tool definitions (matching Bedrock Converse API tool format) ready to be wired into the agent. Everything local, no AWS calls yet.

## Context for Claude Code

- We define TWO tools: `retrieve_knowledge` and `check_order_status`
- In this phase, `retrieve_knowledge` returns a hardcoded string; Bedrock KB integration comes in phase 05
- Mock data lives in-memory (dict). Later moved to DynamoDB in phase 11.
- The assessment's tricky requirements (email regex, SSN last-4, DOB natural-language) are NOT handled here — only in phase 03
- Tool input schemas must match Bedrock Converse API `toolConfig` format exactly

## Steps

### 2.1 — `src/ck_agent/mock_data.py`

Create a dict of 4 mock users. Cover these cases explicitly:

| Email | Name | Orders | Purpose |
|-------|------|--------|---------|
| `alice@ck1.com` | Alice Nguyen | 3 orders | Tests multi-order selection flow |
| `bob@ck2.com` | Bob Tran | 1 order | Tests simple happy path |
| `carol@ck123.com` | Carol Le | 0 orders | Tests "no orders found" |
| `dan@ck5.com` | Dan Pham | 2 orders, one delayed | Tests varied statuses |

Each user has: `full_name`, `ssn_full` (9 digits, string), `dob_iso` (YYYY-MM-DD), `orders` list.
Each order has: `order_id` (like `ORD-2025-001`), `status` (`Processing` | `Shipped` | `Out for Delivery` | `Delivered` | `Delayed`), `last_updated` (ISO timestamp), `tracking_number`, `items_summary` (short string).

Expose:
- `USERS: dict[str, User]` — keyed by email
- `get_user_by_email(email: str) -> User | None`
- Pydantic models: `Order`, `User`

### 2.2 — `src/ck_agent/tools.py`

Define tool schemas in the exact format Bedrock Converse API expects. Two tools:

**Tool 1: `retrieve_knowledge`**
```python
{
    "toolSpec": {
        "name": "retrieve_knowledge",
        "description": "Search internal company documents (policies, FAQs, shipping info, company information) to answer user questions. Use this for any question about company policies, shipping, returns, or general company information.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query derived from the user's question"
                    }
                },
                "required": ["query"]
            }
        }
    }
}
```

**Tool 2: `check_order_status`**
```python
{
    "toolSpec": {
        "name": "check_order_status",
        "description": "Look up order information for a verified user. REQUIRES all three verification fields: email, last 4 digits of SSN, and date of birth in ISO format. Never call this tool until all three fields have been collected from the user.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "User email matching pattern @ck<digits>.com"},
                    "ssn_last4": {"type": "string", "description": "Exactly 4 digits"},
                    "dob_iso": {"type": "string", "description": "Date of birth in YYYY-MM-DD format"},
                    "selected_order_id": {"type": "string", "description": "Optional. If the user has multiple orders and has chosen one, pass the order ID here to get details for that specific order."}
                },
                "required": ["email", "ssn_last4", "dob_iso"]
            }
        }
    }
}
```

Note the `selected_order_id` optional parameter — this is how the agent handles the multi-order flow.

### 2.3 — Tool implementation stubs in `tools.py`

```python
def retrieve_knowledge(query: str) -> str:
    """Stub — replaced with Bedrock KB call in phase 05."""
    return f"[STUB: knowledge lookup for '{query}' — will be wired to Bedrock KB in phase 05]"

def check_order_status(
    email: str,
    ssn_last4: str,
    dob_iso: str,
    selected_order_id: str | None = None,
) -> dict:
    """
    Verifies user and returns order info.
    Verification logic imported from verification.py (phase 03 will implement).
    Returns structured dict with verification_ok + orders or error.
    """
    # Import here to avoid circular imports during phase 02 stub
    from ck_agent.verification import verify_user

    result = verify_user(email=email, ssn_last4=ssn_last4, dob_iso=dob_iso)
    if not result.verified:
        return {
            "verified": False,
            "reason": result.reason,
        }

    user = result.user
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

    # Multiple orders — return summary list and flag
    return {
        "verified": True,
        "multiple_orders_found": True,
        "action_required": "ask_user_to_select",
        "orders_summary": [
            {"order_id": o.order_id, "status": o.status, "items_summary": o.items_summary}
            for o in orders
        ],
    }
```

### 2.4 — Export the tool config

Expose `TOOL_CONFIG` as a dict in the Bedrock Converse API format:
```python
TOOL_CONFIG = {
    "tools": [RETRIEVE_KNOWLEDGE_TOOL, CHECK_ORDER_STATUS_TOOL]
}
```

And a dispatch function:
```python
def dispatch_tool(name: str, arguments: dict) -> str:
    """Route a tool call to its implementation. Returns JSON-serializable result."""
    if name == "retrieve_knowledge":
        return retrieve_knowledge(**arguments)
    if name == "check_order_status":
        return check_order_status(**arguments)
    raise ValueError(f"Unknown tool: {name}")
```

### 2.5 — Since phase 03 hasn't run yet, stub `verification.py`

Create minimal stub so `tools.py` imports don't fail:
```python
# src/ck_agent/verification.py
from pydantic import BaseModel

class VerificationResult(BaseModel):
    verified: bool
    reason: str | None = None
    user: object | None = None  # typed properly in phase 03

def verify_user(email: str, ssn_last4: str, dob_iso: str) -> VerificationResult:
    """Stub — phase 03 will implement real logic."""
    return VerificationResult(verified=False, reason="verification not implemented yet")
```

## Verification (human-runnable)

```bash
# Import smoke test
python -c "from ck_agent.tools import TOOL_CONFIG, dispatch_tool; print(len(TOOL_CONFIG['tools']), 'tools loaded')"
# Expected: 2 tools loaded

# Mock data is structured correctly
python -c "from ck_agent.mock_data import USERS; print([u.full_name for u in USERS.values()])"
# Expected: ['Alice Nguyen', 'Bob Tran', 'Carol Le', 'Dan Pham']

# Knowledge tool stub returns a string
python -c "from ck_agent.tools import retrieve_knowledge; print(retrieve_knowledge('return policy')[:30])"
# Expected: [STUB: knowledge lookup for 'r

# Alice has 3 orders
python -c "from ck_agent.mock_data import USERS; print(len(USERS['alice@ck1.com'].orders))"
# Expected: 3
```

## Definition of Done

- [ ] All 4 verification commands pass
- [ ] `mock_data.py` has 4 users with orders as specified
- [ ] `tools.py` has both tool definitions in Bedrock Converse format
- [ ] `verification.py` stub exists (implementation deferred to phase 03)
- [ ] `dispatch_tool` function routes correctly

## Out of Scope

- ❌ Implementing actual verification logic (that's phase 03)
- ❌ Calling Bedrock KB (that's phase 05)
- ❌ Running the agent loop (that's phase 04)
- ❌ Persisting mock data to DynamoDB (that's phase 11)

## Commit Message

```
[phase 02] Mock data and tool definitions

- 4 mock users covering single-order, multi-order, and no-order cases
- Pydantic models: User, Order
- Tool definitions in Bedrock Converse API format: retrieve_knowledge, check_order_status
- Tool dispatch function for agent loop wiring
- Verification module stub (implementation deferred to phase 03)
- Reference: plans/02_mock_data_and_tools.md
```
