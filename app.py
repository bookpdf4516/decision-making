"""
Script2.py — Studio 2
=====================
Questionario Sistema 3 — Versione estesa con output LLM precompilato.

Compatibilità con Studio 1:
- Scala slider 0-100 invariata
- Formula F_i identica
- Scenari T1/T2/T3 identici
- Item Likert originali invariati + 6 item aggiuntivi per P e G separati
- Output LLM strutturato come stimolo aggiuntivo dopo la direzione relativa
- Auto-selezione ruolo con quota per ruolo (max 1 TL, 3 SR, 4 JR, 2 CV)
- Nessuna password — controllo tramite quota e coerenza profilo
"""

import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import smtplib
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

st.set_page_config(
    page_title="Questionario Sistema 3 — Studio 2",
    page_icon="🧠",
    layout="wide"
)

# ============================================================
# CONFIGURAZIONE
# ============================================================

OUTPUT_DIR = Path(r"C:\Users\casti\OneDrive\Desktop\1_SOCIO_FISICA\studio2")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH       = OUTPUT_DIR / "studio2_risposte.sqlite"
CSV_RESPONSES = OUTPUT_DIR / "studio2_01_risposte.csv"

AI_COSTANTE   = 65
ADMIN_PWD     = "admin2026"

# Struttura organizzativa target per team da 9
# Compatibile con Studio 1: 1 TL + 3 SR + 3 JR + 2 CV
MAX_P = 90  # 10 team da 9 partecipanti

AREE_OPERATIVE = [
    "Intelligence / sicurezza",
    "Investigativa / law enforcement",
]
AREE_CIVILI = [
    "Cyber / tecnologia",
    "Economico-finanziaria",
    "OSINT / analisi fonti aperte",
    "Accademica / ricerca",
    "Linguistica / area studies",
]

COND_LABEL = {
    "T1": "Configurazione α — Sessione analitica ordinaria",
    "T2": "Configurazione β — Sessione analitica straordinaria",
    "T3": "Configurazione γ — Sessione analitica di crisi",
}

COND_CONTESTO = {
    "T1": """**Configurazione α — Sessione analitica ordinaria**

Il team opera in condizioni standard. La sessione è stata convocata
per una valutazione di routine del quadro informativo disponibile.
Non vi sono indicatori di urgenza operativa immediata.""",

    "T2": """**Configurazione β — Sessione analitica straordinaria**

Il CASA è stato convocato in sessione straordinaria a seguito
dell'evoluzione del quadro informativo. È richiesta una risposta
analitica motivata. La situazione operativa mostra segnali
di crescente instabilità.""",

    "T3": """**Configurazione γ — Sessione analitica di crisi**

Il quadro operativo richiede una valutazione immediata.
Il Team Leader coordina la risposta analitica del gruppo.
Gli elementi informativi disponibili devono essere valutati adesso.""",
}

BRIEFING = {
"T1": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Nelle ultime settimane si è registrato un incremento significativo di segnali informativi
relativi a possibili minacce alle infrastrutture critiche nazionali.

**Piano fisico.** Fonti confidenziali segnalano movimenti anomali in prossimità di nodi
ferroviari nell'Italia centrale. Gruppi di matrice antagonista hanno circolato materiale
operativo che individua nelle reti di trasporto merci un obiettivo prioritario. I segnali
sono coerenti con schemi di ricognizione preliminare. Non si registrano eventi concreti.
Nessuna rivendicazione è pervenuta.

**Piano cyber.** Negli ultimi giorni sono comparsi sui principali forum riservati del dark
web annunci relativi alla disponibilità di documentazione tecnica sottratta a operatori del
settore energetico nazionale. I file offerti comprenderebbero schemi infrastrutturali e
procedure di sicurezza interna. Non è stata verificata l'autenticità del materiale né
l'identità degli offerenti.

**Piano OSINT.** Piattaforme digitali di area antagonista hanno avviato una campagna di
critica sistematica agli accordi energetici italiani con Paesi africani. Vengono pubblicati
profili di rappresentanti istituzionali e dirigenti aziendali coinvolti nelle trattative.
Il tono è ostile. Non sono presenti ancora incitamenti espliciti ad azioni dirette.

**Fonti disponibili:** HUMINT (attendibilità non verificata), OSINT (verificata),
cyber (in corso di analisi), open source (verificata). Nessun elemento isolato costituisce
evidenza di una minaccia imminente.

---""",

"T2": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Nelle ultime ore si è verificato un evento che modifica il peso degli indicatori
precedentemente valutati. Il quadro richiede una rivalutazione urgente.

**Piano fisico.** Un treno merci è deragliato sulla linea Leonardiana, in prossimità della
stazione di Rinascenza, a seguito del posizionamento deliberato di un oggetto sui binari.
L'interruzione del traffico è in corso. Non si registrano vittime. Sul luogo è stato
rinvenuto materiale a contenuto politico che richiama la causa palestinese e cita la
multinazionale Zypron. Tre distinti gruppi antagonisti hanno rilasciato dichiarazioni
compatibili con una rivendicazione. Nessuna è stata ancora attribuita con certezza.

**Piano cyber.** Le offerte di dati trafugati dal settore energetico precedentemente
segnalate hanno registrato un incremento significativo di volume e specificità. I file ora
offerti includerebbero planimetrie di impianti critici, protocolli operativi e informazioni
finanziarie riservate. Si teme un utilizzo coordinato con l'azione fisica in corso.

**Piano OSINT.** Le piattaforme antagoniste hanno intensificato la pubblicazione di dati
personali relativi a manager e funzionari italiani operanti in ambito energetico all'estero.
Alcuni post richiamano esplicitamente il deragliamento ferroviario come atto inaugurale
di una più ampia campagna.

**Fonti disponibili:** HUMINT (attendibilità parziale), OSINT (verificata),
cyber (in corso di analisi), open source (verificata).

---""",

"T3": """**BRIEFING OPERATIVO — LIVELLO RISERVATO**

---

Il quadro informativo ha subito una grave deteriorazione nelle ultime ore. Si registra
una seconda azione ostile con potenziale coinvolgimento di attori statuali.

**Piano fisico.** Al sabotaggio ferroviario sulla linea Leonardiana si è aggiunto un
secondo evento critico. Un'esplosione in una struttura rurale nella località costiera di
Nereide, in Sicilia, ha portato alla scoperta di un laboratorio per la preparazione di
esplosivi artigianali. Nessun ferito. La localizzazione del sito è geograficamente coerente
con la presenza di cavi dati sottomarini e oleodotti nella stessa area costiera.

**Piano cyber.** I dati trafugati dal settore energetico sono ora in fase di negoziazione
attiva. Fonti riservate segnalano trattative con un intermediario non identificato con
possibili connessioni a entità statuali ostili.

**Piano OSINT.** La campagna di doxing contro rappresentanti italiani si è estesa a nuove
piattaforme e a destinatari in Paesi africani. I contenuti pubblicati includono informazioni
operative sulle installazioni italiane all'estero.

**Elemento aggiuntivo.** Nei giorni precedenti l'esplosione di Nereide, una nave mercantile
di bandiera russa è stata avvistata nelle acque prospicienti la costa siciliana. Il dato
non è ancora confermato da fonti indipendenti.

**Fonti disponibili:** HUMINT (parzialmente verificata), OSINT (verificata),
cyber (in corso di analisi), intelligence marittima (non confermata).

---""",
}

DOMANDA = (
    "Sulla base delle informazioni disponibili, lo scenario descritto "
    "costituisce una minaccia coordinata contro infrastrutture critiche "
    "nazionali che richiede l'innalzamento immediato del livello di allerta?"
)

# ── OUTPUT LLM PRECOMPILATI ──────────────────────────────────
# Fissi per tutti i partecipanti — garantisce stimolo identico (requisito scientifico)

LLM_OUTPUT = {
"T1": {
    "valutazione": "Probabilmente no",
    "indicatori": [
        ("Piano fisico — ricognizione preliminare senza eventi concreti", "basso"),
        ("Piano cyber — annunci dark web non verificati",                  "basso"),
        ("Piano OSINT — campagna critica senza incitamenti espliciti",     "basso"),
        ("Convergenza tematica tra fonti eterogenee",                      "medio"),
    ],
    "coerenza": (
        "Gli indicatori disponibili mostrano una convergenza tematica ma non operativa. "
        "Nessun evento fisico è occorso. Il quadro è coerente con una fase di "
        "preparazione o ricognizione preliminare, non con un'azione imminente."
    ),
    "incertezza": "elevata",
    "nota": (
        "La stima è condizionata dall'assenza di eventi concreti verificati. "
        "Un singolo elemento confermato modificherebbe significativamente il quadro."
    ),
},
"T2": {
    "valutazione": "Probabilmente sì",
    "indicatori": [
        ("Piano fisico — deragliamento verificato, linea Leonardiana",         "elevato"),
        ("Piano cyber — incremento volume e specificità dati offerti",         "medio"),
        ("Piano OSINT — campagna che richiama l'evento fisico come atto inaugurale", "medio"),
        ("Convergenza temporale tra i tre piani",                              "elevato"),
    ],
    "coerenza": (
        "L'evento fisico avvenuto aumenta il peso degli indicatori cyber e OSINT "
        "precedentemente valutati come segnali deboli. La convergenza temporale "
        "tra i tre piani è coerente con una campagna coordinata. "
        "Rimane incerta la regia comune."
    ),
    "incertezza": "moderata",
    "nota": (
        "La stima è condizionata dall'attribuzione delle rivendicazioni. "
        "L'assenza di un attore identificato mantiene un margine di incertezza significativo."
    ),
},
"T3": {
    "valutazione": "Sì",
    "indicatori": [
        ("Piano fisico — secondo evento: laboratorio esplosivi a Nereide",        "elevato"),
        ("Coerenza geografica con infrastrutture sottomarine critiche",           "elevato"),
        ("Piano cyber — dati in negoziazione con intermediario statuale",         "elevato"),
        ("Elemento intelligence marittima — nave russa in area strategica",       "medio"),
        ("Piano OSINT — campagna estesa a più Paesi con dati operativi",          "medio"),
    ],
    "coerenza": (
        "La concatenazione di due eventi fisici distinti, l'intensificazione "
        "delle attività cyber e OSINT e la presenza di un elemento di intelligence "
        "marittima producono un quadro di convergenza significativa. "
        "Il possibile coinvolgimento di un attore statuale rappresenta "
        "un elemento di discontinuità rispetto alle valutazioni precedenti."
    ),
    "incertezza": "bassa",
    "nota": (
        "La stima è condizionata dalla non conferma dell'elemento marittimo. "
        "La convergenza degli indicatori giustifica tuttavia una valutazione di minaccia elevata."
    ),
},
}

SCALA_ORDINALE = [
    "— seleziona —",
    "No — nessuna evidenza di minaccia coordinata",
    "Probabilmente no — segnali deboli, quadro non coerente",
    "Incerto — elementi contrastanti, giudizio sospeso",
    "Probabilmente sì — convergenza di indicatori significativa",
    "Sì — evidenza solida di campagna coordinata",
]

ORDINI = ["T1-T2-T3", "T2-T3-T1", "T3-T1-T2"]

# ============================================================
# DATABASE
# ============================================================

def get_conn():
    return sqlite3.connect(str(DB_PATH))

def init_db():
    con = get_conn()
    con.execute("""
    CREATE TABLE IF NOT EXISTS risposte (
        session_uuid TEXT PRIMARY KEY,
        timestamp TEXT,
        ruolo TEXT,
        experience TEXT,
        coordination INTEGER,
        specialist_area TEXT,
        ai_use INTEGER,
        ai_critical INTEGER,
        ai_llm_use INTEGER,
        ai_llm_trust INTEGER,
        ordine TEXT,
        team_id INTEGER,
        posizione_team INTEGER,
        T1_pre_ai INTEGER, T1_pre_ordinale TEXT,
        T1_conf_pre INTEGER,
        T1_llm_utile INTEGER,
        T1_post_ai INTEGER, T1_post_ordinale TEXT,
        T1_motivo TEXT,
        T1_trust_ai INTEGER, T1_confidence INTEGER,
        T1_leader_acceptance INTEGER, T1_need_group INTEGER,
        T1_gravity INTEGER, T1_uncertainty INTEGER, T1_strategic INTEGER,
        T1_pressione_1 INTEGER, T1_pressione_2 INTEGER, T1_pressione_3 INTEGER,
        T2_pre_ai INTEGER, T2_pre_ordinale TEXT,
        T2_conf_pre INTEGER,
        T2_llm_utile INTEGER,
        T2_post_ai INTEGER, T2_post_ordinale TEXT,
        T2_motivo TEXT,
        T2_trust_ai INTEGER, T2_confidence INTEGER,
        T2_leader_acceptance INTEGER, T2_need_group INTEGER,
        T2_gravity INTEGER, T2_uncertainty INTEGER, T2_strategic INTEGER,
        T2_pressione_1 INTEGER, T2_pressione_2 INTEGER, T2_pressione_3 INTEGER,
        T3_pre_ai INTEGER, T3_pre_ordinale TEXT,
        T3_conf_pre INTEGER,
        T3_llm_utile INTEGER,
        T3_post_ai INTEGER, T3_post_ordinale TEXT,
        T3_motivo TEXT,
        T3_trust_ai INTEGER, T3_confidence INTEGER,
        T3_leader_acceptance INTEGER, T3_need_group INTEGER,
        T3_gravity INTEGER, T3_uncertainty INTEGER, T3_strategic INTEGER,
        T3_pressione_1 INTEGER, T3_pressione_2 INTEGER, T3_pressione_3 INTEGER
    )""")
    con.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT
    )""")
    con.execute("INSERT OR IGNORE INTO settings VALUES ('closed','0')")
    con.commit(); con.close()

def assegna_ruolo(experience, specialist_area, n_risposta_nel_team):
    """
    Assegnazione automatica del ruolo basata su:
    - Area specialistica (operativa vs tecnica → Senior/Junior vs Civile)
    - Anni di esperienza (Junior 0-10, Senior 11+)
    - Posizione nella sequenza del team (primo → Team Leader)

    Compatibilità Studio 1: struttura target 1 TL + 3 SR + 3 JR + 2 CV per team.
    Differenza dichiarata: Studio 1 usava posizione reale; Studio 2 usa
    area e anzianità dichiarate.
    """
    # Il primo partecipante di ogni team diventa Team Leader
    if n_risposta_nel_team == 0:
        return "Team Leader"

    # Area tecnica → Analista Civile
    if specialist_area in AREE_CIVILI:
        return "Analista Civile"

    # Area operativa → Junior o Senior per anzianità
    exp_map = {
        "Meno di 5 anni": 2,
        "5-10 anni":       7,
        "11-20 anni":     15,
        "Oltre 20 anni":  25,
    }
    anni = exp_map.get(experience, 7)
    if anni <= 10:
        return "Analista Junior"
    else:
        return "Analista Senior"


def n_risposta_nel_team():
    """Restituisce la posizione del partecipante nel team corrente (0-indexed)."""
    df = load_risposte()
    if df.empty:
        return 0
    return len(df) % 9  # team da 9 partecipanti


def get_team_id():
    """Restituisce l'ID del team corrente (0-indexed)."""
    df = load_risposte()
    if df.empty:
        return 0
    return len(df) // 9


def load_risposte():
    try:
        con = get_conn()
        df = pd.read_sql_query("SELECT * FROM risposte", con)
        con.close()
        return df
    except:
        return pd.DataFrame()



def save_risposta(row):
    con = get_conn()
    cols = list(row.keys())
    sql = (f"INSERT OR REPLACE INTO risposte ({','.join(cols)}) "
           f"VALUES ({','.join(['?']*len(cols))})")
    con.execute(sql, [row[c] for c in cols])
    con.commit(); con.close()
    try:
        df = load_risposte()
        df.to_csv(str(CSV_RESPONSES), index=False, encoding="utf-8-sig")
    except:
        pass
    invia_email(row)

def is_closed():
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT value FROM settings WHERE key='closed'")
    r = cur.fetchone(); con.close()
    return r and r[0] == "1"

def set_closed(v):
    con = get_conn()
    con.execute("UPDATE settings SET value=? WHERE key='closed'", ("1" if v else "0",))
    con.commit(); con.close()

def reset_db():
    con = get_conn()
    con.execute("DELETE FROM risposte")
    con.execute("UPDATE settings SET value='0' WHERE key='closed'")
    con.commit(); con.close()

# ============================================================
# EMAIL
# ============================================================

def get_email_config():
    try:
        cfg = st.secrets["email"]
        return {"mittente": cfg["mittente"],
                "password": cfg["password"],
                "destinatario": cfg["destinatario"]}
    except:
        return None

def invia_email(row):
    cfg = get_email_config()
    if not cfg: return
    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["mittente"]
        msg["To"]      = cfg["destinatario"]
        msg["Subject"] = (f"Studio 2 — Risposta {row.get('ruolo','?')} "
                          f"[{row.get('timestamp','')[:10]}]")
        corpo = (f"Nuova risposta Studio 2.\n\n"
                 f"Ruolo: {row.get('ruolo','?')}\n"
                 f"Timestamp: {row.get('timestamp','?')}\n"
                 f"Ordine: {row.get('ordine','?')}")
        msg.attach(MIMEText(corpo, "plain", "utf-8"))
        df = load_risposte()
        if not df.empty:
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            part = MIMEBase("application", "octet-stream")
            part.set_payload(buf.getvalue().encode("utf-8"))
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            "attachment; filename=studio2_risposte.csv")
            msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(cfg["mittente"], cfg["password"])
            s.sendmail(cfg["mittente"], cfg["destinatario"], msg.as_string())
    except:
        pass

# ============================================================
# RENDERING OUTPUT LLM
# ============================================================

def mostra_output_llm(T):
    out = LLM_OUTPUT[T]
    st.info(
        "**Sistema di supporto analitico — Valutazione automatizzata**\n\n"
        "Il modello linguistico ha elaborato le stesse informazioni contenute "
        "nel briefing e produce la seguente analisi strutturata."
    )
    # Valutazione
    valutazione_color = {
        "No": "🟢", "Probabilmente no": "🟡",
        "Incerto": "🟠", "Probabilmente sì": "🔴", "Sì": "🔴"
    }
    emoji = valutazione_color.get(out["valutazione"], "⚪")
    st.markdown(f"**Valutazione della minaccia:** {emoji} **{out['valutazione']}**")

    # Tabella indicatori
    st.markdown("**Indicatori analizzati:**")
    for indicatore, peso in out["indicatori"]:
        emoji_peso = {"elevato":"🔴","medio":"🟡","basso":"🟢"}.get(peso,"⚪")
        st.markdown(f"- {emoji_peso} **{peso.capitalize()}** — {indicatore}")

    # Coerenza
    st.markdown(f"**Coerenza tra fonti:** {out['coerenza']}")

    # Incertezza
    inc_map = {"elevata":"🟡 Elevata","moderata":"🟠 Moderata","bassa":"🔴 Bassa"}
    st.markdown(f"**Incertezza residua:** {inc_map.get(out['incertezza'], out['incertezza'])}")

    # Nota
    st.caption(f"⚠️ {out['nota']}")
    st.caption("Il giudizio analitico finale spetta a te.")

# ============================================================
# UI — UTENTE
# ============================================================

init_db()

st.title("Questionario Sistema 3 — Studio 2")
st.markdown("Raccolta dati individuali — Analisi decisionale con supporto LLM")

admin = st.sidebar.text_input("Password back office", type="password")

# ── BACK OFFICE ──────────────────────────────────────────────
if admin == ADMIN_PWD:
    st.sidebar.success("Back office attivo")
    st.header("Back Office — Studio 2")

    df = load_risposte()
    c1,c2,c3 = st.columns(3)
    c1.metric("Risposte totali", len(df))
    c2.metric("Team completati", len(df)//9)
    cfg = get_email_config()
    c3.metric("Email", "🟢 Attivo" if cfg else "🔴 Non attivo")

    if not df.empty and "ruolo" in df.columns:
        st.subheader("Distribuzione ruoli assegnati")
        dist = df["ruolo"].value_counts()
        for r in ["Team Leader","Analista Senior","Analista Junior","Analista Civile"]:
            n = int(dist.get(r, 0))
            attesi = {"Team Leader":10,"Analista Senior":30,
                      "Analista Junior":30,"Analista Civile":20}.get(r,0)
            st.progress(min(n/max(attesi,1),1.0),
                        text=f"{r}: {n} (attesi {attesi} su 90 partecipanti)")

    col1,col2,col3 = st.columns(3)
    with col1:
        if st.button("Chiudi rilevazione"):
            set_closed(True); st.rerun()
    with col2:
        if st.button("Reset"):
            reset_db(); st.rerun()
    with col3:
        if cfg and st.button("Test email"):
            invia_email({"ruolo":"TEST","timestamp":datetime.now().isoformat(),
                         "ordine":"T1-T2-T3"})
            st.success("Email inviata.")

    if not df.empty:
        st.divider()
        st.subheader("Risposte raccolte")
        st.dataframe(df, hide_index=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Scarica CSV", csv,
                           "studio2_risposte.csv", "text/csv")
    st.stop()

# ── QUESTIONARIO UTENTE ───────────────────────────────────────
if is_closed():
    st.info("La rilevazione è terminata. Grazie per la partecipazione.")
    st.stop()

st.header("Questionario decisionale individuale")
n_tot = len(load_risposte())
st.progress(min(n_tot / MAX_P, 1.0),
            text=f"Risposte completate: {n_tot}/{MAX_P}")

# Ordine scenari in base alla posizione progressiva
ordine_str = ORDINI[n_tot % 3]
ordine     = ordine_str.split("-")

with st.expander("Istruzioni operative", expanded=True):
    st.markdown("""
Il presente questionario riproduce tre sessioni di analisi individuale
in condizioni operative distinte. Per ciascuna sessione:

1. **Leggi il briefing operativo** nella sua interezza.
2. **Formula una stima autonoma** della minaccia e indica il tuo livello
   di sicurezza analitica. Clicca **Conferma** per procedere.
3. **Consulta la valutazione del modello linguistico** che ha analizzato
   le stesse informazioni del briefing.
4. **Aggiorna o conferma la tua stima** alla luce dell'analisi del modello.
5. **Rispondi alle domande di contesto** sullo scenario.

Non esistono risposte corrette o scorrette. È richiesta una valutazione
analitica autentica basata sulla tua esperienza professionale.
""")

# Profilo
st.subheader("Profilo professionale")
st.caption("Usato esclusivamente per la parametrizzazione del modello.")

experience = st.selectbox("Anni di esperienza nel settore",
    ["— seleziona —","Meno di 5 anni","5-10 anni","11-20 anni","Oltre 20 anni"])

coordination = st.slider(
    "Esperienza nel coordinamento di gruppi in contesti operativi", 1, 7, 4,
    help="1 = nessuna  |  7 = consolidata")

specialist_area = st.selectbox("Area operativa prevalente",
    ["— seleziona —","Intelligence / sicurezza","Investigativa / law enforcement",
     "Cyber / tecnologia","Economico-finanziaria","OSINT / analisi fonti aperte",
     "Accademica / ricerca","Linguistica / area studies"])

ai_use = st.slider(
    "Frequenza di utilizzo di strumenti di analisi automatizzata nel lavoro", 1, 7, 4,
    help="1 = mai  |  7 = quotidianamente")

ai_critical = st.slider(
    "Capacità di valutare criticamente l'output di un sistema automatizzato", 1, 7, 4,
    help="1 = limitata  |  7 = elevata")

ai_llm_use = st.slider(
    "Frequenza di utilizzo di modelli linguistici (LLM) nel lavoro operativo", 1, 7, 4,
    help="1 = mai  |  7 = quotidianamente")

ai_llm_trust = st.slider(
    "Fiducia generale negli output LLM in contesti analitici operativi", 1, 7, 4,
    help="1 = nessuna fiducia  |  7 = fiducia elevata")

# Validazione profilo
profilo_ok = (ruolo != "— seleziona —" and
              experience != "— seleziona —" and
              specialist_area != "— seleziona —")

if not profilo_ok:
    st.warning("Completa il profilo professionale per procedere agli scenari.")
    st.stop()

# Assegnazione automatica del ruolo — non visibile al partecipante
pos_nel_team = n_risposta_nel_team()
team_id      = get_team_id()
ruolo        = assegna_ruolo(experience, specialist_area, pos_nel_team)

# Inizializza session state
for T in ordine:
    for key in ["confirmed","pre_val","conf_pre_saved"]:
        if f"{T}_{key}" not in st.session_state:
            st.session_state[f"{T}_{key}"] = (False if key=="confirmed" else 50)

responses = {}
st.divider()

# ── SCENARI ──────────────────────────────────────────────────
for T in ordine:
    st.header(f"Scenario — {COND_LABEL[T]}")

    idx_T = ordine.index(T)
    precedenti_ok = all(
        st.session_state.get(f"{c}_confirmed", False)
        for c in ordine[:idx_T])

    if not precedenti_ok:
        st.info("🔒 Completa lo scenario precedente per sbloccare questo.")
        st.divider()
        continue

    st.info(COND_CONTESTO[T])
    with st.expander("📄 Leggi il briefing operativo",
                     expanded=not st.session_state[f"{T}_confirmed"]):
        st.markdown(BRIEFING[T])

    # ── SEZIONE I: valutazione autonoma pre-LLM ──────────────
    if not st.session_state[f"{T}_confirmed"]:
        st.subheader("Sezione I — Valutazione analitica individuale")
        st.markdown(
            "Sulla base esclusiva delle informazioni contenute nel briefing, "
            "formula la tua stima della minaccia **prima** di consultare "
            "il modello linguistico.")

        pre_ai = st.slider(
            "Probabilità stimata di campagna coordinata (0–100)",
            0, 100, 50, key=f"{T}_pre_slider",
            help="0 = nessuna evidenza  |  100 = evidenza certa")

        pre_ordinale = st.selectbox(
            "Esprimi la stessa valutazione sulla scala qualitativa",
            SCALA_ORDINALE, key=f"{T}_pre_ord")

        conf_pre = st.slider(
            "Livello di sicurezza analitica di questa valutazione",
            1, 7, 4, key=f"{T}_conf_pre",
            help="1 = molto incerto  |  7 = molto sicuro")

        if st.button(f"✅ Conferma e consulta il modello linguistico — {T}",
                     key=f"{T}_confirm_btn", type="primary"):
            if pre_ordinale == "— seleziona —":
                st.error("Seleziona una valutazione qualitativa prima di procedere.")
            else:
                st.session_state[f"{T}_confirmed"]      = True
                st.session_state[f"{T}_pre_val"]        = pre_ai
                st.session_state[f"{T}_pre_ord_val"]    = pre_ordinale
                st.session_state[f"{T}_conf_pre_saved"] = conf_pre
                st.rerun()
        st.warning("⚠️ Conferma la valutazione per accedere all'analisi del modello.")
        st.divider()
        continue

    # Sezione I confermata
    pre_ai      = st.session_state[f"{T}_pre_val"]
    pre_ordinale = st.session_state.get(f"{T}_pre_ord_val", "— seleziona —")
    conf_pre    = st.session_state.get(f"{T}_conf_pre_saved", 4)
    responses[f"{T}_pre_ai"]      = pre_ai
    responses[f"{T}_pre_ordinale"] = pre_ordinale
    responses[f"{T}_conf_pre"]    = conf_pre
    st.success(f"✅ Scenario {T} — Sezione I completata.")

    # ── SEZIONE II: output LLM ────────────────────────────────
    st.subheader("Sezione II — Analisi del modello linguistico")
    st.markdown(
        f"Hai valutato la minaccia sulla base della tua esperienza. "
        f"Consulti ora un modello linguistico che, analizzando le stesse "
        f"informazioni del briefing, propone la seguente valutazione:")

    mostra_output_llm(T)

    st.markdown(f"**{DOMANDA}**")
    st.caption("Puoi confermare la tua valutazione iniziale o modificarla.")

    responses[f"{T}_post_ai"] = st.slider(
        "Probabilità aggiornata (0–100)",
        0, 100, pre_ai, key=f"{T}_post",
        help="Puoi confermare o modificare la stima precedente")

    responses[f"{T}_post_ordinale"] = st.selectbox(
        "Esprimi la stessa valutazione aggiornata sulla scala qualitativa",
        SCALA_ORDINALE, key=f"{T}_post_ord")

    responses[f"{T}_llm_utile"] = st.slider(
        "Quanto è stata utile l'analisi del modello linguistico per la tua decisione?",
        1, 7, 4, key=f"{T}_llm_u",
        help="1 = per nulla utile  |  7 = molto utile")

    # ── SEZIONE III: motivazione ──────────────────────────────
    st.subheader("Sezione III — Motivazione analitica")
    responses[f"{T}_motivo"] = st.selectbox(
        "Qual è il fattore principale che ha determinato la tua valutazione finale?",
        ["— seleziona —",
         "La valutazione del modello linguistico ha modificato la mia "
         "interpretazione degli indicatori disponibili",
         "Ho rivalutato autonomamente le informazioni del briefing, "
         "indipendentemente dall'analisi del modello",
         "Ho scelto di allineare la mia stima a quella del modello "
         "per coerenza con l'analisi disponibile",
         "La mia valutazione non ha subito modifiche significative",
         "Altro"],
        key=f"{T}_motivo")

    # ── SEZIONE IV: variabili contestuali ────────────────────
    st.subheader("Sezione IV — Valutazione del contesto operativo")

    # Item originali Studio 1 — invariati per compatibilità
    st.caption("**Variabili del contesto** (compatibili con Studio 1)")
    responses[f"{T}_gravity"] = st.slider(
        "Gravità operativa del quadro informativo", 1,7,4, key=f"{T}_grav")
    responses[f"{T}_uncertainty"] = st.slider(
        "Incertezza informativa dello scenario", 1,7,4, key=f"{T}_unc")
    responses[f"{T}_strategic"] = st.slider(
        "Rilevanza strategica della decisione", 1,7,4, key=f"{T}_str")
    responses[f"{T}_trust_ai"] = st.slider(
        "Attendibilità del modello linguistico in questo scenario", 1,7,4, key=f"{T}_tr")
    responses[f"{T}_confidence"] = st.slider(
        "Sicurezza analitica della tua valutazione finale", 1,7,4, key=f"{T}_conf")
    responses[f"{T}_leader_acceptance"] = st.slider(
        "Disponibilità ad accettare la sintesi del Team Leader", 1,7,4, key=f"{T}_la")
    responses[f"{T}_need_group"] = st.slider(
        "Necessità di confronto con gli altri analisti", 1,7,4, key=f"{T}_ng")

    # Item aggiuntivi Studio 2 — P e G separati
    st.caption("**Pressione temporale percepita** (Studio 2 — separata dalla criticità)")
    responses[f"{T}_pressione_1"] = st.slider(
        "In questa sessione ho percepito una pressione a decidere rapidamente",
        1,7,4, key=f"{T}_p1",
        help="1 = nessuna pressione  |  7 = pressione molto elevata")
    responses[f"{T}_pressione_2"] = st.slider(
        "Il tempo disponibile era adeguato alla complessità dello scenario",
        1,7,4, key=f"{T}_p2",
        help="1 = del tutto inadeguato  |  7 = pienamente adeguato (item invertito)")
    responses[f"{T}_pressione_3"] = st.slider(
        "Ho avvertito la necessità di rispondere prima di completare l'analisi",
        1,7,4, key=f"{T}_p3",
        help="1 = mai  |  7 = continuamente")

    # Pulsante scenario successivo
    if idx_T < len(ordine) - 1:
        prossimo = ordine[idx_T + 1]
        if st.button(f"▶ Vai allo scenario successivo ({prossimo})",
                     key=f"{T}_next"):
            st.rerun()
    st.divider()

# ── INVIO ─────────────────────────────────────────────────────
tutti_confermati = all(
    st.session_state.get(f"{T}_confirmed", False) for T in ordine)
tutti_completi = all(
    f"{T}_post_ai" in responses and
    responses.get(f"{T}_motivo","— seleziona —") != "— seleziona —" and
    responses.get(f"{T}_post_ordinale","— seleziona —") != "— seleziona —"
    for T in ordine)

if tutti_confermati and tutti_completi:
    if st.button("📨 Invia questionario", type="primary"):
        row = {
            "session_uuid":   str(uuid.uuid4()),
            "timestamp":      datetime.now().isoformat(timespec="seconds"),
            "ruolo":          ruolo,
            "team_id":        team_id,
            "posizione_team": pos_nel_team,
            "experience":     experience,
            "coordination":   coordination,
            "specialist_area":specialist_area,
            "ai_use":         ai_use,
            "ai_critical":    ai_critical,
            "ai_llm_use":     ai_llm_use,
            "ai_llm_trust":   ai_llm_trust,
            "ordine":         ordine_str,
        }
        row.update(responses)
        save_risposta(row)
        if len(load_risposte()) >= MAX_P:
            set_closed(True)
        st.success("✅ Risposta salvata. Grazie per la partecipazione.")
        st.rerun()
else:
    mancanti = []
    if not tutti_confermati:
        mancanti.append("conferma di tutti gli scenari")
    if not tutti_completi:
        mancanti.append("selezione della motivazione e della valutazione qualitativa")
    st.info(f"Per procedere all'invio: {' e '.join(mancanti)}.")
