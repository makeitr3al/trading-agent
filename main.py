from broker.propr_client import ProprClient
from config.propr_config import ProprConfig


def main() -> None:
    config = ProprConfig()
    client = ProprClient(config)

    print("Trading app architecture initialized.")
    print("The project structure has been consolidated into app/, strategy/, and broker/ layers.")
    print(f"broker_base_url: {client.config.base_url}")
    print("A single app cycle can now orchestrate strategy, broker sync, and guarded execution on the refactored architecture.")
    print("First challenge and risk guards can now block execution before any order submit or replace step.")
    print("External Propr pending order ids can now be synchronized into the AgentState for safer submit, replace, and cancel flows across cycles.")
    print("The broker layer now adapts the local official SDK in broker/propr_sdk.py instead of relying on the older low-level broker abstraction.")
    print("The next step is to continue development on the simplified structure without introducing real API calls here.")


if __name__ == "__main__":
    main()
