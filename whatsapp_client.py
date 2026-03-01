import os
import time
import requests

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v19.0")

_RETRY_DELAYS = (2, 5, 10)  # seconds between retries


def _retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) up to 4 times with exponential back-off."""
    last_exc = None
    for attempt, delay in enumerate((_RETRY_DELAYS[0], _RETRY_DELAYS[1], _RETRY_DELAYS[2], None)):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if delay is None:
                break
            print(f"[WA RETRY] attempt={attempt+1} error={exc} sleeping={delay}s", flush=True)
            time.sleep(delay)
    raise last_exc


def upload_media_to_wa(
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    wa_token: str,
    phone_number_id: str,
    graph_version: str = None,
) -> str:
    """
    Upload media to Meta's servers.
    Returns the media_id string.
    """
    version = graph_version or GRAPH_VERSION
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/media"

    def _do():
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

    return _retry(_do)


def get_media_url(
    media_id: str,
    wa_token: str,
    graph_version: str = None,
) -> str:
    """
    Retrieve the temporary download URL for a media_id.
    Returns the URL string.
    """
    version = graph_version or GRAPH_VERSION
    url = f"https://graph.facebook.com/{version}/{media_id}"

    def _do():
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {wa_token}"},
            timeout=15,
        )
        print(f"[WA MEDIA URL] media_id={media_id} status={r.status_code}", flush=True)
        r.raise_for_status()
        return r.json()["url"]

    return _retry(_do)


def download_media(media_url: str, wa_token: str) -> bytes:
    """
    Download binary content from a Meta media URL.
    Returns raw bytes.
    """
    def _do():
        r = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {wa_token}"},
            timeout=60,
        )
        r.raise_for_status()
        return r.content

    return _retry(_do)


def send_whatsapp_media(
    to: str,
    wa_token: str,
    phone_number_id: str,
    msg_type: str,
    media_id: str,
    caption: str = None,
    filename: str = None,
    graph_version: str = None,
):
    """
    Send a media message (image, document, audio, video) via WhatsApp Cloud API.
    msg_type must be one of: 'image', 'document', 'audio', 'video'.
    Returns the raw requests.Response.
    """
    version = graph_version or GRAPH_VERSION
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"

    media_obj: dict = {"id": media_id}
    if caption:
        media_obj["caption"] = caption
    if msg_type == "document" and filename:
        media_obj["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": msg_type,
        msg_type: media_obj,
    }

    def _do():
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {wa_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        print(f"[WA SEND MEDIA] to={to} type={msg_type} status={r.status_code} body={r.text[:200]}", flush=True)
        r.raise_for_status()
        return r

    return _retry(_do)


def send_whatsapp_message(
    to: str,
    text: str,
    wa_token: str,
    wa_phone_number_id: str,
    graph_version: str = None,
):
    """
    Invia un messaggio di testo tramite WhatsApp Cloud API (Meta Graph API).

    Args:
        to: numero destinatario con prefisso internazionale (es. "+39333...")
        text: testo del messaggio
        wa_token: access token WhatsApp Business
        wa_phone_number_id: Phone Number ID del mittente (da Meta Developers)
        graph_version: versione Graph API (default da env GRAPH_VERSION)

    Raises:
        requests.HTTPError: se la Graph API restituisce un codice HTTP di errore
    """
    version = graph_version or GRAPH_VERSION
    url = f"https://graph.facebook.com/{version}/{wa_phone_number_id}/messages"

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
    print(f"[WA SEND] to={to} status={r.status_code} body={r.text[:200]}", flush=True)
    r.raise_for_status()
    return r
