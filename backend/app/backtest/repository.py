from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .models import BacktestEquity, BacktestOrder, BacktestRun, BacktestTrade


def persist_result(db: Session, run: BacktestRun, result: dict) -> None:
    db.execute(delete(BacktestOrder).where(BacktestOrder.run_id == run.id))
    db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run.id))
    db.execute(delete(BacktestEquity).where(BacktestEquity.run_id == run.id))
    trade_ids = {}
    for trade in result["trades"]:
        record = BacktestTrade(
            run_id=run.id, signal_id=trade.signal_id, entry_date=trade.entry_date,
            exit_date=trade.exit_date, entry_price=trade.entry_price,
            exit_price=trade.exit_price, quantity=trade.quantity,
            initial_stop=trade.initial_stop, exit_reason=trade.exit_reason,
            gross_pnl=trade.gross_pnl, net_pnl=trade.net_pnl,
            total_fee=trade.total_fee, total_slippage=trade.total_slippage,
            return_ratio=(trade.net_pnl / (trade.entry_price * trade.quantity)) if trade.net_pnl is not None else None,
            status="CLOSED" if trade.exit_date else "OPEN",
        )
        db.add(record)
        db.flush()
        trade_ids[trade.signal_id] = record.id
    benchmark_base = result["benchmark_start_price"]
    for row in result["equity"]:
        values = {key: value for key, value in row.items() if key != "benchmark_close"}
        values["benchmark_net_value"] = row["benchmark_close"] / benchmark_base
        db.add(BacktestEquity(run_id=run.id, **values))
    for order in result["orders"]:
        db.add(BacktestOrder(
            run_id=run.id, trade_id=trade_ids.get(order.signal_id), signal_id=order.signal_id,
            side=order.side, order_type=order.order_type, trade_date=order.trade_date,
            trigger_price=order.trigger_price, fill_price=order.fill_price,
            quantity=order.quantity, notional=order.notional, fee=order.fee,
            slippage=order.slippage, reason=order.reason,
        ))
    skipped = [{**row, "trade_date": row["trade_date"].isoformat() if row.get("trade_date") else None} for row in result["skipped"][:100]]
    run.summary = {**result["summary"], "skipped": skipped}
    run.status = "SUCCESS"
    run.finished_at = datetime.utcnow()
