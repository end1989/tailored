"""Which settings apply to a person: the one resolver (spec 5.2).

Every render and every web default reads settings through settings_for with
the application's OWNER, never with whoever is picked in a browser. That is
what keeps an MCP agent's renders independent of the web app's person picker.
"""
from __future__ import annotations

from pathlib import Path

from ..config import load_user_settings
from ..models import Profile, get_profile_settings
from .render import TEMPLATES


def settings_for(data_dir: Path, profile: Profile | None) -> dict[str, str]:
    """load_user_settings(data_dir) overlaid with get_profile_settings(profile).

    That is DEFAULT_USER_SETTINGS, then data/settings.json, then the person's
    own values, key by key. With no profile it is the app-wide values alone.
    A person's default_template that is not a registered template (a typo, or
    a template removed after it was chosen) is ignored, so the app-wide one
    applies. Always a fresh dict.
    """
    values = load_user_settings(Path(data_dir))
    if profile is not None:
        own = get_profile_settings(profile)
        if "default_template" in own and own["default_template"] not in TEMPLATES:
            del own["default_template"]
        values.update(own)
    return values
