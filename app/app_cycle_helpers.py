from broker.order_service import apply_symbol_spec_to_order
from config.strategy_config import StrategyConfig
from models.order import Order, OrderType
from models.symbol_spec import SymbolSpec
from strategy.position_sizer import calculate_position_size, evaluate_position_size_execution
from strategy.state import AgentState


def _beta_blocks_standalone_entry_order(order: Order | None, environment: str | None) -> bool:
    """Skip API submit for standalone stop-limit entries on Beta: Propr returns 13056 conditional_order_requires_position_or_group."""
    if (environment or "").strip().lower() != "beta" or order is None:
        return False
    return order.order_type in {OrderType.BUY_STOP, OrderType.SELL_STOP}


def _count_open_order_trade_slots(state: AgentState | None) -> int:
    if state is None:
        return 0

    return (
        int(getattr(state, "account_open_entry_orders_count", 0) or 0)
        + int(getattr(state, "account_open_positions_count", 0) or 0)
    )


def _apply_symbol_specific_position_size(
    order: Order,
    config: StrategyConfig,
    account_balance: float,
    desired_leverage: int,
    symbol_spec: SymbolSpec,
) -> Order:
    sizing_result = calculate_position_size(
        entry=order.entry,
        stop_loss=order.stop_loss,
        account_balance=account_balance,
        risk_per_trade_pct=config.risk_per_trade_pct,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
    )
    prepared_order = order.model_copy(update={"position_size": sizing_result.position_size})
    return apply_symbol_spec_to_order(prepared_order, symbol_spec)


def _validate_pending_order_execution_size(
    order: Order,
    account_balance: float,
    desired_leverage: int,
    symbol_spec: SymbolSpec | None,
) -> str | None:
    if order.position_size is None:
        return "position size unavailable"

    sizing_execution_result = evaluate_position_size_execution(
        entry=order.entry,
        position_size=order.position_size,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        max_leverage=symbol_spec.max_leverage if symbol_spec is not None else None,
    )
    return sizing_execution_result.reason
