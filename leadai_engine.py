# -*- coding: utf-8 -*-
"""
Lead-AI Engine (definitivo v1)
- Usa DB dict (psycopg2.connect(**DB))
- Classifica messaggi (lead forte/debole vs non-lead) con keyword
- Memoria per cliente (lead_ai_state)
- Campi CHIAVE preventivo:
  tipologia, quantita, misure, colore, nome (solo se nel testo), servizi (montaggio+trasporto insieme)
- Niente "si/no"
- Se manca qualcosa: chiede SOLO i campi mancanti (1 => 1, 3 => 3, tutti => tutti)
- Saluto: "Ciao Nome," solo se nome estratto dal messaggio; altrimenti "Ciao,"
"""

import time
import re
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta  # ✅ FIX: aggiunto timedelta (serviva in parse_preferred_send_at)
import uuid

import os
print("🚨 IMPORT leadai_engine.py DA:", os.path.abspath(__file__), flush=True)

print("### LEADAI_ENGINE IMPORTATO ###", flush=True)

def build_quote_payload(state: dict, contact_key: str) -> dict:
    """
    Crea una bozza preventivo (JSON) con i dati raccolti.
    Non inventa nulla: usa solo quello che c'è nello state.
    """
    return {
        "azienda": "EXPERT INFISSI SRLS",
        "contact_key": contact_key,
        "cliente": {
            "intestazione": state.get("intestazione") or state.get("customer_name"),
        },
        "richiesta": {
            "tipologia": state.get("tipologia"),
            "quantita": state.get("quantita"),
            "misure": state.get("misure"),
            "colore": state.get("colore"),
            "servizi": state.get("servizi"),  # es: inclusi
            "materiale": state.get("materiale"),
            "tipologia_vetro": state.get("tipologia_vetro"),
            "grate_persiane": state.get("grate_persiane"),
            "note": state.get("note"),
        },
        "meta": {
            "created_iso": datetime.utcnow().isoformat() + "Z",
            "version": 1
        }
    }

def save_quote(conn, contact_key: str, quote_payload: dict) -> int:
    """
    Salva la bozza preventivo in tabella quotes e ritorna l'id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quotes (contact_key, quote_json)
            VALUES (%s, %s::jsonb)
            RETURNING id
            """,
            (contact_key, json.dumps(quote_payload, ensure_ascii=False))
        )
        quote_id = cur.fetchone()[0]
    conn.commit()
    return quote_id

# =========================
# CONFIG DB (TUO)
# =========================
DB = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "leadai",
    "user": "leadai",
    "password": "leadai",
}

POLL_SECONDS = 5
LEADS_TABLE = "lead_ai_db"
STATE_TABLE = "lead_ai_state"

# =========================
# KEYWORDS (filtro lead)
# =========================
KEYWORDS_FORTI = [
    # intento preventivo
    "preventivo", "quanto costa", "quanto costano", "prezzo", "costo", "costi",
    # prodotti/settore
    "infisso", "infissi", "finestra", "finestre", "porta", "portafinestra",
    "scorrevole", "alzante", "hs", "zanzariera", "zanzariere", "persiana", "persiane",
    "tapparella", "tapparelle", "vetro", "vetrata", "vetrate",
    # indizi tecnici
    "misura", "misure", "pvc", "alluminio", "legno", "ral"
]

KEYWORDS_DEBOLI = [
    "info", "informazioni", "dettagli", "consiglio", "preventivi"
]

KEYWORDS_SALUTO = [
    "ciao", "salve", "buongiorno", "buonasera", "hey", "buon pomeriggio"
]

KEYWORDS_RUMORE = [
    "grazie", "ok", "perfetto", "arrivederci", "👍", "👌"
]

# =========================
# CAMPI OBBLIGATORI PREVENTIVO
# =========================
REQUIRED_FIELDS = ["tipologia", "quantita", "misure", "colore", "intestazione", "servizi"]

QUOTE_FIELDS = ["tipologia", "quantita", "misure", "colore", "servizi"]

def new_quote_id() -> str:
    return uuid.uuid4().hex[:8]

def reset_quote_keep_contact(state: dict) -> dict:
    keep = {}
    if state.get("customer_name"):
        keep["customer_name"] = state["customer_name"]
    keep["quote_id"] = new_quote_id()
    keep["quote_status"] = "OPEN"
    keep["quote_started_at"] = int(time.time())
    return keep

def is_reset_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"reset", "/reset", "resetta"}

def looks_like_new_quote_request(text: str) -> bool:
    t = (text or "").strip().lower()
    trigger = ["preventivo", "finestre", "porta", "porte", "zanzar", "infissi", "scorrevole", "battente"]
    return any(k in t for k in trigger)

# =========================
# SQL
# =========================
SQL_LAST_LEAD = f"""
SELECT id, nome, messaggio
FROM {LEADS_TABLE}
ORDER BY id DESC
LIMIT 1;
"""

# =========================
# DB UTILS
# =========================
def get_conn():
    return psycopg2.connect(**DB)

def update_lead_status(conn, lead_id: int, status: str):
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {LEADS_TABLE} SET status=%s WHERE id=%s;",
            (status, lead_id)
        )
    conn.commit()

def ensure_state_table(conn):
    with conn.cursor() as cur:
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
            contact_key TEXT PRIMARY KEY,
            state_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
    conn.commit()

def load_state(conn, contact_key: str) -> dict:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SELECT state_json FROM {STATE_TABLE} WHERE contact_key=%s;", (contact_key,))
        row = cur.fetchone()
        return dict(row["state_json"]) if row and row.get("state_json") else {}

def save_state(conn, contact_key: str, state: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(f"""
        INSERT INTO {STATE_TABLE} (contact_key, state_json, updated_at)
        VALUES (%s, %s::jsonb, NOW())
        ON CONFLICT (contact_key)
        DO UPDATE SET state_json=EXCLUDED.state_json, updated_at=NOW();
        """, (contact_key, json.dumps(state, ensure_ascii=False)))
    conn.commit()

def fetch_last_lead(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SQL_LAST_LEAD)
        return cur.fetchone()  # dict or None

# =========================
# IDENTITÀ CLIENTE (provvisorio)
# =========================

def build_contact_key(row: dict) -> str:
    nome = (row.get("customer_name") or "").strip().lower()
    if nome:
        return f"nome:{nome}"
    return "anon_test"

import re

# =========================
# CLASSIFICAZIONE MESSAGGIO
# =========================
def classifica_messaggio(msg: str, conversazione_aperta: bool) -> str:
    t = (msg or "").lower().strip()
    t = (msg or "").lower().strip()
    t_clean = re.sub(r"[^\w\s]", "", t).strip()
    
    match_rumore = any(k in t for k in KEYWORDS_RUMORE)
    match_forti = any(k in t for k in KEYWORDS_FORTI)
    match_deboli = any(k in t for k in KEYWORDS_DEBOLI)

    SALUTI_PURI = {"ciao", "buongiorno", "buonasera", "salve", "hey"}
    t_clean = re.sub(r"[^\w\s]", "", t).strip()

    # SALUTO SOLO se è DAVVERO solo un saluto (nessun intento preventivo dentro)
    if t_clean in SALUTI_PURI and not (match_forti or match_deboli):
        return "SALUTO"
    
    # 2️⃣ Lead forte / debole
    if match_forti:
        return "LEAD_FORTE"

    if match_deboli:
        return "LEAD_DEBOLE"

    # 3️⃣ Follow-up SOLO se conversazione aperta
    if conversazione_aperta:
        return "FOLLOW_UP"

    # 4️⃣ Rumore generico
    if match_rumore:
        return "SALUTO"

    return "NON_LEAD"

# =========================
# ESTRAZIONE DATI DAL TESTO
# =========================

import re

NUMERI_PAROLE = {
    "uno": 1, "una": 1, "una": 1, "un": 1,
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10
}

def estrai_nome_saluto(msg: str) -> str | None:
    if not msg:
        return None

    m = re.search(
        r"\b(?:sono|mi chiamo)\s+([A-Za-zÀ-ÿ']+)\b",
        msg.strip(),
        flags=re.IGNORECASE
    )
    if m:
        return m.group(1).capitalize()

    return None

def estrai_nome_da_testo_safe(msg: str) -> str | None:
    if not msg:
        return None

    s = msg.strip()

    # prende SOLO se dichiarato esplicitamente
    m = re.search(
        r"\b(?:mi chiamo|sono|nome|intestat[oa]\s+a)\s+([A-Za-zÀ-ÖØ-öø-ÿ']+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ']+){0,2})\b",
        s,
        flags=re.IGNORECASE
    )
    if m:
        nome = m.group(1).strip()
        return nome.capitalize()

    return None

def estrai_intestazione_da_testo_safe(msg: str) -> str | None:
    if not msg:
        return None

    s = msg.strip()

    # prende SOLO quando è esplicitato: "a Mario Rossi", "intestato a Mario Rossi", "a nome Fabio Lillo"
    m = re.search(
        r"\b(?:intestat[oa]\s*(?:a)?|intestare\s*(?:a)?|a\s+nome\s+di|a\s+nome|preventivo\s+a\s+nome|a)\s+([A-Za-zÀ-ÖØ-öø-ÿ']+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ']+){0,2})\b",
        s,
        flags=re.IGNORECASE
    )
    if m:
        nome = m.group(1).strip()
        return nome.title()

    return None

def estrai_quote_name(msg: str) -> str | None:
    if not msg:
        return None
    s = msg.strip()

    m = re.search(
        r"\b(?:intestat[oa]\s+a|a\s+nome\s+di|preventivo\s+intestat[oa]\s+a)\s+([A-Za-zÀ-ÖØ-öø-ÿ]+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ]+){0,2})\b",
        s,
        flags=re.IGNORECASE
    )
    if m:
        return m.group(1).strip().title()
    return None

import re  # lasciato come nel tuo file (duplicato ok)

def estrai_misure(msg: str) -> str | None:
    t = (msg or "").lower()

    # accetta: 120x200, 120 x 200, l 120 x h 200, l120xh200, 120 x h200
    m = re.search(r"\b(?:l\s*)?(\d{2,4})\s*[xX]\s*(?:h\s*)?(\d{2,4})\b", t)
    if m:
        return f"{m.group(1)}x{m.group(2)}"

    return None

import re  # lasciato come nel tuo file (duplicato ok)

def estrai_quantita(t: str):
    t = (t or "").strip().lower()

    # 1) Formati: "10 pz", "10 pezzi", "10 pz.", "10pcs"
    m = re.search(r"\b(\d+)\s*(?:pz\.?|pezzi|pcs)\b", t, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 2) Formati: "quantità 3", "quantita:3", "pezzi=3", "n. 2", "n 2"
    m = re.search(r"\b(?:quantit[aà]|quantita|pezzi|pz|n\.?|num(?:ero)?)\s*[:=]?\s*(\d+)\b", t, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 3) Formati: "più pezzi 3", "piu pezzi 3"
    m = re.search(r"\bpi[uù]\s+(?:pezzi|pz)\s*[:=]?\s*(\d+)\b", t, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 4) Formati: "tot 11", "totale 11", "tot: 11"
    m = re.search(r"\b(?:tot|totale)\s*[:=]?\s*(\d+)\b", t, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 5) Frasi: "me ne servono 3", "ne servono 3", "mi servono 3"
    m = re.search(r"\b(?:me\s+ne\s+servono|ne\s+servono|mi\s+servono|me\s+ne\s+occorrono|ne\s+occorrono)\s*(\d+)\b", t, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 6) "2 finestre", "3 porte", "4 infissi"
    m = re.search(r"\b(\d{1,3})\s*(?:pz|pezzi|pcs|finestre|finestra|porte|porta|infissi|infisso)\b", t, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # ✅ FIX: qui prima c’era un `return None` che rendeva morto il codice sotto.
    # Lo lascio, ma sposto il return alla fine e DISATTIVO il blocco vecchio duplicato.

    # return None  # ❌ DISATTIVATO: era troppo presto e rompeva il flusso

    # ----------------------------------------------------------------
    # BLOCCO DUPLICATO VECCHIO (lasciato ma disattivato)
    # ----------------------------------------------------------------
    
    """
    # "2 finestre", "3 porte", "2 infissi"
    m = re.search(r"\b(\d{1,3})\s*(?:pz|pezzi|finestre|finestra|porte|porta|infissi|infisso|zanzariere|zanzariera)\b", tl)
    if m:
        return int(m.group(1))

    # "mi servono 2"
    m2 = re.search(r"\bmi servon[oa]\s+(\d{1,3})\b", tl)
    if m2:
        return int(m2.group(1))
    """
    # ----------------------------------------------------------------

    # 6) Numeri a parole: "due", "tre", "quattro" (anche senza 'pz/pezzi')
    for parola, valore in NUMERI_PAROLE.items():
        if re.search(rf"\b{parola}\b", t):
            return valore
    
    return None

def estrai_tipologia(msg: str) -> str | None:
    tl = (msg or "").lower()
    if "alzante scorrevole" in tl or re.search(r"\bhs\b", tl):
        return "alzante scorrevole"
    if "scorrevol" in tl:
        return "scorrevole"
    if "porta finestra" in tl or "portafinestra" in tl:
        return "portafinestra"
    if "zanzar" in tl:
        return "zanzariera"
    if "finestr" in tl:
        return "finestra"
    if "porta" in tl:
        return "porta"
    if "infiss" in tl:
        return "infisso"
    return None

def estrai_colore(msg: str) -> str | None:
    t = (msg or "").lower()

    # bianco: bianco/bianca/bianchi/bianche
    if re.search(r"\bbianc(?:o|a|hi|he)\b", t):
        return "bianco"

    # nero: nero/nera/neri/nere
    if re.search(r"\bner(?:o|a|i|e)\b", t):
        return "nero"

    # altri colori (qui puoi aggiungere varianti se vuoi)
    if re.search(r"\bgrigi(?:o|a|i|e)\b", t):
        return "grigio"

    if re.search(r"\bantracite\b", t):
        return "antracite"

    if re.search(r"\bavori(?:o|a)\b", t):
        return "avorio"

    if re.search(r"\bmarron(?:e|i)\b", t):
        return "marrone"

    if re.search(r"\bnoc(?:e|i)\b", t):
        return "noce"

    if re.search(r"\brover(?:e|i)\b", t):
        return "rovere"

    if re.search(r"\bverd(?:e|i)\b", t):
        return "verde"

    # RAL (es. "ral 7016")
    m = re.search(r"\bral\s*(\d{4})\b", t)
    if m:
        return f"RAL {m.group(1)}"

    return None

def estrai_servizi(msg: str) -> str | None:
    """
    Montaggio+trasporto insieme, senza si/no.
    Ritorna una stringa 'inclusi', 'esclusi', 'solo montaggio', 'solo trasporto' se rilevabile.
    Altrimenti None (quindi verrà chiesto).
    """
    tl = (msg or "").lower()

    # Frasi esplicite
    if "solo montaggio" in tl:
        return "solo montaggio"
    if "solo trasporto" in tl:
        return "solo trasporto"

    # inclusi / compresi
    if ("montaggio" in tl or "trasporto" in tl) and any(w in tl for w in ["inclus", "compres", "compreso", "compresi", "inclusi", "incluso"]):
        # se menziona almeno uno dei due e parla di inclusione -> assumiamo "inclusi"
        return "inclusi"

    # esclusi / senza
    if ("montaggio" in tl or "trasporto" in tl) and any(w in tl for w in ["esclus", "senza", "non incluso", "non compreso"]):
        return "esclusi"

    return None

def estrai_extra(msg: str) -> dict:
    """
    Extra non obbligatori: materiale, vetro, grate/persiane, note.
    (Li salviamo, ma NON bloccano il preventivo)
    """
    tl = (msg or "").lower()
    out = {
        "materiale": None,
        "tipologia_vetro": None,
        "grate_persiane": None,
        "note": None
    }

    # materiale
    if "pvc" in tl:
        out["materiale"] = "pvc"
    elif "alluminio" in tl:
        out["materiale"] = "alluminio"
    elif "legno" in tl:
        out["materiale"] = "legno"

    # grate/persiane
    if "grata" in tl or "grate" in tl:
        out["grate_persiane"] = "grate"
    elif "persiana" in tl or "persiane" in tl:
        out["grate_persiane"] = "persiane"

    # vetro (base)
    if "triplo" in tl or "triplo vetro" in tl:
        out["tipologia_vetro"] = "triplo"
    elif "doppio" in tl or "doppio vetro" in tl:
        out["tipologia_vetro"] = "doppio"

    # note (parole chiave)
    note_kw = ["maniglia", "cassonetto", "celetti", "cellette", "coprifilo", "soglia", "microventilazione"]
    found = [k for k in note_kw if k in tl]
    if found:
        out["note"] = ", ".join(found)

    return out

def estrai_dati(msg: str) -> dict:
    """
    Estrae tutto quello che può dal messaggio.

    customer_name = nome per SALUTO (gestito fuori, non qui)
    intestazione  = nome per INTESTARE il preventivo (qui sì)
    """
    msg_norm = (msg or "").strip()

    return {
        "tipologia": estrai_tipologia(msg_norm),
        "quantita": estrai_quantita(msg_norm),
        "misure": estrai_misure(msg_norm),
        "colore": estrai_colore(msg_norm),

        # ✅ QUESTO È IL PEZZO CHE TI MANCAVA
        "intestazione": estrai_intestazione_da_testo_safe(msg_norm),

        # servizi: ok tenerlo qui (montaggio/trasporto/si/no)
        "servizi": estrai_servizi_safe(msg_norm),

        # opzionale se lo usi
        "quote_name": estrai_quote_name(msg_norm),
    }

import re  # lasciato

def estrai_colore_(msg: str) -> str | None:
    t = (msg or "").lower()

    # BIANCO: bianco, bianca, bianchi, bianche
    if re.search(r"\bbianc(?:o|a|hi|he)\b", t):
        return "bianco"

    # NERO: nero, nera, neri, nere
    if re.search(r"\bner(?:o|a|i|e)\b", t):
        return "nero"

    return None

def estrai_servizi_safe(msg: str, servizi_gia_chiesti: bool = False) -> str | None:
    if not msg:
        return None

    t = msg.lower().strip()

    # 1) Risposte corte tipo "sì/no" SOLO se stavamo parlando di servizi
    if servizi_gia_chiesti:
        if t in {"si", "sì", "ok", "certo", "va bene", "inclusi", "incluso"}:
            return "inclusi"
        if t in {"no", "non inclusi", "esclusi", "escluso"}:
            return "esclusi"

    # 2) Riconosci parole chiave (posa = montaggio)
    has_montaggio = bool(re.search(r"\b(montaggio|posa|installazione)\b", t))
    has_trasporto = bool(re.search(r"\b(trasporto|consegna)\b", t))
    has_trasporto = bool(re.search(r"\b(inclus[oaie])\b", t))
   
    # 3) Se dice esplicitamente esclusi / senza
    if re.search(r"\b(senza|esclus[oi]|non inclus[oi])\b", t):
        # se dice "senza trasporto" ecc, puoi gestirlo dopo; per ora: esclusi
        return "esclusi"

    # 4) Normalizza in 4 stati
    if has_montaggio and has_trasporto:
        return "inclusi"           # montaggio+trasporto
    if has_montaggio:
        return "solo montaggio"
    if has_trasporto:
        return "solo trasporto"

    return None


def estrai_nome_da_testo_safe(msg: str) -> str | None:
    # ✅ NOTA: questa funzione è DUPLICATA nel file (la lasciamo perché hai chiesto di non togliere nulla)
    # ma questa è la versione migliore: gestisce anche accenti.
    s = (msg or "").strip()
    s = re.sub(r"\s+", " ", s)

    pattern = r"\b([A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ']{1,}\s+[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ']{1,})\b"
    m = re.search(pattern, s)
    if not m:
        return None

    candidato = m.group(1).strip()

    blacklist = {
        "montaggio incluso", "trasporto incluso",
        "bianche", "bianchi", "bianco", "nere", "neri", "nero",
        "ciao", "salve", "buongiorno", "buonasera"
    }

    if candidato.lower() in blacklist:
        return None

    return candidato

# =========================
# MERGE STATE (memoria)
# =========================
def merge_state(state: dict, nuovi: dict) -> dict:
    state = dict(state or {})
    for k, v in (nuovi or {}).items():
        # NON sovrascrivere con None
        if v is None:
            continue
        # NON sovrascrivere con stringhe vuote
        if isinstance(v, str) and not v.strip():
            continue
        state[k] = v
    return state

# =========================
# MANCANTI + RISPOSTA
# =========================
def calcola_mancanti(state: dict) -> list[str]:
    mancanti = []
    for f in REQUIRED_FIELDS:
        if not state.get(f):
            mancanti.append(f)
    return mancanti

def genera_domande(mancanti: list[str], nome: str | None) -> str:
    """
    Niente si/no. Domande naturali.
    Montaggio+trasporto insieme => 'servizi'
    """
    intro = f"Ciao {nome},\n" if nome else "Ciao,\n"

    domande = {
        "tipologia": "Che tipologia di infisso ti serve (scorrevole, battente, porta, ecc.)?",
        "quantita": "Quanti pezzi ti servono?",
        "misure": "Mi dai le misure approssimative (es. 120x150)?",
        "colore": "Che colore preferisci?",
        "intestazione": "A che nome devo intestare il preventivo?",
        "servizi": "Nel preventivo vuoi che siano inclusi montaggio e trasporto?"
    }

    righe = [f"- {domande.get(k, k)}" for k in mancanti]
    return intro + "Per prepararti un preventivo preciso mi servono ancora queste info:\n" + "\n".join(righe)


def parse_preferred_send_at(text: str) -> datetime | None:
    t = (text or "").lower().strip()

    # match "alle 18" / "alle 18:30"
    m = re.search(r"\balle\s+(\d{1,2})(?::(\d{2}))?\b", t)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    now = datetime.now()
    day_offset = 0

    if "domani" in t:
        day_offset = 1
    elif "stasera" in t and hour < 12:
        pass

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)

    # se non dice "domani" e l'orario è già passato oggi -> sposta a domani
    if day_offset == 0 and target <= now:
        target = target + timedelta(days=1)

    return target

# =========================
# MAIN
# =========================

def process_text_message(conn, contact_key: str, text: str) -> str:
    """
    Processa un singolo messaggio (testo) per un contatto e ritorna la risposta automatica.
    Riusa tutta la logica già presente: state, classificazione, estrazione, mancanti, domande.
    """
    # carica stato (memoria)
    state = load_state(conn, contact_key) or {}
    
    state = state or {}

    # 0) se non esiste, inizializza una pratica
    if "quote_id" not in state:
        state = reset_quote_keep_contact(state)
        save_state(conn, contact_key, state)

    # capisco se in questo momento "servizi" è tra i mancanti
    mancanti_preview = calcola_mancanti(state)
    servizi_serve_adesso = ("servizi" in mancanti_preview)

    servizi = estrai_servizi_safe(text, servizi_gia_chiesti=True)
    if servizi:
        state["servizi"] = servizi
        save_state(conn, contact_key, state)
   
    # 1) comando reset (per test): nuova pratica e basta
    if is_reset_command(text):
        state = reset_quote_keep_contact(state)
        save_state(conn, contact_key, state)
        nome = state.get("customer_name")
        if nome:
            return f"Ok {nome}: reset fatto ✅ Dimmi cosa ti serve (finestre/porte/zanzariere) e misure/quantità."
        return "Reset fatto ✅ Dimmi cosa ti serve (finestre/porte/zanzariere) e misure/quantità."

    # 2) se preventivo era CHIUSO e l'utente scrive di nuovo cose da preventivo → apri nuovo preventivo
    if state.get("quote_status") == "COMPLETED" and looks_like_new_quote_request(text):
     state = reset_quote_keep_contact(state)  # nome resta
    save_state(conn, contact_key, state)
    
    ha_memoria = bool(state)

    tipo = classifica_messaggio(text, ha_memoria)

    # se non è lead e non c'è conversazione aperta → risposta neutra
    if tipo == "NON_LEAD" and not ha_memoria:
     return "Ciao! 🙂 Dimmi cosa ti serve (finestre/porte/zanzariere) e se hai misure e quantità."
   
    # se non è lead ma c'è memoria → trattalo come follow-up
    if tipo == "NON_LEAD" and ha_memoria:
        tipo = "FOLLOW_UP"

    nome_saluto = estrai_nome_saluto(text)
    if nome_saluto:
     state["nome_saluto"] = nome_saluto
    
    nome_estratto = estrai_nome_da_testo_safe(text)
    if nome_estratto:
     state["customer_name"] = nome_estratto
    
    intest = estrai_intestazione_da_testo_safe(text)
    if intest:
     state["intestazione"] = intest
    
    # estrai dati e aggiorna memoria
    nuovi = estrai_dati(text)
    state = merge_state(state, nuovi)
    save_state(conn, contact_key, state)

    if tipo == "SALUTO":
        nome = state.get("customer_name")
        if nome:
            return f"Ciao {nome}! 🙂 Dimmi pure come possiamo aiutarti"
        return "Ciao! 🙂 Dimmi pure come possiamo aiutarti"
    
    # protezione: nome valido solo se "pulito"
    bad = {"ciao", "salve", "buongiorno", "buonasera", "vorrei", "preventivo", "info"}

    customer_name = (state.get("customer_name") or "").strip()
    if customer_name:
       parole = [p.lower() for p in customer_name.split()]
       if any(p in bad for p in parole) or len(parole) > 2:
           state["customer_name"] = None

    # calcola cosa manca e genera risposta
    mancanti = calcola_mancanti(state)
    nome_saluto = state.get("customer_name")  # solo se estratto

    if mancanti:
        return genera_domande(mancanti, nome_saluto)

    # se completo
    if nome_saluto:
        return f"Ciao {nome_saluto}, perfetto, abbiamo tutto cio che ci serve. A breve ti invieremo il preventivo dettagliato. Buona giornata"   
    return "perfetto, abbiamo tutto cio che ci serve. A breve ti invieremo il preventivo dettagliato. Buona giornata"

def main():
    conn = get_conn()
    ensure_state_table(conn)

    last_seen_id = None
    print("[OK] Lead-AI engine avviato.")

    while True:
        row = fetch_last_lead(conn)

        if not row:
            print("[INFO] Nessun lead trovato.")
            time.sleep(POLL_SECONDS)
            continue

        lead_id = row["id"]
        msg = row.get("messaggio") or ""

        # evita riprocessare lo stesso record
        if last_seen_id == lead_id:
            time.sleep(POLL_SECONDS)
            continue
        last_seen_id = lead_id

        contact_key = build_contact_key(row)

        # carico stato per capire FOLLOW_UP
        state = load_state(conn, contact_key) or {}
        ha_memoria = bool(state)

        tipo = classifica_messaggio(msg, ha_memoria)
        print(f"[DEBUG] tipo={tipo} ha_memoria={ha_memoria} state_keys={list(state.keys())}")

        if tipo == "NON_LEAD" and not ha_memoria:
            print(f"[NON_LEAD] id={lead_id} ignorato: {msg}")
            time.sleep(POLL_SECONDS)
            continue

        if tipo == "NON_LEAD" and ha_memoria:
            tipo = "FOLLOW_UP"

        # stesso flusso per lead debole/forte/follow-up
        nuovi = estrai_dati(msg)
        state = merge_state(state, nuovi)
        save_state(conn, contact_key, state)

         # --- 1) SALUTO: se non c'è intento preventivo, rispondi solo con saluto ---
        tl = (msg or "").strip().lower()

        servizi = estrai_servizi_safe(msg)
        if servizi:
           state["servizi"] = servizi
           save_state(conn, contact_key, state)  # IMPORTANTISSIMO: risalva
        
        lead_intent = any(k in tl for k in (KEYWORDS_FORTI + KEYWORDS_DEBOLI))

        if not lead_intent:
            nome = state.get("customer_name")
            if nome:
                return f"Ciao {nome}! 😊 Come possiamo aiutarti?"
            return "Ciao! 😊 Come possiamo aiutarti?"
        # --- fine saluto ---
        
        mancanti = calcola_mancanti(state)
        print("=== STATE FINALE ===", state, flush=True)
        print("=== MANCANTI ===", mancanti, flush=True)

        # ✅ FIX CRITICO: qui prima passavi contact_key al posto di lead_id
        if mancanti:
            update_lead_status(conn, lead_id, "COLLECTING_DATA")
        else:
            update_lead_status(conn, lead_id, "READY_FOR_QUOTE")

        nome_saluto = state.get("nome_saluto")

        intro = f"Ciao {nome_saluto},\n" if nome_saluto else "Ciao,\n"
        
        if mancanti:
            risposta = genera_domande(mancanti, nome_saluto)
        else:
            print(">>> STO CREANDO BOZZA PREVENTIVO <<<", flush=True)
            print("STATE FINALE =", state, flush=True)
            quote_payload = build_quote_payload(state, contact_key)
            quote_id = save_quote(conn, contact_key, quote_payload)
            print(">>> QUOTE_ID =", quote_id, flush=True)

            if nome_saluto:
                risposta = f"Ciao {nome_saluto}, perfetto: ho tutto. Ti preparo il preventivo (bozza #{quote_id})."
            else:
                risposta = f"Perfetto: ho tutto. Ti preparo il preventivo (bozza #{quote_id})."

        # ----------------------------------------------------------------
        # FUNZIONE DUPLICATA DENTRO main (LA LASCIO MA LA DISATTIVO)
        # Perché: in Python è inutile e confonde, e può creare bug strani.
        # ----------------------------------------------------------------
        """
        def process_text_message(conn, contact_key: str, text: str) -> str:
            # 1) carica lo stato (memoria) del contatto
            state = load_state(conn, contact_key) or {}

            # 2) estrae dati dal messaggio e aggiorna lo stato
            nuovi = estrai_dati(text)
            state = merge_state(state, nuovi)
            save_state(conn, contact_key, state)

            # 3) calcola campi mancanti e genera risposta
            mancanti = calcola_mancanti(state)
            nome_saluto = state.get("nome")

            if mancanti:
                return genera_domande(mancanti, nome_saluto)

            # se non manca nulla:
            if nome_saluto:
                return f"Ciao {nome_saluto}, perfetto: ho tutto. Ti preparo il preventivo."
            return "Perfetto: ho tutto. Ti preparo il preventivo."
        """
        # ----------------------------------------------------------------

        print("\n==============================")
        print(f"[TIPO] {tipo} | id={lead_id} | contact_key={contact_key}")
        print("[MSG]", msg)
        print("[ESTRATTI]", nuovi)
        print("[STATE]", state)
        print("[MANCANTI]", mancanti)
        print("----- RISPOSTA AUTOMATICA -----")
        print(risposta)
        print("------------------------------")

        save_state(conn, contact_key, state)

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()