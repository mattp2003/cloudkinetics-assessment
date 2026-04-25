from pydantic import BaseModel


class Order(BaseModel):
    order_id: str
    status: str
    last_updated: str
    tracking_number: str
    items_summary: str


class User(BaseModel):
    full_name: str
    ssn_full: str
    dob_iso: str
    orders: list[Order]


USERS: dict[str, User] = {
    "alice@ck1.com": User(
        full_name="Alice Nguyen",
        ssn_full="123456789",
        dob_iso="1990-03-15",
        orders=[
            Order(
                order_id="ORD-2025-001",
                status="Delivered",
                last_updated="2025-01-10T14:30:00Z",
                tracking_number="TRK100000001",
                items_summary="Blue denim jacket x1, white sneakers x1",
            ),
            Order(
                order_id="ORD-2025-002",
                status="Shipped",
                last_updated="2025-01-18T09:00:00Z",
                tracking_number="TRK100000002",
                items_summary="Wireless headphones x1",
            ),
            Order(
                order_id="ORD-2025-003",
                status="Processing",
                last_updated="2025-01-20T11:15:00Z",
                tracking_number="TRK100000003",
                items_summary="Running shoes x1, gym bag x1",
            ),
        ],
    ),
    "bob@ck2.com": User(
        full_name="Bob Tran",
        ssn_full="987654321",
        dob_iso="1985-07-22",
        orders=[
            Order(
                order_id="ORD-2025-004",
                status="Out for Delivery",
                last_updated="2025-01-21T08:45:00Z",
                tracking_number="TRK100000004",
                items_summary="Standing desk x1",
            ),
        ],
    ),
    "carol@ck123.com": User(
        full_name="Carol Le",
        ssn_full="456789123",
        dob_iso="1995-11-05",
        orders=[],
    ),
    "dan@ck5.com": User(
        full_name="Dan Pham",
        ssn_full="321654987",
        dob_iso="1988-04-30",
        orders=[
            Order(
                order_id="ORD-2025-005",
                status="Delayed",
                last_updated="2025-01-19T16:00:00Z",
                tracking_number="TRK100000005",
                items_summary="Gaming monitor x1",
            ),
            Order(
                order_id="ORD-2025-006",
                status="Delivered",
                last_updated="2025-01-15T12:00:00Z",
                tracking_number="TRK100000006",
                items_summary="Mechanical keyboard x1, mouse pad x1",
            ),
        ],
    ),
}


def get_user_by_email(email: str) -> User | None:
    return USERS.get(email)
