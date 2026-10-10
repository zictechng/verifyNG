
import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from reports.models import FraudReport, AuditLog

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=FraudReport)
def track_report_state_change(sender, instance, **kwargs):
    """
    Caches previous state on instance before save.
    """
    if instance.pk:
        try:
            previous = FraudReport.objects.filter(pk=instance.pk).values('state').first()
            instance._previous_state = previous['state'] if previous else None
        except Exception:
            instance._previous_state = None
    else:
        instance._previous_state = None


@receiver(post_save, sender=FraudReport)
def log_report_lifecycle_audit_fallback(sender, instance, created, update_fields=None, **kwargs):
    """
    Fallback receiver that catches direct model saves outside the service layer.
    - Suppressed if instance._audit_logged is set (and safely resets it for future saves).
    - Checks update_fields: skips transition logging if 'state' was not updated.
    """
    if getattr(instance, '_audit_logged', False):
        # Reset flag so future saves on this in-memory instance are not suppressed
        instance._audit_logged = False
        return

    # If update_fields was provided on an existing instance and 'state' was excluded, skip
    if not created and update_fields is not None and 'state' not in update_fields:
        return

    if created:
        AuditLog.objects.create(
            report=instance,
            action="REPORT_SUBMITTED",
            performed_by=instance.reporter,
            details={
                "reference_number": instance.reference_number,
                "initial_state": instance.state,
                "source": "model_signal_fallback"
            }
        )
    else:
        prev_state = getattr(instance, '_previous_state', None)
        if prev_state and prev_state != instance.state:
            AuditLog.objects.create(
                report=instance,
                action=f"STATE_TRANSITION_{prev_state.upper()}_TO_{instance.state.upper()}",
                details={
                    "previous_state": prev_state,
                    "new_state": instance.state,
                    "reference_number": instance.reference_number,
                    "source": "model_signal_fallback"
                }
            )
