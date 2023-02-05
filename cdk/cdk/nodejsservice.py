import os

from aws_cdk import (
    Fn,
    CfnOutput,
    Duration,
    Stack,
    aws_appmesh,
    aws_ec2,
    aws_ecs,
    aws_iam,
    aws_logs,
)
from constructs import Construct

from cdk.baseplatform import BasePlatform


class NodejsService(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        base_platform = BasePlatform(self, self.stack_name)

        fargate_task_def = aws_ecs.TaskDefinition(
            self,
            "TaskDef",
            compatibility=aws_ecs.Compatibility.EC2_AND_FARGATE,
            cpu='256',
            memory_mib='512',
            # appmesh-proxy-uncomment
            # proxy_configuration=aws_ecs.AppMeshProxyConfiguration(
            #     container_name="envoy",  # App Mesh side card name that will proxy the requests
            #     properties=aws_ecs.AppMeshProxyConfigurationProps(
            #         app_ports=[3000],  # nodejs application port
            #         proxy_ingress_port=15000,  # side card default config
            #         proxy_egress_port=15001,  # side card default config
            #         # side card default config
            #         egress_ignored_i_ps=["169.254.170.2", "169.254.169.254"],
            #         ignored_uid=1337  # side card default config
            #     )
            # )
            # appmesh-proxy-uncomment
        )

        log_group = aws_logs.LogGroup(
            self,
            "ecsworkshopNodejs",
            retention=aws_logs.RetentionDays.ONE_WEEK
        )

        container = fargate_task_def.add_container(
            "NodeServiceContainerDef",
            image=aws_ecs.ContainerImage.from_registry(
                "public.ecr.aws/aws-containers/ecsdemo-nodejs"),
            memory_reservation_mib=128,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix='/nodejs-container',
                log_group=log_group
            ),
            environment={
                "REGION": os.getenv('AWS_DEFAULT_REGION')
            },
            container_name="nodejs-app"
        )

        container.add_port_mappings(
            aws_ecs.PortMapping(
                container_port=3000
            )
        )

        fargate_service = aws_ecs.FargateService(
            self,
            "NodejsFargateService",
            service_name='ecsdemo-nodejs',
            task_definition=fargate_task_def,
            cluster=base_platform.ecs_cluster,
            security_groups=[base_platform.services_sec_grp],
            desired_count=1,
            cloud_map_options=aws_ecs.CloudMapOptions(
                cloud_map_namespace=base_platform.sd_namespace,
                name='ecsdemo-nodejs'
            )
        )

        fargate_task_def.add_to_task_role_policy(
            aws_iam.PolicyStatement(
                actions=['ec2:DescribeSubnets'],
                resources=['*']
            )
        )

        # Enable Service Autoscaling
        # autoscale = fargate_service.auto_scale_task_count(
        #     min_capacity=3,
        #     max_capacity=10
        # )

        # autoscale.scale_on_cpu_utilization(
        #     "CPUAutoscaling",
        #     target_utilization_percent=50,
        #     scale_in_cooldown=Duration.seconds(30),
        #     scale_out_cooldown=Duration.seconds(30)
        # )
        # self.autoscale = autoscale

        self.fargate_task_def = fargate_task_def
        self.log_group = log_group
        self.container = container
        self.fargate_service = fargate_service

        # App Mesh Implementation
        # self.appmesh()

    def appmesh(self):

        # Importing app mesh service
        mesh = aws_appmesh.Mesh.from_mesh_arn(
            self,
            "EcsWorkShop-AppMesh",
            mesh_arn=Fn.import_value("MeshArn")
        )

        # Importing App Mesh virtual gateway
        mesh_vgw = aws_appmesh.VirtualGateway.from_virtual_gateway_attributes(
            self,
            "Mesh-VGW",
            mesh=mesh,
            virtual_gateway_name=Fn.import_value("MeshVGWName")
        )

        # App Mesh virtual node configuration
        mesh_nodejs_vn = aws_appmesh.VirtualNode(
            self,
            "MeshNodeJsNode",
            mesh=mesh,
            virtual_node_name="nodejs",
            listeners=[aws_appmesh.VirtualNodeListener.http(port=3000)],
            service_discovery=aws_appmesh.ServiceDiscovery.cloud_map(
                self.fargate_service.cloud_map_service),
            access_log=aws_appmesh.AccessLog.from_file_path("/dev/stdout")
        )

        # App Mesh envoy proxy container configuration
        envoy_container = self.fargate_task_def.add_container(
            "NodeJsServiceProxyContdef",
            image=aws_ecs.ContainerImage.from_registry(
                "public.ecr.aws/appmesh/aws-appmesh-envoy:v1.18.3.0-prod"),
            container_name="envoy",
            memory_reservation_mib=128,
            environment={
                "REGION": os.getenv('AWS_DEFAULT_REGION'),
                "ENVOY_LOG_LEVEL": "trace",
                "ENABLE_ENVOY_STATS_TAGS": "1",
                # "ENABLE_ENVOY_XRAY_TRACING": "1",
                "APPMESH_RESOURCE_ARN": mesh_nodejs_vn.virtual_node_arn
            },
            essential=True,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix='/mesh-envoy-container',
                log_group=self.log_group
            ),
            health_check=aws_ecs.HealthCheck(
                interval=Duration.seconds(5),
                timeout=Duration.seconds(10),
                retries=10,
                command=[
                    "CMD-SHELL", "curl -s http://localhost:9901/server_info | grep state | grep -q LIVE"],
            ),
            user="1337"
        )

        envoy_container.add_ulimits(aws_ecs.Ulimit(
            hard_limit=15000,
            name=aws_ecs.UlimitName.NOFILE,
            soft_limit=15000
        )
        )

        # Primary container needs to depend on envoy before it can be reached out
        self.container.add_container_dependencies(aws_ecs.ContainerDependency(
            container=envoy_container,
            condition=aws_ecs.ContainerDependencyCondition.HEALTHY
        )
        )

        # Enable app mesh Xray observability
        # xray_container = self.fargate_task_def.add_container(
        #     "NodeJsServiceXrayContdef",
        #     image=aws_ecs.ContainerImage.from_registry(
        #         "amazon/aws-xray-daemon"),
        #     logging=aws_ecs.LogDriver.aws_logs(
        #         stream_prefix='/xray-container',
        #         log_group=self.log_group
        #     ),
        #     essential=True,
        #     container_name="xray",
        #     memory_reservation_mib=256,
        #     user="1337"
        # )

        # envoy_container.add_container_dependencies(aws_ecs.ContainerDependency(
        #       container=xray_container,
        #       condition=aws_ecs.ContainerDependencyCondition.START
        #   )
        # )

        self.fargate_task_def.add_to_task_role_policy(
            aws_iam.PolicyStatement(
                actions=['ec2:DescribeSubnets'],
                resources=['*']
            )
        )

        self.fargate_service.connections.allow_from_any_ipv4(
            port_range=aws_ec2.Port(protocol=aws_ec2.Protocol.TCP,
                                    string_representation="tcp_3000",
                                    from_port=3000, to_port=3000),
            description="Allow TCP connections on port 3000"
        )

        # Adding policies to work with observability (xray and cloudwath)
        self.fargate_task_def.execution_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryReadOnly"))
        self.fargate_task_def.execution_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess"))
        self.fargate_task_def.task_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchFullAccess"))
        # self.fargate_task_def.task_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess"))
        self.fargate_task_def.task_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_aws_managed_policy_name("AWSAppMeshEnvoyAccess"))

        # Adding mesh virtual service
        self.mesh_nodejs_vs = aws_appmesh.VirtualService(self, "mesh-nodejs-vs",
                                                         virtual_service_provider=aws_appmesh.VirtualServiceProvider.virtual_node(
                                                             self.mesh_nodejs_vn),
                                                         virtual_service_name="{}.{}".format(
                                                             self.fargate_service.cloud_map_service.service_name, self.fargate_service.cloud_map_service.namespace.namespace_name)
                                                         )

        # Exporting CF (outputs) to make references from other cdk projects.
        CfnOutput(self, "MeshNodejsVSARN",
                  value=self.mesh_nodejs_vs.virtual_service_arn, export_name="MeshNodejsVSARN")
        CfnOutput(self, "MeshNodeJsVSName",
                  value=self.mesh_nodejs_vs.virtual_service_name, export_name="MeshNodeJsVSName")

        self.mesh = mesh
        self.mesh_vgw = mesh_vgw
        self.mesh_nodejs_vn = mesh_nodejs_vn
        self.envoy_container = envoy_container
        # self.xray_container = xray_container
