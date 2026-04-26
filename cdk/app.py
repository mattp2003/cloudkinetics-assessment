#!/usr/bin/env python3
import os
from aws_cdk import App, Environment
from ck_agent_stack import CkAgentStack

app = App()

kb_id = app.node.try_get_context("kb_id") or os.environ.get("BEDROCK_KB_ID")
if not kb_id:
    raise RuntimeError(
        "BEDROCK_KB_ID not set. Pass via: cdk deploy -c kb_id=<ID>  "
        "or set env var BEDROCK_KB_ID"
    )

CkAgentStack(
    app, "CkAgentStack",
    kb_id=kb_id,
    env=Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="us-east-1",
    ),
)

app.synth()
