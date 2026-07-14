from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from fsm.models import WorkActivity


TWO_PLACES = Decimal('0.01')


def close_activity(activity, location, ended_at=None, note=''):
    if not activity or activity.ended_at:
        return activity
    lat, lng, accuracy = location
    activity.ended_at = ended_at or timezone.now()
    activity.end_lat = lat
    activity.end_lng = lng
    activity.end_accuracy = accuracy
    if note:
        activity.note = '\n'.join(filter(None, [activity.note, note]))
    activity.save(update_fields=['ended_at', 'end_lat', 'end_lng', 'end_accuracy', 'note'])
    return activity


def start_activity(*, worker, workspace, activity_type, location, job=None, assignment=None, field_shift=None, material_run=None, is_paid=True, note='', started_at=None):
    lat, lng, accuracy = location
    return WorkActivity.objects.create(
        workspace=workspace,
        worker=worker,
        job=job,
        assignment=assignment,
        field_shift=field_shift,
        material_run=material_run,
        activity_type=activity_type,
        is_paid=is_paid,
        started_at=started_at or timezone.now(),
        start_lat=lat,
        start_lng=lng,
        start_accuracy=accuracy,
        note=note,
    )


def active_activity(worker):
    return WorkActivity.objects.filter(worker=worker, ended_at__isnull=True).select_related(
        'job', 'assignment', 'workspace', 'material_run'
    ).order_by('-started_at', '-id').first()


def activity_ledger(activities, now=None):
    now = now or timezone.now()
    rows = []
    workspace_totals = defaultdict(lambda: {'paid_seconds': 0, 'unpaid_seconds': 0, 'cost': Decimal('0'), 'mileage': Decimal('0')})
    material_run_ids = set()
    paid_seconds = 0
    unpaid_seconds = 0
    for activity in activities:
        end = activity.ended_at or now
        seconds = max(int((end - activity.started_at).total_seconds()), 0)
        hours = (Decimal(seconds) / Decimal('3600')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        rows.append({'activity': activity, 'seconds': seconds, 'hours': hours, 'is_open': activity.ended_at is None})
        bucket = workspace_totals[activity.workspace_id]
        bucket['workspace'] = activity.workspace
        if activity.is_paid:
            paid_seconds += seconds
            bucket['paid_seconds'] += seconds
        else:
            unpaid_seconds += seconds
            bucket['unpaid_seconds'] += seconds
        if activity.material_run_id and activity.material_run_id not in material_run_ids:
            material_run_ids.add(activity.material_run_id)
            bucket['cost'] += activity.material_run.material_cost
            bucket['mileage'] += activity.material_run.mileage

    def hours(value):
        return (Decimal(value) / Decimal('3600')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    summaries = []
    for bucket in workspace_totals.values():
        summaries.append({
            'workspace': bucket['workspace'],
            'paid_hours': hours(bucket['paid_seconds']),
            'unpaid_hours': hours(bucket['unpaid_seconds']),
            'material_cost': bucket['cost'].quantize(TWO_PLACES),
            'mileage': bucket['mileage'].quantize(TWO_PLACES),
        })
    summaries.sort(key=lambda item: item['paid_hours'], reverse=True)
    max_paid = max((item['paid_hours'] for item in summaries), default=Decimal('0'))
    for item in summaries:
        item['width_percent'] = int(item['paid_hours'] / max_paid * 100) if max_paid else 0
    return {
        'rows': rows,
        'workspace_summaries': summaries,
        'paid_hours': hours(paid_seconds),
        'unpaid_hours': hours(unpaid_seconds),
        'material_cost': sum((item['material_cost'] for item in summaries), Decimal('0')).quantize(TWO_PLACES),
        'mileage': sum((item['mileage'] for item in summaries), Decimal('0')).quantize(TWO_PLACES),
        'active_count': sum(1 for row in rows if row['is_open']),
    }
