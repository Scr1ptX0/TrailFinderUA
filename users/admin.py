from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Trail Profile", {"fields": ("bio", "avatar", "saved_trails")}),
    )
    filter_horizontal = ("saved_trails", "groups", "user_permissions")
    list_display = ["username", "email", "is_staff", "date_joined"]
