from __future__ import annotations

import nox
from release_toolkit.nox_release import release_session

nox.options.default_venv_backend = "uv"


@nox.session(name="release", python=False, default=False)
def release(session):
    release_session(session, use_filter=False)
