"""
CIRO Authentication System
============================
Email-verified registration, login with JWT tokens.
Uses Gmail App Password for OTP delivery.

Endpoints:
    POST /auth/register  → Create account + send OTP to email
    POST /auth/verify    → Verify OTP code → mark user verified
    POST /auth/login     → Login → get JWT token
    GET  /auth/me        → Get current user profile (requires token)
"""

import os
import random
import smtplib
import time
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr

load_dotenv()

router = APIRouter()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "ciro-default-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
# Gmail App Passwords have spaces — strip them before use
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
OTP_EXPIRY_MINUTES = 10

# ---------------------------------------------------------------------------
# In-memory user store (falls back if Firebase unavailable)
# In production, all data goes to Firestore.
# ---------------------------------------------------------------------------
_users_store: dict[str, dict] = {}
_otp_store: dict[str, dict] = {}  # email -> {code, expires_at}


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class VerifyRequest(BaseModel):
    email: str
    code: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    status: str
    message: str
    token: Optional[str] = None
    user: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helper: Firebase or In-Memory
# ---------------------------------------------------------------------------
def _get_firebase():
    """Get Firebase client, returns (client, use_mock)."""
    try:
        from utils.firebase_client import FirebaseClient
        fb = FirebaseClient()
        return fb, fb.use_mock
    except Exception:
        return None, True


def _save_user(email: str, user_data: dict):
    fb, use_mock = _get_firebase()
    if use_mock or fb is None:
        _users_store[email] = user_data
    else:
        fb.db.collection("users").document(email).set(user_data)


def _get_user(email: str) -> Optional[dict]:
    fb, use_mock = _get_firebase()
    if use_mock or fb is None:
        return _users_store.get(email)
    else:
        doc = fb.db.collection("users").document(email).get()
        return doc.to_dict() if doc.exists else None


# ---------------------------------------------------------------------------
# Helper: Send OTP Email via Gmail
# ---------------------------------------------------------------------------
def _build_otp_html(user_name: str, otp_code: str, purpose: str = "Email Verification") -> str:
    """Build a beautiful HTML email template."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0a0e1a;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0e1a;padding:40px 20px;">
    <tr><td align="center">
      <table width="540" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#1a1f35,#0d1226);border-radius:16px;border:1px solid rgba(99,179,237,0.2);overflow:hidden;">
        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,#1e3a8a,#1e40af);padding:32px 40px;text-align:center;">
          <h1 style="margin:0;color:#fff;font-size:28px;font-weight:800;letter-spacing:4px;">CIRO</h1>
          <p style="margin:6px 0 0;color:rgba(255,255,255,0.7);font-size:12px;letter-spacing:2px;text-transform:uppercase;">Crisis Intelligence &amp; Response Orchestrator</p>
        </td></tr>
        <!-- Body -->
        <tr><td style="padding:40px;">
          <p style="color:#94a3b8;font-size:14px;margin:0 0 8px;">Hello,</p>
          <h2 style="color:#e2e8f0;font-size:22px;margin:0 0 24px;">Hi {user_name} 👋</h2>
          <p style="color:#94a3b8;font-size:15px;line-height:1.6;margin:0 0 32px;">
            You requested a <strong style="color:#63b3ed;">{purpose}</strong> code for your CIRO account.
            Use the code below to continue:
          </p>
          <!-- OTP Box -->
          <div style="background:rgba(30,58,138,0.3);border:1px solid rgba(99,179,237,0.3);border-radius:12px;padding:28px;text-align:center;margin:0 0 32px;">
            <p style="color:#94a3b8;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;">Your Verification Code</p>
            <div style="display:inline-block;background:linear-gradient(135deg,#1e3a8a,#1e40af);border-radius:8px;padding:16px 32px;">
              <span style="font-size:40px;font-weight:900;letter-spacing:12px;color:#fff;font-family:'Courier New',monospace;">{otp_code}</span>
            </div>
            <p style="color:#64748b;font-size:12px;margin:16px 0 0;">⏱ Expires in {OTP_EXPIRY_MINUTES} minutes</p>
          </div>
          <p style="color:#64748b;font-size:13px;line-height:1.6;margin:0;">
            If you did not request this code, you can safely ignore this email.
            Your account remains secure.
          </p>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background:rgba(0,0,0,0.2);padding:20px 40px;text-align:center;border-top:1px solid rgba(255,255,255,0.05);">
          <p style="color:#475569;font-size:12px;margin:0;">© 2026 CIRO · AISeekho Hackathon · Pakistan 🇵🇰</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _send_email(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Send email via Gmail SMTP. Tries SSL (465) then STARTTLS (587)."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"[Auth] SMTP not configured. Email would go to: {to_email}")
        print(f"[Auth] Subject: {subject}")
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"CIRO System <{SMTP_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        print(f"[Auth] ✅ Email sent to {to_email} via STARTTLS")
        return True
    except Exception as e:
        print(f"[Auth] Email failed: {e}")
        return False


def _send_otp_email(to_email: str, otp_code: str, user_name: str) -> bool:
    """Send OTP verification email."""
    html = _build_otp_html(user_name, otp_code, "Email Verification")
    plain = f"Hello {user_name},\n\nYour CIRO verification code is: {otp_code}\n\nThis code expires in {OTP_EXPIRY_MINUTES} minutes.\n\nCIRO System"
    return _send_email(to_email, f"CIRO – Verify your email [{otp_code}]", html, plain)


# ---------------------------------------------------------------------------
# Helper: JWT
# ---------------------------------------------------------------------------
def _create_token(email: str, name: str) -> str:
    payload = {
        "email": email,
        "name": name,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(authorization: str = Header(...)) -> dict:
    """Dependency: extract user from Bearer token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1]
    return _decode_token(token)


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------
@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest):
    """Register a new user. Sends 6-digit OTP to email."""
    email = req.email.strip().lower()
    name = req.name.strip()

    if not email or not name or not req.password:
        raise HTTPException(status_code=400, detail="All fields are required")

    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Check if user already exists
    existing = _get_user(email)
    if existing and existing.get("verified", False):
        raise HTTPException(status_code=409, detail="Email already registered")

    # Hash password
    hashed = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # Generate OTP
    otp_code = str(random.randint(100000, 999999))
    expires_at = time.time() + (OTP_EXPIRY_MINUTES * 60)

    # Save user (unverified)
    user_data = {
        "name": name,
        "email": email,
        "password_hash": hashed,
        "verified": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_user(email, user_data)

    # Save OTP
    _otp_store[email] = {"code": otp_code, "expires_at": expires_at}

    # Send email
    sent = _send_otp_email(email, otp_code, name)
    if not sent:
        # Still allow registration even if email fails (for testing)
        print(f"[Auth] Email send failed but continuing. OTP: {otp_code}")

    return AuthResponse(
        status="otp_sent",
        message=f"Verification code sent to {email}. Check your inbox.",
    )


# ---------------------------------------------------------------------------
# POST /auth/verify
# ---------------------------------------------------------------------------
@router.post("/verify", response_model=AuthResponse)
async def verify_email(req: VerifyRequest):
    """Verify email with 6-digit OTP code."""
    email = req.email.strip().lower()
    code = req.code.strip()

    otp_data = _otp_store.get(email)
    if not otp_data:
        raise HTTPException(status_code=400, detail="No verification pending for this email")

    if time.time() > otp_data["expires_at"]:
        del _otp_store[email]
        raise HTTPException(status_code=400, detail="OTP expired. Please register again.")

    if otp_data["code"] != code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Mark user as verified
    user = _get_user(email)
    if user:
        user["verified"] = True
        _save_user(email, user)

    # Clean up OTP
    del _otp_store[email]

    return AuthResponse(
        status="verified",
        message="Email verified successfully! You can now login.",
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    """Login with email and password. Returns JWT token."""
    email = req.email.strip().lower()

    user = _get_user(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("verified", False):
        raise HTTPException(status_code=403, detail="Email not verified. Please check your inbox for the verification code.")

    # Check password
    if not bcrypt.checkpw(req.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Generate token
    token = _create_token(email, user["name"])

    return AuthResponse(
        status="success",
        message="Login successful",
        token=token,
        user={
            "name": user["name"],
            "email": email,
            "created_at": user.get("created_at", ""),
        },
    )


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------
@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user profile from JWT token."""
    return {
        "status": "success",
        "user": {
            "name": current_user.get("name", ""),
            "email": current_user.get("email", ""),
        },
    }


# ---------------------------------------------------------------------------
# Forgot / Reset Password Models
# ---------------------------------------------------------------------------
class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


# ---------------------------------------------------------------------------
# POST /auth/forgot-password
# ---------------------------------------------------------------------------
@router.post("/forgot-password", response_model=AuthResponse)
async def forgot_password(req: ForgotPasswordRequest):
    """Send a password reset OTP to the user's email."""
    email = req.email.strip().lower()

    user = _get_user(email)
    if not user:
        # Don't reveal whether email exists (security)
        return AuthResponse(
            status="otp_sent",
            message="If this email is registered, a reset code has been sent.",
        )

    # Generate reset OTP
    otp_code = str(random.randint(100000, 999999))
    expires_at = time.time() + (OTP_EXPIRY_MINUTES * 60)
    _otp_store[f"reset_{email}"] = {"code": otp_code, "expires_at": expires_at}

    # Send reset email
    _send_reset_email(email, otp_code, user.get("name", "User"))

    return AuthResponse(
        status="otp_sent",
        message="If this email is registered, a reset code has been sent.",
    )


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------
@router.post("/reset-password", response_model=AuthResponse)
async def reset_password(req: ResetPasswordRequest):
    """Reset password using the OTP code from email."""
    email = req.email.strip().lower()
    code = req.code.strip()

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    otp_key = f"reset_{email}"
    otp_data = _otp_store.get(otp_key)
    if not otp_data:
        raise HTTPException(status_code=400, detail="No reset request pending for this email")

    if time.time() > otp_data["expires_at"]:
        del _otp_store[otp_key]
        raise HTTPException(status_code=400, detail="Reset code expired. Please request again.")

    if otp_data["code"] != code:
        raise HTTPException(status_code=400, detail="Invalid reset code")

    # Update password
    user = _get_user(email)
    if user:
        user["password_hash"] = bcrypt.hashpw(
            req.new_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        _save_user(email, user)

    # Clean up
    del _otp_store[otp_key]

    return AuthResponse(
        status="success",
        message="Password reset successfully! You can now login with your new password.",
    )


# ---------------------------------------------------------------------------
# Helper: Send Reset Email
# ---------------------------------------------------------------------------
def _send_reset_email(to_email: str, otp_code: str, user_name: str) -> bool:
    """Send password reset OTP email using the shared template."""
    html = _build_otp_html(user_name, otp_code, "Password Reset")
    plain = (
        f"Hello {user_name},\n\n"
        f"Your CIRO password reset code is: {otp_code}\n\n"
        f"This code expires in {OTP_EXPIRY_MINUTES} minutes.\n"
        f"If you didn't request this, ignore this email.\n\n"
        f"CIRO System"
    )
    return _send_email(
        to_email,
        f"CIRO \u2013 Reset your password [{otp_code}]",
        html,
        plain,
    )
