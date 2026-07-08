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
    """Invia email con riepilogo e CSV allegato."""
    cfg = get_email_config()
    if cfg is None:
        return False, "Configurazione email non trouvata nei secrets."

    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["mittente"]
        msg["To"]      = cfg["destinatario"]
        msg["Subject"] = (
            f"Sistema 3 — Risposta {row.get('participant_code','?')} "
            f"[{row.get('timestamp','')[:10]}]"
        )

        n_completate = int(df_completo["completed"].fillna(0).astype(int).sum())
        codice = row.get("participant_code", "?")
        ruolo  = row.get("ruolo_assegnato", "?")
        ts     = row.get("timestamp", "?")
        ordine = row.get("ordine_somministrazione", "?")
        corpo  = (
            "Nuova risposta ricevuta.\n\n"
            f"Partecipante: {codice}\n"
            f"Ruolo: {ruolo}\n"
            f"Timestamp: {ts}\n"
            f"Ordine scenari: {ordine}\n\n"
            f"Risposte completate finora: {n_completate}/{MAX_P}\n\n"
            "In allegato il CSV completo di tutte le risposte."
        )
        msg.attach(MIMEText(corpo, "plain", "utf-8"))

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

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(cfg["mittente"], cfg["password"])
            server.sendmail(cfg["mittente"], cfg["destinatario"], msg.as_string())

        return True, "Email inviata."
    except Exception as e:
        return False, str(e)

# ── CREDENZIALI ──────────────────────────────────────────────
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

ORDINI_FISSI = {v["code"]: v["ordine"] for v in CREDENZIALI.values()}
RUOLI_FISSI  = {v["code"]: v["ruolo"]  for v in CREDENZIALI.values()}
VALID_CODES  = [v["code"] for v in CREDENZIALI.values()]
PIN_TO_CODE  = {k: v["code"] for k, v in CREDENZIALI.items()}
PIN_USATI    = set()

COND_LABEL = {
    "T1": "Configurazione α",
    "T2": "Configurazione β",
    "T3": "Configurazione γ",
}

COND_CONTESTO = {
    "T1": """Il team di analisi opera in condizioni ordinarie.
Non è stata dichiarata alcuna emergenza.
Il team ha convocato una sessione di lavoro standard.
Il contesto operativo consente l'attivazione dei protocolli ordinari.
Non vi sono vincoli imminenti per la formulazione della sintesi finale.""",

    "T2": """Il team è stato convocato in sessione straordinaria.
È richiesta la trasmissione rapida di una sintesi analitica.
Il contesto operativo richiede una riduzione dei tempi di valutazione individuale.
È necessaria una risposta analitica tempestiva e focalizzata.
La situazione operativa mostra segnali di crescente instabilità.""",

    "T3": """🔴 **EMERGENZA OPERATIVA DICHIARATA.**
La direzione richiede una valutazione immediata e non differibile.
È necessario formulare la sintesi decisionale senza alcuna dilazione.
Non è possibile attendere ulteriori approfondimenti informativi o tecnici.
La valutazione individuale deve essere consolidata nell'immediato.""",
}

BRIEFING = {

"T1": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Il quadro informativo segnala un incremento di indicatori relativi a possibili azioni ostili contro infrastrutture critiche nazionali. Nessun evento specifico è ancora occorso. La valutazione è richiesta in via precauzionale.

**Piano fisico.** Fonti confidenziali segnalano movimenti anomali in prossimità di nodi ferroviari nell'Italia centrale. Gruppi di matrice antagonista hanno circolato materiale operativo che individua nelle reti di trasporto merci un obiettivo prioritario. I segnali sono coerenti con schemi di ricognizione preliminare. Non si registrano eventi concreti. Nessuna rivendicazione è pervenuta.

**Piano cyber.** Sono comparsi sui principali forum riservati del dark web annunci relativi alla disponibilità di documentazione tecnica sottratta a operatori del settore energetico nazionale. I file offerti comprenderebbero schemi infrastrutturali e procedure di sicurezza interna. Non è stata verificata l'autenticità del materiale né l'identità degli offerenti.

**Piano OSINT.** Piattaforme digitali di area antagonista hanno avviato una campagna di critica sistematica agli accordi energetici italiani con Paesi africani. Vengono pubblicati profili di rappresentanti istituzionali e dirigenti aziendali coinvolti nelle trattative. Il tono è ostile. Non sono presenti ancora incitamenti espliciti ad azioni dirette.

**Fonti disponibili:** HUMINT (attendibilità non verificata), OSINT (verificata), cyber (in corso di analisi), open source (verificata). Nessun elemento isolato costituisce evidenza di una minaccia imminente. La convergenza degli indicatori giustifica una valutazione analitica integrata.

---""",

"T2": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Si è verificato un evento che modifica il peso degli indicatori precedentemente valutati. Il quadro richiede una rivalutazione sulla base degli elementi aggiornati.

**Piano fisico.** Un treno merci è deragliato sulla linea Leonardiana, in prossimità della stazione di Rinascenza, a seguito del posizionamento deliberato di un oggetto sui binari. L'interruzione del traffico è in corso. Non si registrano vittime. Sul luogo è stato rinvenuto materiale a contenuto politico che richiama la causa palestinese e cita la multinazionale Zypron, società attiva nel settore della sicurezza e registrata in un paradiso fiscale. Tre distinti gruppi antagonisti hanno rilasciato dichiarazioni compatibili con una rivendicazione. Nessuna è stata ancora attribuita con certezza.

**Piano cyber.** Le offerte di dati trafugati dal settore energetico precedentemente segnalate hanno registrato un incremento significativo di volume e specificità. I file ora offerti includerebbero planimetrie di impianti critici, protocolli operativi e informazioni finanziarie riservate. Si teme un utilizzo coordinato con l'azione fisica in corso. Le aziende coinvolte non sono state identificate.

**Piano OSINT.** Le piattaforme antagoniste hanno intensificato la pubblicazione di dati personali relativi a manager e funzionari italiani operanti in ambito energetico all'estero. Alcuni post richiamano esplicitamente il deragliamento ferroviario come atto inaugurale di una più ampia campagna. Le autorità stanno monitorando la diffusione dei contenuti.

**Fonti disponibili:** HUMINT (attendibilità parziale), OSINT (verificata), cyber (in corso di analisi), open source (verificata). L'evento fisico avvenuto modifica il contesto valutativo. La combinazione degli indicatori richiede una valutazione analitica con carattere di urgenza.

---""",

"T3": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Il quadro informativo ha subito una grave deteriorazione. Si registra una seconda azione ostile con potenziale coinvolgimento di attori statuali. La decisione non può essere differita.

**Piano fisico.** Al sabotaggio ferroviario sulla linea Leonardiana si è aggiunto un secondo evento critico. Un'esplosione in una struttura rurale nella località costiera di Nereide, in Silicon, ha portato alla scoperta di un laboratorio per la preparazione di esplosivi artigianali. Nessun ferito. La localizzazione del sito è geograficamente coerente con la presenza di cavi dati sottomarini e oleodotti nella stessa area costiera. Le forze dell'ordine stanno verificando possibili connessioni tra i due episodi. Non è esclusa una regia comune.

**Piano cyber.** I dati trafugati dal settore energetico sono ora in fase di negoziazione attiva. Fonti riservate segnalano trattative con un intermediario non identificato con possibili connessioni a entità statuali ostili. Il rischio di utilizzo operativo del materiale è considerato elevato dagli esperti di settore.

**Piano OSINT.** La campagna di doxing contro rappresentanti italiani si è estesa a nuove piattaforme e a destinatari in Paesi africani teatro degli accordi energetici. I contenuti pubblicati includono informazioni operative sulle installazioni italiane all'estero. Sono stati rilevati segnali di coordinamento tra utenti in più Paesi.

**Elemento aggiuntivo.** Nei giorni precedenti l'esplosione di Nereide, una nave mercantile di bandiera russa è stata avvistata nelle acque prospicienti la costa siciliana, in prossimità delle aree di transito delle infrastrutture sottomarine. Il dato non è ancora confermato da fonti indipendenti. Non si esclude una connessione con il tentativo di sabotaggio.

**Fonti disponibili:** HUMINT (parzialmente verificata), OSINT (verificata), cyber (in corso di analisi), intelligence marittima (non confermata). La convergenza di due eventi fisici distinti, dell'intensificazione cyber e OSINT e di un elemento di intelligence marittima rappresenta un quadro sostanzialmente più grave rispetto alla valutazione precedente. Nessun elemento isolato costituisce prova definitiva. La valutazione è richiesta immediatamente.

---"""

}
DOMANDA = "Sulla base delle informazioni disponibili, qual è la probabilità che gli eventi in corso facciano parte di una campagna coordinata contro infrastrutture critiche nazionali che richieda l'innalzamento immediato del livello di allerta?"

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
                "precedentemente valutati como segnali deboli. La convergenza temporale "
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
