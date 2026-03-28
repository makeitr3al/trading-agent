from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.propr_config import ProprConfig
from scripts import propr_smoke_test


class FakeClient:
    def __init__(self, _config) -> None:
        self._config = _config

    def health_check(self):
        return {"status": "OK"}

    def get_user_profile(self):
        return {"id": "user-1", "status": "active"}

    def get_challenge_attempts(self):
        return {"data": [{"attemptId": "attempt-1", "accountId": "account-1", "status": "active"}]}

    def get_orders(self, account_id: str):
        assert account_id == "account-1"
        return {"data": [{"orderId": "order-1"}]}

    def get_positions(self, account_id: str):
        assert account_id == "account-1"
        return {"data": [{"positionId": "position-1"}]}

    def get_trades(self, account_id: str):
        assert account_id == "account-1"
        return {"data": [{"tradeId": "trade-1"}]}


class FailingClient:
    def __init__(self, _config) -> None:
        pass

    def health_check(self):
        raise TimeoutError("read timeout")


def test_propr_smoke_test_returns_zero_on_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(propr_smoke_test, "load_propr_config_from_env", lambda: ProprConfig(api_key="key", environment="beta"))
    monkeypatch.setattr(propr_smoke_test, "ProprClient", FakeClient)
    monkeypatch.setattr(propr_smoke_test, "parse_challenge_attempts", lambda payload: [SimpleNamespace(attempt_id="attempt-1", account_id="account-1", status="active")])
    monkeypatch.setattr(
        propr_smoke_test,
        "get_active_challenge_context",
        lambda client: SimpleNamespace(
            account_id="account-1",
            attempt=SimpleNamespace(attempt_id="attempt-1", status="active"),
        ),
    )

    result = propr_smoke_test.main()

    assert result == 0
    captured = capsys.readouterr()
    assert "Read-only Propr smoke test finished." in captured.out


def test_propr_smoke_test_returns_non_zero_on_exception(monkeypatch, capsys) -> None:
    monkeypatch.setattr(propr_smoke_test, "load_propr_config_from_env", lambda: ProprConfig(api_key="key", environment="beta"))
    monkeypatch.setattr(propr_smoke_test, "ProprClient", FailingClient)

    result = propr_smoke_test.main()

    assert result == 1
    captured = capsys.readouterr()
    assert "Smoke test failed: read timeout" in captured.out
