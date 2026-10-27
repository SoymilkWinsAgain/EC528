import getpass
import os
from pathlib import Path
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2.credentials import Credentials


def setup_schema(connection):
    schema_path = Path(__file__).with_name("schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8-sig")

    cursor = connection.cursor()
    try:
        cursor.execute(schema_sql)

        # check if the tables were created successfully
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('request_log', 'request_errors')
            ORDER BY table_name
        """)
        tables = cursor.fetchall()

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    print("Schema setup completed.")
    for (table_name,) in tables:
        print(f"Table: {table_name}")


def main():
    instance = os.environ.get("INSTANCE_CONNECTION_NAME", "cs528-project-0-508215:us-east1:hw5-db",)
    password = os.environ.get("DB_PASSWORD") or getpass.getpass("Database password: ")

    token = os.environ.get("GCP_ACCESS_TOKEN")
    credentials = Credentials(token) if token else None
    with Connector(credentials=credentials, refresh_strategy="LAZY") as connector:
        connection = connector.connect(
            instance,
            "pg8000",
            user=os.environ.get("DB_USER", "postgres"),
            password=password,
            db=os.environ.get("DB_NAME", "hw5"),
            ip_type=IPTypes.PUBLIC,
            timeout=30,
        )
        try:
            setup_schema(connection)
        finally:
            connection.close()


if __name__ == "__main__":
    main()