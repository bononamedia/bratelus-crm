from django.core import signing


EMAIL_VERIFICATION_SALT = 'bratelus-email-verification-v1'


def email_verification_token(user):
    return signing.dumps(
        {'user_id': user.pk, 'email': user.email.lower()},
        salt=EMAIL_VERIFICATION_SALT,
        compress=True,
    )


def read_email_verification_token(token, max_age):
    return signing.loads(token, salt=EMAIL_VERIFICATION_SALT, max_age=max_age)
