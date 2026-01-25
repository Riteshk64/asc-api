import os
import jwt
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

# Initialize Firebase Admin ONLY ONCE
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)


def verify_firebase_token(id_token):
    """
    Verifies Firebase ID token.
    - In DEV (emulator): decode without signature verification
    - In PROD: verify normally using Firebase Admin SDK
    """

    use_emulator = os.getenv("USE_FIREBASE_EMULATOR", "false").lower() == "true"

    if use_emulator:
        # DEV ONLY: emulator tokens are unsigned
        decoded_token = jwt.decode(
            id_token,
            options={"verify_signature": False}
        )
        return decoded_token

    # PROD: real verification
    decoded_token = firebase_auth.verify_id_token(id_token)
    return decoded_token
