"""
Test end-to-end del flusso outbound WhatsApp.

Cosa fa:
  1. Verifica le credenziali WhatsApp in company_integrations
  2. Inserisce un messaggio di test in outbound_messages (status='queued', send_after=NOW())
  3. Esegue un ciclo del worker (pick up + send + update status)
  4. Mostra il risultato (sent / error)

Uso:
    python test_e2e_outbound.py +39333XXXXXXX
    python test_e2e_outbound.py +39333XXXXXXX "Messaggio personalizzato"
"""

import sys
from dotenv import load_dotenv
load_dotenv()

from leadai_engine import get_conn
from whatsapp_client import send_whatsapp_message

AZIENDA_ID = "af603b86-cd6b-4b59-b69f-bcc4e8d1bc41"


# ──────────────────────────────────────────────
# 1) Verifica credenziali
# ──────────────────────────────────────────────

def check_credentials(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT wa_access_token, wa_phone_number_id, is_enabled
            FROM company_integrations
            WHERE azienda_id = %s AND channel = 'whatsapp'
            LIMIT 1
            """,
            (AZIENDA_ID,),
        )
        return cur.fetchone()


# ──────────────────────────────────────────────
# 2) Inserisce messaggio in coda
# ──────────────────────────────────────────────

def enqueue(conn, contact_key: str, body: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO outbound_messages
                (azienda_id, channel, contact_key, body, status, send_after)
            VALUES
                (%s, 'whatsapp', %s, %s, 'queued', NOW())
            RETURNING id
            """,
            (AZIENDA_ID, contact_key, body),
        )
        msg_id = cur.fetchone()[0]
    conn.commit()
    return msg_id


# ──────────────────────────────────────────────
# 3) Un ciclo del worker
# ──────────────────────────────────────────────

def run_worker_once(conn):
    results = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, azienda_id, channel, contact_key, body
            FROM outbound_messages
            WHERE status = 'queued'
              AND send_after <= NOW()
              AND azienda_id = %s
            ORDER BY id
            LIMIT 5
            FOR UPDATE SKIP LOCKED
            """,
            (AZIENDA_ID,),
        )
        rows = cur.fetchall()

        for msg_id, azienda_id, channel, contact_key, body in rows:
            try:
                # recupera credenziali
                cur.execute(
                    """
                    SELECT wa_access_token, wa_phone_number_id
                    FROM company_integrations
                    WHERE azienda_id = %s AND channel = 'whatsapp' AND is_enabled = TRUE
                    LIMIT 1
                    """,
                    (azienda_id,),
                )
                cred = cur.fetchone()
                if not cred or not cred[0] or not cred[1]:
                    raise RuntimeError("Credenziali WhatsApp mancanti o is_enabled=FALSE")

                wa_token, wa_phone_number_id = cred
                to = contact_key.removeprefix("wa:")

                r = send_whatsapp_message(to, body, wa_token, wa_phone_number_id)

                cur.execute(
                    "UPDATE outbound_messages SET status='sent', sent_at=NOW(), error=NULL WHERE id=%s",
                    (msg_id,),
                )
                results.append({"id": msg_id, "status": "sent", "http": r.status_code})

            except Exception as e:
                cur.execute(
                    "UPDATE outbound_messages SET status='error', error=%s WHERE id=%s",
                    (str(e), msg_id),
                )
                results.append({"id": msg_id, "status": "error", "error": str(e)})

    conn.commit()
    return results


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python test_e2e_outbound.py +39333XXXXXXX [messaggio]")
        sys.exit(1)

    phone = sys.argv[1]
    text  = sys.argv[2] if len(sys.argv) > 2 else "Test Lead-AI ✅ Flusso outbound funzionante."

    # contact_key normalizzato come fa app.py
    contact_key = f"wa:{phone}" if not phone.startswith("wa:") else phone

    conn = get_conn()
    try:
        # ── step 1: credenziali ──
        row = check_credentials(conn)
        if not row:
            print(f"❌ Nessun record in company_integrations per azienda_id={AZIENDA_ID}")
            print("   Vai su /settings/whatsapp e salva le credenziali prima.")
            sys.exit(1)

        wa_token, wa_phone_number_id, is_enabled = row
        token_preview = (wa_token or "")[:12] + "..." if wa_token else "MANCANTE"
        print(f"✔ Credenziali trovate  phone_number_id={wa_phone_number_id}  token={token_preview}  is_enabled={is_enabled}")

        if not wa_token or not wa_phone_number_id:
            print("❌ Token o phone_number_id vuoti nel DB.")
            sys.exit(1)

        if not is_enabled:
            print("⚠ is_enabled=FALSE — il worker reale salterebbe questo record.")
            print("  Il test continua comunque per verificare l'invio.")

        # ── step 2: accoda ──
        msg_id = enqueue(conn, contact_key, text)
        print(f"✔ Messaggio accodato   id={msg_id}  to={contact_key}")
        print(f"  body={text!r}")

        # ── step 3: worker ──
        print("→ Esecuzione ciclo worker...")
        results = run_worker_once(conn)

        # ── step 4: risultato ──
        if not results:
            print("⚠ Nessun messaggio processato (la query non ha trovato righe).")
            sys.exit(1)

        for r in results:
            if r["status"] == "sent":
                print(f"✅ INVIATO  id={r['id']}  HTTP {r['http']}")
            else:
                print(f"❌ ERRORE   id={r['id']}  {r['error']}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
