from backend.training import build_multi_run_dataset
from backend.training import train_and_save_model

print("Generating training dataset...")

dataset = build_multi_run_dataset(num_runs=1000)

print("Training model...")

model, cm, report, feature_importances, explainer = train_and_save_model(dataset)

print("Training complete.")
print("Confusion Matrix:")
print(cm)