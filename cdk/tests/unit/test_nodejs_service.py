import os

import aws_cdk as core
import aws_cdk.assertions as assertions

from cdk.nodejsservice import NodejsService

account = os.getenv('AWS_ACCOUNT_ID')
region = os.getenv('AWS_DEFAULT_REGION')
env = core.Environment(account=account, region=region)


def test_task_created():
    app = core.App()
    stack = NodejsService(app, "baseplatform", env=env)
    template = assertions.Template.from_stack(stack)

    template.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Cpu": "256"
    })
