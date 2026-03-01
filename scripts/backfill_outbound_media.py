"""
Backfill local_path for outbound_messages rows that have a media_id but NULL local_path.
Downloads the file from Meta Graph API and saves it locally.

Usage:
    python scripts/backfill_outbound_media.py
"""

import os, sys, re, requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadai_engine import get_conn

GRAPH_VERSION = "v19.0"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"

MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "application/pdf": "pdf",
}

def ext_from_mime(mime: str) -> str:
    return MIME_TO_EXT.get(mime, "bin")

def ext_from_filename(fname: str) -> str:
    if fname and "." in fname:
        return fname.rsplit(".", 1)[-1].lower()
    return ""

def download_and_save(row, wa_token: str, wa_phone_number_id: str) -> str | None:
    msg_id, azienda_id, media_id, mime, fname, send_after = row

    ext = ext_from_filename(fname or "") or ext_from_mime(mime or "") or "bin"
    date_str = (send_after or datetime.utcnow()).strftime("%Y%m%d")
    out_dir = UPLOADS_DIR / "outbound" / str(azienda_id) / date_str
    final_dest = out_dir / f"{media_id}.{ext}"

    if final_dest.exists():
        local_path = f"/uploads/outbound/{azienda_id}/{date_str}/{media_id}.{ext}"
        print(f"  [id={msg_id}] file already exists → {final_dest}")
        return local_path

    # Get media URL from Meta
    url_resp = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}",
        headers={"Authorization": f"Bearer {wa_token}"},
        timeout=20,
    )
    if not url_resp.ok:
        print(f"  [id={msg_id}] ERROR getting media URL: {url_resp.status_code} {url_resp.text[:200]}")
        return None

    media_url = url_resp.json().get("url")
    if not media_url:
        print(f"  [id={msg_id}] ERROR: no url in response: {url_resp.text[:200]}")
        return None

    # Download file
    dl_resp = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {wa_token}"},
        timeout=60,
    )
    if not dl_resp.ok:
        print(f"  [id={msg_id}] ERROR downloading: {dl_resp.status_code}")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    final_dest.write_bytes(dl_resp.content)
    local_path = f"/uploads/outbound/{azienda_id}/{date_str}/{media_id}.{ext}"
    print(f"  [id={msg_id}] saved {len(dl_resp.content)}B → {final_dest}")
    return local_path


def main():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Find all outbound media rows with missing local_path
            cur.execute("""
                SELECT om.id, om.azienda_id, om.media_id, om.mime_type, om.filename, om.send_after,
                       ci.wa_access_token, ci.wa_phone_number_id
                FROM outbound_messages om
                JOIN company_integrations ci
                    ON ci.azienda_id = om.azienda_id
                   AND ci.channel = 'whatsapp'
                   AND ci.is_enabled = TRUE
                WHERE om.media_id IS NOT NULL
                  AND (om.local_path IS NULL OR om.local_path = '')
                ORDER BY om.id
            """)
            rows = cur.fetchall()

        if not rows:
            print("No rows need backfilling.")
            return

        print(f"Found {len(rows)} row(s) to backfill:")
        for r in rows:
            print(f"  id={r[0]} azienda={r[1]} media_id={r[2]!r} mime={r[3]!r} fname={r[4]!r}")

        print()
        for r in rows:
            msg_id, azienda_id, media_id, mime, fname, send_after, wa_token, wa_phone_number_id = r
            data = (msg_id, azienda_id, media_id, mime, fname, send_after)
            local_path = download_and_save(data, wa_token, wa_phone_number_id)
            if local_path:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE outbound_messages SET local_path=%s WHERE id=%s",
                        (local_path, msg_id),
                    )
                conn.commit()
                print(f"  [id={msg_id}] DB updated → local_path={local_path!r}")
            else:
                print(f"  [id={msg_id}] SKIPPED (download failed)")

        print("\nDone.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
