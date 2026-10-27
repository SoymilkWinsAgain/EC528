import os
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine
from database import insert_request


class RequestDatabase:
    def __init__(self):
        instance = os.environ["INSTANCE_CONNECTION_NAME"]
        user = os.environ.get("DB_USER", "postgres")
        password = os.environ["DB_PASSWORD"]
        database = os.environ.get("DB_NAME", "hw5")

        self.connector = Connector(refresh_strategy="LAZY")

        def create_connection():
            return self.connector.connect(
                instance,
                "pg8000",
                user=user,
                password=password,
                db=database,
                ip_type=IPTypes.PUBLIC,
                timeout=30,
            )

        self.engine = create_engine(
            "postgresql+pg8000://",
            creator=create_connection,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_pre_ping=True,
        )

    def write_request(self, request_data, status_code):
        connection = self.engine.raw_connection()
        try:
            return insert_request(connection, request_data, status_code)
        finally:
            # Return the borrowed connection to the pool.
            connection.close()

    def close(self):
        try:
            self.engine.dispose()
        finally:
            self.connector.close()