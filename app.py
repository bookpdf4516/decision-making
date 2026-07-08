import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt
import networkx as nx

# Google Sheets — opzionale, attivo solo se credenziali configurate
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False

# Email — librerie standard Python, sempre disponibili
import smtplib
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

st.set_page_config(
    page_title="Questionario Sistema 3",
    page_icon="🧠",
    layout="wide"
)

# ============================================================
# CONFIGURAZIONE
# ============================================================

OUTPUT_DIR = Path(r"C:\Users\casti\OneDrive\Desktop\1_SOCIO_FISICA\questionario")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH        = OUTPUT_DIR / "questionario_sistema3.sqlite"
CSV_RESPONSES  = OUTPUT_DIR / "01_risposte_questionario.csv"
CSV_DESC       = OUTPUT_DIR / "02_statistiche_descrittive.csv"
CSV_TEAM       = OUTPUT_DIR / "03_team_parametrizzato.csv"
CSV_ABM        = OUTPUT_DIR / "04_risultati_abm_singolo.csv"
CSV_MC         = OUTPUT_DIR / "05_risultati_montecarlo.csv"
CSV_MC_SUM     = OUTPUT_DIR / "06_sintesi_montecarlo.csv"
CSV_SYNTH_SUM  = OUTPUT_DIR / "07_sintesi_team_sintetici.csv"
FIG_DESC       = OUTPUT_DIR / "fig_00_descrittive.png"
FIG_NET        = OUTPUT_DIR / "fig_01_rete.png"
FIG_ABM        = OUTPUT_DIR / "fig_02_abm.png"
FIG_MC         = OUTPUT_DIR / "fig_03_montecarlo.png"
FIG_REGIMI     = OUTPUT_DIR / "fig_04_regimi.png"
FIG_DASH       = OUTPUT_DIR / "fig_05_cruscotto.png"

AI_COSTANTE    = 65          # usato internamente per calcoli ABM
AI_DIREZIONE   = "superiore" # direzione comunicata all'utente — non il numero
MAX_P          = 9
VALID_CODES    = [f"P{i:02d}" for i in range(1, MAX_P + 1)]
N_SYNTH_TEAMS  = 20    # repliche sintetiche — aumentare offline (max 100)
N_MC           = 75    # run per replica — aumentare offline (max 1000)
BASE_SEED      = 2026
ADMIN_PWD      = "admin"

# ── GOOGLE SHEETS ────────────────────────────────────────────
# Per attivare: inserire le credenziali del service account in
# .streamlit/secrets.toml (vedi istruzioni nel README)
# Se non configurato, lo script funziona solo con SQLite locale.

GSHEETS_ENABLED = False  # diventa True automaticamente se secrets disponibili
GSHEET_NAME     = "Sistema3_Risposte"  # nome del foglio Google

@st.cache_resource
def get_gsheet():
    """Connessione al foglio Google — cached per tutta la sessione."""
    global GSHEETS_ENABLED
    if not GSHEETS_AVAILABLE:
        return None
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open(GSHEET_NAME).sheet1
        GSHEETS_ENABLED = True
        return sheet
    except Exception:
        return None

def gsheet_append_row(row: dict):
    """Aggiunge una riga al foglio Google se disponibile."""
    sheet = get_gsheet()
    if sheet is None:
        return False
    try:
        # Prima volta: scrivi intestazioni se il foglio è vuoto
        existing = sheet.get_all_values()
        if not existing:
            sheet.append_row(list(row.keys()))
        sheet.append_row([str(row.get(k, "")) for k in row.keys()])
        return True
    except Exception:
        return False

def gsheet_load_all() -> pd.DataFrame:
    """Carica tutte le risposte dal foglio Google."""
    sheet = get_gsheet()
    if sheet is None:
        return pd.DataFrame()
    try:
        data = sheet.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def gsheet_reset():
    """Svuota il foglio Google mantenendo le intestazioni."""
    sheet = get_gsheet()
    if sheet is None:
        return
    try:
        headers = sheet.row_values(1)
        sheet.clear()
        if headers:
            sheet.append_row(headers)
    except Exception:
        pass

# ── EMAIL BACKUP ─────────────────────────────────────────────
# Configurazione tramite st.secrets oppure variabili dirette.
# Su Streamlit Cloud: inserire in Settings → Secrets:
#   [email]
#   mittente = "tuoindirizzo@gmail.com"
#   password  = "password-per-app-gmail"
#   destinatario = "tuoindirizzo@gmail.com"
#
# Gmail richiede una "Password per le app" (non la password normale):
# Account Google → Sicurezza → Verifica in 2 passaggi → Password per le app

def get_email_config():
    """Legge la configurazione email dai secrets o restituisce None."""
    try:
        cfg = st.secrets["email"]
        return {
            "mittente":     cfg["mittente"],
            "password":     cfg["password"],
            "destinatario": cfg["destinatario"],
        }
    except Exception:
        return None

def invia_email_risposta(row: dict, df_completo: pd.DataFrame):
    """
    Invia email con:
    - oggetto: codice partecipante e timestamp
    - corpo: riepilogo risposta in testo
    - allegato: CSV completo di tutte le risposte fino ad ora
    """
    cfg = get_email_config()
    if cfg is None:
        return False, "Configurazione email non trovata nei secrets."

    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["mittente"]
        msg["To"]      = cfg["destinatario"]
        msg["Subject"] = (
            f"Sistema 3 — Risposta {row.get('participant_code','?')} "
            f"[{row.get('timestamp','')[:10]}]"
        )

        # Corpo email
        n_completate = int(df_completo["completed"].fillna(0).astype(int).sum())
        codice = row.get("participant_code", "?")
        ruolo  = row.get("ruolo_assegnato", "?")
        ts     = row.get("timestamp", "?")
        ordine = row.get("ordine_somministrazione", "?")
        corpo  = (
            "Nuova risposta ricevuta.\n\n"
            f"Partecipante: {codice}\n"
            f"Ruolo interno: {ruolo}\n"
            f"Timestamp: {ts}\n"
            f"Ordine scenari: {ordine}\n\n"
            f"Risposte completate finora: {n_completate}/{MAX_P}\n\n"
            "In allegato il CSV completo di tutte le risposte."
        )
        msg.attach(MIMEText(corpo, "plain", "utf-8"))

        # Allegato CSV completo
        csv_buffer = io.StringIO()
        df_completo.to_csv(csv_buffer, index=False, encoding="utf-8")
        csv_bytes = csv_buffer.getvalue().encode("utf-8")

        part = MIMEBase("application", "octet-stream")
        part.set_payload(csv_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename=risposte_sistema3_{row.get('timestamp','')[:10]}.csv"
        )
        msg.attach(part)

        # Invio via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(cfg["mittente"], cfg["password"])
            server.sendmail(cfg["mittente"], cfg["destinatario"], msg.as_string())

        return True, "Email inviata."

    except Exception as e:
        return False, str(e)

# ── CREDENZIALI ──────────────────────────────────────────────
# PIN assegnati dal ricercatore — comunicati ai partecipanti
# via canale separato dal link. Modificare prima della somministrazione.
CREDENZIALI = {
    "TL2026":  {"code": "P01", "ruolo": "Team Leader",     "ordine": ["T1","T2","T3"]},
    "SR2026A": {"code": "P02", "ruolo": "Analista Senior",  "ordine": ["T1","T2","T3"]},
    "SR2026B": {"code": "P03", "ruolo": "Analista Senior",  "ordine": ["T2","T3","T1"]},
    "SR2026C": {"code": "P04", "ruolo": "Analista Senior",  "ordine": ["T3","T1","T2"]},
    "JR2026A": {"code": "P05", "ruolo": "Analista Junior",  "ordine": ["T1","T2","T3"]},
    "JR2026B": {"code": "P06", "ruolo": "Analista Junior",  "ordine": ["T2","T3","T1"]},
    "JR2026C": {"code": "P07", "ruolo": "Analista Junior",  "ordine": ["T3","T1","T2"]},
    "CV2026A": {"code": "P08", "ruolo": "Analista Civile",  "ordine": ["T1","T2","T3"]},
    "CV2026B": {"code": "P09", "ruolo": "Analista Civile",  "ordine": ["T2","T3","T1"]},
}

# Lookup derivato da CREDENZIALI — non modificare
ORDINI_FISSI = {v["code"]: v["ordine"] for v in CREDENZIALI.values()}
RUOLI_FISSI  = {v["code"]: v["ruolo"]  for v in CREDENZIALI.values()}
VALID_CODES  = [v["code"] for v in CREDENZIALI.values()]
PIN_TO_CODE  = {k: v["code"] for k, v in CREDENZIALI.items()}
PIN_USATI    = set()  # aggiornato a runtime dal DB

COND_LABEL = {
    "T1": "α",
    "T2": "β",
    "T3": "γ",
}

COND_CONTESTO = {
    "T1": """Leggi il briefing operativo e formula la tua valutazione individuale.
Le informazioni disponibili devono essere considerate nel loro insieme.
Nessun elemento isolato è sufficiente a produrre una conclusione definitiva.""",

    "T2": """Leggi il briefing operativo e formula la tua valutazione individuale.
Le informazioni disponibili devono essere considerate nel loro insieme.
Il quadro informativo presenta elementi aggiuntivi rispetto alla configurazione precedente.""",

    "T3": """Leggi il briefing operativo e formula la tua valutazione individuale.
Le informazioni disponibili devono essere considerate nel loro insieme.
Il quadro informativo presenta ulteriori elementi di complessità rispetto alle configurazioni precedenti.""",
}

# ── BRIEFING DISTINTI PER CONDIZIONE ────────────────────────
# Schema fisso in tutte e tre le condizioni:
# Piano fisico | Piano cyber | Piano OSINT | Fonti | Conclusione
# Varia: intensità degli eventi, rilevanza operativa dichiarata, volume informativo

BRIEFING = {

"T1": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Il quadro informativo delle ultime settimane segnala un incremento di indicatori relativi a possibili azioni ostili contro infrastrutture critiche nazionali. Nessun evento specifico è ancora occorso. La valutazione è richiesta per finalità analitiche.

**Piano fisico.** Fonti confidenziali segnalano movimenti anomali in prossimità di nodi ferroviari nell'Italia centrale. Gruppi di matrice antagonista hanno circolato materiale operativo che individua nelle reti di trasporto merci un obiettivo prioritario. I segnali sono coerenti con schemi di ricognizione preliminare. Non si registrano eventi concreti. Nessuna rivendicazione è pervenuta.

**Piano cyber.** Negli ultimi giorni sono comparsi sui principali forum riservati del dark web annunci relativi alla disponibilità di documentazione tecnica sottratta a operatori del settore energetico nazionale. I file offerti comprenderebbero schemi infrastrutturali e procedure di sicurezza interna. Non è stata verificata l'autenticità del materiale né l'identità degli offerenti.

**Piano OSINT.** Piattaforme digitali di area antagonista hanno avviato una campagna di critica sistematica agli accordi energetici italiani con Paesi africani. Vengono pubblicati profili di rappresentanti istituzionali e dirigenti aziendali coinvolti nelle trattative. Il tono è ostile. Non sono presenti ancora incitamenti espliciti ad azioni dirette.

**Fonti disponibili:** HUMINT (attendibilità non verificata), OSINT (verificata), cyber (in corso di analisi), open source (verificata). Nessun elemento isolato costituisce evidenza di una minaccia imminente. La convergenza degli indicatori giustifica una valutazione analitica integrata.

---""",

"T2": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Nel quadro aggiornato si è verificato un evento che modifica il peso degli indicatori precedentemente valutati. Il quadro richiede una rivalutazione analitica sulla base degli elementi aggiornati.

**Piano fisico.** Un treno merci è deragliato sulla linea Leonardiana, in prossimità della stazione di Rinascenza, a seguito del posizionamento deliberato di un oggetto sui binari. L'interruzione del traffico è in corso. Non si registrano vittime. Sul luogo è stato rinvenuto materiale a contenuto politico che richiama la causa palestinese e cita la multinazionale Zypron, società attiva nel settore della sicurezza e registrata in un paradiso fiscale. Tre distinti gruppi antagonisti hanno rilasciato dichiarazioni compatibili con una rivendicazione. Nessuna è stata ancora attribuita con certezza.

**Piano cyber.** Le offerte di dati trafugati dal settore energetico precedentemente segnalate hanno registrato un incremento significativo di volume e specificità. I file ora offerti includerebbero planimetrie di impianti critici, protocolli operativi e informazioni finanziarie riservate. Si teme un utilizzo coordinato con l'azione fisica in corso. Le aziende coinvolte non sono state identificate.

**Piano OSINT.** Le piattaforme antagoniste hanno intensificato la pubblicazione di dati personali relativi a manager e funzionari italiani operanti in ambito energetico all'estero. Alcuni post richiamano esplicitamente il deragliamento ferroviario come atto inaugurale di una più ampia campagna. Le autorità stanno monitorando la diffusione dei contenuti.

**Fonti disponibili:** HUMINT (attendibilità parziale), OSINT (verificata), cyber (in corso di analisi), open source (verificata). L'evento fisico avvenuto modifica il contesto valutativo. La combinazione degli indicatori richiede una valutazione analitica con carattere di rilevanza operativa.

---""",

"T3": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Il quadro informativo ha subito una maggiore complessità nel quadro aggiornato. Si registra una seconda azione ostile con potenziale coinvolgimento di attori statuali. La valutazione richiede particolare attenzione.

**Piano fisico.** Al sabotaggio ferroviario sulla linea Leonardiana si è aggiunto un secondo evento critico. Un'esplosione in una struttura rurale nella località costiera di Nereide, in Sicilia, ha portato alla scoperta di un laboratorio per la preparazione di esplosivi artigianali. Nessun ferito. La localizzazione del sito è geograficamente coerente con la presenza di cavi dati sottomarini e oleodotti nella stessa area costiera. Le forze dell'ordine stanno verificando possibili connessioni tra i due episodi. Non è esclusa una regia comune.

**Piano cyber.** I dati trafugati dal settore energetico sono ora in fase di negoziazione attiva. Fonti riservate segnalano trattative con un intermediario non identificato con possibili connessioni a entità statuali ostili. Il rischio di utilizzo operativo del materiale è considerato elevato dagli esperti di settore.

**Piano OSINT.** La campagna di doxing contro rappresentanti italiani si è estesa a nuove piattaforme e a destinatari in Paesi africani teatro degli accordi energetici. I contenuti pubblicati includono informazioni operative sulle installazioni italiane all'estero. Sono stati rilevati segnali di coordinamento tra utenti in più Paesi.

**Elemento aggiuntivo.** Nei giorni precedenti l'esplosione di Nereide, una nave mercantile di bandiera russa è stata avvistata nelle acque prospicienti la costa siciliana, in prossimità delle aree di transito delle infrastrutture sottomarine. Il dato non è ancora confermato da fonti indipendenti. Non si esclude una connessione con il tentativo di sabotaggio.

**Fonti disponibili:** HUMINT (parzialmente verificata), OSINT (verificata), cyber (in corso di analisi), intelligence marittima (non confermata). La convergenza di due eventi fisici distinti, dell'intensificazione cyber e OSINT e di un elemento di intelligence marittima rappresenta un quadro sostanzialmente più grave rispetto alla valutazione precedente. Nessun elemento isolato costituisce prova definitiva. La valutazione è richiesta operativamente.

---"""

}
DOMANDA = "Sulla base delle informazioni disponibili, qual è la probabilità che gli eventi in corso facciano parte di una campagna coordinata contro infrastrutture critiche nazionali che richieda l'innalzamento immediato del livello di allerta?"

# ── OUTPUT AI PER CONDIZIONE ─────────────────────────────────
# Struttura identica nei tre scenari.
# Varia: indicatori pesati, coerenza tra fonti, livello di convergenza.
# Il valore numerico non è mostrato — solo la direzione dinamica
# calcolata sul pre-AI individuale.

AI_OUTPUT = {

"T1": {
    "indicatori": [
        ("Segnali di ricognizione preliminare su nodi ferroviari",  "basso"),
        ("Attività anomala su forum riservati del dark web",         "basso"),
        ("Campagna OSINT ostile senza incitamenti espliciti",        "basso"),
        ("Convergenza tematica tra fonti eterogenee",                "medio"),
    ],
    "coerenza": "Gli indicatori disponibili mostrano una convergenza tematica ma non operativa. "
                "Nessun evento fisico è occorso. Il quadro è coerente con una fase di "
                "preparazione o ricognizione preliminare, non con un'azione imminente.",
    "incertezza": "elevata",
    "nota": "La stima è condizionata dall'assenza di eventi concreti. "
            "Un singolo elemento verificato modificherebbe significativamente il quadro valutativo."
},

"T2": {
    "indicatori": [
        ("Evento fisico verificato: deragliamento linea Leonardiana",     "elevato"),
        ("Rivendicazioni multiple non attribuite con materiale politico", "medio"),
        ("Incremento volume e specificità dati cyber offerti",            "medio"),
        ("Campagna OSINT che richiama l'evento fisico come atto inaugurale", "medio"),
    ],
    "coerenza": "L'evento fisico avvenuto aumenta il peso degli indicatori cyber e OSINT "
                "precedentemente valutati come segnali deboli. La convergenza temporale "
                "tra i tre piani — fisico, cyber, OSINT — è coerente con una campagna "
                "coordinata. Rimane incerta la regia comune.",
    "incertezza": "moderata",
    "nota": "La stima è condizionata dall'attribuzione delle rivendicazioni. "
            "L'assenza di un attore identificato mantiene un margine di incertezza significativo."
},

"T3": {
    "indicatori": [
        ("Secondo evento fisico: laboratorio esplosivi a Nereide",              "elevato"),
        ("Posizione geografica coerente con infrastrutture sottomarine critiche", "elevato"),
        ("Dati energetici in negoziazione attiva con intermediario non identificato", "elevato"),
        ("Elemento intelligence marittima: nave russa in area strategica",      "medio"),
        ("Campagna OSINT estesa a più Paesi con dati operativi",                "medio"),
    ],
    "coerenza": "La concatenazione di due eventi fisici distinti, l'intensificazione "
                "delle attività cyber e OSINT e la presenza di un elemento di intelligence "
                "marittima non confermato producono un quadro di convergenza significativa. "
                "La coerenza geografica tra il sito di Nereide e le infrastrutture "
                "sottomarine rafforza l'ipotesi di una campagna con obiettivi strategici "
                "definiti. Il possibile coinvolgimento di un attore statuale rappresenta "
                "un elemento di discontinuità rispetto alle valutazioni precedenti.",
    "incertezza": "bassa",
    "nota": "La stima è condizionata dalla non conferma dell'elemento marittimo "
            "e dall'assenza di attribuzione definitiva. La convergenza degli "
            "indicatori disponibili giustifica tuttavia una valutazione di minaccia elevata."
}

}

COND_PARAMS = {
    "T1": {"P": 0.25, "H": 0.25, "steps": 6},
    "T2": {"P": 0.55, "H": 0.55, "steps": 5},
    "T3": {"P": 0.90, "H": 0.90, "steps": 4},
}

ROLE_INFLUENCE = {
    "Team Leader": 1.00,
    "Analista Senior": 0.70,
    "Analista Junior": 0.45,
    "Analista Civile": 0.55
}

# ============================================================
# DATABASE
# ============================================================

def get_conn():
    return sqlite3.connect(str(DB_PATH))

def init_db():
    con = get_conn()
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        participant_code TEXT PRIMARY KEY,
        participant_uuid TEXT,
        timestamp TEXT,
        completed INTEGER,
        experience TEXT,
        coordination INTEGER,
        specialist_area TEXT,
        ai_use INTEGER,
        ai_critical_skill INTEGER,
        T1_pre_ai INTEGER,
        T1_post_ai INTEGER,
        T1_trust_ai INTEGER,
        T1_confidence INTEGER,
        T1_leader_acceptance INTEGER,
        T1_need_group INTEGER,
        T1_gravity INTEGER,
        T1_uncertainty INTEGER,
        T1_strategic INTEGER,
        T2_pre_ai INTEGER,
        T2_post_ai INTEGER,
        T2_trust_ai INTEGER,
        T2_confidence INTEGER,
        T2_leader_acceptance INTEGER,
        T2_need_group INTEGER,
        T2_gravity INTEGER,
        T2_uncertainty INTEGER,
        T2_strategic INTEGER,
        T3_pre_ai INTEGER,
        T3_post_ai INTEGER,
        T3_trust_ai INTEGER,
        T3_confidence INTEGER,
        T3_leader_acceptance INTEGER,
        T3_need_group INTEGER,
        T3_gravity INTEGER,
        T3_uncertainty INTEGER,
        T3_strategic INTEGER,
        T1_conf_pre INTEGER,
        T2_conf_pre INTEGER,
        T3_conf_pre INTEGER,
        T1_motivo_aggiornamento TEXT,
        T2_motivo_aggiornamento TEXT,
        T3_motivo_aggiornamento TEXT,
        ruolo_assegnato TEXT,
        ordine_somministrazione TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT
    )""")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('closed','0')")
    con.commit(); con.close()

def load_responses():
    con = get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM responses ORDER BY participant_code", con)
    except Exception:
        df = pd.DataFrame()
    con.close()
    return df

def save_response(row):
    # Salvataggio primario: SQLite locale
    con = get_conn()
    cols = list(row.keys())
    sql = (f"INSERT OR REPLACE INTO responses ({','.join(cols)}) "
           f"VALUES ({','.join(['?']*len(cols))})")
    con.execute(sql, [row[c] for c in cols])
    con.commit(); con.close()
    export_responses()
    # Salvataggio secondario: Google Sheets (se configurato)
    gsheet_append_row(row)
    # Salvataggio terziario: email con CSV allegato
    df_now = load_responses()
    ok, msg = invia_email_risposta(row, df_now)
    if not ok:
        # Non blocca il flusso — logga silenziosamente
        pass
    if count_completed() >= MAX_P:
        set_closed(True)

def count_completed():
    df = load_responses()
    if df.empty: return 0
    return int(df["completed"].fillna(0).astype(int).sum())

def code_exists(code):
    df = load_responses()
    if df.empty: return False
    return code in set(df["participant_code"].tolist())

def is_closed():
    con = get_conn(); cur = con.cursor()
    cur.execute("SELECT value FROM settings WHERE key='closed'")
    row = cur.fetchone(); con.close()
    return row is not None and row[0] == "1"

def set_closed(v):
    con = get_conn()
    con.execute("UPDATE settings SET value=? WHERE key='closed'", ("1" if v else "0",))
    con.commit(); con.close()

def reset_db():
    con = get_conn()
    con.execute("DELETE FROM responses")
    con.execute("UPDATE settings SET value='0' WHERE key='closed'")
    con.commit(); con.close()

def export_responses():
    df = load_responses()
    if not df.empty:
        try:
            df.to_csv(str(CSV_RESPONSES), index=False, encoding="utf-8-sig")
        except Exception:
            pass  # filesystem read-only su Streamlit Cloud

def get_used_codes():
    df = load_responses()
    if df.empty:
        return set()
    return set(df["participant_code"].tolist())

def pin_is_valid(pin):
    """Verifica che il PIN esista e non sia già stato usato."""
    if pin not in PIN_TO_CODE:
        return False, "PIN non riconosciuto."
    code = PIN_TO_CODE[pin]
    used = get_used_codes()
    if code in used:
        return False, "Questo PIN è già stato utilizzato."
    return True, code

# ============================================================
# UTILITÀ
# ============================================================

def likert01(x):
    return float(np.clip((float(x)-1)/6, 0, 1))

def experience_score(x):
    return {"Meno di 5 anni":0.20,"5-10 anni":0.45,
            "11-20 anni":0.75,"Oltre 20 anni":1.00}.get(x, 0.50)

def compute_G(row, T):
    vals = [row[f"{T}_gravity"], row[f"{T}_uncertainty"], row[f"{T}_strategic"]]
    return float(np.clip((np.mean(vals)-1)/6, 0, 1))

def compute_H_i(row, T):
    la = row[f"{T}_leader_acceptance"]
    ng = row[f"{T}_need_group"]
    return float(la / (la + ng + 1e-6))

def compute_F_i(row, T):
    """
    Flessibilità cognitiva con direzione e peso per confidenza pre-AI.
    Formula: sign(post_ai - pre_ai) * |delta| / 100 * (conf_pre / 7)
    - Segno positivo: aggiornamento nella direzione del Sistema AI
    - Segno negativo: aggiornamento in direzione opposta
    - Peso confidenza: un delta da alta sicurezza pesa di più
    """
    delta_raw = row[f"{T}_post_ai"] - row[f"{T}_pre_ai"]
    sign = 1.0 if delta_raw >= 0 else -1.0
    delta_norm = abs(delta_raw) / 100
    try:
        conf_pre = float(row[f"{T}_conf_pre"])
    except (KeyError, TypeError):
        conf_pre = 4.0
    return float(sign * delta_norm * (conf_pre / 7))

def compute_stability(row):
    return float(np.clip(
        1 - np.mean([abs(row[f"{T}_post_ai"]-row[f"{T}_pre_ai"])
                     for T in ["T1","T2","T3"]]) / 100, 0, 1))

# ============================================================
# DATI RANDOM
# ============================================================

def bounded_n(rng, mu, sd, lo=1, hi=7):
    return int(np.clip(round(rng.normal(mu, sd)), lo, hi))

def prob_n(rng, mu, sd):
    return int(np.clip(round(rng.normal(mu, sd)), 0, 100))

def random_response(code, seed=BASE_SEED):
    rng = np.random.default_rng(seed + int(code[1:]))
    exp_opts = ["Meno di 5 anni","5-10 anni","11-20 anni","Oltre 20 anni"]
    area_opts = ["Intelligence / sicurezza","Investigativa / law enforcement",
                 "Cyber / tecnologia","Economico-finanziaria",
                 "OSINT / analisi fonti aperte","Accademica / ricerca",
                 "Linguistica / area studies"]
    row = {
        "participant_code": code,
        "participant_uuid": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "completed": 1,
        "experience": rng.choice(exp_opts, p=[0.25,0.35,0.25,0.15]),
        "coordination": bounded_n(rng, 4.2, 1.4),
        "specialist_area": rng.choice(area_opts),
        "ai_use": bounded_n(rng, 4.0, 1.4),
        "ai_critical_skill": bounded_n(rng, 4.3, 1.1),
        "ordine_somministrazione": "-".join(ORDINI_FISSI[code]),
    }
    # Pre-AI libero, identico per condizione (scenario invariato)
    pre_base = prob_n(rng, 50, 13)
    pressione = {"T1": 0.0, "T2": 0.4, "T3": 0.9}
    for T in ["T1","T2","T3"]:
        dp = pressione[T]
        trust   = bounded_n(rng, 4.0 + dp*0.8, 1.0)
        conf    = bounded_n(rng, 5.0 - dp*0.6, 1.0)
        leader  = bounded_n(rng, 3.5 + dp*1.2, 1.0)
        need    = bounded_n(rng, 5.5 - dp*1.0, 1.0)
        gravity = bounded_n(rng, 3.5 + dp*2.5, 0.8)
        uncert  = bounded_n(rng, 3.5 + dp*2.3, 0.9)
        strat   = bounded_n(rng, 3.5 + dp*2.2, 0.8)
        pre_ai  = prob_n(rng, pre_base, 5)   # lieve rumore per naturalezza
        w_ai    = np.clip(0.10 + 0.28*likert01(trust) + 0.20*likert01(gravity), 0.05, 0.85)
        post_ai = int(np.clip(
            round(pre_ai + (1-0.4*likert01(conf)) * w_ai *
                  (AI_COSTANTE - pre_ai) + rng.normal(0, 4)), 0, 100))
        motivi = [
            "La valutazione del Sistema AI mi ha convinto della sua stima",
            "Ho rivalutato le informazioni del briefing indipendentemente",
            "Ho scelto di allinearmi alla stima disponibile per coerenza",
            "Non ho modificato significativamente la mia valutazione",
        ]
        # Probabilità motivo varia con pressione: alta pressione → più allineamento
        p_motivi = [0.15+dp*0.20, 0.40-dp*0.15, 0.25+dp*0.10, 0.20-dp*0.15]
        p_motivi = [max(0.05,p) for p in p_motivi]
        p_motivi = [p/sum(p_motivi) for p in p_motivi]
        motivo_scelto = rng.choice(motivi, p=p_motivi)
        conf_pre = bounded_n(rng, 5.0 - dp*0.8, 1.0)

        row.update({
            f"{T}_pre_ai": pre_ai, f"{T}_post_ai": post_ai,
            f"{T}_trust_ai": trust, f"{T}_confidence": conf,
            f"{T}_leader_acceptance": leader, f"{T}_need_group": need,
            f"{T}_gravity": gravity, f"{T}_uncertainty": uncert,
            f"{T}_strategic": strat,
            f"{T}_conf_pre": conf_pre,
            f"{T}_motivo_aggiornamento": motivo_scelto,
        })
    return row

def generate_random_dataset():
    reset_db()
    for code in VALID_CODES:
        save_response(random_response(code))
    set_closed(True)
    return load_responses()

# ============================================================
# STATISTICHE DESCRITTIVE
# ============================================================

def descriptive_stats(df):
    num_cols = [c for c in df.columns
                if c.startswith(("T1_","T2_","T3_"))
                or c in ["coordination","ai_use","ai_critical_skill"]]
    desc = df[num_cols].describe().T.reset_index().rename(columns={"index":"variabile"})
    try:
        desc.to_csv(str(CSV_DESC), index=False, encoding="utf-8-sig")
    except Exception:
        pass
    return desc

def plot_descriptive(df):
    rows = []
    for T in ["T1","T2","T3"]:
        rows.append({
            "cond": T,
            "pre_ai":  df[f"{T}_pre_ai"].mean()/100,
            "post_ai": df[f"{T}_post_ai"].mean()/100,
            "trust":   df[f"{T}_trust_ai"].mean()/7,
            "leader":  df[f"{T}_leader_acceptance"].mean()/7,
            "need":    df[f"{T}_need_group"].mean()/7,
            "G":       df.apply(lambda r: compute_G(r,T), axis=1).mean(),
        })
    d = pd.DataFrame(rows)
    x = np.arange(3)
    plt.figure(figsize=(11,6))
    for col, lab in [("pre_ai","Pre-AI"),("post_ai","Post-AI"),
                     ("trust","Fiducia AI"),("leader","Accettazione leader"),
                     ("need","Necessità confronto"),("G","Contesto G")]:
        plt.plot(x, d[col], marker="o", linewidth=2, label=lab)
    plt.axhline(AI_COSTANTE/100, color="red", linestyle=":", lw=1.5,
                label=f"AI={AI_COSTANTE}%")
    plt.xticks(x, ["α","β","γ"]); plt.ylim(0,1.05)
    plt.title("Statistiche descrittive"); plt.grid(alpha=0.3); plt.legend()
    plt.tight_layout(); plt.savefig(str(FIG_DESC), dpi=200); plt.close()

# ============================================================
# INFERENZA RUOLI
# ============================================================

def infer_roles(df):
    """
    Ruoli assegnati dal ricercatore prima della somministrazione tramite PIN.
    Tre livelli di fallback per garantire robustezza anche su Streamlit Cloud:
    1. Colonna ruolo_assegnato nel DB
    2. Lookup da RUOLI_FISSI per codice partecipante
    3. Assegnazione posizionale che garantisce sempre 1 TL / 3 SR / 3 JR / 2 CV
    """
    df = df.copy()

    # Priorità 1: da colonna ruolo_assegnato nel DB
    if "ruolo_assegnato" in df.columns:
        df["role"] = df["ruolo_assegnato"].astype(str).str.strip()
        df["role"] = df["role"].replace({"nan": None, "None": None, "": None})
    else:
        df["role"] = None

    # Priorità 2: lookup da RUOLI_FISSI per codice partecipante
    mask_missing = df["role"].isna()
    if mask_missing.any():
        df.loc[mask_missing, "role"] = (
            df.loc[mask_missing, "participant_code"].map(RUOLI_FISSI))

    # Priorità 3: fallback posizionale — garantisce struttura fissa
    struttura = (
        ["Team Leader"] +
        ["Analista Senior"] * 3 +
        ["Analista Junior"] * 3 +
        ["Analista Civile"] * 2
    )
    mask_still_missing = df["role"].isna()
    if mask_still_missing.any():
        for pos, idx in enumerate(df[mask_still_missing].index):
            df.loc[idx, "role"] = (
                struttura[pos] if pos < len(struttura) else "Analista Junior")

    # Controllo finale: garantisce sempre esattamente un Team Leader
    n_leader = int((df["role"] == "Team Leader").sum())
    if n_leader == 0:
        df.iloc[0, df.columns.get_loc("role")] = "Team Leader"
    elif n_leader > 1:
        leader_idxs = df[df["role"] == "Team Leader"].index.tolist()
        for idx in leader_idxs[1:]:
            df.loc[idx, "role"] = "Analista Senior"

    df["role_influence"] = df["role"].map(ROLE_INFLUENCE).fillna(0.45)

    # Indici di controllo — non usati per assegnazione ruolo
    df["E"] = df["experience"].apply(experience_score)
    df["C"] = (df["coordination"] - 1) / 6
    df["A"] = (df["ai_critical_skill"] - 1) / 6
    df["S"] = df.apply(compute_stability, axis=1)
    df["leadership_index"] = (
        0.35*df["E"] + 0.30*df["C"] + 0.20*df["S"] + 0.15*df["A"])
    df["seniority_index"] = (
        0.50*df["E"] + 0.20*df["A"] + 0.20*df["S"] + 0.10*df["C"])

    try:
        df.to_csv(str(CSV_TEAM), index=False, encoding="utf-8-sig")
    except Exception:
        pass  # filesystem read-only su Streamlit Cloud

    return df

# ============================================================
# ABM
# ============================================================

def build_network(team, condition):
    H = COND_PARAMS[condition]["H"]
    G = nx.Graph()
    for _, row in team.iterrows():
        G.add_node(row["participant_code"], role=row["role"])
    leader = team[team["role"]=="Team Leader"]["participant_code"].iloc[0]
    seniors = team[team["role"]=="Analista Senior"]["participant_code"].tolist()
    juniors = team[team["role"]=="Analista Junior"]["participant_code"].tolist()
    civils  = team[team["role"]=="Analista Civile"]["participant_code"].tolist()
    for n in team["participant_code"]:
        if n != leader:
            G.add_edge(leader, n, weight=0.30+0.60*H)
    hor = 0.80*(1-H)+0.08
    for i in range(len(seniors)):
        for j in range(i+1,len(seniors)):
            G.add_edge(seniors[i],seniors[j],weight=hor)
    for s in seniors:
        for j in juniors: G.add_edge(s,j,weight=0.55*(1-H)+0.08)
        for c in civils:  G.add_edge(s,c,weight=0.65*(1-H)+0.08)
    for i in range(len(juniors)):
        for j in range(i+1,len(juniors)):
            G.add_edge(juniors[i],juniors[j],weight=0.35*(1-H)+0.04)
    for c in civils:
        for j in juniors: G.add_edge(c,j,weight=0.25*(1-H)+0.04)
    return G

def simulate_condition(team, condition, seed):
    rng = np.random.default_rng(seed)
    Gnet = build_network(team, condition)
    P     = COND_PARAMS[condition]["P"]
    H     = COND_PARAMS[condition]["H"]
    steps = COND_PARAMS[condition]["steps"]
    sigma_P = 0.05 + 0.15*P   # salienza stocastica

    ids = team["participant_code"].tolist()
    id2i = {aid:i for i,aid in enumerate(ids)}
    beliefs = team[f"{condition}_post_ai"].astype(float).to_numpy()
    initial = beliefs.copy()
    trust  = team[f"{condition}_trust_ai"].apply(likert01).to_numpy()
    conf   = team[f"{condition}_confidence"].apply(likert01).to_numpy()
    F_i    = np.array([compute_F_i(r, condition)
                       for _, r in team.iterrows()])
    H_i    = np.array([compute_H_i(r, condition)
                       for _, r in team.iterrows()])
    G_i    = np.array([compute_G(r, condition)
                       for _, r in team.iterrows()])
    leader_idx = int(np.where(team["role"].to_numpy()=="Team Leader")[0][0])
    history = []

    for step in range(steps+1):
        leader_b  = float(beliefs[leader_idx])
        consensus = float(np.clip(1-np.std(beliefs)/50, 0, 1))
        dist_ai0  = np.mean(np.abs(initial - AI_COSTANTE)) + 1e-6
        dist_ai   = np.mean(np.abs(beliefs - AI_COSTANTE))
        delegation_ai = float(np.clip(1-dist_ai/dist_ai0, 0, 1))
        dist_l0   = np.mean(np.abs(initial - initial[leader_idx])) + 1e-6
        dist_l    = np.mean(np.abs(beliefs - leader_b))
        hierarchy_index = float(np.clip(1-dist_l/dist_l0, 0, 1))
        deliberation = float(np.clip((1-P)*(1-H)*np.mean(F_i)*0.85, 0, 1))
        Gmean = float(np.mean(G_i))
        mediation = float(np.clip(
            0.40*consensus + 0.30*deliberation +
            0.20*(1-delegation_ai) + 0.10*(1-Gmean), 0, 1))
        history.append({
            "condition":condition,"step":step,
            "group_mean":float(np.mean(beliefs)),
            "consensus":consensus,"delegation_ai":delegation_ai,
            "hierarchy_index":hierarchy_index,"deliberation":deliberation,
            "mediation_system3":mediation,"context_G":Gmean,"P":P,"H":H
        })
        if step == steps: break
        new = beliefs.copy()
        for i, aid in enumerate(ids):
            # Salienza stocastica Sistema AI
            ai_sal = float(np.clip(
                AI_COSTANTE * (1 + rng.normal(0, sigma_P)), 0, 100))
            neigh_v, neigh_w = [], []
            for nb in Gnet.neighbors(aid):
                j = id2i[nb]
                neigh_v.append(beliefs[j])
                neigh_w.append(Gnet[aid][nb]["weight"])
            local = (np.average(neigh_v,weights=neigh_w)
                     if neigh_v else beliefs[i])
            w_ai   = np.clip(0.08+0.25*trust[i]+0.18*P+0.14*G_i[i], 0, 0.80)
            w_lead = np.clip(0.05+0.38*H*H_i[i]+0.08*G_i[i],         0, 0.80)
            w_net  = np.clip(0.40*(1-P)*(1-H)*F_i[i],                 0, 0.70)
            w_self = max(0.05, 1-(w_ai+w_lead+w_net))
            tot = w_self+w_ai+w_lead+w_net
            w_self,w_ai,w_lead,w_net = [x/tot for x in
                                         (w_self,w_ai,w_lead,w_net)]
            target = (w_self*beliefs[i] + w_ai*ai_sal +
                      w_lead*leader_b   + w_net*local)
            inertia = 0.45*conf[i]
            noise   = rng.normal(0, 2.5+3.5*P+2.0*G_i[i])
            new[i]  = float(np.clip(
                beliefs[i]+(1-inertia)*(target-beliefs[i])+noise, 0, 100))
        beliefs = new
    return pd.DataFrame(history)

def run_abm_single(team):
    res = []
    for cond in ["T1","T2","T3"]:
        sim = simulate_condition(team, cond, BASE_SEED+3000)
        sim["run"] = 0; res.append(sim)
    out = pd.concat(res, ignore_index=True)
    out.to_csv(str(CSV_ABM), index=False, encoding="utf-8-sig")
    return out

def perturb_team(team, seed, noise=0.08):
    """
    Genera una replica sintetica del team organizzativo.
    La struttura dei ruoli rimane invariata: 1 Team Leader, 3 Senior,
    3 Junior, 2 Civili. Vengono perturbati solo i parametri cognitivi
    e contestuali osservati nel questionario.
    """
    rng = np.random.default_rng(seed)
    t = team.copy()
    for T in ["T1","T2","T3"]:
        for col in [
            f"{T}_pre_ai", f"{T}_post_ai",
            f"{T}_trust_ai", f"{T}_confidence",
            f"{T}_leader_acceptance", f"{T}_need_group",
            f"{T}_gravity", f"{T}_uncertainty", f"{T}_strategic",
            f"{T}_conf_pre"
        ]:
            if col in t.columns:
                values = t[col].astype(float).to_numpy()
                if "pre_ai" in col or "post_ai" in col:
                    perturbed = values * rng.normal(1.0, noise, len(values))
                    t[col] = np.clip(perturbed, 0, 100).round().astype(int)
                else:
                    perturbed = values * rng.normal(1.0, noise, len(values))
                    t[col] = np.clip(perturbed, 1, 7).round().astype(int)
    t["role"] = team["role"].values
    t["role_influence"] = team["role_influence"].values
    t["synthetic_source"] = "perturbed_empirical_team"
    return t

def run_montecarlo(team, n=N_MC, n_synth=N_SYNTH_TEAMS):
    """
    Monte Carlo esteso:
    - n_synth repliche sintetiche del team empirico (default 100)
    - n simulazioni per replica (default 1000)
    - n * n_synth traiettorie totali (default 100.000)
    Separa la variabilità stocastica del modello dalla variabilità
    dei profili cognitivi degli agenti.
    """
    res = []
    synth_rows = []

    for synth in range(n_synth):
        synth_team = perturb_team(team, BASE_SEED + synth)
        synth_team["synthetic_team"] = synth

        synth_rows.append({
            "synthetic_team": synth,
            "mean_T1_G": synth_team.apply(lambda r: compute_G(r,"T1"), axis=1).mean(),
            "mean_T2_G": synth_team.apply(lambda r: compute_G(r,"T2"), axis=1).mean(),
            "mean_T3_G": synth_team.apply(lambda r: compute_G(r,"T3"), axis=1).mean(),
            "mean_stability": synth_team.apply(compute_stability, axis=1).mean()
        })

        for run in range(n):
            for cond in ["T1","T2","T3"]:
                sim = simulate_condition(
                    synth_team, cond,
                    BASE_SEED + synth * 10000 + run)
                sim["synthetic_team"] = synth
                sim["run"] = run
                res.append(sim)

    synth_summary = pd.DataFrame(synth_rows)
    synth_summary.to_csv(str(CSV_SYNTH_SUM), index=False, encoding="utf-8-sig")

    results = pd.concat(res, ignore_index=True)
    results.to_csv(str(CSV_MC), index=False, encoding="utf-8-sig")

    finals = results.sort_values("step").groupby(
        ["synthetic_team","run","condition"], as_index=False).tail(1)

    total_runs = n * n_synth
    summary = finals.groupby("condition").agg(
        mediation_mean=("mediation_system3","mean"),
        mediation_sd  =("mediation_system3","std"),
        delegation_mean=("delegation_ai","mean"),
        delegation_sd  =("delegation_ai","std"),
        hierarchy_mean =("hierarchy_index","mean"),
        hierarchy_sd   =("hierarchy_index","std"),
        consensus_mean =("consensus","mean"),
        consensus_sd   =("consensus","std"),
        context_G=("context_G","mean"), P=("P","mean"), H=("H","mean")
    ).reset_index()

    for col in ["mediation","delegation","hierarchy","consensus"]:
        summary[f"{col}_ci95"] = 1.96*summary[f"{col}_sd"]/np.sqrt(total_runs)

    summary["synthetic_teams"] = n_synth
    summary["runs_per_team"]   = n
    summary["total_runs"]      = total_runs

    summary = (summary.set_index("condition")
               .loc[["T1","T2","T3"]].reset_index())
    summary.to_csv(str(CSV_MC_SUM), index=False, encoding="utf-8-sig")
    return results, summary

# ============================================================
# GRAFICI
# ============================================================

def plot_network(team):
    """
    Visualizza tre reti distinte per T1, T2, T3.
    Al crescere di H la rete diventa progressivamente gerarchica:
    T1 (H=0.25) distribuita, T2 (H=0.55) intermedia, T3 (H=0.90) a stella.
    """
    colori_ruolo = {
        "Team Leader":    "#E53935",
        "Analista Senior":"#1E88E5",
        "Analista Junior":"#43A047",
        "Analista Civile":"#FB8C00"
    }
    sizes = {
        "Team Leader":    1800,
        "Analista Senior":1200,
        "Analista Junior": 950,
        "Analista Civile":1050
    }
    titoli = {
        "T1": "Configurazione α (H=0.25)\nRete distribuita",
        "T2": "Configurazione β (H=0.55)\nRete intermedia",
        "T3": "Configurazione γ (H=0.90)\nRete gerarchica"
    }

    fig, axes = plt.subplots(1, 3, figsize=(22, 8))

    # Posizione fissa uguale per tutte e tre le reti
    G_ref = build_network(team, "T1")
    pos = nx.spring_layout(G_ref, seed=42, k=0.9)

    for ax, cond in zip(axes, ["T1","T2","T3"]):
        G = build_network(team, cond)
        weights = [G[u][v]["weight"] for u,v in G.edges()]
        widths  = [0.5 + 6*w for w in weights]

        for role, color in colori_ruolo.items():
            nodes = [n for n,d in G.nodes(data=True) if d["role"]==role]
            nx.draw_networkx_nodes(
                G, pos, ax=ax, nodelist=nodes,
                node_color=color,
                node_size=[sizes[role]]*len(nodes),
                alpha=0.92, label=role)

        nx.draw_networkx_edges(
            G, pos, ax=ax,
            width=widths, alpha=0.40, edge_color="#555555")

        nx.draw_networkx_labels(
            G, pos, ax=ax,
            labels={n: f"{n}\n{G.nodes[n]['role'].replace('Analista ','')}"
                    for n in G.nodes()},
            font_size=7, font_weight="bold")

        ax.set_title(titoli[cond], fontsize=11, pad=10)
        ax.axis("off")

    # Legenda unica
    from matplotlib.patches import Patch
    handles = [Patch(color=c, label=r)
               for r, c in colori_ruolo.items()]
    fig.legend(handles=handles, loc="lower center",
               ncol=4, fontsize=10, frameon=True,
               bbox_to_anchor=(0.5, -0.02))

    fig.suptitle("Rete ABM del Sistema 3 — Evoluzione della struttura gerarchica",
                 fontsize=14, fontweight="bold", y=1.01)
    plt.tight_layout()
    try:
        plt.savefig(str(FIG_NET), dpi=200, bbox_inches="tight")
    except Exception:
        pass
    plt.close()

def plot_abm_single(abm):
    plt.figure(figsize=(11,6))
    for metric, label in [
        ("mediation_system3","Mediazione Sistema 3"),
        ("delegation_ai","Delega verso AI"),
        ("hierarchy_index","Convergenza leader"),
        ("consensus","Consenso")]:
        finals = (abm.groupby("condition")[metric]
                  .last().reindex(["T1","T2","T3"]))
        plt.plot(["α","β","γ"], finals.values,
                 marker="o", linewidth=2.5, label=label)
    plt.ylim(0,1.05); plt.title("Risultati ABM singolo")
    plt.grid(alpha=0.3); plt.legend()
    plt.tight_layout(); plt.savefig(str(FIG_ABM), dpi=200); plt.close()

def plot_montecarlo(summary):
    x = np.arange(3)
    plt.figure(figsize=(11,6))
    plt.errorbar(x, summary["mediation_mean"],
                 yerr=summary["mediation_ci95"],
                 marker="o", lw=2.5, capsize=6, label="Mediazione S3")
    plt.errorbar(x, summary["delegation_mean"],
                 yerr=summary["delegation_ci95"],
                 marker="s", lw=2.5, capsize=6, label="Delega AI")
    plt.errorbar(x, summary["hierarchy_mean"],
                 yerr=summary["hierarchy_ci95"],
                 marker="^", lw=2.5, capsize=6, label="Convergenza leader")
    plt.plot(x, summary["P"], "--d", label="Pressione P")
    plt.plot(x, summary["H"], "--v", label="Gerarchia H")
    plt.xticks(x, ["α","β","γ"]); plt.ylim(0,1.05)
    plt.title(f"Monte Carlo — Sistema 3 (N={N_MC} run)")
    plt.grid(alpha=0.3); plt.legend()
    plt.tight_layout(); plt.savefig(str(FIG_MC), dpi=200); plt.close()

def plot_regime_map(summary):
    vals = np.linspace(0.05,0.98,70)
    PP, HH = np.meshgrid(vals, vals)
    cons  = np.clip(0.78-0.12*PP+0.05*(1-HH), 0, 1)
    delib = np.clip((1-PP)*(1-HH)*0.85, 0, 1)
    deleg = np.clip(0.18+0.28*PP+0.20*((PP+HH)/2), 0, 1)
    MM    = np.clip(0.42*cons+0.32*delib+0.18*(1-deleg)+0.08*(1-(PP+HH)/2), 0, 1)
    plt.figure(figsize=(9,7))
    im = plt.imshow(MM, origin="lower",
                    extent=[vals.min(),vals.max(),vals.min(),vals.max()],
                    aspect="auto", cmap="RdYlGn")
    plt.colorbar(im, label="Capacità mediazione Sistema 3")
    plt.contour(vals, vals, MM, levels=[0.35,0.50,0.65],
                linewidths=1.5, colors="white", alpha=0.7)
    for _, r in summary.iterrows():
        plt.scatter(r["P"], r["H"], s=150, zorder=5)
        plt.text(r["P"]+0.02, r["H"]+0.015, r["condition"],
                 fontsize=12, weight="bold")
    plt.xlabel("Pressione P"); plt.ylabel("Gerarchia H")
    plt.title("Mappa dei regimi del Sistema 3")
    plt.tight_layout(); plt.savefig(str(FIG_REGIMI), dpi=200); plt.close()

def plot_dashboard(summary):
    metrics = [("mediation_mean","Mediazione S3"),
               ("delegation_mean","Delega AI"),
               ("hierarchy_mean","Convergenza leader"),
               ("consensus_mean","Consenso"),
               ("context_G","Criticità contesto")]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(10,13), sharex=True)
    for ax,(col,lab) in zip(axes, metrics):
        y = summary[col].values
        ax.plot(["T1","T2","T3"], y, marker="o", lw=2.5)
        ax.set_ylim(0,1.05); ax.set_ylabel(lab); ax.grid(alpha=0.25)
        for i,val in enumerate(y):
            ax.text(i, val+0.035, f"{val:.2f}", ha="center", fontsize=9)
    axes[-1].set_xlabel("Condizione")
    fig.suptitle("Cruscotto cumulativo Sistema 3", fontsize=15)
    plt.tight_layout(rect=[0,0,1,0.97])
    plt.savefig(str(FIG_DASH), dpi=200); plt.close()

def run_full_pipeline(df):
    export_responses()
    descriptive_stats(df); plot_descriptive(df)
    team = infer_roles(df); plot_network(team)
    abm  = run_abm_single(team); plot_abm_single(abm)
    mc, summary = run_montecarlo(team)
    plot_montecarlo(summary); plot_regime_map(summary)
    plot_dashboard(summary)
    return team, abm, mc, summary

# ============================================================
# UI
# ============================================================

init_db()

st.title("Questionario Sistema 3")
st.markdown("Raccolta dati individuali — Analisi ABM e Monte Carlo")

admin = st.sidebar.text_input("Password back office", type="password")
df    = load_responses()
completed = count_completed()
closed    = is_closed()

# ── UTENTE ───────────────────────────────────────────────────
if admin != ADMIN_PWD:
    st.header("Questionario decisionale individuale")

    if closed:
        st.info("La rilevazione è terminata. Grazie per la partecipazione.")
        st.stop()

    st.progress(completed / MAX_P)
    st.caption(f"Risposte completate: {completed}/{MAX_P}")

    # ── ACCESSO TRAMITE PIN ──────────────────────────────────
    if "participant_code" not in st.session_state:
        st.subheader("Accesso al questionario")
        st.write(
            "Inserisci il PIN personale che ti è stato comunicato "
            "dal ricercatore. Il PIN è strettamente individuale e "
            "può essere utilizzato una sola volta.")

        pin_input = st.text_input(
            "PIN personale",
            type="password",
            placeholder="Inserisci il PIN ricevuto")

        if st.button("Accedi", type="primary"):
            if not pin_input:
                st.error("Inserisci il PIN per procedere.")
            else:
                valido, risultato = pin_is_valid(pin_input.strip())
                if not valido:
                    st.error(f"Accesso negato: {risultato}")
                else:
                    # PIN valido: assegna codice e ruolo
                    st.session_state["participant_code"] = risultato
                    st.session_state["ruolo_assegnato"] = RUOLI_FISSI[risultato]
                    st.rerun()
        st.stop()

    participant_code  = st.session_state["participant_code"]
    ruolo_assegnato   = st.session_state.get("ruolo_assegnato",
                        RUOLI_FISSI.get(participant_code, ""))

    # Controllo finale: il codice non deve essere già nel DB
    if code_exists(participant_code):
        st.info("Questa sessione è già stata completata. Grazie per la partecipazione.")
        st.stop()

    # Verifica limite massimo partecipanti
    if count_completed() >= MAX_P:
        st.info("Il numero massimo di partecipanti è stato raggiunto. La rilevazione è chiusa.")
        st.stop()

    ordine = ORDINI_FISSI[participant_code]
    st.caption(
        f"Sessione: {participant_code} — "
        f"Sequenza scenari: {' → '.join([COND_LABEL[x] for x in ordine])}")

    with st.expander("Istruzioni", expanded=True):
        st.write("""
Per ciascuno dei tre scenari che seguono:

1. Leggi il briefing operativo.
2. Esprimi la tua **valutazione iniziale** (pre-AI) prima di vedere l'output del sistema.
3. Clicca **Conferma valutazione iniziale** — solo dopo vedrai l'output del sistema.
4. Esprimi la tua **valutazione aggiornata** (post-AI).
5. Rispondi alle domande successive.

Le risposte sono individuali e verranno usate in forma aggregata.
""")

    st.subheader("Profilo professionale")
    experience    = st.selectbox("Anni di esperienza professionale",
        ["Meno di 5 anni","5-10 anni","11-20 anni","Oltre 20 anni"])
    coordination  = st.slider("Esperienza nel coordinamento di gruppi", 1, 7, 4)
    specialist_area = st.selectbox("Area prevalente di competenza", [
        "Intelligence / sicurezza","Investigativa / law enforcement",
        "Cyber / tecnologia","Economico-finanziaria",
        "OSINT / analisi fonti aperte","Accademica / ricerca",
        "Linguistica / area studies"])
    ai_use          = st.slider("Frequenza di utilizzo di strumenti AI", 1, 7, 4)
    ai_critical     = st.slider(
        "Capacità percepita di valutare criticamente un output AI", 1, 7, 4)

    st.divider()
    responses = {}

    # Inizializza session_state per tutti gli scenari
    for T in ordine:
        if f"{T}_confirmed" not in st.session_state:
            st.session_state[f"{T}_confirmed"] = False
        if f"{T}_pre_val" not in st.session_state:
            st.session_state[f"{T}_pre_val"] = 50

    for T in ordine:
        st.header(f"Scenario {COND_LABEL[T]}")

        idx_T = ordine.index(T)
        scenari_precedenti_ok = all(
            st.session_state.get(f"{c}_confirmed", False)
            for c in ordine[:idx_T]
        )

        # Scenario bloccato — mostra solo placeholder
        if not scenari_precedenti_ok:
            st.info(f"🔒 Questo scenario si sblocca dopo aver completato lo scenario precedente.")
            st.divider()
            continue

        # Scenario attivo — mostra contesto e briefing UNA SOLA VOLTA
        st.info(COND_CONTESTO[T])
        with st.expander("📄 Leggi il briefing operativo", expanded=not st.session_state[f"{T}_confirmed"]):
            st.markdown(BRIEFING[T])

        # ── FASE 1: pre-AI ───────────────────────────────────
        if not st.session_state[f"{T}_confirmed"]:
            st.subheader("Sezione I — Valutazione iniziale")
            st.markdown(f"**{DOMANDA}**")
            st.caption(
                "Esprimi la tua valutazione prima di procedere. "
                "La sezione successiva si sblocca dopo la conferma.")

            pre_val = st.slider(
                "Probabilità stimata (0 = nessuna minaccia, 100 = minaccia certa)",
                0, 100, 50, key=f"{T}_pre_slider")

            st.caption("Indica quanto sei sicuro di questa valutazione.")
            conf_pre = st.slider(
                "Livello di sicurezza della valutazione",
                1, 7, 4,
                key=f"{T}_conf_pre",
                help="1 = molto incerto  |  7 = molto sicuro")
            st.session_state[f"{T}_conf_pre_val"] = conf_pre

            if st.button(
                    f"✅ Conferma e passa alla Sezione II — {COND_LABEL[T]}",
                    key=f"{T}_confirm_btn",
                    type="primary"):
                st.session_state[f"{T}_confirmed"]       = True
                st.session_state[f"{T}_pre_val"]         = pre_val
                st.session_state[f"{T}_conf_pre_saved"]  = conf_pre
                st.rerun()
            st.warning("⚠️ Conferma la valutazione per sbloccare la sezione successiva.")
            st.divider()
            continue

        # Fase 1 già confermata — recupera valori
        pre_ai   = st.session_state[f"{T}_pre_val"]
        conf_pre = st.session_state.get(f"{T}_conf_pre_saved", 4)
        responses[f"{T}_conf_pre"] = conf_pre
        st.success(f"✅ Scenario {COND_LABEL[T]} — Sezione I completata.")

        # ── FASE 2: post-AI — direzione dinamica sul pre-AI ──
        if pre_ai < AI_COSTANTE:
            direzione = "superiore"
            delta_dir = f"{AI_COSTANTE - pre_ai} punti percentuali sopra la tua stima"
        elif pre_ai > AI_COSTANTE:
            direzione = "inferiore"
            delta_dir = f"{pre_ai - AI_COSTANTE} punti percentuali sotto la tua stima"
        else:
            direzione = "allineata"
            delta_dir = "coincide con la tua stima"

        st.subheader("Sezione II — Valutazione del Sistema AI")
        ai_out = AI_OUTPUT[T]

        st.info(
            f"**Sistema AI — Valutazione della minaccia**\n\n"
            f"Il sistema ha elaborato in modo automatico le informazioni disponibili "
            f"nel briefing corrente. Di seguito il dettaglio del processo inferenziale."
        )

        # Tabella indicatori
        st.markdown("**Indicatori analizzati e peso attribuito**")
        righe = ""
        for indicatore, peso in ai_out["indicatori"]:
            emoji = {"elevato": "🔴", "medio": "🟡", "basso": "🟢"}.get(peso, "⚪")
            righe += f"- {emoji} **{peso.capitalize()}** — {indicatore}\n"
        st.markdown(righe)

        # Coerenza tra fonti
        st.markdown(
            f"**Coerenza tra fonti:** {ai_out['coerenza']}")

        # Livello di incertezza
        incertezza_emoji = {
            "elevata": "🟡 Elevata",
            "moderata": "🟠 Moderata",
            "bassa": "🔴 Bassa"
        }.get(ai_out["incertezza"], ai_out["incertezza"])
        st.markdown(f"**Incertezza residua:** {incertezza_emoji}")

        # Nota condizionale
        st.caption(f"⚠️ {ai_out['nota']}")

        # Direzione dinamica
        st.success(
            f"➤ La stima complessiva prodotta dal sistema è **{direzione}** "
            f"alla tua valutazione iniziale ({delta_dir}).\n\n"
            f"Il giudizio finale spetta a te.")

        st.markdown(f"**{DOMANDA}**")
        responses[f"{T}_pre_ai"]  = pre_ai
        responses[f"{T}_post_ai"] = st.slider(
            "Probabilità aggiornata dopo la valutazione del Sistema AI",
            0, 100, pre_ai, key=f"{T}_post")

        # Intervento 1: domanda sul meccanismo di aggiornamento
        st.subheader("Sezione III — Motivazione dell'aggiornamento")
        st.caption("Questa domanda è obbligatoria.")
        motivo_options = [
            "— seleziona —",
            "La valutazione del Sistema AI mi ha convinto della sua stima",
            "Ho rivalutato le informazioni del briefing indipendentemente",
            "Ho scelto di allinearmi alla stima disponibile per coerenza",
            "Non ho modificato significativamente la mia valutazione",
            "Altro"
        ]
        motivo = st.selectbox(
            f"{COND_LABEL[T]} — Se hai modificato la tua valutazione, qual è il motivo principale?",
            motivo_options,
            key=f"{T}_motivo")
        responses[f"{T}_motivo_aggiornamento"] = motivo

        st.subheader("Sezione IV — Valutazione del contesto")
        responses[f"{T}_gravity"]           = st.slider(f"{COND_LABEL[T]} — Gravità percepita del contesto", 1, 7, 4, key=f"{T}_grav")
        responses[f"{T}_uncertainty"]       = st.slider(f"{COND_LABEL[T]} — Incertezza percepita dello scenario", 1, 7, 4, key=f"{T}_unc")
        responses[f"{T}_strategic"]         = st.slider(f"{COND_LABEL[T]} — Impatto strategico potenziale", 1, 7, 4, key=f"{T}_str")
        responses[f"{T}_trust_ai"]          = st.slider(f"{COND_LABEL[T]} — Fiducia attribuita al Sistema AI", 1, 7, 4, key=f"{T}_tr")
        responses[f"{T}_confidence"]        = st.slider(f"{COND_LABEL[T]} — Sicurezza della tua decisione finale", 1, 7, 4, key=f"{T}_conf")
        responses[f"{T}_leader_acceptance"] = st.slider(f"{COND_LABEL[T]} — Disponibilità ad accettare la sintesi finale del gruppo", 1, 7, 4, key=f"{T}_la")
        responses[f"{T}_need_group"]        = st.slider(f"{COND_LABEL[T]} — Necessità percepita di confronto con gli altri analisti", 1, 7, 4, key=f"{T}_ng")

        # Pulsante continua — sblocca visivamente lo scenario successivo
        idx_T = ordine.index(T)
        if idx_T < len(ordine) - 1:
            prossimo = ordine[idx_T + 1]
            if st.button(f"▶ Vai allo scenario successivo ({COND_LABEL[prossimo]})",
                         key=f"{T}_next_btn"):
                st.rerun()
        st.divider()

    tutti_confermati = all(
        st.session_state.get(f"{T}_confirmed", False) for T in ordine)
    tutti_completi = all(
        f"{T}_post_ai" in responses for T in ordine)

    if tutti_confermati and tutti_completi:
        if st.button("📨 Invia questionario"):
            row = {
                "participant_code": participant_code,
                "participant_uuid": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "completed": 1,
                "ruolo_assegnato": ruolo_assegnato,
                "experience": experience,
                "coordination": coordination,
                "specialist_area": specialist_area,
                "ai_use": ai_use,
                "ai_critical_skill": ai_critical,
                "ordine_somministrazione": "-".join(ordine),
            }
            row.update(responses)
            save_response(row)
            st.success("Risposta salvata. Grazie per la partecipazione.")
            st.rerun()
    else:
        st.info("Completa la conferma della valutazione iniziale per tutti e tre gli scenari per procedere all'invio.")
    st.stop()

# ── BACK OFFICE ──────────────────────────────────────────────
st.sidebar.success("Back office attivo")
st.header("Back Office")

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Completati", f"{completed}/{MAX_P}")
c2.metric("Rilevazione", "Chiusa" if closed else "Aperta")
c3.metric("Repliche sintetiche", N_SYNTH_TEAMS)
c4.metric("Monte Carlo", f"{N_SYNTH_TEAMS}×{N_MC}")
gs = get_gsheet()
c5.metric("Google Sheets", "🟢 Connesso" if gs else "🔴 Non attivo")

# Stato email
email_cfg = get_email_config()
if email_cfg:
    st.success(f"📧 Email backup attivo — invio a: {email_cfg['destinatario']}")
else:
    st.warning(
        "📧 Email backup non configurato. "
        "Aggiungi la sezione [email] nei secrets di Streamlit Cloud "
        "per ricevere ogni risposta via email con CSV allegato.")

col1,col2,col3,col4 = st.columns(4)
with col1:
    if st.button("Genera 9 risposte random"):
        df = generate_random_dataset()
        st.success("9 risposte generate.")
        st.rerun()
with col2:
    if st.button("Esegui analisi completa"):
        df = load_responses()
        if len(df) < MAX_P:
            st.error("Servono 9 risposte complete.")
        else:
            with st.spinner("Calcolo in corso..."):
                team, abm, mc, summary = run_full_pipeline(df)
            st.success("Analisi completata.")
with col3:
    if st.button("Chiudi rilevazione"):
        set_closed(True); st.rerun()
with col4:
    if st.button("Reset"):
        reset_db(); st.rerun()

# Test email manuale
if get_email_config():
    if st.button("📧 Test email"):
        df_test = load_responses()
        test_row = {
            "participant_code": "TEST",
            "ruolo_assegnato": "Test",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "ordine_somministrazione": "T1-T2-T3"
        }
        ok, msg_email = invia_email_risposta(test_row, df_test)
        if ok:
            st.success("Email di test inviata correttamente.")
        else:
            st.error(f"Errore invio: {msg_email}")

# ── DOWNLOAD IN MEMORIA ──────────────────────────────────────
# Funziona su Streamlit Cloud senza filesystem persistente
st.divider()
df = load_responses()

# Download da Google Sheets se disponibile
gs = get_gsheet()
if gs:
    col_gs1, col_gs2 = st.columns(2)
    with col_gs1:
        if st.button("🔄 Sincronizza da Google Sheets"):
            df_gs = gsheet_load_all()
            if not df_gs.empty:
                st.success(f"Caricate {len(df_gs)} righe da Google Sheets.")
                st.dataframe(df_gs, hide_index=True)
                csv_gs = df_gs.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Scarica da Google Sheets",
                    csv_gs,
                    "risposte_da_gsheets.csv",
                    "text/csv")
            else:
                st.info("Nessun dato trovato in Google Sheets.")
    with col_gs2:
        if st.button("🗑️ Svuota Google Sheets"):
            gsheet_reset()
            st.success("Foglio Google svuotato.")

if not df.empty:
    col_dl1, col_dl2, col_dl3 = st.columns(3)

    with col_dl1:
        csv_risposte = df.to_csv(index=False, encoding="utf-8").encode("utf-8")
        st.download_button(
            label="⬇️ Scarica risposte (CSV)",
            data=csv_risposte,
            file_name="01_risposte_questionario.csv",
            mime="text/csv",
            help="Scarica subito le risposte — non dipende dal filesystem"
        )

    with col_dl2:
        num_cols = [c for c in df.columns
                    if c.startswith(("T1_","T2_","T3_"))
                    or c in ["coordination","ai_use","ai_critical_skill"]]
        if num_cols:
            desc = df[num_cols].describe().T.reset_index()
            desc.columns = ["variabile"] + list(desc.columns[1:])
            csv_desc = desc.to_csv(index=False, encoding="utf-8").encode("utf-8")
            st.download_button(
                label="⬇️ Scarica statistiche (CSV)",
                data=csv_desc,
                file_name="02_statistiche_descrittive.csv",
                mime="text/csv"
            )

    with col_dl3:
        if len(df) >= MAX_P:
            try:
                team_dl = infer_roles(df)
                csv_team = team_dl.to_csv(index=False, encoding="utf-8").encode("utf-8")
                st.download_button(
                    label="⬇️ Scarica team parametrizzato (CSV)",
                    data=csv_team,
                    file_name="03_team_parametrizzato.csv",
                    mime="text/csv"
                )
            except Exception as e:
                st.warning(f"Team non disponibile: {e}")

st.divider()

tabs = st.tabs(["Risposte","Descrittive","Team e ruoli",
                "ABM","Monte Carlo","Grafici","Download"])

with tabs[0]:
    st.subheader("Risposte raccolte")
    if df.empty: st.info("Nessuna risposta.")
    else: st.dataframe(df, hide_index=True)

with tabs[1]:
    if not df.empty:
        desc = descriptive_stats(df)
        plot_descriptive(df)
        st.dataframe(desc, hide_index=True)
        if FIG_DESC.exists(): st.image(str(FIG_DESC))

with tabs[2]:
    if len(df) >= MAX_P:
        team = infer_roles(df)
        st.dataframe(team[["participant_code","role","experience",
                            "leadership_index","seniority_index"]], hide_index=True)
        plot_network(team)
        if FIG_NET.exists(): st.image(str(FIG_NET))

with tabs[3]:
    if len(df) >= MAX_P:
        team = infer_roles(df)
        abm  = run_abm_single(team)
        plot_abm_single(abm)
        st.dataframe(abm, hide_index=True)
        if FIG_ABM.exists(): st.image(str(FIG_ABM))

with tabs[4]:
    if len(df) >= MAX_P:
        team = infer_roles(df)
        _, summary = run_montecarlo(team)
        plot_montecarlo(summary); plot_regime_map(summary)
        plot_dashboard(summary)
        st.dataframe(summary, hide_index=True)
        if FIG_MC.exists(): st.image(str(FIG_MC))

with tabs[5]:
    for title, fig in [
        ("Descrittive",FIG_DESC),("Rete ABM",FIG_NET),
        ("ABM singolo",FIG_ABM),("Monte Carlo",FIG_MC),
        ("Regimi",FIG_REGIMI),("Cruscotto",FIG_DASH)]:
        if fig.exists():
            st.subheader(title); st.image(str(fig))

with tabs[6]:
    for f in [CSV_RESPONSES,CSV_DESC,CSV_TEAM,CSV_ABM,
              CSV_MC,CSV_MC_SUM,CSV_SYNTH_SUM,FIG_DESC,FIG_NET,
              FIG_ABM,FIG_MC,FIG_REGIMI,FIG_DASH]:
        if f.exists():
            with open(str(f),"rb") as fh:
                st.download_button(
                    label=f"Scarica {f.name}",
                    data=fh, file_name=f.name,
                    mime="application/octet-stream")
