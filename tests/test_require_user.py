"""
require user tests.
"""

import pytest
import wandb


@pytest.fixture
def require_mock(mocker):
    cleanup = []

    def fn(require, func):
        cleanup.append(require)
        mocker.patch.object(
            wandb.wandb_sdk.wandb_require._Requires,
            "require_" + require,
            func,
            create=True,
        )

    yield fn
    for require in cleanup:
        wandb.__dict__.pop("require_" + require, None)


def test_require_single(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something")
    captured = capsys.readouterr()
    assert "unsupported requirement: something" in captured.err
    assert "http://wandb.me/library-require" in captured.err


def test_require_list(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require(["something", "another"])
    captured = capsys.readouterr()
    assert "unsupported requirement: something" in captured.err
    assert "unsupported requirement: another" in captured.err


def test_require_version(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something@beta")
    captured = capsys.readouterr()
    assert "unsupported requirement: something" in captured.err


def test_require_param(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something:param@beta")
    captured = capsys.readouterr()
    assert "unsupported requirement: something" in captured.err


def test_require_good(user_test, require_mock):
    def mock_require_test(self):
        wandb.require_test = lambda x: x + 2

    require_mock("test", mock_require_test)
    wandb.require("test")

    assert wandb.require_test(2) == 4


def test_require_require(user_test, require_mock):
    # This is a noop now that it is "released"
    wandb.require("require")
