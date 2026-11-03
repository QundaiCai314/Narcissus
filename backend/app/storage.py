from functools import lru_cache
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from .config import settings


@lru_cache
def s3():
    s = settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    )


def initialize_bucket():
    try:
        s3().head_bucket(Bucket=settings().s3_bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            raise
        s3().create_bucket(Bucket=settings().s3_bucket)


def put(key, data, content_type="application/pdf"):
    s3().put_object(
        Bucket=settings().s3_bucket, Key=key, Body=data, ContentType=content_type
    )


def read(key):
    result = s3().get_object(Bucket=settings().s3_bucket, Key=key)
    try:
        return result["Body"].read()
    finally:
        result["Body"].close()


def head(key):
    return s3().head_object(Bucket=settings().s3_bucket, Key=key)


def read_range(key, start: int, end: int):
    result = s3().get_object(
        Bucket=settings().s3_bucket, Key=key, Range=f"bytes={start}-{end}"
    )
    try:
        return result["Body"].read()
    finally:
        result["Body"].close()


def remove(key):
    s3().delete_object(Bucket=settings().s3_bucket, Key=key)
