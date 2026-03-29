from pathlib import Path
import json
import os
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_operator_config_set_and_show_roundtrip(tmp_path: Path) -> None:
    data_path = tmp_path / 'trading-agent-data'
    config_path = data_path / 'operator_config.json'
    env = dict(os.environ)
    env['TRADING_AGENT_DATA_PATH'] = str(data_path)
    env['TRADING_AGENT_OPERATOR_CONFIG_PATH'] = str(config_path)

    set_result = subprocess.run(
        [
            sys.executable,
            'operator_config.py',
            'set',
            '--mode',
            'preflight',
            '--environment',
            'beta',
            '--leverage',
            '3',
            '--markets',
            'btc/usdc:btc,eth/usdc:eth',
            '--scheduling-enabled',
            'true',
            '--schedule-time',
            '07:15',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert set_result.returncode == 0
    persisted = json.loads(config_path.read_text(encoding='utf-8'))
    assert persisted['mode'] == 'preflight'
    assert persisted['environment'] == 'beta'
    assert persisted['leverage'] == 3
    assert persisted['markets'] == 'BTC/USDC:BTC,ETH/USDC:ETH'
    assert persisted['scheduling_enabled'] is True
    assert persisted['schedule_time'] == '07:15'

    show_result = subprocess.run(
        [sys.executable, 'operator_config.py', 'show'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert show_result.returncode == 0
    payload = json.loads(show_result.stdout)
    assert payload['config']['mode'] == 'preflight'
    assert payload['derived']['primary_symbol'] == 'BTC/USDC'
    assert payload['paths']['journal_path'].endswith('trading_journal_beta.jsonl')
    assert payload['paths']['journal_table_path'].endswith('journal_table.json')


def test_operator_config_export_env_contains_shell_exports(tmp_path: Path) -> None:
    data_path = tmp_path / 'trading-agent-data'
    config_path = data_path / 'operator_config.json'
    data_path.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                'mode': 'scharf',
                'environment': 'prod',
                'leverage': 2,
                'markets': 'SOL/USDC:SOL',
                'scheduling_enabled': False,
                'schedule_time': '07:00',
            }
        ) + '\n',
        encoding='utf-8',
    )
    env = dict(os.environ)
    env['TRADING_AGENT_DATA_PATH'] = str(data_path)
    env['TRADING_AGENT_OPERATOR_CONFIG_PATH'] = str(config_path)

    export_result = subprocess.run(
        [sys.executable, 'operator_config.py', 'export-env'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert export_result.returncode == 0
    assert 'export OPERATOR_MODE=scharf' in export_result.stdout
    assert 'export OPERATOR_ENVIRONMENT=prod' in export_result.stdout
    assert 'export OPERATOR_PRIMARY_SYMBOL=SOL/USDC' in export_result.stdout
    assert 'export OPERATOR_RUN_SUMMARY_PATH=' in export_result.stdout
    assert 'export OPERATOR_JOURNAL_TABLE_PATH=' in export_result.stdout

