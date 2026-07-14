from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


MONEY = Decimal('0.01')


def assignment_time_and_earnings(assignment, now=None):
    now = now or timezone.now()
    start = assignment.clocked_in_at
    end = assignment.clocked_out_at or assignment.work_completed_at
    is_open = bool(start and not end)
    effective_end = end or (now if start else None)
    seconds = max((effective_end - start).total_seconds(), 0) if start and effective_end else 0
    hours = (Decimal(str(seconds)) / Decimal('3600')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if assignment.pay_type == 'hourly':
        earnings = assignment.pay_rate * hours
    else:
        earnings = assignment.pay_rate if start else Decimal('0')
    earnings = (earnings + assignment.tip_split).quantize(MONEY, rounding=ROUND_HALF_UP)
    return {
        'hours': hours,
        'earnings': earnings,
        'is_open': is_open,
        'started_at': start,
        'ended_at': end,
    }


def workforce_ledger(assignments):
    rows = []
    workspace_totals = defaultdict(lambda: {'hours': Decimal('0'), 'earnings': Decimal('0'), 'jobs': set()})
    total_hours = Decimal('0')
    total_earnings = Decimal('0')
    for assignment in assignments:
        values = assignment_time_and_earnings(assignment)
        workspace = assignment.job.organization
        row = {
            'assignment': assignment,
            'workspace': workspace,
            **values,
        }
        rows.append(row)
        total_hours += values['hours']
        total_earnings += values['earnings']
        bucket = workspace_totals[workspace.id]
        bucket['workspace'] = workspace
        bucket['hours'] += values['hours']
        bucket['earnings'] += values['earnings']
        bucket['jobs'].add(assignment.job_id)

    summaries = []
    for bucket in workspace_totals.values():
        summaries.append({
            'workspace': bucket['workspace'],
            'hours': bucket['hours'].quantize(Decimal('0.01')),
            'earnings': bucket['earnings'].quantize(MONEY),
            'jobs': len(bucket['jobs']),
        })
    summaries.sort(key=lambda item: item['hours'], reverse=True)
    max_hours = max((item['hours'] for item in summaries), default=Decimal('0'))
    for item in summaries:
        item['width_percent'] = int((item['hours'] / max_hours * 100)) if max_hours else 0
    return {
        'rows': rows,
        'workspace_summaries': summaries,
        'total_hours': total_hours.quantize(Decimal('0.01')),
        'total_earnings': total_earnings.quantize(MONEY),
        'job_count': len({row['assignment'].job_id for row in rows}),
    }
