"""
Migration: VenomApp fields
- wa_inbound_messages.read_at  (unread tracking)
- company_settings.business_phone (Chiama Ora button)
"""
from dotenv import load_dotenv
load_dotenv()

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from leadai_engine import get_conn

def run():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE wa_inbound_messages ADD COLUMN IF NOT EXISTS read_at TIMESTAMP")
            print("OK: wa_inbound_messages.read_at")

            cur.execute("ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS business_phone TEXT")
            print("OK: company_settings.business_phone")

            cur.execute(
                "CREATE INDEX IF NOT EXISTS ix_wa_inbound_read "
                "ON wa_inbound_messages (from_wa, read_at)"
            )
            print("OK: index ix_wa_inbound_read")

        conn.commit()
        print("Migration completed.")
    finally:
        conn.close()

if __name__ == "__main__":
    run()
