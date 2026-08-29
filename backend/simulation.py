from backend.generator import generate_accounts, generate_normal_transactions
from backend.config import NUM_ACCOUNTS, NUM_TRANSACTIONS

def reset_simulation():
    accounts_df = generate_accounts(NUM_ACCOUNTS)
    transactions_df = generate_normal_transactions(accounts_df, NUM_TRANSACTIONS)
    return accounts_df, transactions_df
