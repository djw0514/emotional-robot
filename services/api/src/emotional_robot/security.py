import hashlib
import secrets

from sqlalchemy import select

from .models import User


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_user(session, name: str) -> tuple[User, str]:
    token = secrets.token_urlsafe(32)
    user = User(name=name, token_hash=token_digest(token))
    session.add(user)
    session.flush()
    return user, token


def seed_demo(session, token: str):
    digest = token_digest(token)
    if not session.scalar(select(User).where(User.token_hash == digest)):
        session.add(User(name="本地体验用户", token_hash=digest, is_demo=True))
