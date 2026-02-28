"""
check_waba_subscription.py
--------------------------
Verifica se il WABA è iscritto all'app Meta e, se no, lo iscrive automaticamente.

Uso:
    python scripts/check_waba_subscription.py

Richiede:
    - DB leadai accessibile (legge wa_waba_id e wa_access_token da company_integrations)
    - dotenv con META_APP_ID (opzionale, per display)
"""

import sys
import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v19.0")
META_APP_ID   = os.getenv("META_APP_ID", "")

DB_PARAMS = dict(host="127.0.0.1", dbname="leadai", user="leadai", password="leadai")


def get_credentials():
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT wa_waba_id, wa_access_token
                FROM company_integrations
                WHERE channel = 'whatsapp'
                  AND is_enabled = TRUE
                  AND wa_waba_id IS NOT NULL
                  AND wa_access_token IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        print("❌  Nessuna integrazione WhatsApp attiva con WABA ID trovata in DB.")
        sys.exit(1)

    waba_id, token = row
    return waba_id, token


def check_subscription(waba_id: str, token: str) -> list:
    """GET /{waba_id}/subscribed_apps — restituisce la lista delle app iscritte."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/subscribed_apps"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    print(f"\nGET {url}")
    print(f"→ HTTP {resp.status_code}")
    data = resp.json()
    print(f"→ Response: {data}\n")
    resp.raise_for_status()
    return data.get("data") or []


def subscribe(waba_id: str, token: str) -> dict:
    """POST /{waba_id}/subscribed_apps — iscrive l'app corrente al WABA."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/subscribed_apps"
    resp = requests.post(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    print(f"POST {url}")
    print(f"→ HTTP {resp.status_code}")
    data = resp.json()
    print(f"→ Response: {data}\n")
    resp.raise_for_status()
    return data


def main():
    print(f"META_APP_ID : {META_APP_ID or '(non in .env)'}")
    print(f"GRAPH_VERSION: {GRAPH_VERSION}")

    waba_id, token = get_credentials()
    print(f"WABA_ID     : {waba_id}")
    print(f"Token       : {token[:20]}...")

    # 1) Controlla iscrizioni esistenti
    apps = check_subscription(waba_id, token)

    if apps:
        print(f"✅  WABA già iscritto a {len(apps)} app:")
        for app in apps:
            # Meta returns app details nested under whatsapp_business_api_data
            inner = app.get("whatsapp_business_api_data") or app
            name  = inner.get("name", app.get("name", "?"))
            app_id = inner.get("id", app.get("id", "?"))
            link  = inner.get("link", "")
            print(f"   • {name} (id={app_id}{', link=' + link if link else ''})")
    else:
        print("⚠️   Nessuna app iscritta. Eseguo la subscription automatica...")
        result = subscribe(waba_id, token)
        if result.get("success"):
            print("✅  Subscription completata con successo!")
            print("   Verifica nuovamente...")
            apps2 = check_subscription(waba_id, token)
            if apps2:
                print(f"✅  Ora iscritto a {len(apps2)} app: {apps2}")
            else:
                print("⚠️   La lista è ancora vuota — potrebbe essere necessario")
                print("     verificare i permessi del token (whatsapp_business_management).")
        else:
            print(f"❌  Subscription fallita: {result}")


if __name__ == "__main__":
    main()
