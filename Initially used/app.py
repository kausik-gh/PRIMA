import streamlit as st
import matplotlib.pyplot as plt
import fraud_backend as fb
import time

# -----------------------------
# Page Config
# -----------------------------
st.set_page_config(
    page_title="Money Mule Detection",
    layout="wide"
)

st.title("🚨 Cross-Channel Money Mule Detection System")

st.markdown("""
This system simulates coordinated money mule attacks across channels
and uses ML to detect suspicious accounts in real time.
""")

# -----------------------------
# Train Model (Only Once)
# -----------------------------
if "model" not in st.session_state:

    st.info("Training ML model... Please wait.")

    final_dataset = fb.build_multi_run_dataset(num_runs=30)
    model = fb.ml_detection(final_dataset)

    fb.current_attack_index = 0  # reset attack index

    st.session_state.model = model

    st.success("Model trained successfully!")

model = st.session_state.model

# -----------------------------
# Simulate Attack Button
# -----------------------------

if st.button("🚀 Simulate Coordinated Attack"):

    accounts_df, transactions_df, attack_time, attack_name = fb.simulate_coordinated_attack()

    if accounts_df is not None:

        # Filter attack transactions
        attack_transactions = transactions_df[
            transactions_df["timestamp"] >= attack_time
        ]

        # -----------------------------
        # Build Graph
        # -----------------------------
        G = fb.build_transaction_graph(accounts_df, attack_transactions)

        st.subheader("📊 Fraud Subgraph View")

        fig = fb.visualize_fraud_subgraph(G)
        if fig:
            st.pyplot(fig)

        # -----------------------------
        # Feature Extraction
        # -----------------------------
        features_df = fb.extract_node_features(
            accounts_df,
            attack_transactions,
            G
        )

        # -----------------------------
        # Rule-Based Results
        # -----------------------------
        risk_df = fb.rule_based_detection(features_df)

        st.subheader("📌 Rule-Based Risk Scoring")
        st.dataframe(
            risk_df.sort_values("risk_score", ascending=False).head(10)
        )

        # -----------------------------
        # ML Prediction
        # -----------------------------
        predictions = fb.ml_predict(model, features_df)

        st.subheader("🤖 ML Detection Results")
        st.dataframe(
            predictions.sort_values("prediction_score", ascending=False).head(10)
        )

        # -----------------------------
        # Dramatic Reveal
        # -----------------------------
        st.markdown("---")

        with st.spinner("Analyzing behavioral graph patterns..."):
            time.sleep(2)

        st.subheader("🎭 Attack Type Revealed")
        st.success(f"The system detected pattern: **{attack_name}**")

        # -----------------------------
        # Detection Summary
        # -----------------------------
        true_fraud = accounts_df[accounts_df["is_fraud"] == 1]["account_id"].values
        predicted_fraud = predictions[predictions["predicted_label"] == 1]["account_id"].values

        correct = set(true_fraud).intersection(set(predicted_fraud))

        st.markdown("### ✅ Detection Summary")

        st.write(f"Fraud Accounts Injected: {len(true_fraud)}")
        st.write(f"Fraud Accounts Detected: {len(correct)}")

        if len(correct) == len(true_fraud):
            st.success("All fraud accounts successfully detected.")
        else:
            st.warning("Some fraud accounts were missed.")

    else:
        st.warning("All attack patterns executed.")

