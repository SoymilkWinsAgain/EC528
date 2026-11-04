import json
import os
from ipaddress import ip_address
from pathlib import Path

import pandas as pd
from google.cloud import storage
from google.cloud.sql.connector import Connector
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier


def load_data():
    with Connector(refresh_strategy="LAZY") as connector:
        connection = connector.connect(
            os.environ["INSTANCE_CONNECTION_NAME"],
            "pg8000",
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            db=os.environ["DB_NAME"],
        )

        try:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT
                    r.request_id,
                    host(r.client_ip) AS client_ip,
                    c.country,
                    r.gender,
                    r.age_group,
                    r.income_group
                FROM hw6.requests AS r
                JOIN hw6.clients AS c
                    ON r.client_ip = c.client_ip
                ORDER BY r.request_id
            """)

            columns = [column[0] for column in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)
        finally:
            connection.close()
            

def save_predictions(test, target, predictions, filename, bucket):
    result = test[["request_id", "client_ip", target]].copy()
    result = result.rename(columns={target: "actual"})
    result["predicted"] = predictions
    result["correct"] = result["actual"] == result["predicted"]

    path = Path("output") / filename
    result.to_csv(path, index=False)

    blob_name = f"hw6/{filename}"
    bucket.blob(blob_name).upload_from_filename(str(path))
    print(f"Saved: gs://{bucket.name}/{blob_name}", flush=True)
    

def main():
    Path("output").mkdir(exist_ok=True)

    data = load_data()
    data["ip_number"] = data["client_ip"].map(
        lambda value: int(ip_address(value))
    )

    split = GroupShuffleSplit(
        n_splits=1,
        test_size=0.2,
        random_state=114514,
    )
    train_index, test_index = next(split.split(data, groups=data["client_ip"]))

    train = data.iloc[train_index].copy()
    test = data.iloc[test_index].copy()

    print(f"Loaded rows: {len(data)}", flush=True)
    print(f"Training rows: {len(train)}", flush=True)
    print(f"Test rows: {len(test)}", flush=True)

    bucket = storage.Client().bucket(os.environ["BUCKET_NAME"])

    # client IP -> country
    print("Training country model...", flush=True)

    country_model = DecisionTreeClassifier(random_state=114514)

    # Each training IP only needs one country label.
    country_train = train.drop_duplicates("client_ip")
    country_model.fit(
        country_train[["ip_number"]],
        country_train["country"],
    )

    country_predictions = country_model.predict(test[["ip_number"]])
    country_accuracy = accuracy_score(
        test["country"], country_predictions
    )

    print(f"Country test accuracy: {country_accuracy:.4%}", flush=True)

    save_predictions(
        test,
        "country",
        country_predictions,
        "country_predictions.csv",
        bucket,
    )

    # country, gender, age and IP -> income group
    print("Training income model...", flush=True)

    income_train = train.dropna(subset=["income_group"]).copy()
    income_test = test.dropna(subset=["income_group"]).copy()

    categorical = ["country", "gender", "age_group"]
    features = categorical + ["ip_number"]

    income_train[categorical] = income_train[categorical].fillna("Unknown")
    income_test[categorical] = income_test[categorical].fillna("Unknown")

    preprocessing = ColumnTransformer([
        (
            "categories",
            OneHotEncoder(handle_unknown="ignore"),
            categorical,
        ),
        ("ip", "passthrough", ["ip_number"]),
    ])

    income_model = make_pipeline(
        preprocessing,
        RandomForestClassifier(
            n_estimators=100,
            max_depth=20,
            min_samples_leaf=2,
            random_state=114514,
            n_jobs=2,
        ),
    )

    income_model.fit(
        income_train[features],
        income_train["income_group"],
    )

    income_predictions = income_model.predict(income_test[features])
    income_accuracy = accuracy_score(
        income_test["income_group"], income_predictions
    )

    # always predicting the most common training label
    majority_income = income_train["income_group"].mode().iloc[0]
    baseline_accuracy = float(
        (income_test["income_group"] == majority_income).mean()
    )

    print(f"Income test accuracy: {income_accuracy:.4%}", flush=True)
    print(f"Income baseline accuracy: {baseline_accuracy:.4%}", flush=True)

    save_predictions(
        income_test,
        "income_group",
        income_predictions,
        "income_predictions.csv",
        bucket,
    )

    metrics = {
        "random_state": 114514,
        "split": "80/20 by client IP; no shared IPs",
        "total_rows": len(data),
        "country_train_unique_ips": len(country_train),
        "country_test_rows": len(test),
        "country_accuracy": country_accuracy,
        "income_train_rows": len(income_train),
        "income_test_rows": len(income_test),
        "income_accuracy": income_accuracy,
        "income_baseline_accuracy": baseline_accuracy,
    }

    metrics_path = Path("output/metrics.json")
    metrics_path.write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )
    bucket.blob("hw6/metrics.json").upload_from_filename(
        str(metrics_path)
    )

    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == "__main__":
    main()