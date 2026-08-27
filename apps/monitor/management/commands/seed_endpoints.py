"""
Isi tabel APIEndpoint dengan semua endpoint dari ApotekApps.
Jalankan: python manage.py seed_endpoints
"""
from django.core.management.base import BaseCommand
from apps.monitor.models import APIEndpoint

ENDPOINTS = [
    # Login (modul terpisah)
    ("Login",           "POST", "/auth/login/",        "login"),
    ("Login OAuth",     "POST", "/auth/login/oauth/",  "login"),
    # Register (modul terpisah)
    ("Register",        "POST", "/auth/register/",     "register"),
    ("Verify OTP",      "POST", "/auth/register/verify/", "register"),
    # POS — Apotek
    ("POS Scan",        "POST", "/pos/scan/",          "pos"),
    ("POS Apotek",      "GET",  "/pos/apotek/",        "pos"),
    ("POS Checkout",    "POST", "/pos/checkout/",      "pos"),
    # Feature2
    ("Feature2 Index",  "GET",  "/feature2/",          "feature2"),
    ("Feature2 Submit", "POST", "/feature2/submit/",   "feature2"),
    # Auth
    ("Refresh Token",   "POST", "/auth/refresh/",  "auth"),
    ("Profile",         "GET",  "/auth/profile/",  "auth"),
    # Users
    ("List Users",      "GET",  "/users/",              "users"),
    ("Me",              "GET",  "/users/me/",            "users"),
    ("Change Password", "POST", "/users/change-password/", "users"),
    # Roles
    ("List Roles",      "GET",  "/roles/",              "roles"),
    ("List Permissions","GET",  "/roles/permissions/",  "roles"),
    # Medicines
    ("List Medicines",  "GET",  "/medicines/",          "medicines"),
    ("List Categories", "GET",  "/medicines/categories/", "medicines"),
    ("List Units",      "GET",  "/medicines/units/",    "medicines"),
    # Suppliers
    ("List Suppliers",  "GET",  "/suppliers/",          "suppliers"),
    # Inventory
    ("List Batches",    "GET",  "/inventory/batches/",          "inventory"),
    ("Expiring Batches","GET",  "/inventory/batches/expiring/", "inventory"),
    ("Expired Batches", "GET",  "/inventory/batches/expired/",  "inventory"),
    ("Transactions",    "GET",  "/inventory/transactions/",     "inventory"),
    ("Opnames",         "GET",  "/inventory/opnames/",          "inventory"),
    ("Destroys",        "GET",  "/inventory/destroys/",         "inventory"),
    # Purchasing
    ("Purchase Orders", "GET",  "/purchase-orders/purchase-orders/",  "purchasing"),
    ("Goods Receipts",  "GET",  "/purchase-orders/goods-receipts/",   "purchasing"),
    # Sales
    ("Sales Transactions", "GET",  "/sales/transactions/", "sales"),
    ("Create Sale",        "POST", "/sales/transactions/", "sales"),
    # Orders
    ("Customer Orders", "GET",  "/orders/customer-orders/", "orders"),
    # Attendance
    ("Daily Attendance","GET",  "/attendance/daily/",    "attendance"),
    # Dashboard
    ("KPI",             "GET",  "/dashboard/kpi/",       "dashboard"),
    ("Recent Sales",    "GET",  "/dashboard/recent-sales/", "dashboard"),
    ("Store Info",      "GET",  "/dashboard/store/",     "dashboard"),
    # Reports
    ("Sales Report",    "GET",  "/reports/sales/",       "reports"),
    ("Inventory Report","GET",  "/reports/inventory/",   "reports"),
    ("Daily Sales Report","GET","/reports/daily-sales/", "reports"),
    # Audit
    ("Audit Logs",      "GET",  "/audit/logs/",          "audit"),
    # Common
    ("Stores",          "GET",  "/common/stores/",       "common"),
    # Deliveries
    ("Medicine Deliveries", "GET",  "/deliveries/",      "deliveries"),
]


class Command(BaseCommand):
    help = "Seed APIEndpoint table dengan semua endpoint ApotekApps"

    def handle(self, *args, **kwargs):
        created = 0
        skipped = 0
        for name, method, path, module in ENDPOINTS:
            obj, is_new = APIEndpoint.objects.get_or_create(
                method=method,
                path=path,
                defaults={"name": name, "module": module, "is_active": True},
            )
            if is_new:
                created += 1
                self.stdout.write(f"  + [{method}] {path}")
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nSelesai: {created} endpoint dibuat, {skipped} sudah ada."
        ))
