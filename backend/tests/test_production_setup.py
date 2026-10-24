import sys
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts import setup_production
from scripts.runtime_env import read_env
from app.config import Settings


def arguments():
    return ('cargo.example.com','owner@example.com','123456789:unit_test_not_a_real_token','111','222')


def test_production_configuration_is_valid_and_separate():
    values=setup_production.prepare({},*arguments())
    config=Settings(_env_file=None,**{key.lower():value for key,value in values.items() if key.lower() in Settings.model_fields})
    assert config.env=='production' and config.dev_mode is False
    assert config.bot_mode=='webhook' and config.webapp_url=='https://cargo.example.com'
    assert config.jwt_secret!=config.bot_token and config.webhook_secret_token!=config.webhook_path_secret
    assert config.database_url.startswith('postgresql+asyncpg://')
    assert config.forwarded_allow_ips=='127.0.0.1,::1,172.30.0.2'


@pytest.mark.parametrize('domain',['https://cargo.example.com','127.0.0.1','localhost','a.example/path','a.example:443','-bad.example','cargo.example.com\nattack'])
def test_invalid_domains_rejected(domain):
    with pytest.raises(ValueError): setup_production.prepare({},domain,*arguments()[1:])


def test_existing_server_secrets_are_never_replaced():
    with pytest.raises(ValueError): setup_production.prepare({'ENV':'production','POSTGRES_PASSWORD':'existing'},*arguments())


def test_wizard_preserves_local_env_and_does_not_echo_tokens(tmp_path,monkeypatch,capsys):
    (tmp_path/'.env').write_text('local config kept\n')
    (tmp_path/'.env.production.example').write_text('OWNER_USERNAME=ZontikTech\n')
    monkeypatch.setattr(setup_production,'ROOT',tmp_path)
    monkeypatch.setattr('builtins.input',Mock(side_effect=['cargo.example.com','owner@example.com','111','222','да']))
    monkeypatch.setattr(setup_production,'hidden_prompt',lambda _:arguments()[2])
    assert setup_production.main([])==0
    assert (tmp_path/'.env').read_text()=='local config kept\n'
    values=read_env(tmp_path/'.env.production')
    assert values['BOT_TOKEN']==arguments()[2]
    assert values['OWNER_USERNAME']=='ZontikTech'
    output=capsys.readouterr().out
    for key in ['BOT_TOKEN','POSTGRES_PASSWORD','JWT_SECRET','WEBHOOK_SECRET_TOKEN']:
        assert values[key] not in output
    previous=(tmp_path/'.env.production').read_bytes()
    assert setup_production.main([])==1
    assert (tmp_path/'.env.production').read_bytes()==previous


@pytest.mark.parametrize('proxies',['*','caddy','127.0.0.1,','127.0.0.1\nattack',''])
def test_only_explicit_proxy_addresses_are_allowed(proxies):
    with pytest.raises(ValueError): Settings(_env_file=None,jwt_secret='x'*48,bot_enabled=False,forwarded_allow_ips=proxies)
