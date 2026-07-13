import json

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import UserPasskeyCredential


def _rp(request):
    rp_id = getattr(settings, 'PASSKEY_RP_ID', '') or request.get_host().split(':')[0]
    origin = getattr(settings, 'PASSKEY_ORIGIN', '') or request.build_absolute_uri('/').rstrip('/')
    return rp_id, origin


def _json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


@login_required
@require_POST
def passkey_registration_options(request):
    rp_id, _ = _rp(request)
    credentials = request.user.passkey_credentials.all()
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name='Bratelus Field',
        user_id=str(request.user.pk).encode(),
        user_name=request.user.email or request.user.username,
        user_display_name=request.user.get_full_name() or request.user.username,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(item.credential_id)) for item in credentials],
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    payload = json.loads(options_to_json(options))
    request.session['passkey_registration_challenge'] = payload['challenge']
    return JsonResponse(payload)


@login_required
@require_POST
def passkey_registration_verify(request):
    challenge = request.session.pop('passkey_registration_challenge', None)
    if not challenge:
        return JsonResponse({'error': 'Passkey setup expired. Start again.'}, status=400)
    rp_id, origin = _rp(request)
    credential = _json_body(request)
    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception as exc:
        return JsonResponse({'error': f'Passkey could not be verified: {exc}'}, status=400)
    transports = credential.get('response', {}).get('transports', [])
    UserPasskeyCredential.objects.update_or_create(
        credential_id=verification.credential_id,
        defaults={
            'user': request.user,
            'public_key': verification.credential_public_key,
            'sign_count': verification.sign_count,
            'transports': transports,
            'device_type': str(verification.credential_device_type),
            'backed_up': verification.credential_backed_up,
        },
    )
    return JsonResponse({'message': 'Face ID passkey is ready.'})


@require_POST
def passkey_authentication_options(request):
    identifier = _json_body(request).get('username', '').strip()
    User = get_user_model()
    user = User.objects.filter(username__iexact=identifier, is_active=True).first()
    if not user:
        user = User.objects.filter(email__iexact=identifier, is_active=True).first()
    credentials = list(user.passkey_credentials.all()) if user else []
    if not credentials:
        return JsonResponse({'error': 'No Face ID passkey is enrolled for this login.'}, status=400)
    rp_id, _ = _rp(request)
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=bytes(item.credential_id), transports=item.transports) for item in credentials],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    payload = json.loads(options_to_json(options))
    request.session['passkey_authentication_challenge'] = payload['challenge']
    request.session['passkey_authentication_user_id'] = user.pk
    return JsonResponse(payload)


@require_POST
def passkey_authentication_verify(request):
    challenge = request.session.pop('passkey_authentication_challenge', None)
    user_id = request.session.pop('passkey_authentication_user_id', None)
    if not challenge or not user_id:
        return JsonResponse({'error': 'Face ID request expired. Start again.'}, status=400)
    credential = _json_body(request)
    try:
        credential_id = base64url_to_bytes(credential.get('id', ''))
        stored = UserPasskeyCredential.objects.select_related('user').get(credential_id=credential_id, user_id=user_id)
        rp_id, origin = _rp(request)
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(stored.public_key),
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        return JsonResponse({'error': f'Face ID verification failed: {exc}'}, status=400)
    stored.sign_count = verification.new_sign_count
    stored.last_used_at = timezone.now()
    stored.save(update_fields=['sign_count', 'last_used_at'])
    login(request, stored.user, backend='django.contrib.auth.backends.ModelBackend')
    return JsonResponse({'redirect': '/field/'})
