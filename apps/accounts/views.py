from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone

from .models import MonitorProfile
from apps.monitor.services import get_apotek_users


def _is_admin(u):
    return u.is_authenticated and (u.is_superuser or u.is_staff)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    login_error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next", "/")
            return redirect(next_url)
        else:
            login_error = "Username atau password salah."

    return render(request, "accounts/login.html", {"login_error": login_error})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
@user_passes_test(_is_admin)
def user_list(request):
    users = User.objects.select_related("monitor_profile").all().order_by("username")
    ctx = {
        "users": users,
        "can_sync": bool(getattr(request.user, "monitor_profile", None)
                         and request.user.monitor_profile.source == MonitorProfile.SOURCE_APOTEKAPPS)
                         or True,
    }
    return render(request, "accounts/user_list.html", ctx)


@login_required
@user_passes_test(_is_admin)
def user_create(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("password_confirm", "")
        is_staff = request.POST.get("is_staff") == "on"

        err = None
        if not username:
            err = "Username wajib diisi."
        elif User.objects.filter(username=username).exists():
            err = f"User '{username}' sudah ada."
        elif not password:
            err = "Password wajib diisi."
        elif password != confirm:
            err = "Konfirmasi password tidak cocok."
        elif len(password) < 8:
            err = "Password minimal 8 karakter."

        if err:
            return render(request, "accounts/user_form.html", {
                "err": err,
                "username": username, "email": email, "is_staff": is_staff,
            })

        user = User.objects.create_user(
            username=username, email=email, password=password, is_staff=is_staff,
        )
        MonitorProfile.objects.get_or_create(
            user=user, defaults={"source": MonitorProfile.SOURCE_LOCAL})
        messages.success(request, f"User '{username}' berhasil dibuat.")
        return redirect("user_list")

    return render(request, "accounts/user_form.html", {})


@login_required
@user_passes_test(_is_admin)
@require_POST
def user_delete(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user.pk == request.user.pk:
        messages.error(request, "Tidak bisa menghapus user yang sedang login.")
        return redirect("user_list")
    if user.is_superuser:
        messages.error(request, "Superuser tidak bisa dihapus dari sini.")
        return redirect("user_list")
    uname = user.username
    user.delete()
    messages.success(request, f"User '{uname}' dihapus.")
    return redirect("user_list")


@login_required
@user_passes_test(_is_admin)
@require_POST
def user_sync_apotekapps(request):
    """Sinkronisasi user dari ApotekApps ke Monitor sebagai viewer.

    User yang sudah ada (berdasarkan username) diperbarui profilnya;
    user baru dibuat sebagai non-staff viewer tanpa password login lokal
    (hanya untuk pelacakan/otorisasi eksternal).
    """
    ok, apotek_users, error = get_apotek_users()
    if not ok:
        messages.error(request, f"Gagal sinkron user ApotekApps: {error}")
        return redirect("user_list")

    created, updated, skipped = 0, 0, 0
    for au in apotek_users:
        username = (au.get("username") or "").strip()
        if not username:
            skipped += 1
            continue
        ext_id = au.get("id")
        defaults = {
            "email": au.get("email", ""),
            "first_name": au.get("first_name", "") or "",
            "last_name": au.get("last_name", "") or "",
        }
        user, was_created = User.objects.update_or_create(
            username=username, defaults=defaults)
        # pastikan viewer (non-staff) — jangan timpa hak admin lokal
        if was_created:
            user.is_staff = False
            user.set_unusable_password()
            user.save()
            created += 1
        else:
            updated += 1
        MonitorProfile.objects.update_or_create(
            user=user,
            defaults={
                "source": MonitorProfile.SOURCE_APOTEKAPPS,
                "external_id": ext_id,
                "synced_at": timezone.now(),
            },
        )

    messages.success(
        request,
        f"Sinkron selesai — baru: {created}, diperbarui: {updated}, dilewati: {skipped}.")
    return redirect("user_list")
