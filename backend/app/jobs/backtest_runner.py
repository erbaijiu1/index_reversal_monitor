import time
from datetime import datetime
from threading import Lock

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from ..backtest.data_loader import load_theoretical_data
from ..backtest.engine import run_backtest
from ..backtest.models import BacktestRun
from ..backtest.repository import persist_result
from ..core.db import SessionLocal

_execution_lock = Lock()


def execute_backtest(run_id: int) -> bool:
    # FastAPI background tasks share this process. Serial execution avoids MySQL
    # auto-increment/FK deadlocks when A/B/C are submitted together.
    with _execution_lock:
        return _execute_backtest(run_id)


def _execute_backtest(run_id: int) -> bool:
    with SessionLocal() as db:
        claimed = db.execute(
            update(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.status == "QUEUED").values(status="RUNNING")
        )
        db.commit()
        if claimed.rowcount != 1:
            return False
        error = None
        for attempt in range(3):
            try:
                run = db.get(BacktestRun, run_id)
                bars, signals, weekly_lows, data_version, algorithm_version = load_theoretical_data(db, run)
                p = run.parameters
                result = run_backtest(
                    bars, signals, run.strategy, float(run.initial_capital),
                    p["risk_ratio"], p["max_position_ratio"], p["max_stop_ratio"],
                    p["fee_ratio"], p["slippage_ratio"], weekly_lows,
                    p.get("take_profit_r", 2.0), p.get("lot_size", 1),
                    p.get("entry_timing", "NEXT_OPEN"), p.get("stop_buffer_ratio", 0.0),
                    p.get("signal_period", "1w"),
                )
                run.data_version = data_version
                run.signal_algorithm_version = algorithm_version
                persist_result(db, run, result)
                db.commit()
                return True
            except OperationalError as caught:
                db.rollback()
                error = caught
                code = caught.orig.args[0] if getattr(caught, "orig", None) and caught.orig.args else None
                if code not in {1205, 1213} or attempt == 2:
                    break
                time.sleep(0.2 * (attempt + 1) + (run_id % 3) * 0.05)
            except Exception as caught:
                db.rollback()
                error = caught
                break
        run = db.get(BacktestRun, run_id)
        if run:
            run.status = "FAILED"
            run.error_message = str(error)[:2000]
            run.finished_at = datetime.utcnow()
            db.commit()
        return False


def run_worker(poll_seconds: float = 2.0, once: bool = False):
    while True:
        with SessionLocal() as db:
            run_id = db.scalar(select(BacktestRun.id).where(BacktestRun.status == "QUEUED").order_by(BacktestRun.id).limit(1))
        if run_id is not None:
            execute_backtest(run_id)
        elif once:
            return
        else:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()
