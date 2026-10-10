import importlib.util
from pathlib import Path

import pytest

APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('candidate_check',APP/'cloudflare-production/check.py')
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)


@pytest.mark.parametrize('name',['IKIMONO_PREVIEW_PASSWORD','IKIMONO_SESSION_SECRET'])
@pytest.mark.parametrize('value',['same',' ',''])
def test_candidate_refuses_reused_or_missing_credentials(name,value):
    state={'IKIMONO_PREVIEW_PASSWORD':'different-password','IKIMONO_SESSION_SECRET':'different-session'}
    state[name]=value
    with pytest.raises(ValueError,match='credentials'):
        checks.validate_separation(state,{'IKIMONO_PREVIEW_PASSWORD':'same','IKIMONO_SESSION_SECRET':'same'})


def test_distinct_candidate_credentials_are_accepted():
    checks.validate_separation({'IKIMONO_PREVIEW_PASSWORD':'new-password','IKIMONO_SESSION_SECRET':'new-session'},
        {'IKIMONO_PREVIEW_PASSWORD':'old-password','IKIMONO_SESSION_SECRET':'old-session'})


def test_secret_comparison_supports_utf8_without_logging():
    checks.validate_separation({'IKIMONO_PREVIEW_PASSWORD':'新規パスワード','IKIMONO_SESSION_SECRET':'new-session'},
        {'IKIMONO_PREVIEW_PASSWORD':'旧パスワード','IKIMONO_SESSION_SECRET':'old-session'})


def test_guest_needs_a_distinct_session_key_but_no_basic_password():
    preview={'IKIMONO_PREVIEW_PASSWORD':'old-password','IKIMONO_SESSION_SECRET':'old-session'}
    checks.validate_separation({'IKIMONO_SESSION_SECRET':'new-session'},preview,guest=True)
    for value in ('old-session','',' '):
        with pytest.raises(ValueError,match='credentials'):
            checks.validate_separation({'IKIMONO_SESSION_SECRET':value},preview,guest=True)
