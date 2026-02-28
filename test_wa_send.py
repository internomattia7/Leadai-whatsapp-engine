"""
Test rapido invio WhatsApp.

Uso:
    python test_wa_send.py +39333XXXXXXX
    python test_wa_send.py +39333XXXXXXX "Messaggio personalizzato"

Legge le credenziali dal DB (company_integrations) per azienda_id=1.
"""

import sys
from dotenv import load_dotenv
load_dotenv()

from leadai_engine import get_conn
from whatsapp_client import send_whatsapp_message

AZIENDA_ID = "af603b86-cd6b-4b59-b69f-bcc4e8d1bc41"


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_wa_send.py +39333XXXXXXX [messaggio]")
        sys.exit(1)

    to = sys.argv[1]
    text = sys.argv[2] if len(sys.argv) > 2 else "Test Lead-AI ✅ Messaggio di prova."

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT wa_access_token, wa_phone_number_id
                FROM company_integrations
                WHERE azienda_id = %s
                  AND channel = 'whatsapp'
                LIMIT 1
                """,
                (AZIENDA_ID,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        print(f"❌ Nessuna integrazione WhatsApp trovata per azienda_id={AZIENDA_ID}")
        print("   Vai su /settings/whatsapp e salva le credenziali prima.")
        sys.exit(1)

    wa_token, wa_phone_number_id = row
    if not wa_token or not wa_phone_number_id:
        print("❌ Credenziali incomplete nel DB (token o phone_number_id mancanti).")
        sys.exit(1)

    print(f"→ Invio a {to} da phone_number_id={wa_phone_number_id}")
    print(f"→ Messaggio: {text!r}")

    try:
        r = send_whatsapp_message(to, text, wa_token, wa_phone_number_id)
        print(f"✅ Inviato. Status={r.status_code} Risposta={r.text}")
    except Exception as e:
        print(f"❌ Errore: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
