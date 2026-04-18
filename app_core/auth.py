import firebase_admin
from firebase_admin import auth
from fastapi import Header, HTTPException
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Initialize Firebase Admin SDK
firebase_app = None
try:
    firebase_app = firebase_admin.get_app()
except ValueError:
    from app_core.config import config

    # Use the Firebase-Specific Project ID for Authentication
    firebase_id = config.get_firebase_config().get("project_id")
    firebase_app = firebase_admin.initialize_app(options={"projectId": firebase_id})
    logger.info(f"Firebase Admin initialized for Auth Project: {firebase_id}")


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
        from app_core.utils import access_secret_version
        from app_core.config import config

        # Verify the ID token
        decoded_token = auth.verify_id_token(
            id_token, check_revoked=False, app=firebase_app
        )
        uid = decoded_token["uid"]
        email = decoded_token.get("email")

        # Security: Check against Authorized Users list
        auth_users_raw = access_secret_version(
            config.secrets.authorized_users_secret_id
        )
        if auth_users_raw:
            authorized_list = [
                u.strip().lower() for u in auth_users_raw.split(",") if u.strip()
            ]
            # Check by email (preferred) or UID
            identifier = email.lower() if email else uid
            if identifier not in authorized_list:
                logger.warning(f"Unauthorized access attempt by {identifier}")
                raise HTTPException(
                    status_code=403,
                    detail="Access denied. Your account is not on the authorized list.",
                )

        logger.info(f"Access granted to authorized user: {email or uid}")
        return uid
    except auth.ExpiredIdTokenError:
        logger.error("Firebase ID Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except auth.RevokedIdTokenError:
        logger.error("Firebase ID Token revoked")
        raise HTTPException(status_code=401, detail="Token revoked")
    except auth.InvalidIdTokenError as e:
        logger.error(f"INVALID TOKEN ERROR: {str(e)}")
        # Try to decode it unverified just to see the project ID it claims to be for
        try:
            from jose import jwt

            unverified_claims = jwt.get_unverified_claims(id_token)
            logger.error(f"Token claims project: {unverified_claims.get('aud')}")
            logger.error(f"Backend expects project: {firebase_app.project_id}")
        except Exception as decode_err:
            logger.error(f"Could not even decode token: {decode_err}")

        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"AUTHENTICATION FAILED (Unexpected): {str(e)}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
