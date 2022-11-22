import os

from aws_cdk import (
    Stack,
    aws_ecs as ecs,
    aws_logs as logs,
    aws_iam as iam,
)
from constructs import Construct

from cdk.baseplatform import BasePlatform


class NodejsService(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        base_platform = BasePlatform(self, self.stack_name)

        fargate_task_def = ecs.TaskDefinition(
            self,
            "TaskDef",
            compatibility=ecs.Compatibility.EC2_AND_FARGATE,
            cpu='256',
            memory_mib='512',
        )

        log_group = logs.LogGroup(
            self,
            "ecsworkshopNodejs",
            retention=logs.RetentionDays.ONE_WEEK
        )

        container = fargate_task_def.add_container(
            "NodeServiceContainerDef",
            image=ecs.ContainerImage.from_registry(
                "public.ecr.aws/aws-containers/ecsdemo-nodejs"),
            memory_reservation_mib=128,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix='/nodejs-container',
                log_group=log_group
            ),
            environment={
                "REGION": os.getenv('AWS_DEFAULT_REGION')
            },
            container_name="nodejs-app"
        )

        container.add_port_mappings(
            ecs.PortMapping(
                container_port=3000
            )
        )

        ecs.FargateService(
            self,
            "NodejsFargateService",
            service_name='ecsdemo-nodejs',
            task_definition=fargate_task_def,
            cluster=base_platform.ecs_cluster,
            security_groups=[base_platform.services_sec_grp],
            desired_count=1,
            cloud_map_options=ecs.CloudMapOptions(
                cloud_map_namespace=base_platform.sd_namespace,
                name='ecsdemo-nodejs'
            )
        )

        fargate_task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['ec2:DescribeSubnets'],
                resources=['*']
            )
        )
