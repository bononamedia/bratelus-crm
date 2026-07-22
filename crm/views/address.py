import re

import zipcodes
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@login_required
@require_GET
def postal_code_lookup_view(request):
    postal_code = re.sub(r'[^0-9-]', '', request.GET.get('postal_code', '').strip())
    if len(postal_code) not in (5, 10):
        return JsonResponse({'detail': 'Enter a valid 5-digit or ZIP+4 postal code.'}, status=400)
    try:
        matches = zipcodes.matching(postal_code)
    except (TypeError, ValueError):
        matches = []
    active = next((item for item in matches if item.get('active')), matches[0] if matches else None)
    if not active:
        return JsonResponse({'detail': 'Postal code not found.'}, status=404)
    return JsonResponse({
        'postal_code': active['zip_code'],
        'city': active['city'],
        'state': active['state'],
        'country': 'United States',
    })
