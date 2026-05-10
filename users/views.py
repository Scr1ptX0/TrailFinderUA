from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.shortcuts import redirect, render

from .models import UserProfile


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = AuthenticationForm(data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect(request.GET.get("next", "home"))
    return render(request, "users/login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("home")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "users/register.html", {"form": form})


@login_required
def profile_view(request):
    saved_trails = request.user.saved_trails.filter(is_active=True).order_by("name")
    reviews      = request.user.reviews.select_related("trail").order_by("-created_at")
    return render(request, "users/profile.html", {
        "saved_trails": saved_trails,
        "reviews":      reviews,
    })
