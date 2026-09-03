from backend.simulation import reset_simulation
from backend.attacks import attack_registry


def simulate_coordinated_attack(attack_index):

    if attack_index < len(attack_registry):

        accounts_df, transactions_df = reset_simulation()

        attack_function = attack_registry[attack_index]

        accounts_df, transactions_df, attack_name, attack_time = attack_function(
            accounts_df, transactions_df
        )

        return accounts_df, transactions_df, attack_time, attack_name

    else:
        return None, None, None, None

