import firebase_admin
from firebase_admin import auth
from fastapi import Header, HTTPException
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Initialize Firebase Admin SDK
try:
    # This will use default application credentials (e.g. from GCP metadata or GOOGLE_APPLICATION_CREDENTIALS)
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency to verify the Firebase ID Token.
    Returns the Firebase UID if valid, otherwise raises 401.
    """
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Missing or invalid Authorization header")
        raise HTTPException(
            status_code=401, detail="Missing or invalid authentication token"
        )

    id_token = authorization.split("Bearer ")[1]

    try:
        # Verify the ID token while checking if the token is revoked by passing check_revoked=True.
        decoded_token = auth.verify_id_token(id_token, check_revoked=True)
        uid = decoded_token["uid"]
        return uid
    except auth.ExpiredIdTokenError:
        logger.error("Firebase ID Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except auth.RevokedIdTokenError:
        logger.error("Firebase ID Token revoked")
        raise HTTPException(status_code=401, detail="Token revoked")
    except auth.InvalidIdTokenError:
        logger.error("Invalid Firebase ID Token")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Error verifying Firebase token: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed")
