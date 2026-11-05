"""Contract checks that keep cross-file invariants from drifting during edits."""
import json
import shutil
import subprocess
from importlib.resources import files

import pytest

from mythread import dom
from mythread.browser_ui import BrowserApp, HomeAction, primary_button
from mythread.messages import _STATE_TITLES
from mythread.model import COUNT_PATTERN, State
from mythread.screens import BrowserArticle, BrowserReader, CommentsScreen


def test_reply_count_pattern_is_shared_with_snapshot_js():
    # snapshot.js holds the pattern as a JS string literal (backslashes doubled).
    assert json.dumps(COUNT_PATTERN, ensure_ascii=False)[1:-1] in dom.SNAPSHOT


@pytest.mark.skipif(not shutil.which('node'), reason='node not installed')
@pytest.mark.parametrize('name', ['snapshot.js', 'scroll.js'])
def test_page_scripts_are_valid_javascript(name):
    path = files('mythread.dom').joinpath(name)
    subprocess.run(['node', '--check', str(path)], check=True)


@pytest.mark.parametrize('owner', [BrowserApp, BrowserReader, BrowserArticle, CommentsScreen])
def test_button_actions_point_to_methods(owner):
    for button_id, method in owner.BUTTON_ACTIONS.items():
        assert callable(getattr(owner, method, None)), f'{owner.__name__}: #{button_id} -> {method}'


def test_every_non_login_state_has_a_status_title():
    assert set(State) - {State.LOGIN} == set(_STATE_TITLES)


def test_primary_button_follows_state():
    assert primary_button(State.CLOSED, True) == 'recover'
    assert primary_button('initial', False) == 'background'
    assert primary_button(State.LOGIN, True) == 'open'
    assert primary_button(State.READY, True) == 'read'
    assert {a.value for a in HomeAction} >= {'open', 'read', 'next', 'recover', 'background'}
