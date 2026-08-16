import boto3
import psycopg
import pytest

from app.core.config import settings


@pytest.fixture(scope="session")
def db_conn():
    with psycopg.connect(settings.database_url) as conn:
        yield conn


@pytest.fixture(scope="session")
def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_default_region,
    )
