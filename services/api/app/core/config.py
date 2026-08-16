from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@postgres:5432/nimbus"

    s3_endpoint_url: str = "http://localstack:4566"
    s3_bucket_name: str = "nimbus-dev"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_default_region: str = "us-east-1"

    openrouter_api_key: str = ""


settings = Settings()
