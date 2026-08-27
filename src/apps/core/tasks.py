"""Example Dramatiq background tasks."""

from django.core.mail import send_mail
from dramatiq import actor


@actor
def send_welcome_email(email: str) -> None:
    """Send a welcome email to a new user."""
    send_mail(
        subject="Welcome to Dristi",
        message="Thanks for signing up!",
        from_email=None,
        recipient_list=[email],
        fail_silently=True,
    )


@actor
def process_long_running_job(job_id: str) -> str:
    """Placeholder for a CPU / IO intensive background job."""
    return f"job-{job_id}-completed"
