from __future__ import annotations

from pathlib import Path

from utils.runtime_overrides import get_effective_runtime_value, load_dotenv_defaults, save_runtime_overrides


def test_load_dotenv_defaults_parses_simple_key_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TRADING_AGENT_USE_DOTENV_FALLBACK', 'YES')
    (tmp_path / '.env').write_text("PROPR_ENV=beta\nPROPR_SYMBOL='BTC/USDC'\n# comment\n", encoding='utf-8')

    values = load_dotenv_defaults()

    assert values['PROPR_ENV'] == 'beta'
    assert values['PROPR_SYMBOL'] == 'BTC/USDC'


def test_get_effective_runtime_value_prefers_overrides_then_env_then_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TRADING_AGENT_USE_DOTENV_FALLBACK', 'YES')
    monkeypatch.delenv('PROPR_SYMBOL', raising=False)
    monkeypatch.setenv('TRADING_AGENT_RUNTIME_CONFIG_PATH', str(tmp_path / 'artifacts' / 'runtime_overrides.json'))
    (tmp_path / '.env').write_text('PROPR_SYMBOL=ETH/USDC\n', encoding='utf-8')

    assert get_effective_runtime_value('PROPR_SYMBOL') == 'ETH/USDC'

    monkeypatch.setenv('PROPR_SYMBOL', 'SOL/USDC')
    assert get_effective_runtime_value('PROPR_SYMBOL') == 'SOL/USDC'

    save_runtime_overrides({'PROPR_SYMBOL': 'BTC/USDC'})
    assert get_effective_runtime_value('PROPR_SYMBOL') == 'BTC/USDC'
