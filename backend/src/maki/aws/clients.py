import boto3

from maki.settings import settings


def ecs_client():
    return boto3.client("ecs", region_name=settings.aws_region)


def amplify_client():
    return boto3.client("amplify", region_name=settings.aws_region)


def cloudwatch_client():
    return boto3.client("cloudwatch", region_name=settings.aws_region)


def logs_client():
    return boto3.client("logs", region_name=settings.aws_region)


def sts_client():
    return boto3.client("sts", region_name=settings.aws_region)
