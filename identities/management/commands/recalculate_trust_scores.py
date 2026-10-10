
# identities/management/commands/recalculate_trust_scores.py
"""
Management command to backfill TrustScore for all existing SubjectEntity records.

Usage:
    python manage.py recalculate_trust_scores
    python manage.py recalculate_trust_scores --subject-id 42
"""

from django.core.management.base import BaseCommand
from identities.models import SubjectEntity
from identities.trust_score import recalculate_trust_score


class Command(BaseCommand):
    help = 'Recalculate TrustScore for all SubjectEntity records (or a single one).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--subject-id',
            type=int,
            default=None,
            help='Recalculate only this SubjectEntity pk.',
        )

    def handle(self, *args, **options):
        subject_id = options.get('subject_id')

        if subject_id:
            queryset = SubjectEntity.objects.filter(pk=subject_id)
        else:
            queryset = SubjectEntity.objects.all()

        total = queryset.count()
        self.stdout.write(f"Recalculating TrustScore for {total} subject(s)...")

        success = 0
        failed  = 0

        for subject in queryset.iterator():
            try:
                ts = recalculate_trust_score(subject.id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [{subject.id}] {subject.name} → {ts.score}/1000 ({ts.label})"
                    )
                )
                success += 1
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"  [{subject.id}] {subject.name} → FAILED: {e}")
                )
                failed += 1

        self.stdout.write(f"\nDone. Success: {success}  Failed: {failed}")

        