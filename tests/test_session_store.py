import importlib
import os

import boto3
import pytest
from moto import mock_aws


TABLE_CONVERSATIONS = "ck-conversations"
TABLE_SESSIONS = "ck-sessions"


@pytest.fixture
def store():
    """Spin up mocked DynamoDB tables and reload session_store against them."""
    with mock_aws():
        os.environ["CONVERSATIONS_TABLE"] = TABLE_CONVERSATIONS
        os.environ["SESSIONS_TABLE"] = TABLE_SESSIONS
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

        client = boto3.client("dynamodb", region_name="us-east-1")

        client.create_table(
            TableName=TABLE_CONVERSATIONS,
            KeySchema=[
                {"AttributeName": "conversation_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "conversation_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "by_user",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )

        client.create_table(
            TableName=TABLE_SESSIONS,
            KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "connection_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        import ck_agent.session_store as ss
        importlib.reload(ss)
        yield ss


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def test_create_new_session_returns_empty_messages(store):
    s = store.get_or_create_session("conn-1")
    assert s["messages"] == []
    assert s["conversation_id"]


def test_same_connection_returns_same_conversation_id(store):
    s1 = store.get_or_create_session("conn-1")
    s2 = store.get_or_create_session("conn-1")
    assert s1["conversation_id"] == s2["conversation_id"]


def test_different_connections_get_different_conversations(store):
    s1 = store.get_or_create_session("conn-1")
    s2 = store.get_or_create_session("conn-2")
    assert s1["conversation_id"] != s2["conversation_id"]


def test_delete_session_allows_new_session(store):
    store.get_or_create_session("conn-1")
    store.delete_session("conn-1")
    s = store.get_or_create_session("conn-1")
    assert s["messages"] == []


# ---------------------------------------------------------------------------
# Message persistence
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip(store):
    s = store.get_or_create_session("conn-1")
    cid = s["conversation_id"]

    store.save_message(cid, 1, {"role": "user", "content": [{"text": "hello"}]})
    store.save_message(cid, 2, {"role": "assistant", "content": [{"text": "hi there"}]})

    msgs = store.load_messages(cid)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_messages_loaded_on_reconnect(store):
    s = store.get_or_create_session("conn-1")
    cid = s["conversation_id"]
    store.save_message(cid, 1, {"role": "user", "content": [{"text": "remember this"}]})

    # Simulate reconnect — same connection_id
    s2 = store.get_or_create_session("conn-1")
    assert len(s2["messages"]) == 1
    assert s2["messages"][0]["content"][0]["text"] == "remember this"


def test_user_id_persists_after_update(store):
    store.get_or_create_session("conn-1")
    store.update_session_user_id("conn-1", "alice@ck1.com")
    s = store.get_or_create_session("conn-1")
    assert s["user_id"] == "alice@ck1.com"
