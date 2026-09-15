"""API URL routing.

Registration and login routes live in apps.users.urls, also mounted at api/v1/.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("v1/health/", views.health_check, name="health"),
    path("v1/version/", views.version, name="version"),
    path("v1/tasks/demo/", views.demo_task, name="demo-task"),
]
