"""Auth backend: login Monitor with ApotekApps credentials.

Lets any ApotekApps user log into this Monitor dashboard using the SAME
username/password as ApotekApps. On success the local ``User`` is created
(or updated) automatically and linked via ``MonitorProfile.source =
'apotekapps'``. The returned JWT is cached on the profile so Monitor can act
on the user's behalf against the ApotekApps API.

Local Django users (``source='local'``) still authenticate normally — this
backend only runs after the default ``ModelBackend`` and only when the user
is not found locally (or local auth fails for an apotekapps-synced user).
"""
import logging
import time

import requests
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User as AuthUser
from django.utils import timezone

from apps.monitor.services import BASE_URL

logger = logging.getLogger(__name__)


class ApotekAppsBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        # Don't hijack local-only users; let ModelBackend handle them first.
        User = get_user_model()
        local = User.objects.filter(username=username).first()
        if local is not None and getattr(local, "monitor_profile", None) \
                and local.monitor_profile.source == "local":
            return None

        try:
            resp = requests.post(
                f"{BASE_URL}/auth/login/",
                json={"username": username, "password": password},
                timeout=10,
            )
        except Exception as e:
            logger.warning("ApotekApps login request failed: %s", e)
            return None

        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
        except Exception:
            return None

        access = data.get("access")
        refresh = data.get("refresh")
        if not access:
            return None

        user, created = User.objects.get_or_create(username=username)
        # ApotekApps users are viewers by default; never promote to staff
        # automatically (an admin can grant staff separately if desired).
        if created:
            user.set_unusable_password()
        # sync basic profile fields if provided
        for fld in ("email", "first_name", "last_name"):
            if data.get(fld):
                setattr(user, fld, data[fld])
        user.is_active = True
        user.save()

        from .models import MonitorProfile
        profile, _ = MonitorProfile.objects.get_or_create(user=user)
        profile.source = MonitorProfile.SOURCE_APOTEKAPPS
        profile.external_id = data.get("user_id") or data.get("id")
        profile.synced_at = timezone.now()
        profile.set_token(access, refresh)
        profile.save()

        return user

    def get_user(self, user_id):
        return AuthUser.objects.filter(pk=user_id).first()
