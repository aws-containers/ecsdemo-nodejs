#!/usr/bin/env python3

import os

from aws_cdk import (
    App,
    Environment,
)

from cdk.nodejsservice import NodejsService

account = os.getenv('AWS_ACCOUNT_ID')
region = os.getenv('AWS_DEFAULT_REGION')
stack_name = "ecsworkshop-nodejs"
env = Environment(account=account, region=region)

app = App()
NodejsService(app, stack_name, env=env)

app.synth()
