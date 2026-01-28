import os
import json
import jwt
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

# Initialize Firebase Admin ONLY ONCE
if not firebase_admin._apps:
    use_emulator = os.getenv("USE_FIREBASE_EMULATOR", "false").lower() == "true"

    if use_emulator:
        # Emulator / local dev
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    else:
        # Production (Render)
        service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON not set")

        cred = credentials.Certificate(json.loads(service_account_json))
        firebase_admin.initialize_app(cred)


def verify_firebase_token(id_token):
    """
    Verifies Firebase ID token.
    """
    use_emulator = os.getenv("USE_FIREBASE_EMULATOR", "false").lower() == "true"

    if use_emulator:
        # DEV ONLY: emulator tokens are unsigned
        return jwt.decode(id_token, options={"verify_signature": False})

    # PROD: real Firebase verification
    return firebase_auth.verify_id_token(id_token)
