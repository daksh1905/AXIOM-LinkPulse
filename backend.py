"""LinkPulse URL shortener, QR studio API, and governance console.

Run locally with: python backend.py
Secrets belong in .env; never put them in browser JavaScript.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from functools import wraps
import hashlib
import hmac
import os
import re
import secrets
import string
import threading
import time
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, create_engine, or_, inspect, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from user_agents import parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'links.db')}").strip()
# Render/hosted PostgreSQL providers may supply postgres:// or postgresql:// URLs.
# The requirements file includes psycopg 3, so use its SQLAlchemy dialect explicitly.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

API_KEY_SECRET = os.getenv("LINKPULSE_API_KEY", "")  # Legacy env variable; never exposed to browser.
ADMIN_KEY_SECRET = os.getenv("ADMIN_MASTER_KEY", "")
FLASK_SECRET = os.getenv("FLASK_SECRET_KEY", "")
IS_PRODUCTION = os.getenv("FLASK_ENV", "").lower() == "production" or os.getenv("APP_ENV", "").lower() == "production"
if not FLASK_SECRET:
    FLASK_SECRET = secrets.token_urlsafe(32)
    if IS_PRODUCTION:
        raise RuntimeError("FLASK_SECRET_KEY must be configured in production.")
if not ADMIN_KEY_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError("ADMIN_MASTER_KEY must be configured in production.")
    ADMIN_KEY_SECRET = "local-dev-change-this-admin-key"
    print("[LinkPulse] WARNING: using local development admin key. Set ADMIN_MASTER_KEY in .env.")

engine_kwargs = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {"pool_pre_ping": True}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String(20), default="user", nullable=False)
    email_verified = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailOTPModel(Base):
    __tablename__ = "email_otp_verifications"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LinkModel(Base):
    __tablename__ = "links"
    id = Column(Integer, primary_key=True, index=True)
    original_url = Column(String, nullable=False)
    short_code = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, default="Campaign Link")
    password_hash = Column(String, nullable=True)
    click_limit = Column(Integer, nullable=True)
    clicks_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    owner_key_hash = Column(String(64), nullable=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    clicks = relationship("ClickEventModel", back_populates="link", cascade="all, delete-orphan")


class ClickEventModel(Base):
    __tablename__ = "click_events"
    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("links.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    device_type = Column(String, default="Desktop")
    browser = Column(String, default="Unknown")
    is_bot = Column(Boolean, default=False)
    referrer = Column(String(500), default="Direct / unknown")
    link = relationship("LinkModel", back_populates="clicks")


class BlockedDomainModel(Base):
    __tablename__ = "blocked_domains"
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, unique=True, nullable=False)
    reason = Column(String, default="Known abusive or malicious domain")
    added_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)
# Backwards-compatible migration for existing SQLite databases.
if DATABASE_URL.startswith("sqlite"):
    _inspector = inspect(engine)
    if "users" in _inspector.get_table_names():
        _user_columns = {column["name"] for column in _inspector.get_columns("users")}
        if "email_verified" not in _user_columns:
            with engine.begin() as _conn:
                # Existing accounts predate OTP verification; preserve their access.
                _conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1"))
    _inspector = inspect(engine)
    if "links" in _inspector.get_table_names():
        _columns = {column["name"] for column in _inspector.get_columns("links")}
        with engine.begin() as _conn:
            if "owner_key_hash" not in _columns:
                _conn.execute(text("ALTER TABLE links ADD COLUMN owner_key_hash VARCHAR(64)"))
            if "owner_user_id" not in _columns:
                _conn.execute(text("ALTER TABLE links ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"))
    if "click_events" in _inspector.get_table_names():
        _click_columns = {column["name"] for column in _inspector.get_columns("click_events")}
        if "referrer" not in _click_columns:
            with engine.begin() as _conn:
                _conn.execute(text("ALTER TABLE click_events ADD COLUMN referrer VARCHAR(500) DEFAULT 'Direct / unknown'"))
else:
    # Add columns introduced by LinkPulse upgrades when using PostgreSQL or another
    # SQLAlchemy database. create_all() creates tables, but does not alter old ones.
    _inspector = inspect(engine)
    _table_names = set(_inspector.get_table_names())
    with engine.begin() as _conn:
        if "users" in _table_names:
            _user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
            if "email_verified" not in _user_columns:
                _conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE"))
        if "links" in _table_names:
            _link_columns = {column["name"] for column in inspect(engine).get_columns("links")}
            if "owner_key_hash" not in _link_columns:
                _conn.execute(text("ALTER TABLE links ADD COLUMN owner_key_hash VARCHAR(64)"))
            if "owner_user_id" not in _link_columns:
                _conn.execute(text("ALTER TABLE links ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"))
        if "click_events" in _table_names:
            _click_columns = {column["name"] for column in inspect(engine).get_columns("click_events")}
            if "referrer" not in _click_columns:
                _conn.execute(text("ALTER TABLE click_events ADD COLUMN referrer VARCHAR(500) DEFAULT 'Direct / unknown'"))
with SessionLocal() as db:
    if not db.query(BlockedDomainModel).first():
        db.add_all([
            BlockedDomainModel(domain="malware-example.com", reason="Phishing threat detected"),
            BlockedDomainModel(domain="scam-portal.net", reason="Prohibited deceptive site"),
        ])
        db.commit()

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
app.secret_key = FLASK_SECRET
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 4,
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)

# A lightweight in-process creation throttle; use a shared store for multi-worker deployments.
_rate_lock = threading.Lock()
_create_attempts: dict[str, list[float]] = {}

def limited(ip: str, limit: int = 30, window: int = 60) -> bool:
    now = time.time()
    with _rate_lock:
        attempts = [t for t in _create_attempts.get(ip, []) if now - t < window]
        if len(attempts) >= limit:
            _create_attempts[ip] = attempts
            return True
        attempts.append(now)
        _create_attempts[ip] = attempts
        return False

@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store" if request.path.startswith("/api/") else "no-cache")
    # Same-origin only: the frontend and API are served by this Flask app.
    if request.headers.get("Origin") and request.host_url.rstrip("/") == request.headers.get("Origin", "").rstrip("/"):
        response.headers["Access-Control-Allow-Origin"] = request.headers["Origin"]
    response.headers["Vary"] = "Origin"
    return response


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not (session.get("is_admin") or session.get("role") == "admin"):
            return jsonify({"detail": "Admin authentication required."}), 401
        return fn(*args, **kwargs)
    return wrapped


def utcnow():
    return datetime.utcnow()


def parse_expiry(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        if dt <= utcnow():
            raise ValueError("Expiry must be in the future.")
        return dt
    except ValueError as exc:
        if "future" in str(exc):
            raise
        raise ValueError("Invalid expiry date/time.") from exc


def normalise_destination(raw):
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("Destination URL is required.")
    if len(raw) > 2048:
        raise ValueError("Destination URL is too long.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a valid http or https URL.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        _ = parsed.port  # Force invalid-port validation.
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Malformed destination URL.") from exc
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local or internal destinations are not allowed.")
    if not ("." in host or host == "127.0.0.1"):
        raise ValueError("Enter a fully qualified domain name.")
    return raw, host


def is_blocked(host: str, db) -> BlockedDomainModel | None:
    domains = db.query(BlockedDomainModel).all()
    for item in domains:
        blocked = item.domain.lower().strip().rstrip(".")
        if host == blocked or host.endswith("." + blocked):
            return item
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 310_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    # Accept the older unsalted SHA-256 format so existing local database entries remain usable.
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, salt, digest = stored.split("$", 2)
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 310_000).hex()
            return hmac.compare_digest(candidate, digest)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(hashlib.sha256(password.encode("utf-8")).hexdigest(), stored)


def generate_base62(length=6):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def log_click(db, link):
    ua_string = request.headers.get("User-Agent", "")
    ua = parse(ua_string)
    is_bot = bool(ua.is_bot or re.search(r"bot|crawl|spider|slurp|curl|wget|preview", ua_string, re.I))
    device = "Mobile" if ua.is_mobile else ("Tablet" if ua.is_tablet else "Desktop")
    browser = ua.browser.family if ua.browser.family and ua.browser.family != "Other" else "Standard Web"
    ref = request.headers.get("Referer", "").strip()
    try:
        referrer = (urlparse(ref).netloc or "Direct / unknown")[:500] if ref else "Direct / unknown"
    except Exception:
        referrer = "Direct / unknown"
    db.add(ClickEventModel(link_id=link.id, device_type=device, browser=browser, is_bot=is_bot, referrer=referrer, timestamp=utcnow()))
    link.clicks_count = (link.clicks_count or 0) + 1
    db.commit()


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.get("/admin")
def admin_page():
    return send_from_directory(STATIC_DIR, "admin.html")

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "LinkPulse"})


def owner_key_digest(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def owner_key_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        raw_key = request.headers.get("X-Owner-Key", "").strip()
        is_user = session.get("role") == "user" and session.get("user_id")
        if not is_user and not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw_key):
            return jsonify({"detail": "Please sign in or refresh your browser session."}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.post("/api/links/create")
def create_link():
    owner_key = request.headers.get("X-Owner-Key", "").strip()
    user_id = session.get("user_id") if session.get("role") == "user" else None
    if not user_id and not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", owner_key):
        return jsonify({"detail": "Please refresh the page or sign in to create a link."}), 401
    if limited(request.remote_addr or "unknown"):
        return jsonify({"detail": "Too many link creation attempts. Please wait a minute and try again."}), 429
    data = request.get_json(silent=True) or {}
    try:
        url, host = normalise_destination(data.get("original_url"))
        title = str(data.get("title") or "Campaign Link").strip()[:120] or "Campaign Link"
        alias = str(data.get("custom_alias") or "").strip()
        if alias and not re.fullmatch(r"[a-zA-Z0-9_-]{3,40}", alias):
            return jsonify({"detail": "Alias must be 3–40 characters and use only letters, numbers, hyphens, or underscores."}), 400
        password = str(data.get("password") or "").strip()
        if password and len(password) < 4:
            return jsonify({"detail": "Protected-link passwords must be at least 4 characters."}), 400
        expiry = parse_expiry(data.get("expires_at"))
        limit_value = data.get("click_limit")
        limit = int(limit_value) if limit_value not in (None, "", 0, "0") else None
        if limit is not None and not 1 <= limit <= 1_000_000:
            return jsonify({"detail": "Click limit must be between 1 and 1,000,000."}), 400
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify({"detail": str(exc) or "Invalid link settings."}), 400

    db = SessionLocal()
    try:
        blocked = is_blocked(host, db)
        if blocked:
            return jsonify({"detail": f"Safety rule: {host} is blocked ({blocked.reason})."}), 400
        if alias and db.query(LinkModel).filter(LinkModel.short_code == alias).first():
            return jsonify({"detail": f"Alias '{alias}' is already allocated."}), 409
        code = alias
        if not code:
            for _ in range(20):
                candidate = generate_base62()
                if not db.query(LinkModel).filter(LinkModel.short_code == candidate).first():
                    code = candidate
                    break
            if not code:
                return jsonify({"detail": "Could not allocate a short code. Please try again."}), 503
        new_link = LinkModel(
            original_url=url, short_code=code, title=title,
            password_hash=hash_password(password) if password else None,
            click_limit=limit, expires_at=expiry, is_active=True,
            owner_key_hash=owner_key_digest(owner_key) if not user_id else None,
            owner_user_id=user_id,
        )
        db.add(new_link)
        db.commit()
        db.refresh(new_link)
        return jsonify({
            "status": "success", "short_code": new_link.short_code,
            "original_url": new_link.original_url, "title": new_link.title,
            "has_password": bool(new_link.password_hash), "click_limit": new_link.click_limit,
            "expires_at": new_link.expires_at.isoformat() if new_link.expires_at else None,
        }), 201
    finally:
        db.close()


@app.get("/api/links/list")
def list_links():
    owner_key = request.headers.get("X-Owner-Key", "").strip()
    user_id = session.get("user_id") if session.get("role") == "user" else None
    if not user_id and not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", owner_key):
        return jsonify({"detail": "Your browser session is missing. Refresh the page and try again."}), 401
    db = SessionLocal()
    try:
        if user_id:
            links = db.query(LinkModel).filter(LinkModel.owner_user_id == user_id).order_by(LinkModel.created_at.desc()).limit(100).all()
        else:
            digest = owner_key_digest(owner_key)
            links = db.query(LinkModel).filter(LinkModel.owner_key_hash == digest, LinkModel.owner_user_id.is_(None)).order_by(LinkModel.created_at.desc()).limit(100).all()
        return jsonify({"links": [{
            "id": l.id, "title": l.title, "short_code": l.short_code,
            "original_url": l.original_url, "clicks_count": l.clicks_count or 0,
            "click_limit": l.click_limit, "has_password": bool(l.password_hash),
            "is_active": bool(l.is_active), "expires_at": l.expires_at.isoformat() if l.expires_at else None,
            "created_at": l.created_at.strftime("%b %d, %Y %H:%M") if l.created_at else "—",
            "owner_type": "account" if l.owner_user_id else "anonymous",
        } for l in links]})
    finally:
        db.close()


@app.get("/api/admin/users/list")
@admin_required
def admin_list_users():
    db = SessionLocal()
    try:
        users = db.query(UserModel).order_by(UserModel.created_at.desc()).limit(500).all()
        return jsonify({"users": [{"id": u.id, "email": u.email, "role": u.role,
            "created_at": u.created_at.strftime("%b %d, %Y %H:%M") if u.created_at else "—",
            "links_count": db.query(LinkModel).filter(LinkModel.owner_user_id == u.id).count()} for u in users]})
    finally:
        db.close()


@app.get("/api/admin/links/list")
@admin_required
def admin_list_links():
    db = SessionLocal()
    try:
        links = db.query(LinkModel).order_by(LinkModel.created_at.desc()).limit(500).all()
        return jsonify({"links": [{
            "id": l.id, "title": l.title, "short_code": l.short_code,
            "original_url": l.original_url, "clicks_count": l.clicks_count or 0,
            "click_limit": l.click_limit, "has_password": bool(l.password_hash),
            "is_active": bool(l.is_active), "expires_at": l.expires_at.isoformat() if l.expires_at else None,
            "created_at": l.created_at.strftime("%b %d, %Y %H:%M") if l.created_at else "—",
        } for l in links]})
    finally:
        db.close()


@app.get("/api/links/<code>/analytics")
def analytics(code):
    db = SessionLocal()
    try:
        link = db.query(LinkModel).filter(LinkModel.short_code == code).first()
        if not link:
            return jsonify({"detail": "Link not found."}), 404
        is_admin = bool(session.get("is_admin") or session.get("role") == "admin")
        is_owner = False
        if session.get("role") == "user" and session.get("user_id"):
            is_owner = link.owner_user_id == session.get("user_id")
        if not is_owner and not is_admin:
            raw_key = request.headers.get("X-Owner-Key", "").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw_key):
                is_owner = bool(link.owner_key_hash and hmac.compare_digest(link.owner_key_hash, owner_key_digest(raw_key)))
        if not (is_owner or is_admin):
            return jsonify({"detail": "Sign in or use the browser that owns this link to view its analytics."}), 403
        all_events = db.query(ClickEventModel).filter(ClickEventModel.link_id == link.id).all()
        events = sorted(all_events, key=lambda e: e.timestamp or datetime.min, reverse=True)[:100]
        devices, browsers, bot_hits = {"Desktop": 0, "Mobile": 0, "Tablet": 0}, {}, 0
        for event in all_events:
            if event.is_bot:
                bot_hits += 1
                continue
            devices[event.device_type] = devices.get(event.device_type, 0) + 1
            browsers[event.browser] = browsers.get(event.browser, 0) + 1
        return jsonify({"title": link.title, "short_code": link.short_code,
            "original_url": link.original_url, "total_clicks": link.clicks_count or 0,
            "clean_human_clicks": sum(1 for e in all_events if not e.is_bot),
            "filtered_bots": sum(1 for e in all_events if e.is_bot), "devices": devices, "browsers": browsers,
            "recent_clicks": [{"time": e.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"), "device": e.device_type,
                "browser": e.browser, "referrer": e.referrer or "Direct / unknown", "is_bot": bool(e.is_bot)} for e in events]})
    finally:
        db.close()


def otp_code_digest(email: str, code: str) -> str:
    return hmac.new(FLASK_SECRET.encode("utf-8"), f"{email}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


class BrevoEmailError(RuntimeError):
    """Safe, user-independent error raised when Brevo rejects an email request."""


def send_verification_email(to_email: str, code: str) -> None:
    """Send an OTP using Brevo's HTTPS API (no outbound SMTP port required)."""
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    sender = os.getenv("MAIL_FROM_EMAIL", "").strip()
    sender_name = os.getenv("MAIL_FROM_NAME", "LinkPulse").strip() or "LinkPulse"
    if not api_key or not sender:
        raise BrevoEmailError("Email verification is not configured. Set BREVO_API_KEY and MAIL_FROM_EMAIL.")

    text_body = (
        f"Your LinkPulse verification code is {code}.\n\n"
        "It expires in 10 minutes and can be used only once. "
        "If you did not request this code, ignore this email."
    )
    html_body = (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;color:#2b1e16\">"
        "<h2>Your LinkPulse verification code</h2>"
        f"<p style=\"font-size:28px;font-weight:700;letter-spacing:6px\">{code}</p>"
        "<p>This code expires in 10 minutes and can be used only once.</p>"
        "<p>If you did not request this code, you can ignore this email.</p>"
        "</body></html>"
    )
    payload = {
        "sender": {"name": sender_name, "email": sender},
        "to": [{"email": to_email}],
        "subject": "Your LinkPulse verification code",
        "textContent": text_body,
        "htmlContent": html_body,
    }
    req = Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise BrevoEmailError(f"Brevo returned HTTP {response.status}.")
    except HTTPError as exc:
        # Do not log or return raw provider responses; they may contain sensitive details.
        raise BrevoEmailError(f"Brevo rejected the email request (HTTP {exc.code}).") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise BrevoEmailError("Could not reach Brevo over HTTPS. Check the network and try again.") from None


@app.post("/api/auth/register")
def register_user():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 320:
        return jsonify({"detail": "Enter a valid email address."}), 400
    if len(password) < 10 or len(password) > 128:
        return jsonify({"detail": "Password must be between 10 and 128 characters."}), 400
    if limited("register:" + (request.remote_addr or "unknown"), limit=8, window=3600):
        return jsonify({"detail": "Too many account-creation attempts. Please try again later."}), 429
    if limited("otp-send-ip:" + (request.remote_addr or "unknown"), limit=5, window=900):
        return jsonify({"detail": "Too many verification emails requested. Please wait 15 minutes."}), 429
    db = SessionLocal()
    try:
        if db.query(UserModel).filter(UserModel.email == email).first():
            return jsonify({"detail": "An account with this email already exists. Please sign in."}), 409
        if limited("otp-send-email:" + email, limit=3, window=900):
            return jsonify({"detail": "A verification email was sent recently. Please wait before requesting another."}), 429
        code = f"{secrets.randbelow(1_000_000):06d}"
        pending = db.query(EmailOTPModel).filter(EmailOTPModel.email == email).first()
        if pending:
            pending.password_hash = hash_password(password)
            pending.code_hash = otp_code_digest(email, code)
            pending.expires_at = datetime.utcnow() + timedelta(minutes=10)
            pending.attempts = 0
            pending.created_at = datetime.utcnow()
        else:
            pending = EmailOTPModel(email=email, password_hash=hash_password(password),
                code_hash=otp_code_digest(email, code),
                expires_at=datetime.utcnow() + timedelta(minutes=10), attempts=0)
            db.add(pending)
        db.commit()
        try:
            send_verification_email(email, code)
        except Exception as exc:
            db.query(EmailOTPModel).filter(EmailOTPModel.email == email).delete(synchronize_session=False)
            db.commit()
            app.logger.error("Brevo verification email failed: %s", type(exc).__name__)
            return jsonify({"detail": "We could not send the verification email. Check BREVO_API_KEY and that MAIL_FROM_EMAIL is a verified Brevo sender, then try again."}), 503
        return jsonify({"status": "verification_sent", "email": email,
            "message": "We sent a 6-digit verification code. It expires in 10 minutes."}), 200
    finally:
        db.close()


@app.post("/api/auth/verify-email")
def verify_email():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    code = str(data.get("code") or "").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not re.fullmatch(r"\d{6}", code):
        return jsonify({"detail": "Enter the email address and the 6-digit code."}), 400
    if limited("otp-verify:" + (request.remote_addr or "unknown"), limit=20, window=900):
        return jsonify({"detail": "Too many verification attempts. Please wait and try again."}), 429
    db = SessionLocal()
    try:
        pending = db.query(EmailOTPModel).filter(EmailOTPModel.email == email).first()
        if not pending:
            return jsonify({"detail": "No active verification was found. Please start sign-up again."}), 400
        if pending.expires_at < datetime.utcnow():
            db.delete(pending); db.commit()
            return jsonify({"detail": "That code has expired. Please request a new one."}), 400
        if pending.attempts >= 5:
            db.delete(pending); db.commit()
            return jsonify({"detail": "Too many incorrect codes. Please start sign-up again."}), 429
        if not hmac.compare_digest(pending.code_hash, otp_code_digest(email, code)):
            pending.attempts += 1
            db.commit()
            return jsonify({"detail": "That verification code is incorrect."}), 400
        if db.query(UserModel).filter(UserModel.email == email).first():
            db.delete(pending); db.commit()
            return jsonify({"detail": "An account with this email already exists. Please sign in."}), 409
        user = UserModel(email=email, password_hash=pending.password_hash, role="user", email_verified=True)
        db.add(user); db.flush()
        owner_key = request.headers.get("X-Owner-Key", "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", owner_key):
            db.query(LinkModel).filter(LinkModel.owner_key_hash == owner_key_digest(owner_key), LinkModel.owner_user_id.is_(None)).update({"owner_user_id": user.id, "owner_key_hash": None}, synchronize_session=False)
        db.delete(pending)
        db.commit(); db.refresh(user)
        session.clear(); session["user_id"] = user.id; session["email"] = user.email; session["role"] = "user"; session.permanent = True
        return jsonify({"status": "verified", "user": {"email": user.email, "role": user.role}, "redirect": "/"}), 201
    finally:
        db.close()


@app.post("/api/auth/resend-otp")
def resend_otp():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 320:
        return jsonify({"detail": "Enter a valid email address."}), 400
    if limited("otp-resend-ip:" + (request.remote_addr or "unknown"), limit=5, window=900) or limited("otp-resend-email:" + email, limit=3, window=900):
        return jsonify({"detail": "Too many code requests. Please wait before trying again."}), 429
    db = SessionLocal()
    try:
        pending = db.query(EmailOTPModel).filter(EmailOTPModel.email == email).first()
        if not pending:
            return jsonify({"detail": "No active verification was found. Please start sign-up again."}), 400
        code = f"{secrets.randbelow(1_000_000):06d}"
        # Send first; only replace the active code after Brevo accepts the request.
        # This avoids invalidating the previous code when the email API is unavailable.
        try:
            send_verification_email(email, code)
        except Exception as exc:
            app.logger.error("Brevo resend failed: %s", type(exc).__name__)
            return jsonify({"detail": "We could not send another email. Check BREVO_API_KEY and the verified sender, then try again."}), 503
        pending.code_hash = otp_code_digest(email, code)
        pending.expires_at = datetime.utcnow() + timedelta(minutes=10)
        pending.attempts = 0
        pending.created_at = datetime.utcnow()
        db.commit()
        return jsonify({"status": "verification_sent", "message": "A new code has been sent. The previous code is no longer valid."})
    finally:
        db.close()


@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    if not email or not password:
        return jsonify({"detail": "Enter both email/ID and password."}), 400
    if limited("auth:" + (request.remote_addr or "unknown"), limit=12, window=300):
        return jsonify({"detail": "Too many login attempts. Wait a few minutes and try again."}), 429
    # Admin credentials are configured only on the server in .env; never sent to the browser.
    admin_email = os.getenv("ADMIN_LOGIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("ADMIN_LOGIN_PASSWORD", "")
    if admin_email and admin_password and hmac.compare_digest(email, admin_email) and hmac.compare_digest(password, admin_password):
        session.clear(); session["is_admin"] = True; session["user_id"] = None; session["email"] = admin_email; session["role"] = "admin"; session.permanent = True
        return jsonify({"status": "authenticated", "user": {"email": admin_email, "role": "admin"}, "redirect": "/admin"})
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter(UserModel.email == email).first()
        if not user or not check_password(password, user.password_hash):
            return jsonify({"detail": "Invalid email/ID or password."}), 401
        if not user.email_verified:
            return jsonify({"detail": "Please verify your email before signing in."}), 403
        owner_key = request.headers.get("X-Owner-Key", "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", owner_key):
            db.query(LinkModel).filter(LinkModel.owner_key_hash == owner_key_digest(owner_key), LinkModel.owner_user_id.is_(None)).update({LinkModel.owner_user_id: user.id, LinkModel.owner_key_hash: None}, synchronize_session=False)
            db.commit()
        session.clear(); session["user_id"] = user.id; session["email"] = user.email; session["role"] = "user"; session.permanent = True
        return jsonify({"status": "authenticated", "user": {"email": user.email, "role": user.role}, "redirect": "/"})
    finally:
        db.close()


@app.get("/api/auth/session")
def auth_session():
    role = session.get("role")
    return jsonify({"authenticated": role in ("user", "admin") or bool(session.get("is_admin")),
        "user": {"email": session.get("email"), "role": role or ("admin" if session.get("is_admin") else None)},
        "is_admin": bool(session.get("is_admin") or role == "admin")})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"status": "signed_out"})


@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    supplied = str(data.get("key") or "")
    if not hmac.compare_digest(supplied, ADMIN_KEY_SECRET):
        return jsonify({"detail": "Invalid administrator key."}), 401
    session.clear()
    session["is_admin"] = True
    session["role"] = "admin"
    session["email"] = os.getenv("ADMIN_LOGIN_EMAIL", "administrator")
    session.permanent = True
    return jsonify({"status": "authenticated", "redirect": "/admin"})

@app.post("/api/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return jsonify({"status": "signed_out"})

@app.get("/api/admin/session")
def admin_session():
    return jsonify({"authenticated": bool(session.get("is_admin") or session.get("role") == "admin")})

@app.post("/api/admin/toggle/<code>")
@admin_required
def toggle_admin(code):
    db = SessionLocal()
    try:
        link = db.query(LinkModel).filter(LinkModel.short_code == code).first()
        if not link:
            return jsonify({"detail": "Link not found."}), 404
        link.is_active = not link.is_active
        db.commit()
        return jsonify({"short_code": link.short_code, "is_active": link.is_active,
                        "message": f"Link /{code} is now {'active' if link.is_active else 'disabled'}."})
    finally:
        db.close()


@app.post("/api/links/<code>/toggle")
@owner_key_required
def toggle_owner_link(code):
    owner_key = request.headers.get("X-Owner-Key", "").strip()
    db = SessionLocal()
    try:
        if session.get("role") == "user" and session.get("user_id"):
            link = db.query(LinkModel).filter(LinkModel.short_code == code, LinkModel.owner_user_id == session.get("user_id")).first()
        else:
            link = db.query(LinkModel).filter(LinkModel.short_code == code, LinkModel.owner_key_hash == owner_key_digest(owner_key), LinkModel.owner_user_id.is_(None)).first()
        if not link:
            return jsonify({"detail": "Link not found in your links."}), 404
        link.is_active = not link.is_active
        db.commit()
        return jsonify({"short_code": link.short_code, "is_active": bool(link.is_active),
                        "message": f"Your link /{code} is now {'active' if link.is_active else 'paused'}."})
    finally:
        db.close()


@app.delete("/api/links/<code>")
@owner_key_required
def delete_owner_link(code):
    owner_key = request.headers.get("X-Owner-Key", "").strip()
    db = SessionLocal()
    try:
        if session.get("role") == "user" and session.get("user_id"):
            link = db.query(LinkModel).filter(LinkModel.short_code == code, LinkModel.owner_user_id == session.get("user_id")).first()
        else:
            link = db.query(LinkModel).filter(LinkModel.short_code == code, LinkModel.owner_key_hash == owner_key_digest(owner_key), LinkModel.owner_user_id.is_(None)).first()
        if not link:
            return jsonify({"detail": "Link not found in your links."}), 404
        db.query(ClickEventModel).filter(ClickEventModel.link_id == link.id).delete(synchronize_session=False)
        db.delete(link)
        db.commit()
        return jsonify({"message": f"Link /{code} deleted."})
    finally:
        db.close()


@app.delete("/api/admin/links/<code>")
@admin_required
def admin_delete_link(code):
    db = SessionLocal()
    try:
        link = db.query(LinkModel).filter(LinkModel.short_code == code).first()
        if not link:
            return jsonify({"detail": "Link not found."}), 404
        db.query(ClickEventModel).filter(ClickEventModel.link_id == link.id).delete(synchronize_session=False)
        db.delete(link)
        db.commit()
        return jsonify({"message": f"Link /{code} deleted by administrator."})
    finally:
        db.close()

@app.post("/api/links/import-csv")
def import_csv_links():
    """Import up to 100 links from a CSV with original_url,title,custom_alias columns."""
    owner_key = request.headers.get("X-Owner-Key", "").strip()
    user_id = session.get("user_id") if session.get("role") == "user" else None
    if not user_id and not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", owner_key):
        return jsonify({"detail": "Sign in or refresh the browser session before importing."}), 401
    if "file" not in request.files:
        return jsonify({"detail": "Choose a CSV file in the file field."}), 400
    import csv, io
    raw = request.files["file"].read(1_000_001)
    if len(raw) > 1_000_000:
        return jsonify({"detail": "CSV file must be under 1 MB."}), 413
    try:
        text_data = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_data))
        if not reader.fieldnames or "original_url" not in [h.strip().lower() for h in reader.fieldnames]:
            return jsonify({"detail": "CSV needs an original_url column. Optional columns: title, custom_alias."}), 400
        # Normalize header names once.
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error):
        return jsonify({"detail": "Could not read this CSV. Save it as UTF-8 CSV and try again."}), 400
    if not rows or len(rows) > 100:
        return jsonify({"detail": "CSV must contain between 1 and 100 data rows."}), 400
    db = SessionLocal(); created=[]; errors=[]
    try:
        for idx, row in enumerate(rows, start=2):
            try:
                url, host = normalise_destination(row.get("original_url"))
                if is_blocked(host, db): raise ValueError(f"Destination domain {host} is blocked.")
                alias = str(row.get("custom_alias") or "").strip()
                if alias and (not re.fullmatch(r"[a-zA-Z0-9_-]{3,40}", alias) or db.query(LinkModel).filter(LinkModel.short_code == alias).first()):
                    raise ValueError("Alias is invalid or already allocated.")
                code = alias or generate_base62()
                while not alias and db.query(LinkModel).filter(LinkModel.short_code == code).first(): code = generate_base62()
                link = LinkModel(original_url=url, short_code=code, title=str(row.get("title") or "Imported link").strip()[:120], owner_user_id=user_id, owner_key_hash=owner_key_digest(owner_key) if not user_id else None, is_active=True)
                db.add(link); db.flush(); created.append({"short_code":code,"title":link.title})
            except (ValueError, TypeError) as exc:
                errors.append({"row":idx,"error":str(exc)})
        db.commit()
        return jsonify({"created":created,"errors":errors,"created_count":len(created),"error_count":len(errors)}), 201 if created else 400
    finally:
        db.close()


@app.get("/api/admin/blocklist")
@admin_required
def get_blocklist():
    db = SessionLocal()
    try:
        items = db.query(BlockedDomainModel).order_by(BlockedDomainModel.domain.asc()).all()
        return jsonify({"blocklist": [{"id": b.id, "domain": b.domain, "reason": b.reason,
            "added_at": b.added_at.strftime("%b %d, %Y") if b.added_at else "—"} for b in items]})
    finally:
        db.close()

@app.post("/api/admin/blocklist/add")
@admin_required
def add_blocklist_domain():
    data = request.get_json(silent=True) or {}
    raw_domain = str(data.get("domain") or "").strip().lower()
    reason = str(data.get("reason") or "Flagged by Admin").strip()[:240] or "Flagged by Admin"
    if not raw_domain:
        return jsonify({"detail": "Domain is required."}), 400
    raw_domain = re.sub(r"^https?://", "", raw_domain).split("/")[0].split(":")[0].strip().rstrip(".")
    try:
        domain = raw_domain.encode("idna").decode("ascii")
    except UnicodeError:
        return jsonify({"detail": "Enter a valid domain name."}), 400
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", domain):
        return jsonify({"detail": "Enter a valid domain name without a path or port."}), 400
    db = SessionLocal()
    try:
        if db.query(BlockedDomainModel).filter(BlockedDomainModel.domain == domain).first():
            return jsonify({"detail": "Domain is already blocked."}), 409
        db.add(BlockedDomainModel(domain=domain, reason=reason))
        db.commit()
        return jsonify({"message": f"Domain '{domain}' added to the blocklist."}), 201
    finally:
        db.close()

@app.delete("/api/admin/blocklist/<int:item_id>/delete")
@admin_required
def remove_blocklist_domain(item_id):
    db = SessionLocal()
    try:
        item = db.query(BlockedDomainModel).filter(BlockedDomainModel.id == item_id).first()
        if not item:
            return jsonify({"detail": "Blocklist item not found."}), 404
        db.delete(item)
        db.commit()
        return jsonify({"message": "Domain unblocked."})
    finally:
        db.close()


@app.post("/api/verify-pass")
def verify_password():
    data = request.get_json(silent=True) or {}
    code, password = str(data.get("short_code") or ""), str(data.get("password") or "")
    db = SessionLocal()
    try:
        link = db.query(LinkModel).filter(LinkModel.short_code == code).first()
        if not link or not link.password_hash or not link.is_active:
            return jsonify({"valid": False}), 200
        if link.expires_at and utcnow() > link.expires_at:
            return jsonify({"valid": False, "detail": "This link has expired."}), 200
        if link.click_limit and (link.clicks_count or 0) >= link.click_limit:
            return jsonify({"valid": False, "detail": "This link has reached its click limit."}), 200
        if check_password(password, link.password_hash):
            log_click(db, link)
            return jsonify({"valid": True, "redirect_url": link.original_url})
        return jsonify({"valid": False})
    finally:
        db.close()


def error_page(status, heading, message):
    return f"""<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{status} · LinkPulse</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f2eb;color:#2b1e16;font:16px system-ui,sans-serif}}main{{max-width:460px;margin:24px;padding:42px;border:1px solid #dfd4c2;border-radius:24px;background:#fffdf9;box-shadow:0 20px 70px #4c32151a}}small{{color:#a65c32;letter-spacing:.16em;font-weight:700}}h1{{font-family:Georgia,serif;font-size:30px}}p{{color:#695140;line-height:1.7}}</style><main><small>LINKPULSE · {status}</small><h1>{heading}</h1><p>{message}</p><a href='/' style='color:#a65c32;font-weight:700'>Return to LinkPulse ↗</a></main></html>""", status

@app.get("/<code>")
def handle_redirect(code):
    if code in {"favicon.ico", "static", "api", "admin", "robots.txt", "sitemap.xml"}:
        abort(404)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", code):
        abort(404)
    db = SessionLocal()
    try:
        link = db.query(LinkModel).filter(LinkModel.short_code == code).first()
        if not link:
            return error_page(404, "That link went missing.", "This short code does not exist or may have been removed.")
        if not link.is_active:
            return error_page(403, "This link is paused.", "The platform administrator has temporarily disabled this redirect.")
        if link.expires_at and utcnow() > link.expires_at:
            return error_page(410, "This link has expired.", "The scheduled lifetime for this link has ended.")
        if link.click_limit and (link.clicks_count or 0) >= link.click_limit:
            return error_page(429, "This link has reached its limit.", "The maximum number of visits configured by the creator has been reached.")
        if link.password_hash:
            # Escape the short code even though generated/custom aliases are constrained.
            safe_code = code.replace("&", "&amp;").replace("'", "&#39;").replace("<", "&lt;").replace(">", "&gt;")
            return f"""<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Passphrase required · LinkPulse</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f2eb;color:#2b1e16;font:16px system-ui,sans-serif}}main{{width:min(360px,calc(100% - 56px));padding:34px;border:1px solid #dfd4c2;border-radius:24px;background:#fffdf9;box-shadow:0 20px 70px #4c32151a}}p{{color:#695140;line-height:1.6}}input,button{{box-sizing:border-box;width:100%;padding:13px;border-radius:12px;font:inherit}}input{{border:1px solid #dfd4c2;margin:8px 0 12px}}button{{border:0;background:#a65c32;color:white;font-weight:700;cursor:pointer}}#err{{color:#a52c24;font-size:13px}}</style><main><small style='color:#a65c32;letter-spacing:.14em;font-weight:700'>LINKPULSE · PRIVATE LINK</small><h1>Passphrase required</h1><p>This destination is protected by its creator.</p><form id='form'><input id='pwd' type='password' autocomplete='current-password' placeholder='Enter passphrase' required><button>Continue securely</button></form><p id='err' role='status'></p></main><script>document.getElementById('form').addEventListener('submit',async e=>{{e.preventDefault();const out=document.getElementById('err');out.textContent='Checking…';try{{const r=await fetch('/api/verify-pass',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{short_code:'{safe_code}',password:document.getElementById('pwd').value}})}});const d=await r.json();if(d.valid)location.assign(d.redirect_url);else out.textContent=d.detail||'That passphrase did not match.'}}catch{{out.textContent='Could not connect. Please try again.'}}}});</script></html>"""
        log_click(db, link)
        return redirect(link.original_url, code=302)
    finally:
        db.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"\nLinkPulse server starting on port {port}\n")
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=port, debug=False)
