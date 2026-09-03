# Cross-Channel Money Mule Detection System

## Overview

This project is a hybrid fraud detection platform designed to detect coordinated money mule activity across financial channels using:

- Random Forest Machine Learning
- Graph-Based Behavioral Features
- Rule-Based Risk Scoring
- SHAP Explainability
- Behavioral Drift Detection
- Adaptive Thresholding

The system simulates fraud attack patterns (Fan-In, Fan-Out) and classifies mule roles within coordinated rings.

---

## Project Structure

```
backend/
frontend/
lib/
```

- **backend/** → Core fraud logic, simulation, detection, training
- **frontend/** → HTML/JS web dashboard
- **lib/** → Static assets for the dashboard

---

## Features

- Hybrid Rule + ML detection
- Graph-based behavioral modeling
- SHAP explainability
- Fraud role classification
- Behavioral drift detection
- Adaptive thresholding system
- Interactive web dashboard with live graph visualization

---

## Installation

Clone the repository:

```
git clone https://github.com/kausik-gh/CROSS-CHANNEL-MONEY-MULE-DETECTION.git
```

Install dependencies:

```
pip install fastapi uvicorn pandas numpy scikit-learn shap joblib networkx
```

Run the application:

```
python -m uvicorn backend.api:app --reload --port 8088
```

Open the dashboard at [http://localhost:8088](http://localhost:8088)

---

## Purpose

This system demonstrates a research-oriented approach to cross-channel fraud detection using hybrid AI techniques and graph analytics.

---

## Author

Kausik GH
