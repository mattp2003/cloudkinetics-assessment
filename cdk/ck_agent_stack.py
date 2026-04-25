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
            removal_policy=RemovalPolicy.DESTROY,
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
            code=lambda_.Code.from_asset("../cdk/lambda_dist"),
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
            resources=["*"],
        ))

        # ===== API Gateway WebSocket =====

        websocket_api = apigwv2.WebSocketApi(
            self, "AgentWebSocket",
            api_name="ck-agent-ws",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_integrations.WebSocketLambdaIntegration(
                    "ConnectIntegration", agent_lambda
                ),
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_integrations.WebSocketLambdaIntegration(
                    "DisconnectIntegration", agent_lambda
                ),
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_integrations.WebSocketLambdaIntegration(
                    "DefaultIntegration", agent_lambda
                ),
            ),
        )

        stage = apigwv2.WebSocketStage(
            self, "ProdStage",
            web_socket_api=websocket_api,
            stage_name="prod",
            auto_deploy=True,
        )

        # Allow Lambda to post messages back to connected WebSocket clients
        websocket_api.grant_manage_connections(agent_lambda)

        # Pass callback URL so Lambda can stream tokens back to clients
        agent_lambda.add_environment("WEBSOCKET_ENDPOINT", stage.callback_url)

        # ===== Stack outputs =====

        CfnOutput(self, "WebSocketUrl", value=stage.url)
        CfnOutput(self, "ConversationsTableName", value=conversations_table.table_name)
        CfnOutput(self, "SessionsTableName", value=sessions_table.table_name)
        CfnOutput(self, "LambdaName", value=agent_lambda.function_name)
