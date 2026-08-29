import pandas as pd
import joblib
import shap
from sklearn.model_selection import train_test_split
from backend.simulation import reset_simulation
from backend.attacks import attack_registry
from backend.features import build_transaction_graph, extract_node_features
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

# -----------------------------
# Multi-Run Dataset Builder
# -----------------------------

def build_multi_run_dataset(num_runs=20):

    all_features = []
    attack_index = 0

    for _ in range(num_runs):

        accounts_df, transactions_df = reset_simulation()

        attack_function = attack_registry[attack_index % len(attack_registry)]

        accounts_df, transactions_df, attack_name, attack_time = attack_function(
            accounts_df, transactions_df
        )

        attack_transactions = transactions_df[
            transactions_df["timestamp"] >= attack_time
        ]

        G = build_transaction_graph(accounts_df, attack_transactions)

        features_df = extract_node_features(accounts_df, attack_transactions, G)

        # attach fraud label
        features_df["is_fraud"] = accounts_df.set_index("account_id").loc[
            features_df["account_id"]
        ]["is_fraud"].values

        all_features.append(features_df)

        attack_index += 1

    # combine ALL runs AFTER loop
    final_dataset = pd.concat(all_features, ignore_index=True)

    final_dataset = final_dataset.sample(frac=1, random_state=42).reset_index(drop=True)

    print("\nTraining class distribution:")
    print(final_dataset["is_fraud"].value_counts())

    return final_dataset
def train_and_save_model(features_df, model_path="fraud_model.pkl"):

    feature_columns = [
        "in_degree",
        "out_degree",
        "total_in_amount",
        "total_out_amount",
        "retention_ratio",
        "unique_neighbors",
        "unique_channels",
        "device_cluster_size",
        "transaction_count"
    ]

    X = features_df[feature_columns]
    y = features_df["is_fraud"]

    if y.value_counts().min() >= 2:

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=0.3,
            random_state=42,
            stratify=y
        )

    else:

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=0.3,
            random_state=42
        )

    model = RandomForestClassifier(
        n_estimators=200,
        random_state=42,
        class_weight="balanced"
    )

    model.fit(X_train, y_train)
    model.feature_list = feature_columns

    # Evaluation
    y_pred = model.predict(X_test)

    cm = confusion_matrix(y_test, y_pred)
    report = classification_report(
        y_test,
        y_pred,
        output_dict=True,
        zero_division=0
    )

    feature_importances = pd.DataFrame({
        "feature": feature_columns,
        "importance": model.feature_importances_
    }).sort_values("importance", ascending=False)

    # Save model
    joblib.dump(model, model_path)
    print("✅ Model trained and saved successfully.")


    # Create SHAP explainer (only for training phase)
    explainer = shap.TreeExplainer(model)

    return model, cm, report, feature_importances, explainer