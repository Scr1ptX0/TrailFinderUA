from django.contrib.auth.models import AbstractUser
from django.db import models


class UserProfile(AbstractUser):
    bio         = models.TextField(blank=True)
    avatar      = models.ImageField(upload_to="avatars/", blank=True, null=True)
    saved_trails = models.ManyToManyField(
        "trails.Trail",
        blank=True,
        related_name="saved_by",
    )

    class Meta:
        verbose_name        = "Профіль користувача"
        verbose_name_plural = "Профілі користувачів"

    def __str__(self):
        return self.username
