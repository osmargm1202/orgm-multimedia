import os
import signal
import subprocess
import sys
from orgm_home.resources import CpuMeter, PressureGuard, terminate_family


def test_only_sustained_pressure_closes_the_last_background_source():
    guard=PressureGuard()
    eligible={'youtube','max'}
    guard.observe(95,'youtube',['home','youtube','max'],eligible,now=0)
    guard.observe(95,'max',['home','youtube','max'],eligible,now=10)
    assert guard.observe(95,'max',['home','youtube','max'],eligible,now=59) is None
    assert guard.observe(95,'max',['home','youtube','max'],eligible,now=60)=='youtube'
    guard.closed('youtube','YouTube',now=60)
    assert guard.observe(95,'home',['home','youtube','max'],eligible,now=65) is None
    assert guard.notice['app']=='youtube'


def test_brief_pressure_does_not_close_sources_and_new_selection_gets_grace():
    guard=PressureGuard()
    guard.observe(95,'youtube',['home','youtube','max'],{'youtube','max'},now=0)
    guard.observe(10,'youtube',['home','youtube','max'],{'youtube','max'},now=50)
    assert guard.observe(95,'max',['home','youtube','max'],{'youtube','max'},now=51) is None
    assert guard.observe(95,'max',['home','youtube','max'],{'youtube','max'},now=110) is None
    assert guard.observe(95,'max',['home','youtube','max'],{'youtube','max'},now=111)=='youtube'


def test_active_source_and_spotify_are_protected_and_unknown_focus_does_not_evict():
    guard=PressureGuard()
    for now in [0,60,120]:
        assert guard.observe(99,'youtube',['home','youtube','spotify'],{'youtube'},now=now) is None
    assert guard.observe(99,None,['home','youtube','spotify'],{'youtube'},now=180) is None


def test_cpu_sampler_uses_deltas_not_boot_average(monkeypatch):
    values=iter(['cpu 10 0 10 80 0 0 0 0\n','cpu 50 0 50 100 0 0 0 0\n'])
    monkeypatch.setattr('pathlib.Path.read_text',lambda self:next(values))
    meter=CpuMeter()
    assert meter.sample() is None
    assert meter.sample()==80


def test_terminating_owned_family_does_not_signal_an_unrelated_process():
    target=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    try:
        assert terminate_family({target.pid})
        assert target.wait(timeout=3) in {-signal.SIGTERM,-signal.SIGKILL}
        assert unrelated.poll() is None
    finally:
        for process in [target,unrelated]:
            if process.poll() is None:
                os.kill(process.pid,signal.SIGTERM)
            process.wait(timeout=3)
