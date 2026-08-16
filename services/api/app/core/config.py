from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Plain libpq-style URL, used directly by raw psycopg connections
    # (tenancy/provision.py, seed.py). SQLAlchemy needs its own dialect
    # prefix, see sqlalchemy_database_url below.
    database_url: str = "postgresql://postgres:postgres@postgres:5432/nimbus"

    s3_endpoint_url: str = "http://localstack:4566"
    s3_bucket_name: str = "nimbus-dev"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_default_region: str = "us-east-1"

    # Where seed.py reads fixture files from inside the seed container
    # (mounted read-only from the repo's fixtures/ by docker-compose.yml).
    fixtures_dir: str = "/app/fixtures"

    openrouter_api_key: str = ""

    @property
    def sqlalchemy_database_url(self) -> str:
        # bare "postgresql://" resolves to the psycopg2 driver in
        # SQLAlchemy regardless of what's installed; we only install
        # psycopg (v3), so this must be explicit.
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


settings = Settings()
