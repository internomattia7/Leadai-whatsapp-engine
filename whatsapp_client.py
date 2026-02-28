import os
import requests

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v19.0")


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
