from aws_cdk import (
    Stack,
    Fn,
    aws_ec2 as ec2,
    aws_servicediscovery as servicediscovery,
    aws_ecs as ecs,
)
from constructs import Construct


# Creating a construct that will populate
# the required objects created in the platform repo
# such as vpc, ecs cluster, and service discovery namespace

class BasePlatform(Construct):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = Stack.of(self).region

        # The base platform stack is where the VPC was created,
        # so all we need is the name to do a lookup and import
        # it into this stack for use
        vpc = ec2.Vpc.from_lookup(
            self,
            "VPC",
            vpc_name='ecsworkshop-base/BaseVPC',
            region=region
        )

        sd_namespace = servicediscovery.PrivateDnsNamespace.from_private_dns_namespace_attributes(
            self,
            "SDNamespace",
            namespace_name=Fn.import_value('NSNAME'),
            namespace_arn=Fn.import_value('NSARN'),
            namespace_id=Fn.import_value('NSID')
        )

        ecs_cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "ECSCluster",
            cluster_name=Fn.import_value('ECSClusterName'),
            security_groups=[],
            vpc=vpc,
            default_cloud_map_namespace=sd_namespace
        )

        services_sec_grp = ec2.SecurityGroup.from_security_group_id(
            self,
            "ServicesSecGrp",
            security_group_id=Fn.import_value('ServicesSecGrp')
        )

        self.vpc = vpc
        self.sd_namespace = sd_namespace
        self.ecs_cluster = ecs_cluster
        self.services_sec_grp = services_sec_grp
