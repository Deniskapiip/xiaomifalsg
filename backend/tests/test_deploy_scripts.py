import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def deployment(tmp_path):
    if os.name=='nt' or not shutil.which('flock'):
        pytest.skip('Ubuntu shell utilities required')
    root=tmp_path/'project with spaces'
    shutil.copytree(ROOT/'deploy',root/'deploy')
    binary=tmp_path/'bin'
    binary.mkdir()
    docker=binary/'docker'
    docker.write_text('''#!/bin/sh
set -eu
echo "$*" >> "$TAOJI_QA_CALLS"
case "$*" in
  *pg_dump*) [ "${TAOJI_QA_FAIL_DUMP:-0}" = 0 ] || exit 2; printf 'QA verified archive';;
  *pg_restore*) cat >/dev/null; [ "${TAOJI_QA_FAIL_VERIFY:-0}" = 0 ] || exit 3;;
  *"build app"*) [ "${TAOJI_QA_FAIL_BUILD:-0}" = 0 ] || exit 4;;
esac
''')
    docker.chmod(0o700)
    environment={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'TAOJI_QA_CALLS':str(tmp_path/'calls')}
    return root,environment


@pytest.mark.parametrize('failure',['TAOJI_QA_FAIL_DUMP','TAOJI_QA_FAIL_VERIFY'])
def test_failed_dump_never_publishes_or_rotates(deployment,failure):
    root,environment=deployment
    backups=root/'backups/postgres'
    backups.mkdir(parents=True)
    previous=backups/'taoji-20260101-000000-abcdef.dump'
    previous.write_text('previous valid copy')
    environment[failure]='1'
    result=subprocess.run(['sh',str(root/'deploy/backup-postgres.sh')],env=environment,capture_output=True,timeout=10)
    assert result.returncode!=0
    assert previous.read_text()=='previous valid copy'
    assert not list(backups.glob('.partial-*'))
    assert list(backups.glob('*.dump'))==[previous]


def test_backup_keeps_fourteen_owned_files_and_unrelated_files(deployment):
    root,environment=deployment
    backups=root/'backups/postgres'
    backups.mkdir(parents=True)
    for index in range(20):
        (backups/f'taoji-20260101-{index:06d}-abcdef.dump').write_text('old copy')
    other=backups/'taoji-important-business.dump'
    other.write_text('unrelated')
    result=subprocess.run(['sh',str(root/'deploy/backup-postgres.sh')],env=environment,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr.decode()
    assert other.read_text()=='unrelated'
    assert len(list(backups.glob('taoji-202*.dump')))==14


def test_failed_build_keeps_running_app(deployment):
    root,environment=deployment
    environment['TAOJI_QA_FAIL_BUILD']='1'
    result=subprocess.run(['sh',str(root/'deploy/update.sh')],env=environment,capture_output=True,timeout=10)
    assert result.returncode!=0
    calls=Path(environment['TAOJI_QA_CALLS']).read_text()
    assert 'pg_dump' in calls and 'build app' in calls
    assert 'stop app' not in calls and 'alembic upgrade' not in calls


def test_update_migrates_only_after_stop_and_waits_for_health(deployment):
    root,environment=deployment
    result=subprocess.run(['sh',str(root/'deploy/update.sh')],env=environment,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr.decode()
    calls=Path(environment['TAOJI_QA_CALLS']).read_text()
    assert calls.index('pg_dump')<calls.index('build app')<calls.index('stop app')<calls.index('alembic upgrade')
    assert '--force-recreate --wait --wait-timeout 90 app' in calls
