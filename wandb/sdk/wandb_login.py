#
# -*- coding: utf-8 -*-
"""
Log in to Weights & Biases, authenticating your machine to log data to your
account.
"""
from __future__ import print_function

import enum
import os
from typing import Dict, Optional, Tuple

import click
import wandb
from wandb.errors import UsageError
from wandb.old.settings import Settings as OldSettings

from .internal.internal_api import Api
from .lib import apikey
from .wandb_settings import Settings
from ..apis import InternalApi


def _handle_host_wandb_setting(host: Optional[str], cloud: bool = False) -> None:
    """Write the host parameter from wandb.login or wandb login to
    the global settings file so that it is used automatically by
    the application's APIs."""
    _api = InternalApi()
    if host == "https://api.wandb.ai" or (host is None and cloud):
        _api.clear_setting("base_url", globally=True, persist=True)
        # To avoid writing an empty local settings file, we only clear if it exists
        if os.path.exists(OldSettings._local_path()):
            _api.clear_setting("base_url", persist=True)
    elif host:
        host = host.rstrip("/")
        # force relogin if host is specified
        _api.set_setting("base_url", host, globally=True, persist=True)


def login(anonymous=None, key=None, relogin=None, host=None, force=None, timeout=None):
    """
    Log in to W&B.

    Arguments:
        anonymous: (string, optional) Can be "must", "allow", or "never".
            If set to "must" we'll always login anonymously, if set to
            "allow" we'll only create an anonymous user if the user
            isn't already logged in.
        key: (string, optional) authentication key.
        relogin: (bool, optional) If true, will re-prompt for API key.
        host: (string, optional) The host to connect to.
        timeout: (int, optional) Number of seconds to wait for user input.

    Returns:
        bool: if key is configured

    Raises:
        UsageError - if api_key can not configured and no tty
    """

    _handle_host_wandb_setting(host)
    if wandb.setup()._settings._noop:
        return True
    kwargs = dict(locals())
    configured = _login(**kwargs)
    return True if configured else False


class ApiKeyStatus(enum.Enum):
    VALID = 1
    NOTTY = 2
    OFFLINE = 3
    DISABLED = 4


class _WandbLogin(object):
    def __init__(self):
        self.kwargs: Optional[Dict] = None
        self._settings: Optional[Settings] = None
        self._backend = None
        self._silent = None
        self._wl = None
        self._key = None
        self._relogin = None

    def setup(self, kwargs):
        self.kwargs = kwargs

        # built up login settings
        login_settings: Settings = wandb.Settings()
        settings_param = kwargs.pop("_settings", None)
        if settings_param:
            login_settings._apply_settings(settings_param)
        _logger = wandb.setup()._get_logger()
        # Do not save relogin into settings as we just want to relogin once
        self._relogin = kwargs.pop("relogin", None)
        login_settings._apply_login(kwargs, _logger=_logger)

        # make sure they are applied globally
        self._wl = wandb.setup(settings=login_settings)
        self._settings = self._wl._settings

    def is_apikey_configured(self):
        return apikey.api_key(settings=self._settings) is not None

    def set_backend(self, backend):
        self._backend = backend

    def set_silent(self, silent):
        self._silent = silent

    def login(self):
        apikey_configured = self.is_apikey_configured()
        if self._settings.relogin or self._relogin:
            apikey_configured = False
        if not apikey_configured:
            return False

        if not self._silent:
            self.login_display()

        return apikey_configured

    def login_display(self):
        # check to see if we got an entity from the setup call
        active_entity = self._wl._get_entity()
        login_info_str = "(use `wandb login --relogin` to force relogin)"
        if active_entity:
            login_state_str = "Currently logged in as:"
            wandb.termlog(
                "{} {} {}".format(
                    login_state_str,
                    click.style(active_entity, fg="yellow"),
                    login_info_str,
                ),
                repeat=False,
            )
        else:
            login_state_str = "W&B API key is configured"
            wandb.termlog(
                "{} {}".format(login_state_str, login_info_str,), repeat=False,
            )

    def configure_api_key(self, key):
        if self._settings._jupyter and not self._settings._silent:
            wandb.termwarn(
                (
                    "If you're specifying your api key in code, ensure this "
                    "code is not shared publically.\nConsider setting the "
                    "WANDB_API_KEY environment variable, or running "
                    "`wandb login` from the command line."
                )
            )
        apikey.write_key(self._settings, key)
        self.update_session(key)
        self._key = key

    def update_session(
        self, key: Optional[str], status: ApiKeyStatus = ApiKeyStatus.VALID
    ) -> None:
        _logger = wandb.setup()._get_logger()
        settings: Settings = wandb.Settings()
        login_settings = dict()
        if status == ApiKeyStatus.OFFLINE:
            login_settings = dict(mode="offline")
        elif status == ApiKeyStatus.DISABLED:
            login_settings = dict(mode="disabled")
        elif key:
            login_settings = dict(api_key=key)
        settings._apply_source_login(login_settings, _logger=_logger)
        self._wl._update(settings=settings)
        # Whenever the key changes, make sure to pull in user settings
        # from server.
        if not self._wl.settings._offline:
            self._wl._update_user_settings()

    def _prompt_api_key(self) -> Tuple[Optional[str], ApiKeyStatus]:

        api = Api(self._settings)
        while True:
            try:
                key = apikey.prompt_api_key(
                    self._settings,
                    api=api,
                    no_offline=self._settings.force if self._settings else None,
                    no_create=self._settings.force if self._settings else None,
                )
            except ValueError as e:
                # invalid key provided, try again
                wandb.termerror(e.args[0])
                continue
            except TimeoutError:
                wandb.termlog("W&B disabled due to login timeout.")
                return None, ApiKeyStatus.DISABLED
            if key is False:
                return None, ApiKeyStatus.NOTTY
            if not key:
                return None, ApiKeyStatus.OFFLINE
            return key, ApiKeyStatus.VALID

    def prompt_api_key(self):
        key, status = self._prompt_api_key()
        if status == ApiKeyStatus.NOTTY:
            directive = (
                "wandb login [your_api_key]"
                if self._settings._cli_only_mode
                else "wandb.login(key=[your_api_key])"
            )
            raise UsageError("api_key not configured (no-tty). call " + directive)

        self.update_session(key, status=status)
        self._key = key

    def propogate_login(self):
        # TODO(jhr): figure out if this is really necessary
        if self._backend:
            # TODO: calling this twice is gross, this deserves a refactor
            # Make sure our backend picks up the new creds
            # _ = self._backend.interface.communicate_login(key, anonymous)
            pass


def _login(
    anonymous=None,
    key=None,
    relogin=None,
    host=None,
    force=None,
    timeout=None,
    _backend=None,
    _silent=None,
    _disable_warning=None,
):
    kwargs = dict(locals())
    _disable_warning = kwargs.pop("_disable_warning", None)

    if wandb.run is not None:
        if not _disable_warning:
            wandb.termwarn("Calling wandb.login() after wandb.init() has no effect.")
        return True

    wlogin = _WandbLogin()

    _backend = kwargs.pop("_backend", None)
    if _backend:
        wlogin.set_backend(_backend)

    _silent = kwargs.pop("_silent", None)
    if _silent:
        wlogin.set_silent(_silent)

    # configure login object
    wlogin.setup(kwargs)

    if wlogin._settings._offline:
        return False
    elif wandb.util._is_kaggle() and not wandb.util._has_internet():
        wandb.termerror(
            "To use W&B in kaggle you must enable internet in the settings panel on the right."
        )
        return False

    # perform a login
    logged_in = wlogin.login()

    key = kwargs.get("key")
    if key:
        wlogin.configure_api_key(key)

    if logged_in:
        return logged_in

    if not key:
        wlogin.prompt_api_key()

    # make sure login credentials get to the backend
    wlogin.propogate_login()

    return wlogin._key or False
