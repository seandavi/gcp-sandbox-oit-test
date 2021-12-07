import pulumi
import pulumi_gcp
from pulumi import Output, Config
from pulumi_gcp.cloudrun import (
    ServiceTemplateMetadataArgs,
    ServiceTemplateSpecContainerEnvArgs,
)

import pulumi_gcp as gcp

config = Config()

run_service = gcp.projects.Service("run-service",
    disable_dependent_services=True,
    service="run.googleapis.com")
sqladmin_service = gcp.projects.Service("sqladmin-service",
    disable_dependent_services=True,
    service="sqladmin.googleapis.com")
servicenetworking_service = gcp.projects.Service("servicenetworking-service",
    disable_dependent_services=True,
    service="servicenetworking.googleapis.com")


private_network = gcp.compute.Network("private-network",
    opts=pulumi.ResourceOptions(depends_on=[servicenetworking_service])
)
private_ip_address = gcp.compute.GlobalAddress("private-ip-address",
    purpose="VPC_PEERING",
    address_type="INTERNAL",
    prefix_length=16,
    network=private_network.id)
private_vpc_connection = gcp.servicenetworking.Connection("private-vpc-connection",
    network=private_network.id,
    service="servicenetworking.googleapis.com",
    reserved_peering_ranges=[private_ip_address.name])

cloud_sql_instance = pulumi_gcp.sql.DatabaseInstance(
    "my-cloud-sql-instance",
    database_version="POSTGRES_12",
    deletion_protection=False,
    settings=pulumi_gcp.sql.DatabaseInstanceSettingsArgs(
        tier="db-f1-micro",
        ip_configuration=pulumi_gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
            ipv4_enabled=False,
            private_network='projects/sandbox-sean2davis1-978ebd70/global/networks/default'
        )
    ),
    opts=pulumi.ResourceOptions(depends_on=[private_vpc_connection,sqladmin_service])
)

database = pulumi_gcp.sql.Database(
    "database", instance=cloud_sql_instance.name, name=config.require("db-name")
)

users = pulumi_gcp.sql.User(
    "users",
    name=config.require("db-name"),
    instance=cloud_sql_instance.name,
    password=config.require_secret("db-password"),
)

sql_instance_url = Output.concat(
    "postgres://",
    config.require("db-name"),
    ":",
    config.require_secret("db-password"),
    "@/",
    config.require("db-name"),
    "?host=/cloudsql/",
    cloud_sql_instance.connection_name,
)

cloud_run = pulumi_gcp.cloudrun.Service(
    "default-service",
    opts=pulumi.ResourceOptions(depends_on=[private_vpc_connection,run_service]),
    location=Config("gcp").require("region"),
    template=pulumi_gcp.cloudrun.ServiceTemplateArgs(
        metadata=ServiceTemplateMetadataArgs(
            annotations={
                "run.googleapis.com/cloudsql-instances": cloud_sql_instance.connection_name
            }
        ),
        spec=pulumi_gcp.cloudrun.ServiceTemplateSpecArgs(
            containers=[
                pulumi_gcp.cloudrun.ServiceTemplateSpecContainerArgs(
                    image="gcr.io/cloudrun/hello",
                    envs=[
                        ServiceTemplateSpecContainerEnvArgs(
                            name="DATABASE_URL",
                            value=sql_instance_url,
                        )
                    ],
                )
            ],
        ),
    ),
    traffics=[
        pulumi_gcp.cloudrun.ServiceTrafficArgs(
            latest_revision=True,
            percent=100,
        )
    ],
)

pulumi.export("cloud_sql_instance_name", cloud_sql_instance.name)
pulumi.export("cloud_run_url", cloud_run.statuses[0].url)
