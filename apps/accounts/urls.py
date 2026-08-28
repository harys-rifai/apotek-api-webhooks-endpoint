from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:user_id>/delete/", views.user_delete, name="user_delete"),
    path("users/sync-apotekapps/", views.user_sync_apotekapps, name="user_sync_apotekapps"),
]
