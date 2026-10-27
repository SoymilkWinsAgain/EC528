def insert_request(connection, request_data, status_code):
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO request_log (
                country,
                client_ip,
                gender,
                age_group,
                income_group,
                is_banned,
                client_time,
                received_at,
                requested_file,
                status_code,
                run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING request_id
            """,
            (
                request_data["country"],
                request_data["client_ip"],
                request_data["gender"],
                request_data["age_group"],
                request_data["income_group"],
                request_data["is_banned"],
                request_data["client_time"],
                request_data["received_at"],
                request_data["requested_file"],
                status_code,
                request_data["run_id"],
            ),
        )

        # Get the returned request_id as the auto-generated primary key.
        # AI suggests this method, it's useful!
        request_id = cursor.fetchone()[0]

        if status_code != 200:
            cursor.execute(
                """
                INSERT INTO request_errors (
                    request_id,
                    received_at,
                    requested_file,
                    error_code
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    request_id,
                    request_data["received_at"],
                    request_data["requested_file"],
                    status_code,
                ),
            )

        connection.commit()
        return request_id

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()