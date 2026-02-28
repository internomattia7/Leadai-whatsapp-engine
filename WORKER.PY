import time
from leadai_engine import get_conn
from whatsapp_client import send_whatsapp_message

POLL_SECONDS = 2


def _get_wa_credentials(conn, azienda_id: int):
    """
    Restituisce (wa_access_token, wa_phone_number_id) per l'azienda,
    oppure solleva RuntimeError se non trovata o non abilitata.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT wa_access_token, wa_phone_number_id
            FROM company_integrations
            WHERE azienda_id = %s
              AND channel = 'whatsapp'
              AND is_enabled = TRUE
            LIMIT 1
            """,
            (azienda_id,),
        )
        row = cur.fetchone()

    if not row:
        raise RuntimeError(
            f"Nessuna integrazione WhatsApp attiva per azienda_id={azienda_id}"
        )

    wa_token, wa_phone_number_id = row
    if not wa_token or not wa_phone_number_id:
        raise RuntimeError(
            f"Credenziali WhatsApp incomplete per azienda_id={azienda_id}"
        )

    return wa_token, wa_phone_number_id


def send_message(conn, azienda_id: int, channel: str, contact_key: str, body: str) -> str | None:
    """
    Invia un messaggio sul canale specificato.
    Restituisce il wamid (wa_message_id) ricevuto da Meta, o None se non disponibile.
    """
    if channel == "whatsapp":
        wa_token, wa_phone_number_id = _get_wa_credentials(conn, azienda_id)
        to = contact_key.removeprefix("wa:")
        resp = send_whatsapp_message(to, body, wa_token, wa_phone_number_id)
        try:
            return resp.json()["messages"][0]["id"]
        except Exception:
            return None
    else:
        raise NotImplementedError(f"Channel '{channel}' non supportato dal worker")


def main():
    print("WORKER started ✅", flush=True)

    while True:
        conn = get_conn()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, azienda_id, channel, contact_key, body
                    FROM outbound_messages
                    WHERE status = 'queued'
                      AND send_after <= NOW()
                    ORDER BY id
                    LIMIT 5
                    FOR UPDATE SKIP LOCKED
                    """
                )

                rows = cur.fetchall()

                for msg_id, azienda_id, channel, contact_key, body in rows:
                    try:
                        wamid = send_message(conn, azienda_id, channel, contact_key, body)

                        cur.execute(
                            """
                            UPDATE outbound_messages
                            SET status = 'sent',
                                sent_at = NOW(),
                                wa_message_id = %s,
                                error = NULL
                            WHERE id = %s
                            """,
                            (wamid, msg_id),
                        )
                        print(
                            f"[SENT] id={msg_id} channel={channel} to={contact_key} wamid={wamid}",
                            flush=True,
                        )

                    except Exception as e:
                        print(
                            f"[ERROR] id={msg_id} channel={channel} to={contact_key}: {e}",
                            flush=True,
                        )
                        cur.execute(
                            """
                            UPDATE outbound_messages
                            SET status = 'error',
                                error = %s
                            WHERE id = %s
                            """,
                            (str(e), msg_id),
                        )

            conn.commit()

        finally:
            conn.close()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
