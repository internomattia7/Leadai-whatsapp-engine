import re
import json
import threading
from datetime import datetime, timedelta, time
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
import uvicorn

from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv 
load_dotenv()
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from starlette.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
from email_utils import send_email
from jose import jwt, JWTError
from passlib.context import CryptContext

from leadai_engine import process_text_message, get_conn
from psycopg2.extras import RealDictCursor
import requests

from passlib.context import CryptContext

# app.py (o main.py) - versione corretta pronta da incollare

import os
import secrets
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Body, Depends, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer

# ====== CARICA ENV SUBITO (PRIMA DI os.getenv) ======
load_dotenv()

# ====== CONFIG ======
JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME_SUPER_SECRET")  # mettila in .env
JWT_ALG = "HS256"
JWT_EXPIRE_MIN = 60 * 24  # 24 ore

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v19.0")

META_APP_ID = os.getenv("META_APP_ID")                # es: 4190...
META_APP_SECRET = os.getenv("META_APP_SECRET")        # secret vera
META_REDIRECT_URI = os.getenv("META_REDIRECT_URI")    # es: http://localhost:8000/settings/whatsapp/connect

# debug safe (non crasha se mancano env)
_sec = META_APP_SECRET or ""
print("META_APP_ID set:", bool(META_APP_ID))
print("META_REDIRECT_URI:", META_REDIRECT_URI)
print("META_APP_SECRET set:", bool(META_APP_SECRET))
print("META_APP_SECRET len:", len(_sec))
print("META_APP_SECRET head/tail:", _sec[:4], "...", _sec[-4:])

# ====== SECURITY / AUTH ======
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/")  # se lo usi in Swagger


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def get_current_user(request: Request) -> dict:
    """
    Legge JWT da:
    1) cookie 'access_token' (browser)
    2) header Authorization: Bearer ...
    Ritorna payload dict (es: {"azienda_id": ...})
    """
    token = request.cookies.get("access_token")

    if not token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ====== NORMALIZE HELPERS ======
def normalize_contact_key(channel: str, raw: str) -> str:
    """
    Canonical format: wa:{digits}  — no + after wa:
    Examples:
      "393290927001"    -> "wa:393290927001"
      "+393290927001"   -> "wa:393290927001"
      "wa:393290927001" -> "wa:393290927001"
      "wa:+393290927001"-> "wa:393290927001"
    """
    raw = (raw or "").strip()
    if channel == "whatsapp":
        # strip existing wa: prefix (with or without +)
        for prefix in ("wa:+", "wa:"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        # strip any remaining leading +
        raw = raw.lstrip("+")
        return f"wa:{raw}"
    return raw


def phone_from_key(contact_key: str) -> str:
    """Extract raw digits from a contact_key (e.g. 'wa:393290927001' -> '393290927001')."""
    for prefix in ("wa:+", "wa:"):
        if contact_key.startswith(prefix):
            return contact_key[len(prefix):].lstrip("+")
    return contact_key.lstrip("+")


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_intent_keywords(cur, azienda_id):
    cur.execute(
        """
        SELECT intent, keyword, priority
        FROM intent_keywords
        WHERE azienda_id = %s AND enabled = TRUE
        ORDER BY priority ASC, id ASC
        """,
        (azienda_id,),
    )
    return cur.fetchall()


def detect_intent(text: str, rows):
    t = normalize_text(text)
    for r in rows:
        intent = r["intent"] if isinstance(r, dict) else r[0]
        kw = r["keyword"] if isinstance(r, dict) else r[1]
        kw = normalize_text(kw)
        if kw and kw in t:
            return intent
    return None


# ====== GRAPH HELPERS ======
def _graph_get(path: str, token: str, params: dict | None = None) -> Tuple[int, str, Optional[dict]]:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, params=params or {}, timeout=25)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, r.text, j


def _handle_wa_statuses(statuses: list):
    """
    Process WhatsApp delivery/read/failed receipts from the webhook statuses[] array.
    Matches by wa_message_id (wamid) — never downgrades status.
    Priority: queued < sent < delivered < read (error is terminal).
    """
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                for s in statuses:
                    wamid = s.get("id")
                    wa_status = s.get("status")  # 'sent', 'delivered', 'read', 'failed'
                    if not wamid or not wa_status:
                        continue

                    if wa_status == "delivered":
                        # Accept delivered from any non-terminal state
                        cur.execute(
                            """
                            UPDATE outbound_messages
                            SET status = 'delivered'
                            WHERE wa_message_id = %s
                              AND status NOT IN ('delivered', 'read', 'error')
                            """,
                            (wamid,),
                        )
                        updated = cur.rowcount
                    elif wa_status == "read":
                        # read is always the final positive state
                        cur.execute(
                            """
                            UPDATE outbound_messages
                            SET status = 'read'
                            WHERE wa_message_id = %s
                              AND status != 'error'
                            """,
                            (wamid,),
                        )
                        updated = cur.rowcount
                    elif wa_status == "failed":
                        errors = s.get("errors") or []
                        reason = errors[0].get("message", "failed") if errors else "failed"
                        cur.execute(
                            """
                            UPDATE outbound_messages
                            SET status = 'error', error = %s
                            WHERE wa_message_id = %s
                              AND status NOT IN ('delivered', 'read')
                            """,
                            (reason, wamid),
                        )
                        updated = cur.rowcount
                    else:
                        updated = 0

                    print(f"[WA STATUS] wamid={wamid} → {wa_status} (rows updated: {updated})", flush=True)

            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[WA STATUS ERROR] {e}", flush=True)


def fetch_wa_profile_pic(wa_token: str, wa_phone_number_id: str, from_wa: str) -> str | None:
    """Best-effort: call Meta Contacts API to get the WhatsApp profile picture URL."""
    try:
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{wa_phone_number_id}/contacts"
        resp = requests.get(
            url,
            params={"contacts": json.dumps([from_wa])},
            headers={"Authorization": f"Bearer {wa_token}"},
            timeout=5,
        )
        if resp.status_code != 200:
            print(f"[profile_pic] API {resp.status_code}: {resp.text[:200]}", flush=True)
            return None
        contacts = (resp.json().get("contacts") or [])
        if not contacts:
            return None
        return (contacts[0].get("profile") or {}).get("profile_pic_url") or None
    except Exception as e:
        print(f"[profile_pic] fetch error: {e}", flush=True)
        return None


def _save_profile_pic_bg(wa_token: str, wa_phone_number_id: str, from_wa: str, contact_key: str):
    """Background thread: fetch profile pic and persist it in lead_contacts."""
    pic_url = fetch_wa_profile_pic(wa_token, wa_phone_number_id, from_wa)
    if not pic_url:
        return
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE lead_contacts
                    SET profile_image_url = %s, updated_at = now()
                    WHERE contact_key = %s
                    """,
                    (pic_url, contact_key),
                )
            conn.commit()
            print(f"[profile_pic] saved for {contact_key}", flush=True)
        finally:
            conn.close()
    except Exception as e:
        print(f"[profile_pic] db save error: {e}", flush=True)


def send_whatsapp_message(
    to: str,
    text: str,
    wa_token: str,
    wa_phone_number_id: str,
    graph_version: str = "v19.0",
):
    url = f"https://graph.facebook.com/{graph_version}/{wa_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    print("SEND STATUS:", r.status_code, r.text)
    return r


# ─── Media helpers (WhatsApp Cloud API) ────────────────────────────────────

UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def _wa_upload_media(file_bytes: bytes, mime_type: str, filename: str,
                     wa_token: str, phone_number_id: str,
                     graph_version: str = "v19.0") -> str:
    """Upload media to Meta → returns media_id."""
    url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/media"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {wa_token}"},
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, file_bytes, mime_type)},
        timeout=60,
    )
    print(f"[WA UPLOAD] status={r.status_code} body={r.text[:300]}", flush=True)
    r.raise_for_status()
    return r.json()["id"]


def _wa_get_media_url(media_id: str, wa_token: str,
                      graph_version: str = "v19.0") -> str:
    """Resolve media_id → temporary download URL."""
    url = f"https://graph.facebook.com/{graph_version}/{media_id}"
    r = requests.get(url, headers={"Authorization": f"Bearer {wa_token}"}, timeout=15)
    r.raise_for_status()
    return r.json()["url"]


def _wa_download_media(media_url: str, wa_token: str) -> bytes:
    """Download raw bytes from a Meta media URL."""
    r = requests.get(media_url, headers={"Authorization": f"Bearer {wa_token}"}, timeout=60)
    r.raise_for_status()
    return r.content


def _download_inbound_media_bg(
    media_id: str,
    wa_token: str,
    azienda_id,
    msg_id: str,
    mime_type: str,
    filename: str,
    graph_version: str = "v19.0",
):
    """Background thread: download inbound media and save to disk, then update DB."""
    print(f"[MEDIA DL] START media_id={media_id!r} msg_id={msg_id!r} mime={mime_type!r}", flush=True)
    try:
        # Step 1: resolve media_id → temporary Meta URL
        print(f"[MEDIA DL] fetching URL from Graph API...", flush=True)
        media_url = _wa_get_media_url(media_id, wa_token, graph_version)
        print(f"[MEDIA DL] got URL={media_url[:80]}...", flush=True)

        # Step 2: download binary
        raw = _wa_download_media(media_url, wa_token)
        print(f"[MEDIA DL] downloaded {len(raw)} bytes", flush=True)

        # Step 3: build save path — compute date ONCE to avoid midnight race
        date_str = datetime.utcnow().strftime("%Y%m%d")
        ext = (filename.rsplit(".", 1)[-1] if filename and "." in filename
               else _ext_from_mime(mime_type))
        date_dir = UPLOADS_DIR / "inbound" / str(azienda_id) / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        save_name = f"{media_id}.{ext}"
        dest = date_dir / save_name
        dest.write_bytes(raw)
        local_path = f"/uploads/inbound/{azienda_id}/{date_str}/{save_name}"
        print(f"[MEDIA DL] saved → {local_path}", flush=True)

        # Step 4: update DB
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE wa_inbound_messages SET local_path=%s WHERE msg_id=%s",
                    (local_path, msg_id),
                )
            conn.commit()
            print(f"[MEDIA DL] DB updated OK for msg_id={msg_id!r}", flush=True)
        finally:
            conn.close()
    except Exception as e:
        print(f"[MEDIA DL ERROR] media_id={media_id!r}: {type(e).__name__}: {e}", flush=True)


def _ext_from_mime(mime_type: str) -> str:
    _map = {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
        "image/gif": "gif", "application/pdf": "pdf",
        "audio/ogg": "ogg", "audio/mpeg": "mp3",
        "video/mp4": "mp4",
    }
    return _map.get(mime_type or "", "bin")


# ====== APP ======
app = FastAPI(title="LeadAI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ====== IMPORT TUOI ======
# Assumo che tu abbia questi moduli già:
from leadai_engine import get_conn, process_text_message  # noqa: E402

# ====== WEBHOOK VERIFY TOKEN (solo fallback, ma tu usi DB per token per azienda) ======
VERIFY_TOKEN_FALLBACK = os.getenv("VERIFY_TOKEN", "test123")


@app.get("/webhook/whatsapp")
async def wa_verify(request: Request):
    """
    Meta webhook verification.
    Meta manda:
      hub.mode=subscribe
      hub.verify_token=...
      hub.challenge=...
    Noi controlliamo che quel verify_token esista in company_integrations.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode != "subscribe" or not token:
        return PlainTextResponse("forbidden", status_code=403)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT azienda_id
                FROM company_integrations
                WHERE channel='whatsapp'
                  AND is_enabled=true
                  AND wa_verify_token=%s
                LIMIT 1
                """,
                (token,),
            )
            row = cur.fetchone()

            # fallback opzionale (se vuoi accettare il token fisso)
            if not row and token == VERIFY_TOKEN_FALLBACK:
                print("WA VERIFY OK fallback token")
                return PlainTextResponse(challenge or "", status_code=200)

            if row:
                azienda_id = row[0] if not isinstance(row, dict) else row.get("azienda_id")
                print("WA VERIFY OK per azienda:", azienda_id)
                return PlainTextResponse(challenge or "", status_code=200)

    except Exception as e:
        print("ERRORE VERIFY WEBHOOK:", e)
    finally:
        conn.close()

    return PlainTextResponse("forbidden", status_code=403)


@app.post("/webhook/whatsapp")
async def wa_events(request: Request):
    """
    Riceve gli eventi WhatsApp.
    - trova azienda in base a phone_number_id
    - salva inbound
    - processa testo
    - invia risposta
    """
    data = await request.json()

    print("\n====== WEBHOOK PAYLOAD ======")
    print(json.dumps(data, indent=2))
    print("====== FINE PAYLOAD ======\n")

    try:
        entry0 = (data.get("entry") or [])[0]
        changes0 = (entry0.get("changes") or [])[0]
        value = changes0.get("value") or {}

        phone_number_id = (value.get("metadata") or {}).get("phone_number_id")

        # Handle delivery/read/failed receipts (statuses[] payload)
        statuses = value.get("statuses") or []
        if statuses:
            _handle_wa_statuses(statuses)

        messages = value.get("messages") or []
        if not phone_number_id or not messages:
            return {"ok": True}

        msg0 = messages[0]
        msg_id = msg0.get("id")
        from_wa = msg0.get("from")
        msg_type = msg0.get("type")

        text = None
        media_id = None
        mime_type = None
        filename = None

        if msg_type == "text":
            text = (msg0.get("text") or {}).get("body")
        elif msg_type in ("image", "document", "audio", "video", "sticker"):
            media_block = msg0.get(msg_type) or {}
            media_id = media_block.get("id")
            mime_type = media_block.get("mime_type")
            filename = media_block.get("filename")  # documents only
            caption = media_block.get("caption")
            text = caption or f"[{msg_type}]"

        if not msg_id or not from_wa:
            return {"ok": True}
        # Require at least a text or a known media_id
        if not text and not media_id:
            return {"ok": True}

    except Exception as e:
        print("ERRORE PARSING WEBHOOK:", e)
        return {"ok": True}

    contact_key = normalize_contact_key("whatsapp", from_wa)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1) trova azienda + token per quel numero
            cur.execute(
                """
                SELECT azienda_id, wa_access_token, wa_phone_number_id
                FROM company_integrations
                WHERE channel='whatsapp'
                  AND is_enabled=true
                  AND wa_phone_number_id=%s
                LIMIT 1
                """,
                (phone_number_id,),
            )
            row = cur.fetchone()

            if not row:
                print("NUMERO WHATSAPP NON COLLEGATO:", phone_number_id)
                return {"ok": True}

            if isinstance(row, dict):
                azienda_id = row["azienda_id"]
                wa_token = row["wa_access_token"]
                wa_phone_number_id = row["wa_phone_number_id"]
            else:
                azienda_id, wa_token, wa_phone_number_id = row

            # 2) dedup msg_id
            cur.execute("SELECT 1 FROM wa_inbound_messages WHERE msg_id=%s LIMIT 1", (msg_id,))
            if cur.fetchone():
                return {"ok": True}

            # 3) salva inbound
            cur.execute(
                """
                INSERT INTO wa_inbound_messages
                    (msg_id, phone_number_id, from_wa, text, created_at,
                     msg_type, media_id, mime_type, filename)
                VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s)
                """,
                (msg_id, phone_number_id, from_wa, text,
                 msg_type or "text", media_id, mime_type, filename),
            )

            # 4) upsert contatto (ON CONFLICT per evitare race condition su contact_key univoco)
            cur.execute(
                """
                INSERT INTO lead_contacts (azienda_id, contact_key, telefono, nome_cliente)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (contact_key) DO UPDATE
                    SET telefono     = EXCLUDED.telefono,
                        updated_at   = now()
                """,
                (azienda_id, contact_key, from_wa, from_wa),
            )

            # 5) upsert lead_status
            cur.execute(
                """
                INSERT INTO lead_status (azienda_id, contact_key, fase_preventivo, esito_cliente, last_channel, updated_at)
                VALUES (%s, %s, 'nuovo', NULL, 'whatsapp', now())
                ON CONFLICT (contact_key) DO UPDATE SET
                    last_channel = 'whatsapp',
                    updated_at   = now()
                """,
                (azienda_id, contact_key),
            )

        conn.commit()

        # 6) best-effort: fetch profile pic in background (non blocca il flusso)
        threading.Thread(
            target=_save_profile_pic_bg,
            args=(wa_token, wa_phone_number_id, from_wa, contact_key),
            daemon=True,
        ).start()

        # 6b) if media → download in background
        if media_id:
            threading.Thread(
                target=_download_inbound_media_bg,
                args=(media_id, wa_token, azienda_id, msg_id, mime_type, filename, GRAPH_VERSION),
                daemon=True,
            ).start()

        # 7) genera reply solo per messaggi di testo (non per media puri)
        if msg_type == "text":
            is_test = "[TEST]" in (text or "")
            clean_text = text.replace("[TEST]", "").strip() if is_test else text
            if is_test:
                print(f"[TEST_MODE ON: bypass anti-spam] contact_key={contact_key}", flush=True)

            reply = process_text_message(conn, contact_key, clean_text)
            print("RISPOSTA AI:", reply)

            # 8) invia reply
            if reply:
                send_whatsapp_message(from_wa, reply, wa_token, wa_phone_number_id, graph_version=GRAPH_VERSION)

        return {"ok": True}

    except Exception as e:
        print("ERRORE WEBHOOK WHATSAPP:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": True}
    finally:
        conn.close()


# ====== WHATSAPP CONNECT (OBIETTIVO: token + phone_number_id + waba_id -> DB) ======

def _save_company_integration_whatsapp(
    azienda_id: int,
    access_token: str,
    waba_id: str,
    wa_phone_number_id: str,
    display_phone: Optional[str] = None,
    verified_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Salva su company_integrations:
      wa_access_token, wa_waba_id, wa_phone_number_id, wa_verify_token, wa_webhook_key
    """
    new_verify_token = secrets.token_urlsafe(16)
    new_webhook_key = secrets.token_urlsafe(16)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT wa_verify_token, wa_webhook_key
                FROM company_integrations
                WHERE azienda_id=%s AND channel='whatsapp'
                LIMIT 1
                """,
                (azienda_id,),
            )
            existing = cur.fetchone()
            existing_verify = existing[0] if (existing and not isinstance(existing, dict)) else (existing.get("wa_verify_token") if existing else None)
            existing_key = existing[1] if (existing and not isinstance(existing, dict)) else (existing.get("wa_webhook_key") if existing else None)

            verify_to_save = existing_verify or new_verify_token
            key_to_save = existing_key or new_webhook_key

            # NOTA: serve colonna wa_waba_id nel DB
            cur.execute(
                """
                INSERT INTO company_integrations
                    (azienda_id, channel, wa_access_token, wa_waba_id, wa_phone_number_id,
                     wa_verify_token, wa_webhook_key, is_enabled, updated_at)
                VALUES
                    (%s, 'whatsapp', %s, %s, %s, %s, %s, true, now())
                ON CONFLICT (azienda_id, channel)
                DO UPDATE SET
                    wa_access_token = EXCLUDED.wa_access_token,
                    wa_waba_id = EXCLUDED.wa_waba_id,
                    wa_phone_number_id = EXCLUDED.wa_phone_number_id,
                    wa_verify_token = COALESCE(company_integrations.wa_verify_token, EXCLUDED.wa_verify_token),
                    wa_webhook_key = COALESCE(company_integrations.wa_webhook_key, EXCLUDED.wa_webhook_key),
                    is_enabled = true,
                    updated_at = now()
                """,
                (azienda_id, access_token, waba_id, wa_phone_number_id, verify_to_save, key_to_save),
            )
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "where": "db_save", "error": str(e)}
    finally:
        conn.close()

    return {
        "ok": True,
        "azienda_id": azienda_id,
        "waba_id": waba_id,
        "wa_phone_number_id": wa_phone_number_id,
        "display_phone_number": display_phone,
        "verified_name": verified_name,
        "wa_verify_token": verify_to_save,
        "wa_webhook_key": key_to_save,
    }


def _resolve_waba_and_phone(access_token: str) -> Dict[str, Any]:
    """
    Con access_token:
      1) GET /me/whatsapp_business_accounts -> waba_id
      2) GET /{waba_id}/phone_numbers -> phone_number_id
    """
    st, raw, j = _graph_get("/me/whatsapp_business_accounts", access_token)
    if st != 200 or not j:
        return {"ok": False, "where": "me_waba", "status": st, "raw": raw}

    wabas = j.get("data") or []
    if not wabas:
        return {"ok": False, "where": "me_waba", "error": "no_waba", "graph": j}

    waba_id = (wabas[0] or {}).get("id")
    if not waba_id:
        return {"ok": False, "where": "me_waba", "error": "missing_waba_id", "graph": j}

    st2, raw2, j2 = _graph_get(f"/{waba_id}/phone_numbers", access_token, params={"fields": "id,display_phone_number,verified_name"})
    if st2 != 200 or not j2:
        return {"ok": False, "where": "waba_phone_numbers", "status": st2, "raw": raw2}

    phones = j2.get("data") or []
    if not phones:
        return {"ok": False, "where": "waba_phone_numbers", "error": "no_phones", "graph": j2}

    phone = phones[0] or {}
    wa_phone_number_id = phone.get("id")
    if not wa_phone_number_id:
        return {"ok": False, "where": "waba_phone_numbers", "error": "missing_phone_number_id", "graph": j2}

    return {
        "ok": True,
        "waba_id": waba_id,
        "wa_phone_number_id": wa_phone_number_id,
        "display_phone_number": phone.get("display_phone_number"),
        "verified_name": phone.get("verified_name"),
    }


@app.get("/settings/whatsapp/connect")
async def whatsapp_connect_callback(request: Request):
    """
    Callback OAuth (Meta redirect) che riceve ?code=...
    Scambia code -> access_token e salva:
      access_token + waba_id + phone_number_id nel DB
    """
    # azienda loggata via JWT/cookie/header
    user = get_current_user(request)
    azienda_id = user.get("azienda_id")
    if not azienda_id:
        return JSONResponse({"ok": False, "error": "azienda_id mancante nel token"}, status_code=401)

    if not META_APP_ID or not META_APP_SECRET or not META_REDIRECT_URI:
        return JSONResponse(
            {
                "ok": False,
                "where": "env_check",
                "META_APP_ID": bool(META_APP_ID),
                "META_APP_SECRET": bool(META_APP_SECRET),
                "META_REDIRECT_URI": META_REDIRECT_URI,
            },
            status_code=500,
        )

    code = request.query_params.get("code")
    if not code:
        return JSONResponse({"ok": False, "error": "missing_code"}, status_code=400)

    # exchange code -> token
    token_url = f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token"
    r = requests.get(
        token_url,
        params={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "redirect_uri": META_REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )

    if r.status_code != 200:
        return JSONResponse({"ok": False, "where": "token_exchange", "status": r.status_code, "details": r.text}, status_code=400)

    token_data = r.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return JSONResponse({"ok": False, "where": "token_exchange", "error": "no_access_token", "token_data": token_data}, status_code=400)

    # resolve waba + phone
    res = _resolve_waba_and_phone(access_token)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)

    saved = _save_company_integration_whatsapp(
        azienda_id=azienda_id,
        access_token=access_token,
        waba_id=res["waba_id"],
        wa_phone_number_id=res["wa_phone_number_id"],
        display_phone=res.get("display_phone_number"),
        verified_name=res.get("verified_name"),
    )

    return JSONResponse(saved, status_code=200 if saved.get("ok") else 500)


@app.post("/settings/whatsapp/connect")
async def whatsapp_connect_from_frontend(request: Request, payload: dict = Body(...)):
    print("CONNECT WHATSAPP PAYLOAD:", payload)
    
    """
    Variante: se dal frontend vuoi mandare direttamente un access_token.
    (Funziona per test; in produzione preferisci il flow con code.)
    """
    user = get_current_user(request)
    azienda_id = user.get("azienda_id")
    if not azienda_id:
        return JSONResponse({"ok": False, "error": "azienda_id mancante nel token"}, status_code=401)

    access_token = (payload.get("access_token") or "").strip()
    if not access_token:
        return JSONResponse({"ok": False, "error": "access_token mancante nel payload"}, status_code=400)

    res = _resolve_waba_and_phone(access_token)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)

    saved = _save_company_integration_whatsapp(
        azienda_id=azienda_id,
        access_token=access_token,
        waba_id=res["waba_id"],
        wa_phone_number_id=res["wa_phone_number_id"],
        display_phone=res.get("display_phone_number"),
        verified_name=res.get("verified_name"),
    )

    return JSONResponse(saved, status_code=200 if saved.get("ok") else 500)

class WhatsAppConnectPayload(BaseModel):
    company_id: int
    wa_access_token: str
    wa_phone_number_id: str
    wa_waba_id: str

from fastapi import Form, Request
from fastapi.responses import RedirectResponse
from starlette.responses import JSONResponse
import httpx

@app.post("/settings/whatsapp")
async def settings_whatsapp_save(
    request: Request,
    wa_token: str = Form(...),
    wa_phone_number_id: str = Form(...),
    wa_waba_id: str = Form(...),
):
    # prende l'azienda dall'utente loggato
    user = get_current_user(request)
    azienda_id = user.get("azienda_id")
    if not azienda_id:
        return JSONResponse({"ok": False, "error": "azienda_id mancante nel token"}, status_code=401)

    wa_token = (wa_token or "").strip()
    wa_phone_number_id = (wa_phone_number_id or "").strip()
    wa_waba_id = (wa_waba_id or "").strip()

    if not wa_token or not wa_phone_number_id or not wa_waba_id:
        return JSONResponse({"ok": False, "error": "Campi mancanti"}, status_code=400)

    print("SAVE WHATSAPP FORM:", {
        "azienda_id": azienda_id,
        "wa_phone_number_id": wa_phone_number_id,
        "wa_waba_id": wa_waba_id,
        "token_prefix": wa_token[:10] + "..."
    })

    saved = _save_company_integration_whatsapp(
        azienda_id=azienda_id,
        access_token=wa_token,
        waba_id=wa_waba_id,
        wa_phone_number_id=wa_phone_number_id,
        display_phone=None,
        verified_name=None,
    )

    # torna alla pagina settings (dove hai il form)
    return RedirectResponse("/settings", status_code=303)

@app.post("/settings/whatsapp/connect")
async def settings_whatsapp_connect(request: Request, payload: dict = Body(...)):
    print("CONNECT WHATSAPP PAYLOAD:", payload)

    user = get_current_user(request)
    azienda_id = user.get("azienda_id")
    if not azienda_id:
        return JSONResponse({"ok": False, "error": "azienda_id mancante"}, status_code=401)

    code = (payload.get("code") or "").strip()
    if not code:
        return JSONResponse({"ok": False, "error": "code mancante nel payload"}, status_code=400)

    app_id = os.getenv("META_APP_ID", "").strip()
    app_secret = os.getenv("META_APP_SECRET", "").strip()
    redirect_uri = os.getenv("META_REDIRECT_URI", "").strip()

    if not app_id or not app_secret or not redirect_uri:
        return JSONResponse(
            {"ok": False, "error": "META_APP_ID / META_APP_SECRET / META_REDIRECT_URI mancanti in .env"},
            status_code=500,
        )

    # 1) Scambio CODE -> ACCESS TOKEN (server-side)
    token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
    params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(token_url, params=params)
            data = resp.json()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Errore chiamando Meta oauth: {e}"}, status_code=500)

    if resp.status_code != 200:
        print("META OAUTH ERROR:", data)
        return JSONResponse(
            {"ok": False, "error": data.get("error", data), "where": "oauth_access_token"},
            status_code=400,
        )

    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        return JSONResponse({"ok": False, "error": "Meta non ha restituito access_token"}, status_code=400)

    # 2) Con access_token ricavo WABA ID + Phone Number ID
    res = _resolve_waba_and_phone(access_token)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)

    # 3) Salvo tutto nel DB
    saved = _save_company_integration_whatsapp(
        azienda_id=azienda_id,
        access_token=access_token,
        waba_id=res["waba_id"],
        wa_phone_number_id=res["wa_phone_number_id"],
        display_phone=res.get("display_phone_number"),
        verified_name=res.get("verified_name"),
    )

    return JSONResponse(saved, status_code=200 if saved.get("ok") else 500)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login_web(email: str = Form(...), password: str = Form(...)):
    # 1) verifica credenziali (usa la tua funzione DB)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            row = get_user_by_email(cur, email.lower().strip())
            if not row:
                raise HTTPException(status_code=401, detail="Invalid credentials")

            user_id, azienda_id, email_db, password_hash, role = row
            if not pwd_context.verify(password, password_hash):
                raise HTTPException(status_code=401, detail="Invalid credentials")

            token = create_access_token({
                "sub": str(user_id),
                "azienda_id": str(azienda_id),
                "email": email_db,
                "role": role,
            })
    finally:
        conn.close()

    # 2) cookie + redirect
    resp = RedirectResponse(url="/preventivi", status_code=302)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,   # metti True solo quando sarai in https
        max_age=60*60*24*7  # 7 giorni, così “tu entri sempre”
    )
    return resp

@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
def register(
    request: Request,
    company_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    conn = get_conn()
    cur = conn.cursor()

    password_hash = hash_password(password)

    # 1️⃣ crea azienda
    cur.execute(
        "INSERT INTO aziende (nome) VALUES (%s) RETURNING id",
        (company_name,)
    )
    azienda_id = cur.fetchone()[0]

    # 2️⃣ crea utente collegato
    cur.execute(
        """
        INSERT INTO utenti (azienda_id, email, password_hash, role)
        VALUES (%s, %s, %s, 'admin')
        """,
        (azienda_id, email, password_hash)
    )

    # 3️⃣ crea settings default
    cur.execute(
        "INSERT INTO azienda_settings (azienda_id) VALUES (%s)",
        (azienda_id,)
    )

    conn.commit()
    conn.close()

    return templates.TemplateResponse(
        "login.html",
        {"request": request}     
    )

@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_get(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})

import secrets
from datetime import datetime, timedelta, timezone

def generate_code_6():
    return f"{secrets.randbelow(1_000_000):06d}"

@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_post(request: Request, email: str = Form(...)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM utenti WHERE email=%s AND is_active=true", (email,))
    row = cur.fetchone()

    # Sempre risposta "OK" anche se email non esiste (anti-enumeration)
    if not row:
        conn.close()
        return {"ok": True}

    user_id = row["id"]
    code = generate_code_6()

    code_hash = hash_password(code)  # usa il tuo hash_password

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # invalida vecchi codici non usati (pulizia)
    cur.execute("""
      UPDATE password_reset_codes
      SET used_at = now()
      WHERE user_id=%s AND used_at IS NULL
    """, (user_id,))

    cur.execute("""
      INSERT INTO password_reset_codes (user_id, code_hash, expires_at)
      VALUES (%s, %s, %s)
    """, (user_id, code_hash, expires_at))

    conn.commit()
    conn.close()

    # QUI mandi email col codice
    send_email(
        to=email,
        subject="Codice reset password",
        body=f"Il tuo codice è: {code}\nScade tra 10 minuti."
    )

    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "message": "Se l'email esiste, abbiamo inviato un codice."}
    )

@app.post("/reset-password")
def reset_password(
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...)
):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM utenti WHERE email=%s AND is_active=true", (email,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=400, detail="Codice non valido o scaduto")

    user_id = user["id"]

    cur.execute("""
      SELECT id, code_hash, expires_at
      FROM password_reset_codes
      WHERE user_id=%s AND used_at IS NULL
      ORDER BY created_at DESC
      LIMIT 1
    """, (user_id,))
    pr = cur.fetchone()
    if not pr:
        conn.close()
        raise HTTPException(status_code=400, detail="Codice non valido o scaduto")

    # scadenza
    if pr["expires_at"] < datetime.now(timezone.utc):
        conn.close()
        raise HTTPException(status_code=400, detail="Codice non valido o scaduto")

    # verifica codice
    if not verify_password(code, pr["code_hash"]):  # devi avere verify_password
        conn.close()
        raise HTTPException(status_code=400, detail="Codice non valido o scaduto")

    new_hash = hash_password(new_password)

    cur.execute("UPDATE utenti SET password_hash=%s WHERE id=%s", (new_hash, user_id))
    cur.execute("UPDATE password_reset_codes SET used_at=now() WHERE id=%s", (pr["id"],))

    conn.commit()
    
    send_email(
        to=email,
        subject="Password aggiornata",
        body="Ciao,\n\nLa password del tuo account è stata aggiornata correttamente.\n\nSe non sei stato tu, contattaci subito.\n"
    )

    conn.close()
    return RedirectResponse(url="/login?reset=ok", status_code=303)

# =====================
# CONFIG
# =====================

DB = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "leadai",
    "user": "leadai",
    "password": "leadai",
}

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


def get_conn():
    return psycopg2.connect(**DB)

def create_access_token(data: dict, expires_minutes: int = JWT_EXPIRE_MIN) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


def get_user_by_email(cur, email: str):
    cur.execute(
        """
        SELECT id, azienda_id, email, password_hash, role
        FROM utenti
        WHERE email = %s
        LIMIT 1
        """,
        (email,),
    )
    return cur.fetchone()

# =====================
# MODELLI
# =====================

class Inbound(BaseModel):
    contact_key: str
    channel: str
    text: str
    telefono: Optional[str] = None
    email: Optional[str] = None

class AutoReplySettingsIn(BaseModel):
    auto_reply_enabled: bool = True
    reply_start: time
    reply_end: time
    reply_mode: str  # "window" oppure "fixed"

# =====================
# ROUTE BASE
# =====================

@app.get("/")
def root():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}

@app.get("/settings/auto-reply")
def get_auto_reply_settings(azienda_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COALESCE(auto_reply_enabled, true),
                    COALESCE(reply_start, '09:00'::time),
                    COALESCE(reply_end,   '19:00'::time),
                    COALESCE(reply_mode,  'window')
                FROM company_settings
                WHERE azienda_id = %s
                LIMIT 1
            """, (azienda_id,))
            row = cur.fetchone()

            if not row:
                # default se non esiste riga
                return {
                    "auto_reply_enabled": True,
                    "reply_start": "09:00",
                    "reply_end": "19:00",
                    "reply_mode": "window"
                }

            auto_enabled, reply_start, reply_end, reply_mode = row
            return {
                "auto_reply_enabled": bool(auto_enabled),
                "reply_start": reply_start.strftime("%H:%M"),
                "reply_end": reply_end.strftime("%H:%M"),
                "reply_mode": reply_mode
            }
    finally:
        conn.close()

@app.post("/settings/auto-reply")
def save_auto_reply_settings(payload: AutoReplySettingsIn):
    if payload.reply_mode not in ("window", "fixed"):
        raise HTTPException(status_code=400, detail="reply_mode deve essere 'window' o 'fixed'")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO company_settings (azienda_id, auto_reply_enabled, reply_start, reply_end, reply_mode)
                VALUES (%s, %s, %s::time, %s::time, %s)
                ON CONFLICT (azienda_id) DO UPDATE
                SET auto_reply_enabled = EXCLUDED.auto_reply_enabled,
                    reply_start = EXCLUDED.reply_start,
                    reply_end = EXCLUDED.reply_end,
                    reply_mode = EXCLUDED.reply_mode,
                    updated_at = NOW()
            """, (
                payload.azienda_id,
                payload.auto_reply_enabled,
                payload.reply_start,
                payload.reply_end,
                payload.reply_mode
            ))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

# =====================
# INBOUND (CHAT / WHATSAPP / ETC)
# =====================

@app.post("/inbound")
def inbound(payload: Inbound):

    # 0) testo valido + rilevamento modalità test per-request
    raw_text = (payload.text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="testo vuoto")

    is_test = "[TEST]" in raw_text
    incoming_text = raw_text.replace("[TEST]", "").strip()
    if is_test:
        print(f"[TEST_MODE ON: bypass anti-spam] contact_key={payload.contact_key}", flush=True)

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            # 1) azienda_id (1 sola volta)
            cur.execute(
                "SELECT id FROM aziende WHERE nome = %s LIMIT 1",
                ("Expert Infissi",)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="azienda non trovata")
            azienda_id = row[0]

            # 2) settings (company_settings) (1 sola volta)
            cur.execute("""
                SELECT
                    COALESCE(auto_reply_enabled, true),
                    COALESCE(reply_start, '09:00'::time),
                    COALESCE(reply_end,   '19:00'::time),
                    COALESCE(reply_mode,  'window')
                FROM company_settings
                WHERE azienda_id = %s
                LIMIT 1
            """, (azienda_id,))

            row = cur.fetchone()
            auto_enabled, reply_start, reply_end, reply_mode = (
                row if row else (True, time(9, 0), time(19, 0), "window")
            )

            # 3) se disabilitato -> skippa
            if not auto_enabled:
                conn.commit()
                return {"ok": True, "skipped": True, "reason": "auto_reply_disabled"}

            # 4) contact_key normalizzato
            contact_key = normalize_contact_key(payload.channel, payload.contact_key)

            # 5) upsert contatto
            cur.execute("""
                INSERT INTO lead_contacts (azienda_id, contact_key, telefono, email)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (contact_key) DO UPDATE
                SET telefono = COALESCE(EXCLUDED.telefono, lead_contacts.telefono),
                    email    = COALESCE(EXCLUDED.email, lead_contacts.email),
                    updated_at = NOW();
            """, (azienda_id, contact_key, payload.telefono, payload.email))

            # 6) stato (NON sovrascrive fase)
            cur.execute("""
                INSERT INTO lead_status (azienda_id, contact_key, fase_preventivo, esito_cliente, last_channel)
                VALUES (%s, %s, 'nuovo', 'in_attesa', %s)
                ON CONFLICT (contact_key) DO UPDATE
                SET last_channel = EXCLUDED.last_channel,
                    updated_at = NOW();
            """, (azienda_id, contact_key, payload.channel))

            # 7) call engine
            print(">>> CALL ENGINE", incoming_text, flush=True)
            reply_text = process_text_message(conn, contact_key, incoming_text)
            print("<<< ENGINE RETURN:", repr(reply_text), flush=True)

            # se l'engine decide davvero di non rispondere
            if reply_text is None:
                conn.commit()
                return {"ok": True, "skipped": True, "reason": "engine_none"}

            # fallback se stringa vuota
            if not str(reply_text).strip():
                reply_text = "Ciao! 🙂 Dimmi pure come posso aiutarti."

            # 8) calcolo send_after (orario di risposta)
            now_dt = datetime.utcnow()
            now_t = now_dt.time()

            def next_start(dt_now: datetime, start_t: time) -> datetime:
                target_date = dt_now.date()
                if dt_now.time() > start_t:
                    target_date = target_date + timedelta(days=1)
                return datetime.combine(target_date, start_t)

            if reply_mode == "fixed":
                # sempre al prossimo reply_start
                send_after = next_start(now_dt, reply_start)
            else:
                # window: se dentro fascia rispondi subito, altrimenti prossimo start
                if reply_start <= reply_end:
                    dentro_fascia = (reply_start <= now_t <= reply_end)
                else:
                    # fascia che attraversa mezzanotte
                    dentro_fascia = (now_t >= reply_start or now_t <= reply_end)

                send_after = now_dt if dentro_fascia else next_start(now_dt, reply_start)

            # 9) anti-spam: stessa risposta normalizzata per lo stesso contact_key
            #    [TEST] nel testo → bypassa completamente, body_norm non salvato
            if is_test:
                enqueue_body_norm = None
            else:
                enqueue_body_norm = normalize_text(reply_text)
                cur.execute("""
                    SELECT 1 FROM outbound_messages
                    WHERE contact_key = %s
                      AND body_norm = %s
                      AND status IN ('queued', 'sent')
                      AND send_after >= NOW() - interval '3600 seconds'
                    LIMIT 1
                """, (contact_key, enqueue_body_norm))
                if cur.fetchone():
                    conn.commit()
                    return {"ok": True, "skipped": True, "reason": "anti_spam"}

            # 10) insert outbound (usa send_after calcolato)
            cur.execute("""
                INSERT INTO outbound_messages
                (azienda_id, channel, contact_key, body, body_norm, status, send_after)
                VALUES (%s, %s, %s, %s, %s, 'queued', %s)
            """, (azienda_id, payload.channel, contact_key, reply_text, enqueue_body_norm, send_after))

        conn.commit()
        return {"ok": True, "send_after": send_after.isoformat()}

    finally:
        conn.close()

class AutoReplySettingsIn(BaseModel):
    azienda_id: int
    auto_reply_enabled: bool
    reply_start: str  # "09:00"
    reply_end: str    # "19:00"
    reply_mode: str   # "window" oppure "fixed"


@app.post("/settings/whatsapp")
def settings_whatsapp_save(
    wa_phone_number_id: str = Form(...),
    wa_access_token: str = Form(...),
    user=Depends(get_current_user),
):
    azienda_id = user["azienda_id"]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE company_integrations
                SET wa_phone_number_id = %s,
                    wa_access_token = %s,
                    updated_at = NOW()
                WHERE azienda_id = %s
                """,
                (wa_phone_number_id.strip(), wa_access_token.strip(), azienda_id),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/settings/whatsapp", status_code=303)

@app.post("/auth/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Swagger manda: username + password (form-data)
    email = (form_data.username or "").lower().strip()
    password = form_data.password or ""

    if not email or not password:
        raise HTTPException(status_code=422, detail="Missing credentials")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            row = get_user_by_email(cur, email)
            if not row:
                raise HTTPException(status_code=401, detail="Invalid credentials")

            user_id, azienda_id, email_db, password_hash, role = row

            # Verifica lunghezza password (limite bcrypt 72 byte)
            if len(password.encode("utf-8")) > 72:
             raise HTTPException(status_code=400, detail="Password troppo lunga")

            # Verifica password bcrypt
            if not pwd_context.verify(password, password_hash):
             raise HTTPException(status_code=401, detail="Invalid credentials")
            
            token = create_access_token(
                {
                    "sub": str(user_id),
                    "azienda_id": str(azienda_id),
                    "email": email_db,
                    "role": role,
                }
            )

            return {"access_token": token, "token_type": "bearer"}
    finally:
        conn.close()

# =====================
# FASI PREVENTIVO
# =====================

@app.post("/lead/{id}/fase/in_preparazione")
def fase_in_preparazione(id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE lead_status
                SET fase_preventivo = 'in_preparazione',
                    updated_at = NOW()
                WHERE contact_key = (
                    SELECT contact_key FROM lead_contacts WHERE id = %s
                )
            """, (id,))
        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)
    finally:
        conn.close()


@app.post("/lead/{id}/fase/inviato")
def fase_inviato(id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE lead_status
                SET fase_preventivo = 'inviato',
                    updated_at = NOW()
                WHERE contact_key = (
                    SELECT contact_key FROM lead_contacts WHERE id = %s
                )
            """, (id,))
        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)
    finally:
        conn.close()


@app.post("/lead/{id}/fase/nuovo")
def fase_nuovo(id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE lead_status
                SET fase_preventivo = 'nuovo',
                    updated_at = NOW()
                WHERE contact_key = (
                    SELECT contact_key FROM lead_contacts WHERE id = %s
                )
            """, (id,))
        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)
    finally:
        conn.close()


# =====================
# ESITO CLIENTE (SOLO SE INVIATO)
# =====================

@app.post("/lead/{contact_key}/esito/{esito}")
def set_esito(contact_key: str, esito: str):
    if esito not in ("accettato", "rifiutato", "in_attesa"):
        raise HTTPException(status_code=400, detail="esito non valido")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fase_preventivo
                FROM lead_status
                WHERE contact_key = %s
            """, (contact_key,))
            row = cur.fetchone()

            if not row or row[0] != "inviato":
                raise HTTPException(
                    status_code=400,
                    detail="Esito impostabile solo se fase = inviato"
                )

            cur.execute("""
                UPDATE lead_status
                SET esito_cliente = %s,
                    updated_at = NOW()
                WHERE contact_key = %s
            """, (esito, contact_key))

        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)

    finally:
        conn.close()

@app.post("/lead/{contact_key}/fase/nuovo")
def fase_nuovo_ck(contact_key: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lead_status (contact_key, fase_preventivo, updated_at)
                VALUES (%s, 'nuovo', NOW())
                ON CONFLICT (contact_key) DO UPDATE
                SET fase_preventivo = 'nuovo',
                    updated_at = NOW();
            """, (contact_key,))
        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)
    finally:
        conn.close()


@app.post("/lead/{contact_key}/fase/in_preparazione")
def fase_in_preparazione_ck(contact_key: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lead_status (contact_key, fase_preventivo, updated_at)
                VALUES (%s, 'in_preparazione', NOW())
                ON CONFLICT (contact_key) DO UPDATE
                SET fase_preventivo = 'in_preparazione',
                    updated_at = NOW();
            """, (contact_key,))
        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)
    finally:
        conn.close()

@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp

@app.post("/lead/{contact_key}/fase/inviato")
def fase_inviato_ck(contact_key: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lead_status (contact_key, fase_preventivo, updated_at)
                VALUES (%s, 'inviato', NOW())
                ON CONFLICT (contact_key) DO UPDATE
                SET fase_preventivo = 'inviato',
                    updated_at = NOW();
            """, (contact_key,))
        conn.commit()
        return RedirectResponse("/preventivi", status_code=303)
    finally:
        conn.close()

# =====================
# PAGINE HTML
# =====================

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp

@app.get("/auth/me")
def me(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/home", status_code=303)

import uuid
from fastapi import Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

@app.get("/settings/whatsapp", response_class=HTMLResponse)
def settings_whatsapp(request: Request, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT wa_webhook_key, wa_verify_token, wa_phone_number_id
                FROM company_integrations
                WHERE azienda_id = %s
                """,
                (azienda_id,),
            )
            row = cur.fetchone()

            if not row:
                # creo record base per l’azienda (così possiamo mostrare webhook url + token)
                webhook_key = str(uuid.uuid4())
                verify_token = str(uuid.uuid4())  # token per verifica (copia/incolla su Meta)
                cur.execute(
                    """
                    INSERT INTO company_integrations (azienda_id, wa_webhook_key, wa_verify_token)
                    VALUES (%s, %s, %s)
                    """,
                    (azienda_id, webhook_key, verify_token),
                )
                conn.commit()

                wa_webhook_key, wa_verify_token, wa_phone_number_id = webhook_key, verify_token, None
            else:
                wa_webhook_key, wa_verify_token, wa_phone_number_id = row[0], row[1], row[2]
    finally:
        conn.close()

    # URL webhook: in locale sarà http://127... ma su internet userai dominio/ngrok
    return templates.TemplateResponse(
        "settings_whatsapp.html",
        {
            "request": request,
            "user": user,
            "wa_webhook_key": wa_webhook_key,
            "wa_verify_token": wa_verify_token,
            "wa_phone_number_id": wa_phone_number_id,
        },
    )

@app.get("/webhook/whatsapp/{webhook_key}", response_class=PlainTextResponse)
def wa_webhook_verify(webhook_key: str, request: Request):
    print("WEBHOOK #4 HIT")
    
    q = request.query_params
    mode = q.get("hub.mode")
    token = q.get("hub.verify_token")
    challenge = q.get("hub.challenge")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT wa_verify_token FROM company_integrations WHERE wa_webhook_key = %s",
                (webhook_key,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Webhook key not found")

    expected = row[0]
    if mode == "subscribe" and token == expected and challenge:
        return challenge

    raise HTTPException(status_code=403, detail="Verification failed")

@app.get("/home", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user)):
    # user contiene payload JWT (email, azienda_id, ecc.)
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "user": user}
    )

@app.get("/preventivi", response_class=HTMLResponse)
def preventivi(request: Request, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            azienda_id = user["azienda_id"]
            print("AZIENDA_ID:", azienda_id)
            sql = """
                SELECT
                    c.id AS contact_id,
                    c.contact_key,
                    c.nome_cliente,
                    c.email,
                    c.telefono,
                    s.fase_preventivo,
                    s.esito_cliente,
                    s.last_channel,
                    s.updated_at
                FROM lead_contacts c
                LEFT JOIN lead_status s
                    ON s.contact_key = c.contact_key AND s.azienda_id = c.azienda_id
                    AND s.azienda_id = c.azienda_Id
                WHERE c.azienda_id = %s
                ORDER BY c.id DESC
                LIMIT 200;
            """  
            
            cur.execute(sql, (azienda_id,))
            rows = cur.fetchall()

        return templates.TemplateResponse(
            "preventivi.html",
           {"request": request, "rows": rows, "azienda_id": azienda_id}
        )
         
    finally:
        conn.close()

def _get_or_create_settings(cur, azienda_id):
    cur.execute(
        """
        SELECT azienda_id, timezone,
               quiet_hours_start::text AS quiet_hours_start,
               quiet_hours_end::text AS quiet_hours_end,
               auto_reply_enabled, auto_reply_delay_sec, cooldown_sec
        FROM company_settings
        WHERE azienda_id = %s
        """,
        (azienda_id,),
    )
    row = cur.fetchone()

    if row:
        # row è un dict (RealDictCursor)
        return {
            "azienda_id": str(row["azienda_id"]),
            "timezone": row["timezone"],
            "quiet_hours_start": row["quiet_hours_start"],
            "quiet_hours_end": row["quiet_hours_end"],
            "auto_reply_enabled": row["auto_reply_enabled"],
            "auto_reply_delay_sec": row["auto_reply_delay_sec"],
            "cooldown_sec": row["cooldown_sec"],
        }

    cur.execute(
        "INSERT INTO company_settings (azienda_id) VALUES (%s)",
        (azienda_id,),
    )

    return {
        "azienda_id": str(azienda_id),
        "timezone": "Europe/Rome",
        "quiet_hours_start": "19:00",
        "quiet_hours_end": "08:30",
        "auto_reply_enabled": True,
        "auto_reply_delay_sec": 120,
        "cooldown_sec": 1800,
    }

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            settings = _get_or_create_settings(cur, azienda_id)

            cur.execute(
                """
                SELECT id, azienda_id, enabled, channel, priority, keywords, reply_text
                FROM auto_reply_rules
                WHERE azienda_id = %s
                ORDER BY priority ASC, id ASC
                """,
                (azienda_id,),
            )
            rules = cur.fetchall()

        conn.commit()
    finally:
        conn.close()

    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "settings": settings, "rules": rules}
    )


@app.post("/settings")
def settings_save(
    request: Request,
    auto_reply_enabled: str | None = Form(None),
    quiet_hours_start: str = Form(...),
    quiet_hours_end: str = Form(...),
    auto_reply_delay_sec: int = Form(...),
    cooldown_sec: int = Form(...),
    user=Depends(get_current_user),
):
    azienda_id = user["azienda_id"]
    enabled = auto_reply_enabled is not None

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            _get_or_create_settings(cur, azienda_id)

            cur.execute(
                """
                UPDATE company_settings
                SET auto_reply_enabled = %s,
                    quiet_hours_start = %s,
                    quiet_hours_end = %s,
                    auto_reply_delay_sec = %s,
                    cooldown_sec = %s,
                    updated_at = now()
                WHERE azienda_id = %s
                """,
                (enabled, quiet_hours_start, quiet_hours_end, auto_reply_delay_sec, cooldown_sec, azienda_id),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/rules/add")
def rules_add(
    channel: str = Form(...),
    keywords: str = Form(...),
    reply_text: str = Form(...),
    priority: int = Form(100),
    user=Depends(get_current_user),
):
    azienda_id = user["azienda_id"]
    kw_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_reply_rules (azienda_id, channel, priority, keywords, reply_text)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (azienda_id, channel, priority, kw_list, reply_text),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/rules/{rule_id}/toggle")
def rules_toggle(rule_id: int, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE auto_reply_rules
                SET enabled = NOT enabled, updated_at = now()
                WHERE id = %s AND azienda_id = %s
                """,
                (rule_id, azienda_id),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/settings", status_code=303)



@app.post("/settings/rules/{rule_id}/delete")
def rules_delete(rule_id: int, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM auto_reply_rules WHERE id = %s AND azienda_id = %s",
                (rule_id, azienda_id),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/settings", status_code=303)

from fastapi import Form
from starlette.responses import RedirectResponse

@app.post("/preventivi/{contact_key}/toggle-inviato")
def toggle_inviato(contact_key: str, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # leggo fase attuale (se non c'è, la considero 'in_preparazione')
            cur.execute(
                """
                SELECT fase_preventivo
                FROM lead_status
                WHERE azienda_id = %s AND contact_key = %s
                """,
                (azienda_id, contact_key),
            )
            row = cur.fetchone()

            fase_attuale = row[0] if row else "in_preparazione"
            nuova_fase = "in_preparazione" if fase_attuale == "inviato" else "inviato"

            # UPSERT: 1 record solo per (azienda_id, contact_key)
            cur.execute(
                """
                INSERT INTO lead_status (azienda_id, contact_key, fase_preventivo, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (azienda_id, contact_key)
                DO UPDATE SET fase_preventivo = EXCLUDED.fase_preventivo,
                              updated_at = NOW()
                """,
                (azienda_id, contact_key, nuova_fase),
            )

        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/preventivi", status_code=303)

@app.post("/test/enqueue")
def test_enqueue(
    contact_key: str = Form(...),
    body: str = Form(...),
    delay_minutes: int = Form(0),
    channel: str = Form("whatsapp"),
    user=Depends(get_current_user),
):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outbound_messages
                (azienda_id, channel, contact_key, body, status, send_after)
                VALUES
                (%s, %s, %s, %s, 'queued', NOW() + (%s || ' minutes')::interval)
                """,
                (azienda_id, channel, contact_key, body, delay_minutes),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/settings", status_code=303)

@app.get("/entrate", response_class=HTMLResponse)
def entrate(request: Request):
    return templates.TemplateResponse("entrate.html", {"request": request})

# =====================
# VENOMAPP /api/ ENDPOINTS
# =====================

class LoginJsonIn(BaseModel):
    email: str
    password: str

class UpdateContactIn(BaseModel):
    nome_cliente: Optional[str] = None

class SendMessageIn(BaseModel):
    text: str

class NewChatIn(BaseModel):
    phone: str
    nome: Optional[str] = None

class CompanySettingsIn(BaseModel):
    business_phone: Optional[str] = None


@app.post("/api/auth/login")
def api_login(body: LoginJsonIn):
    email = (body.email or "").lower().strip()
    password = body.password or ""
    if not email or not password:
        raise HTTPException(status_code=422, detail="Missing credentials")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            row = get_user_by_email(cur, email)
            if not row:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            user_id, azienda_id, email_db, password_hash, role = row
            if not pwd_context.verify(password, password_hash):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            cur.execute("SELECT nome FROM aziende WHERE id = %s LIMIT 1", (azienda_id,))
            az = cur.fetchone()
            azienda_nome = az[0] if az else ""
            token = create_access_token({
                "sub": str(user_id),
                "azienda_id": str(azienda_id),
                "email": email_db,
                "role": role,
            })
    finally:
        conn.close()

    resp = JSONResponse({
        "ok": True,
        "user": {
            "email": email_db,
            "azienda_id": str(azienda_id),
            "role": role,
            "azienda_nome": azienda_nome,
        }
    })
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
    )
    return resp


@app.post("/api/auth/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("access_token")
    return resp


@app.get("/api/me")
def api_me(user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT nome FROM aziende WHERE id = %s LIMIT 1", (azienda_id,))
            az = cur.fetchone()
            azienda_nome = az[0] if az else ""
            cur.execute(
                "SELECT business_phone FROM company_settings WHERE azienda_id = %s LIMIT 1",
                (azienda_id,),
            )
            cs = cur.fetchone()
            business_phone = cs[0] if cs else None
    finally:
        conn.close()
    return {
        "user_id": user.get("sub"),
        "email": user.get("email"),
        "role": user.get("role"),
        "azienda_id": azienda_id,
        "azienda_nome": azienda_nome,
        "business_phone": business_phone,
    }


@app.get("/api/chats")
def api_chats(user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.contact_key,
                    c.nome_cliente,
                    c.telefono,
                    c.profile_image_url,
                    s.fase_preventivo,
                    s.esito_cliente,
                    s.updated_at AS status_updated_at,
                    GREATEST(
                        (SELECT created_at FROM wa_inbound_messages
                         WHERE from_wa = LTRIM(c.contact_key, 'wa:+')
                         ORDER BY created_at DESC LIMIT 1),
                        (SELECT send_after FROM outbound_messages
                         WHERE contact_key = c.contact_key
                         ORDER BY id DESC LIMIT 1)
                    ) AS last_at,
                    COALESCE(
                        (SELECT text FROM wa_inbound_messages
                         WHERE from_wa = LTRIM(c.contact_key, 'wa:+')
                         ORDER BY created_at DESC LIMIT 1),
                        (SELECT body FROM outbound_messages
                         WHERE contact_key = c.contact_key
                         ORDER BY id DESC LIMIT 1)
                    ) AS last_message,
                    (SELECT COUNT(*) FROM wa_inbound_messages
                     WHERE from_wa = LTRIM(c.contact_key, 'wa:+')
                       AND read_at IS NULL) AS unread_count
                FROM lead_contacts c
                LEFT JOIN lead_status s
                    ON s.contact_key = c.contact_key
                   AND s.azienda_id = c.azienda_id
                WHERE c.azienda_id = %s
                ORDER BY last_at DESC NULLS LAST
                LIMIT 100
                """,
                (azienda_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/api/chats/{contact_key:path}/messages")
def api_messages(contact_key: str, user=Depends(get_current_user)):
    user_azienda_id = user["azienda_id"]
    canonical_key = normalize_contact_key("whatsapp", contact_key)
    phone = phone_from_key(canonical_key)
    canonical_plus = f"wa:+{phone}"

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Same smart lookup as api_send: find the azienda that owns WA credentials
            # for this contact. outbound_messages are stored under that azienda_id,
            # which may differ from the logged-in user's azienda_id.
            cur.execute(
                """
                SELECT ci.azienda_id
                FROM wa_inbound_messages wim
                JOIN company_integrations ci
                    ON ci.wa_phone_number_id = wim.phone_number_id
                   AND ci.channel = 'whatsapp'
                   AND ci.is_enabled = TRUE
                WHERE wim.from_wa = %s
                ORDER BY wim.created_at DESC
                LIMIT 1
                """,
                (phone,),
            )
            row = cur.fetchone()
            send_azienda_id = row[0] if row else user_azienda_id

            # Use both azienda IDs so outbound messages are always found,
            # even when the WA-credentials company ≠ logged-in user's company.
            azienda_ids = tuple({user_azienda_id, send_azienda_id})

            cur.execute(
                """
                SELECT 'in' AS direction,
                       msg_id AS id,
                       text AS body,
                       created_at AS ts,
                       CASE WHEN read_at IS NULL THEN 'unread' ELSE 'read' END AS status,
                       COALESCE(msg_type, 'text') AS msg_type,
                       local_path AS media_url,
                       mime_type,
                       filename
                FROM wa_inbound_messages
                WHERE from_wa = %s
                UNION ALL
                SELECT 'out' AS direction,
                       id::text AS id,
                       body,
                       COALESCE(sent_at, send_after) AS ts,
                       status,
                       COALESCE(msg_type, 'text') AS msg_type,
                       local_path AS media_url,
                       mime_type,
                       filename
                FROM outbound_messages
                WHERE contact_key IN (%s, %s)
                  AND azienda_id IN %s
                ORDER BY ts ASC NULLS LAST
                LIMIT 200
                """,
                (phone, canonical_key, canonical_plus, azienda_ids),
            )
            rows = cur.fetchall()

    finally:
        conn.close()

    print(f"[DEBUG api_messages] phone={repr(phone)} send_az={send_azienda_id} rows={len(rows)}", flush=True)
    return [
        {
            "direction": r[0], "id": r[1], "body": r[2],
            "ts": r[3].isoformat() if r[3] else None, "status": r[4],
            "msg_type": r[5] or "text",
            "media_url": r[6],
            "mime_type": r[7],
            "filename": r[8],
        }
        for r in rows
    ]


@app.post("/api/chats/{contact_key:path}/send")
def api_send(contact_key: str, body: SendMessageIn, user=Depends(get_current_user)):
    user_azienda_id = user["azienda_id"]
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Empty message")
    canonical_key = normalize_contact_key("whatsapp", contact_key)
    phone = phone_from_key(canonical_key)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Find the azienda that actually owns WA credentials for this contact.
            # Strategy: find the phone_number_id that received inbound from this contact,
            # then look up which company_integrations row owns that phone_number_id.
            # Falls back to the logged-in user's azienda_id if none found.
            cur.execute(
                """
                SELECT ci.azienda_id
                FROM wa_inbound_messages wim
                JOIN company_integrations ci
                    ON ci.wa_phone_number_id = wim.phone_number_id
                   AND ci.channel = 'whatsapp'
                   AND ci.is_enabled = TRUE
                WHERE wim.from_wa = %s
                ORDER BY wim.created_at DESC
                LIMIT 1
                """,
                (phone,),
            )
            row = cur.fetchone()
            send_azienda_id = row[0] if row else user_azienda_id
            print(f"[DEBUG api_send] contact={repr(canonical_key)} phone={phone} "
                  f"user_az={user_azienda_id} send_az={send_azienda_id}", flush=True)

            cur.execute(
                """
                INSERT INTO outbound_messages
                    (azienda_id, channel, contact_key, body, status, send_after)
                VALUES (%s, 'whatsapp', %s, %s, 'queued', NOW())
                RETURNING id
                """,
                (send_azienda_id, canonical_key, text),
            )
            msg_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "id": msg_id}


@app.post("/api/chats/{contact_key:path}/send-media")
async def api_send_media(
    contact_key: str,
    file: UploadFile = File(...),
    caption: str = Form(default=""),
    user=Depends(get_current_user),
):
    """
    Upload a media file → Meta media_id → enqueue in outbound_messages.
    Accepts: image/jpeg, image/png, image/webp, application/pdf, audio/ogg, audio/mpeg, video/mp4
    """
    user_azienda_id = user["azienda_id"]
    canonical_key = normalize_contact_key("whatsapp", contact_key)
    phone = phone_from_key(canonical_key)

    mime = file.content_type or "application/octet-stream"
    fname = file.filename or "upload"

    # Determine WhatsApp media type from MIME
    _mime_to_wa = {
        "image/jpeg": "image", "image/png": "image", "image/webp": "image", "image/gif": "image",
        "video/mp4": "video", "video/3gp": "video",
        "audio/ogg": "audio", "audio/mpeg": "audio", "audio/aac": "audio",
        "application/pdf": "document",
        "application/vnd.ms-excel": "document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
        "application/msword": "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    }
    wa_type = _mime_to_wa.get(mime)
    if not wa_type:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {mime}")

    file_bytes = await file.read()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ci.azienda_id, ci.wa_access_token, ci.wa_phone_number_id
                FROM wa_inbound_messages wim
                JOIN company_integrations ci
                    ON ci.wa_phone_number_id = wim.phone_number_id
                   AND ci.channel = 'whatsapp'
                   AND ci.is_enabled = TRUE
                WHERE wim.from_wa = %s
                ORDER BY wim.created_at DESC
                LIMIT 1
                """,
                (phone,),
            )
            row = cur.fetchone()
            if row:
                send_azienda_id, wa_token, wa_phone_number_id = row
            else:
                # Fall back to user's company credentials
                send_azienda_id = user_azienda_id
                cur.execute(
                    """
                    SELECT wa_access_token, wa_phone_number_id
                    FROM company_integrations
                    WHERE azienda_id = %s AND channel = 'whatsapp' AND is_enabled = TRUE
                    LIMIT 1
                    """,
                    (user_azienda_id,),
                )
                cred_row = cur.fetchone()
                if not cred_row:
                    raise HTTPException(status_code=422, detail="No WhatsApp credentials found")
                wa_token, wa_phone_number_id = cred_row

        # Save file locally FIRST — so we always have a local_path regardless of Meta outcome
        date_str = datetime.utcnow().strftime("%Y%m%d")
        ext = (fname.rsplit(".", 1)[-1] if fname and "." in fname else _ext_from_mime(mime))
        out_dir = UPLOADS_DIR / "outbound" / str(send_azienda_id) / date_str
        out_dir.mkdir(parents=True, exist_ok=True)
        # Use a temporary name; will rename to media_id.ext after Meta responds
        import uuid as _uuid
        tmp_name = f"{_uuid.uuid4().hex}.{ext}"
        tmp_dest = out_dir / tmp_name
        tmp_dest.write_bytes(file_bytes)
        print(f"[SEND-MEDIA] saved locally → {tmp_dest} ({len(file_bytes)}B)", flush=True)

        # Upload to Meta
        print(f"[SEND-MEDIA] uploading fname={fname!r} mime={mime!r} size={len(file_bytes)}B "
              f"phone_id={wa_phone_number_id}", flush=True)
        media_id = _wa_upload_media(file_bytes, mime, fname, wa_token, wa_phone_number_id, GRAPH_VERSION)
        print(f"[SEND-MEDIA] Meta upload OK → media_id={media_id!r}", flush=True)

        # Rename local file to media_id.ext for stable reference
        final_name = f"{media_id}.{ext}"
        final_dest = out_dir / final_name
        tmp_dest.replace(final_dest)  # replace() is atomic and works on Windows even if dest exists
        local_path = f"/uploads/outbound/{send_azienda_id}/{date_str}/{final_name}"
        print(f"[SEND-MEDIA] local_path={local_path!r}", flush=True)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outbound_messages
                    (azienda_id, channel, contact_key, body, status, send_after,
                     msg_type, media_id, mime_type, filename, caption, local_path)
                VALUES (%s, 'whatsapp', %s, %s, 'queued', NOW(),
                        %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (send_azienda_id, canonical_key, caption or f"[{wa_type}]",
                 wa_type, media_id, mime, fname, caption or None, local_path),
            )
            msg_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "id": msg_id, "media_id": media_id, "msg_type": wa_type, "local_path": local_path}


@app.post("/api/chats/new")
def api_new_chat(body: NewChatIn, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    phone = (body.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=422, detail="Phone required")

    contact_key = normalize_contact_key("whatsapp", phone)
    nome = body.nome or phone

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lead_contacts (azienda_id, contact_key, telefono, nome_cliente)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (contact_key) DO UPDATE
                    SET telefono = EXCLUDED.telefono,
                        updated_at = now()
                RETURNING id
                """,
                (azienda_id, contact_key, phone, nome),
            )
            contact_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO lead_status (azienda_id, contact_key, fase_preventivo, last_channel, updated_at)
                VALUES (%s, %s, 'nuovo', 'whatsapp', now())
                ON CONFLICT (contact_key) DO NOTHING
                """,
                (azienda_id, contact_key),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "contact_key": contact_key, "id": contact_id}


@app.post("/api/chats/{contact_key:path}/mark_read")
def api_mark_read(contact_key: str, user=Depends(get_current_user)):
    phone = phone_from_key(normalize_contact_key("whatsapp", contact_key))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE wa_inbound_messages
                SET read_at = NOW()
                WHERE from_wa = %s AND read_at IS NULL
                """,
                (phone,),
            )
            updated = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "marked": updated}


@app.patch("/api/chats/{contact_key:path}/contact")
def api_update_contact(contact_key: str, body: UpdateContactIn, user=Depends(get_current_user)):
    """Update the display name of a contact (lead_contacts.nome_cliente)."""
    canonical_key = normalize_contact_key("whatsapp", contact_key)
    # Allow update regardless of azienda_id (the contact may belong to the sibling company)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE lead_contacts
                SET nome_cliente = %s, updated_at = now()
                WHERE contact_key = %s
                """,
                (body.nome_cliente, canonical_key),
            )
            updated = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    if updated == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True}


@app.get("/api/settings/company")
def api_get_company_settings(user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT azienda_id, timezone, quiet_hours_start, quiet_hours_end,
                       auto_reply_enabled, auto_reply_delay_sec, cooldown_sec, business_phone
                FROM company_settings
                WHERE azienda_id = %s
                LIMIT 1
                """,
                (azienda_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return {"azienda_id": azienda_id, "business_phone": None}
    return dict(row)


@app.post("/api/settings/company")
def api_save_company_settings(body: CompanySettingsIn, user=Depends(get_current_user)):
    azienda_id = user["azienda_id"]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO company_settings (azienda_id, business_phone)
                VALUES (%s, %s)
                ON CONFLICT (azienda_id) DO UPDATE
                    SET business_phone = EXCLUDED.business_phone,
                        updated_at = now()
                """,
                (azienda_id, body.business_phone),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# =====================
# VENOMAPP STATIC (prod)
# =====================

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="venomapp")

# =====================
# AVVIO
# =====================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)