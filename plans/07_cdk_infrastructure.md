# Phase 07 — CDK Infrastructure

## Prerequisites

- [ ] Phase 06 complete (KB works, diagnostic captured)
- [ ] `BEDROCK_KB_ID` saved in `.env`
- [ ] AWS CDK CLI installed (`cdk --version` returns 2.x)

## Goal

An AWS CDK stack in `cdk/` that provisions: Lambda function, API Gateway WebSocket API, two DynamoDB tables. Stack synthesizes cleanly (`cdk synth`). Deploy comes in phase 09 after Lambda is wired.

## Context for Claude Code

- Use CDK v2 in Python. Do not use v1 or mix.
- This stack does NOT create the Bedrock Knowledge Base — that was done manually in phase 05. KB ID is passed in as a context variable.
- Lambda code lives in `src/ck_agent/` and is packaged via CDK's `PythonFunction` or `DockerImageFunction`. We'll use the standard `Function` with an asset bundle — simpler, faster.
- Table names and ARNs are exported as stack outputs for easy debugging

## Steps

### 7.1 — Initialize CDK app

```bash
mkdir -p cdk && cd cdk
cdk init app --language python
# This creates cdk/app.py, cdk/<stack_name>_stack.py, cdk.json, etc.
```

Remove the venv CDK init creates (we'll use our root `.venv`). Adjust `cdk.json` to point Python interpreter to the root venv:

```json
{
  "app": "../.venv/bin/python app.py",
  ...
}
```

(On Windows: `"../.venv/Scripts/python.exe app.py"`)

Install CDK Python libraries in the root venv:
```bash
cd ..
source .venv/bin/activate
pip install "aws-cdk-lib>=2.150.0" "constructs>=10.0.0"
```

### 7.2 — Write the stack: `cdk/ck_agent_stack.py`

Rename the default stack file. Full structure:

```python
from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    RemovalPolicy,
    aws_lambda as lambda_,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class CkAgentStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, kb_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ===== DynamoDB tables =====

        conversations_table = dynamodb.Table(
            self, "ConversationsTable",
            table_name="ck-conversations",
            partition_key=dynamodb.Attribute(name="conversation_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,  # dev: wipe on teardown
        )
        conversations_table.add_global_secondary_index(
            index_name="by_user",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
        )

        sessions_table = dynamodb.Table(
            self, "SessionsTable",
            table_name="ck-sessions",
            partition_key=dynamodb.Attribute(name="connection_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ===== Lambda function =====

        agent_lambda = lambda_.Function(
            self, "AgentHandler",
            function_name="ck-agent-handler",
            runtime=lambda_.Runtime.PYTHON_3_13,
            code=lambda_.Code.from_asset(
                "../src",
                bundling=lambda_.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_13.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install boto3 pydantic -t /asset-output && cp -r ck_agent /asset-output/",
                    ],
                ),
            ),
            handler="ck_agent.lambda_handler.handler",
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment={
                "BEDROCK_KB_ID": kb_id,
                "CONVERSATIONS_TABLE": conversations_table.table_name,
                "SESSIONS_TABLE": sessions_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Grant DynamoDB access
        conversations_table.grant_read_write_data(agent_lambda)
        sessions_table.grant_read_write_data(agent_lambda)

        # Grant Bedrock access
        agent_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:Converse",
                "bedrock:ConverseStream",
                "bedrock:Retrieve",
            ],
            resources=["*"],  # Bedrock models are account-wide; narrowed in prod with model ARNs
        ))

        # ===== API Gateway WebSocket =====

        websocket_api = apigwv2.WebSocketApi(
            self, "AgentWebSocket",
            api_name="ck-agent-ws",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_integrations.WebSocketLambdaIntegration("ConnectIntegration", agent_lambda),
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_integrations.WebSocketLambdaIntegration("DisconnectIntegration", agent_lambda),
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_integrations.WebSocketLambdaIntegration("DefaultIntegration", agent_lambda),
            ),
        )

        stage = apigwv2.WebSocketStage(
            self, "ProdStage",
            web_socket_api=websocket_api,
            stage_name="prod",
            auto_deploy=True,
        )

        # Grant Lambda permission to post messages back to connected clients
        websocket_api.grant_manage_connections(agent_lambda)

        # Pass the callback URL to Lambda so it can post streamed tokens
        agent_lambda.add_environment("WEBSOCKET_ENDPOINT", stage.callback_url)

        # ===== Outputs =====

        CfnOutput(self, "WebSocketUrl", value=stage.url)
        CfnOutput(self, "ConversationsTableName", value=conversations_table.table_name)
        CfnOutput(self, "SessionsTableName", value=sessions_table.table_name)
        CfnOutput(self, "LambdaName", value=agent_lambda.function_name)
```

### 7.3 — `cdk/app.py`

```python
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
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)

app.synth()
```

### 7.4 — Update `src/ck_agent/tools.py` to read env vars

Already done in phase 05 (`KB_ID = os.environ.get("BEDROCK_KB_ID", "")`). Verify.

### 7.5 — Create placeholder Lambda handler

Just a stub so `cdk synth` works. Real handler comes in phase 08.

`src/ck_agent/lambda_handler.py`:
```python
def handler(event, context):
    """Placeholder — real implementation in phase 08."""
    return {"statusCode": 200, "body": "stub"}
```

### 7.6 — Bootstrap CDK (one-time per account+region)

```bash
cd cdk
cdk bootstrap aws://<account_id>/us-east-1
```

Takes ~2 min the first time. Only needed once.

### 7.7 — Synthesize (do NOT deploy yet)

```bash
cd cdk
cdk synth -c kb_id=$BEDROCK_KB_ID
```

Expected: CloudFormation template printed to stdout with no errors. Check for:
- 2 DynamoDB tables
- 1 Lambda function
- 1 WebSocket API with 3 routes

## Verification (human-runnable)

```bash
# CDK synthesizes cleanly
cd cdk
cdk synth -c kb_id=$BEDROCK_KB_ID > /tmp/template.yaml 2>&1
grep -c "AWS::DynamoDB::Table" /tmp/template.yaml
# Expected: 2

grep -c "AWS::Lambda::Function" /tmp/template.yaml
# Expected: at least 1 (the agent; log retention adds more)

grep -c "AWS::ApiGatewayV2::Api" /tmp/template.yaml
# Expected: 1

# CDK bootstrap is done
aws cloudformation describe-stacks --stack-name CDKToolkit --region us-east-1 \
  --query "Stacks[0].StackStatus" --output text
# Expected: CREATE_COMPLETE or UPDATE_COMPLETE
```

## Definition of Done

- [ ] `cdk synth` produces a valid template with no errors
- [ ] Template contains 2 DynamoDB tables, 1 Lambda, 1 WebSocket API with 3 routes
- [ ] CDK bootstrap complete for account + region
- [ ] `cdk/app.py` reads KB_ID from context or env var, errors clearly if missing
- [ ] Stack outputs defined: WebSocketUrl, table names, Lambda name

## Out of Scope

- ❌ Deploying the stack (phase 09 after Lambda is wired)
- ❌ Writing the actual Lambda handler (phase 08)
- ❌ Frontend (phase 10)
- ❌ CloudWatch dashboard (phase 12)
- ❌ VPC, WAF, KMS CMKs (production hardening — design doc only)

## Commit Message

```
[phase 07] CDK infrastructure (synthesizes, not yet deployed)

- CDK v2 Python stack: ck_agent_stack.py
- DynamoDB: ck-conversations (with GSI by_user), ck-sessions
- Lambda (Python 3.13, 1GB, 5min timeout) with Bedrock + DDB permissions
- API Gateway WebSocket with connect/disconnect/default routes
- Stack outputs: WebSocket URL, table names
- KB ID passed via context variable; errors clearly if unset
- Reference: plans/07_cdk_infrastructure.md
```
