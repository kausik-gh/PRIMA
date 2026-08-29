NUM_ACCOUNTS             = 500
TX_INTERVAL_SEC          = 0.5     # very fast — realistic burst activity
TX_STEP_COUNT            = 4       # 4 transactions per step = ~8 TPS
NUM_TRANSACTIONS         = 20      # seed at startup
MAX_TX_MEMORY            = None    # keep full transaction history for the active app session
TX_WINDOW                = 500
EARLY_DETECTION_TOP_PCT  = 0.08    # strict — top 8% only
EARLY_DETECTION_MIN_SIGS = 2
ATTACK_POOL_SIZE         = 12
ATTACK_FRAUD_COUNT       = 7
ATTACK_PREFER_SUS_PCT    = 0.75    # 75% of attack pool from suspicious accounts
