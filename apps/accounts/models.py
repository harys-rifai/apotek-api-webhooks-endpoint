from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model


User = get_user_model()


@receiver(post_save, sender=User)
def _ensure_profile(sender, instance, created, **kwargs):
    if created and not hasattr(instance, "monitor_profile"):
        MonitorProfile.objects.create(user=instance, source=MonitorProfile.SOURCE_LOCAL)


class MonitorProfile(models.Model):
    """Profil tambahan untuk User Monitor.

    Menandai asal user: dibuat lokal (``local``) atau disinkron dari
    ApotekApps (``apotekapps``). User dari ApotekApps hanya punya hak akses
    lihat (viewer) dan tidak bisa login dengan password lokal kecuali di-reset.
    """

    SOURCE_LOCAL = "local"
    SOURCE_APOTEKAPPS = "apotekapps"
    SOURCE_CHOICES = [
        (SOURCE_LOCAL, "Lokal"),
        (SOURCE_APOTEKAPPS, "ApotekApps"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="monitor_profile",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_LOCAL)
    external_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="ID user di ApotekApps (jika disinkron).",
    )
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Monitor Profile"
        verbose_name_plural = "Monitor Profiles"

    def __str__(self):
        return f"{self.user.username} ({self.get_source_display()})"
