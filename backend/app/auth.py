import hashlib
import hmac
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import AuthSession, User, now

hasher = PasswordHasher()


def token_hash(token: str) -> str:
    return hmac.new(
        settings.secret.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


def verify_password(password: str, stored: str) -> bool:
    try:
        return hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("lab_session", "")
    session = db.get(AuthSession, token_hash(token)) if token else None
    user = (
        db.get(User, session.user_id)
        if session and session.expires_at > now()
        else None
    )
    if not user or not user.enabled:
        raise HTTPException(401, "请先登录")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "ADMIN":
        raise HTTPException(403, "需要管理员权限")
    return user
