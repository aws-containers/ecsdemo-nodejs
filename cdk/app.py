#!/usr/bin/env python3

import os
import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    App, CfnOutput, Stack, Environment, Fn, Duration,
    aws_ec2,
    aws_ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam,
    aws_servicediscovery,
    aws_appmesh,
    aws_logs
)
from os import getenv
from cdk.nodejsservice import NodejsService

account = os.getenv('AWS_ACCOUNT_ID')
region = os.getenv('AWS_DEFAULT_REGION')
stack_name = "ecsworkshop-nodejs"
_env = Environment(account=getenv('AWS_ACCOUNT_ID'), region=getenv('AWS_DEFAULT_REGION'))
environment = "ecsworkshop"
stack_name = "{}-nodejs".format(environment)

# Creating a construct that will populate the required objects created in the platform repo such as vpc, ecs cluster, and service discovery namespace
class BasePlatform(Construct):

    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.environment_name = 'ecsworkshop'

        # The base platform stack is where the VPC was created, so all we need is the name to do a lookup and import it into this stack for use
        self.vpc = aws_ec2.Vpc.from_lookup(
            self, "VPC",
            vpc_name='{}-base/BaseVPC'.format(self.environment_name)
        )

        self.sd_namespace = aws_servicediscovery.PrivateDnsNamespace.from_private_dns_namespace_attributes(
            self, "SDNamespace",
            namespace_name=cdk.Fn.import_value('NSNAME'),
            namespace_arn=cdk.Fn.import_value('NSARN'),
            namespace_id=cdk.Fn.import_value('NSID')
        )

        self.ecs_cluster = aws_ecs.Cluster.from_cluster_attributes(
            self, "ECSCluster",
            cluster_name=cdk.Fn.import_value('ECSClusterName'),
            security_groups=[],
            vpc=self.vpc,
            default_cloud_map_namespace=self.sd_namespace
        )

        self.services_sec_grp = aws_ec2.SecurityGroup.from_security_group_id(
            self, "ServicesSecGrp",
            security_group_id=cdk.Fn.import_value('ServicesSecGrp')
        )


class NodejsService(Stack):

    def __init__(self, scope: Stack, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.base_platform = BasePlatform(self, self.stack_name)

        self.fargate_task_def = aws_ecs.TaskDefinition(
            self, "TaskDef",
            compatibility=aws_ecs.Compatibility.EC2_AND_FARGATE,
            cpu='256',
            memory_mib='512',
            #appmesh-proxy-uncomment
            proxy_configuration=aws_ecs.AppMeshProxyConfiguration( 
               container_name="envoy", #App Mesh side card name that will proxy the requests 
               properties=aws_ecs.AppMeshProxyConfigurationProps(
                   app_ports=[3000], 
                   proxy_ingress_port=15000, 
                   proxy_egress_port=15001, 
                   egress_ignored_i_ps=["169.254.170.2","169.254.169.254"], 
                   ignored_uid=1337 
               )
            )
            #appmesh-proxy-uncomment
        )

        self.logGroup = aws_logs.LogGroup(self,"ecsworkshopNodejs",
            # log_group_name="ecsworkshop-nodejs",
            retention=aws_logs.RetentionDays.ONE_WEEK
        )

        self.container = self.fargate_task_def.add_container(
            "NodeServiceContainerDef",
            image=aws_ecs.ContainerImage.from_registry("public.ecr.aws/aws-containers/ecsdemo-nodejs"),
            memory_reservation_mib=128,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix='/nodejs-container',
                log_group=self.logGroup
            ),
            environment={
                "REGION": getenv('AWS_DEFAULT_REGION')
            },
            container_name="nodejs-app"
        )

        self.container.add_port_mappings(
            aws_ecs.PortMapping(
                container_port=3000
            )
        )

        self.fargate_service = aws_ecs.FargateService(
            self, "NodejsFargateService",
            service_name='ecsdemo-nodejs',
            task_definition=self.fargate_task_def,
            cluster=self.base_platform.ecs_cluster,
            security_groups=[self.base_platform.services_sec_grp],
            desired_count=1,
            cloud_map_options=aws_ecs.CloudMapOptions(
                cloud_map_namespace=self.base_platform.sd_namespace,
                name='ecsdemo-nodejs'
            )
        )
        self.fargate_task_def.add_to_task_role_policy(
            aws_iam.PolicyStatement(
                actions=['ec2:DescribeSubnets'],
                resources=['*']
            )
        )
        

        appmesh(self)
    
def appmesh(self):

       
        # Importing app mesh service
        self.mesh = aws_appmesh.Mesh.from_mesh_arn(
            self,
            "EcsWorkShop-AppMesh",
            mesh_arn=cdk.Fn.import_value("MeshArn")
        )

        # Importing App Mesh virtual gateway
        self.mesh_vgw = aws_appmesh.VirtualGateway.from_virtual_gateway_attributes(
            self,
            "Mesh-VGW",
            mesh=self.mesh,
            virtual_gateway_name=cdk.Fn.import_value("MeshVGWName")
        )

        # App Mesh virtual node configuration
        self.mesh_nodejs_vn = aws_appmesh.VirtualNode(
            self,
            "MeshNodeJsNode",
            mesh=self.mesh,
            virtual_node_name="nodejs",
            listeners=[aws_appmesh.VirtualNodeListener.http(port=3000)],
            service_discovery=aws_appmesh.ServiceDiscovery.cloud_map(self.fargate_service.cloud_map_service),
            access_log=aws_appmesh.AccessLog.from_file_path("/dev/stdout")
        )

        # App Mesh envoy proxy container configuration
        self.envoy_container = self.fargate_task_def.add_container(
            "NodeJsServiceProxyContdef",
            image=aws_ecs.ContainerImage.from_registry("public.ecr.aws/appmesh/aws-appmesh-envoy:v1.18.3.0-prod"),
            container_name="envoy",
            memory_reservation_mib=128,
            environment={
                "REGION": getenv('AWS_DEFAULT_REGION'),
                "ENVOY_LOG_LEVEL": "trace",
                "ENABLE_ENVOY_STATS_TAGS": "1",
                "ENABLE_ENVOY_XRAY_TRACING": "1",
                "APPMESH_RESOURCE_ARN": self.mesh_nodejs_vn.virtual_node_arn
            },
            essential=True,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix='/mesh-envoy-container',
                log_group=self.logGroup
            ),
            health_check=aws_ecs.HealthCheck(
                interval=cdk.Duration.seconds(5),
                timeout=cdk.Duration.seconds(10),
                retries=10,
                command=["CMD-SHELL","curl -s http://localhost:9901/server_info | grep state | grep -q LIVE"],
            ),
            user="1337"
        )

        self.envoy_container.add_ulimits(aws_ecs.Ulimit(
            hard_limit=15000,
            name=aws_ecs.UlimitName.NOFILE,
            soft_limit=15000
            )
        )

        # Primary container needs to depend on envoy before it can be reached out
        self.container.add_container_dependencies(aws_ecs.ContainerDependency(
               container=self.envoy_container,
               condition=aws_ecs.ContainerDependencyCondition.HEALTHY
           )
        )

        # Enable app mesh Xray observability
        #ammmesh-xray-uncomment
        #self.xray_container = self.fargate_task_def.add_container(
        #    "NodeJsServiceXrayContdef",
        #    image=aws_ecs.ContainerImage.from_registry("amazon/aws-xray-daemon"),
        #    logging=aws_ecs.LogDriver.aws_logs(
        #        stream_prefix='/xray-container',
        #        log_group=self.logGroup
        #    ),
        #    essential=True,
        #    container_name="xray",
        #    memory_reservation_mib=256,
        #    user="1337"
        #)

        #self.envoy_container.add_container_dependencies(aws_ecs.ContainerDependency(
        #      container=self.xray_container,
        #      condition=aws_ecs.ContainerDependencyCondition.START
        #  )
        #)
        #ammmesh-xray-uncomment
        self.fargate_task_def.add_to_task_role_policy(
            aws_iam.PolicyStatement(
                actions=['ec2:DescribeSubnets'],
                resources=['*']
            )
        )
        
        self.fargate_service.connections.allow_from_any_ipv4(
            port_range=aws_ec2.Port(protocol=aws_ec2.Protocol.TCP, string_representation="tcp_3000", from_port=3000, to_port=3000),
            description="Allow TCP connections on port 3000"
        )
        
        # Adding policies to work with observability (xray and cloudwath)
        self.fargate_task_def.execution_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryReadOnly"))
        self.fargate_task_def.execution_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess"))
        self.fargate_task_def.task_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchFullAccess"))
        self.fargate_task_def.task_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess"))
        self.fargate_task_def.task_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name("AWSAppMeshEnvoyAccess"))
        
        
        # Adding mesh virtual service 
        self.mesh_nodejs_vs = aws_appmesh.VirtualService(self,"mesh-nodejs-vs",
            virtual_service_provider=aws_appmesh.VirtualServiceProvider.virtual_node(self.mesh_nodejs_vn),
            virtual_service_name="{}.{}".format(self.fargate_service.cloud_map_service.service_name,self.fargate_service.cloud_map_service.namespace.namespace_name)
        )
        
        # Exporting CF (outputs) to make references from other cdk projects.
        CfnOutput(self,"MeshNodejsVSARN",value=self.mesh_nodejs_vs.virtual_service_arn,export_name="MeshNodejsVSARN")
        CfnOutput(self,"MeshNodeJsVSName",value=self.mesh_nodejs_vs.virtual_service_name,export_name="MeshNodeJsVSName")
        

app = App()
NodejsService(app, stack_name, env=_env)
app.synth()
