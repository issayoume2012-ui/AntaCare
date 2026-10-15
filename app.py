# -*- coding: utf-8 -*-
"""
ANTACARE — Application Streamlit connectée à Supabase PostgreSQL.
Les données de santé restent sensibles : revue de sécurité, sauvegardes restaurables et validation réglementaire
requises avant toute utilisation clinique réelle.
"""
from datetime import date, datetime, timedelta
import hashlib
import hmac
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DB_PATH = None  # Base distante Supabase PostgreSQL; aucun fichier SQLite local.
EXPORT_DIR = APP_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)

st.set_page_config(
    page_title="ANTACARE | Anta Dièye",
    page_icon="🌸",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------- Style ----------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');
:root { --pink:#d9799d; --pink-light:#fff0f5; --teal:#218f8a; --ink:#263b42; --muted:#687b80; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:linear-gradient(180deg,#fffafd 0%,#f7fcfb 55%,#ffffff 100%); color:var(--ink); }
.block-container { max-width:1440px; padding-top:1.2rem; padding-bottom:3rem; }
.hero { border-radius:26px; padding:30px 34px; background:linear-gradient(120deg,#fff0f5 0%,#ffffff 48%,#e9f8f6 100%); border:1px solid #f2dce5; box-shadow:0 10px 34px #5e73740d; }
.eyebrow { text-transform:uppercase; letter-spacing:2.5px; font-size:.72rem; color:#218f8a; font-weight:700; }
.hero h1 { font-family:'Playfair Display',serif; color:#253d43; font-size:2.6rem; margin:.25rem 0; }
.hero p { color:#5b7075; font-size:1.03rem; margin-bottom:0; }
.pill { display:inline-block; padding:7px 12px; border-radius:999px; background:#ffffffb8; border:1px solid #ead6df; color:#795065; font-size:.82rem; margin:4px 5px 0 0; }
.section-title { font-family:'Playfair Display',serif; font-size:1.65rem; color:#27464b; margin:1rem 0 .25rem; }
.muted { color:#687b80; }
div[data-testid="stMetric"] { background:white; border:1px solid #e6efed; padding:16px 18px; border-radius:18px; box-shadow:0 5px 20px #263b4208; }
div[data-testid="stMetricLabel"] { color:#687b80; }
.stButton>button { border-radius:12px; border:1px solid #d8e8e5; font-weight:600; }
.stButton>button[kind="primary"] { background:#218f8a; border-color:#218f8a; }
.stTabs [data-baseweb="tab-list"] { gap:8px; flex-wrap:wrap; }
.stTabs [data-baseweb="tab"] { border-radius:12px 12px 0 0; padding:10px 16px; }
div[data-testid="stForm"] { background:white; border:1px solid #e5eeec; border-radius:18px; padding:20px; }
.small-note { font-size:.82rem; color:#718286; }
/* ANTACARE premium polish */
@keyframes riseIn { from {opacity:0; transform:translateY(9px)} to {opacity:1; transform:translateY(0)} }
@keyframes softPulse { 0%,100% {box-shadow:0 8px 28px #218f8a0b} 50% {box-shadow:0 12px 34px #218f8a18} }
.block-container { animation:riseIn .45s ease-out both; }
.hero { position:relative; overflow:hidden; animation:softPulse 8s ease-in-out infinite; }
.hero:after { content:'✿'; position:absolute; right:28px; top:-34px; font-size:145px; line-height:1; color:#d9799d12; pointer-events:none; }
.stTabs [data-baseweb="tab-list"] { background:#ffffffc9; border:1px solid #e7efed; border-radius:17px; padding:7px; box-shadow:0 6px 22px #263b4208; }
.stTabs [data-baseweb="tab"] { border-radius:11px; transition:background .2s ease, transform .2s ease; }
.stTabs [data-baseweb="tab"]:hover { background:#fff0f5; transform:translateY(-1px); }
.stTabs [aria-selected="true"] { background:linear-gradient(135deg,#e4f5f2,#fff0f5)!important; color:#214f50!important; font-weight:700; }
.stButton>button, [data-testid="stDownloadButton"] button { min-height:42px; transition:transform .18s ease, box-shadow .18s ease; }
.stButton>button:hover, [data-testid="stDownloadButton"] button:hover { transform:translateY(-2px); box-shadow:0 7px 18px #218f8a18; }
div[data-testid="stMetric"] { transition:transform .2s ease, box-shadow .2s ease; }
div[data-testid="stMetric"]:hover { transform:translateY(-3px); box-shadow:0 12px 26px #263b4210; }
[data-testid="stDataFrame"] { border:1px solid #e5eeec; border-radius:14px; overflow:hidden; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation:none!important; transition:none!important; scroll-behavior:auto!important; } }
</style>
""", unsafe_allow_html=True)

# ---------------------- Database PostgreSQL / Supabase ----------------------
# Configurez DATABASE_URL dans les secrets de l'environnement, jamais dans le code.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

class CursorCompat:
    """Adaptateur limité pour conserver les appels SQLite existants sans exposer SQL brut."""
    def __init__(self, cursor): self._cursor = cursor
    def execute(self, query, params=()):
        query = query.replace("?", "%s")
        # PostgreSQL ne fournit pas lastrowid : RETURNING id le remplace pour les INSERT.
        if query.lstrip().upper().startswith("INSERT INTO") and " RETURNING " not in query.upper():
            query = query.rstrip().rstrip(";") + " RETURNING id"
        self._cursor.execute(query, params or ())
        return self
    @property
    def lastrowid(self):
        row = self._cursor.fetchone()
        return row["id"] if row else None
    def fetchone(self): return self._cursor.fetchone()
    def fetchall(self): return self._cursor.fetchall()
    def __iter__(self): return iter(self._cursor)
    def close(self): self._cursor.close()

class ConnectionCompat:
    def __init__(self, raw): self.raw = raw
    def execute(self, query, params=()):
        cur = self.raw.cursor(cursor_factory=RealDictCursor)
        return CursorCompat(cur).execute(query, params)
    def executescript(self, script):
        cur = self.raw.cursor()
        for statement in script.split(';'):
            statement = statement.strip()
            if statement: cur.execute(statement)
        cur.close()
    def __enter__(self): return self
    def __exit__(self, typ, value, tb):
        if typ is None: self.raw.commit()
        else: self.raw.rollback()
        self.raw.close()
    def cursor(self, *args, **kwargs): return self.raw.cursor(*args, **kwargs)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL absent. Configurez-le dans les secrets de déploiement.")
    raw = psycopg2.connect(DATABASE_URL, sslmode="verify-full", connect_timeout=10,
                           application_name="ANTACARE")
    raw.set_session(autocommit=False)
    return ConnectionCompat(raw)

def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Administratrice', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, patient_code TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_date TEXT, phone TEXT, locality TEXT,
        emergency_contact TEXT, created_at TEXT NOT NULL, notes TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS pregnancies (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, lmp_date TEXT, edd_date TEXT,
        edd_method TEXT DEFAULT 'Règle des 280 jours', gravida INTEGER, para INTEGER,
        risk_notes TEXT DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS visits (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, visit_date TEXT NOT NULL,
        visit_type TEXT NOT NULL, reason TEXT DEFAULT '', observations TEXT DEFAULT '', examinations TEXT DEFAULT '',
        next_visit TEXT, referral TEXT DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, appointment_date TEXT NOT NULL,
        reason TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Prévu', notes TEXT DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS postpartum (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, delivery_date TEXT,
        delivery_place TEXT, mother_followup TEXT DEFAULT '', newborn_followup TEXT DEFAULT '', next_checkup TEXT,
        notes TEXT DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS family_planning (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, consultation_date TEXT NOT NULL,
        method_discussed TEXT DEFAULT '', informed_choice TEXT DEFAULT '', followup_date TEXT,
        reported_effects TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS training_events (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, title TEXT NOT NULL, activity_type TEXT NOT NULL,
        organizer TEXT DEFAULT '', topic TEXT DEFAULT '', start_date TEXT, end_date TEXT, location TEXT DEFAULT '',
        format TEXT DEFAULT 'Présentiel', participation_status TEXT NOT NULL DEFAULT 'Prévu',
        certificate_status TEXT NOT NULL DEFAULT 'À demander', hours DOUBLE PRECISION DEFAULT 0,
        cost DOUBLE PRECISION DEFAULT 0, currency TEXT DEFAULT 'FCFA', link TEXT DEFAULT '',
        document_name TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, username TEXT NOT NULL, action TEXT NOT NULL,
        object_type TEXT NOT NULL, object_id INTEGER, occurred_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_visits_patient_date ON visits(patient_id, visit_date);
    CREATE INDEX IF NOT EXISTS idx_appointments_date_status ON appointments(appointment_date, status);
    CREATE INDEX IF NOT EXISTS idx_pregnancies_patient ON pregnancies(patient_id);
    CREATE INDEX IF NOT EXISTS idx_audit_occurred ON audit_log(occurred_at);
    """
    with get_conn() as conn:
        conn.executescript(schema)
        # Pas de compte/mot de passe de démonstration codé en dur.
        admin_password = os.environ.get("ANTACARE_ADMIN_PASSWORD", "")
        username = os.environ.get("ANTACARE_ADMIN_USERNAME", "anta").strip()
        count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if count == 0 and admin_password:
            if len(admin_password) < 14:
                raise RuntimeError("ANTACARE_ADMIN_PASSWORD doit contenir au moins 14 caractères.")
            salt = os.urandom(16).hex()
            pw_hash = hashlib.pbkdf2_hmac("sha256", admin_password.encode(), bytes.fromhex(salt), 600_000).hex()
            conn.execute("INSERT INTO users(username,password_hash,salt,role,created_at) VALUES(?,?,?,?,?)",
                         (username, pw_hash, salt, "Administratrice", datetime.now().isoformat(timespec="seconds")))

def log_action(action, obj_type, obj_id=None):
    with get_conn() as conn:
        conn.execute("INSERT INTO audit_log(username,action,object_type,object_id,occurred_at) VALUES(?,?,?,?,?)",
                     (st.session_state.get("username", "inconnu"), action, obj_type, obj_id, datetime.now().isoformat(timespec="seconds")))

def verify_password(username, password):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row: return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(row["salt"]), 600_000).hex()
    return hmac.compare_digest(candidate, row["password_hash"])

def change_password(username, new_password):
    salt = os.urandom(16).hex()
    pw_hash = hashlib.pbkdf2_hmac("sha256", new_password.encode(), bytes.fromhex(salt), 600_000).hex()
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?", (pw_hash, salt, username))
    log_action("Modification du mot de passe", "user")

try:
    init_db()
except Exception as exc:
    st.error("Connexion PostgreSQL impossible ou initialisation échouée. Vérifiez les secrets DATABASE_URL et l'accès réseau Supabase.")
    st.stop()

# ---------------------- Helpers ----------------------
def read_df(query, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(query.replace("?", "%s"), conn.raw, params=params)

def patient_label(row):
    return f"{row['patient_code']} — {row['last_name']} {row['first_name']}"

def all_patients():
    return read_df("SELECT id, patient_code, first_name, last_name, birth_date, phone, locality FROM patients ORDER BY last_name, first_name")

def calc_edd(lmp):
    return lmp + timedelta(days=280)

def get_patient_map():
    df = all_patients()
    return {patient_label(row): int(row["id"]) for _, row in df.iterrows()}

def get_patient_name(patient_id):
    df = read_df("SELECT patient_code,first_name,last_name FROM patients WHERE id=?", (patient_id,))
    if df.empty:
        return "Patiente inconnue"
    r = df.iloc[0]
    return f"{r['patient_code']} — {r['last_name']} {r['first_name']}"

def render_table(df, empty_message="Aucune donnée enregistrée pour le moment."):
    if df.empty:
        st.info(empty_message)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

def create_pdf_report(title, subtitle, body_lines, filename):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.units import mm
        path = EXPORT_DIR / filename
        doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="ANTATitle", parent=styles["Title"], textColor=colors.HexColor("#218f8a"), alignment=TA_CENTER, fontSize=21, leading=26, spaceAfter=8))
        styles.add(ParagraphStyle(name="ANTASub", parent=styles["Normal"], textColor=colors.HexColor("#687b80"), alignment=TA_CENTER, fontSize=9, spaceAfter=16))
        styles.add(ParagraphStyle(name="ANTABody", parent=styles["BodyText"], fontSize=10, leading=15, spaceAfter=7))
        story = [Paragraph(title, styles["ANTATitle"]), Paragraph(subtitle, styles["ANTASub"]), Spacer(1, 5*mm)]
        for line in body_lines:
            safe = str(line).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, styles["ANTABody"]))
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Document généré par ANTACARE — prototype local. À vérifier avant tout usage professionnel.", styles["Italic"]))
        doc.build(story)
        return path
    except ImportError:
        st.error("Le module reportlab n'est pas installé. Lancez : pip install reportlab")
        return None

def create_pdf_table_report(title, subtitle, dataframe, intro="Rapport de synthèse"):
    """Génère un PDF professionnel paginé avec tableau répétant son en-tête."""
    try:
        from io import BytesIO
        from xml.sax.saxutils import escape
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.units import mm
        output = BytesIO()
        wide = len(dataframe.columns) > 5
        page_size = landscape(A4) if wide else A4
        doc = SimpleDocTemplate(output, pagesize=page_size, rightMargin=12*mm, leftMargin=12*mm, topMargin=15*mm, bottomMargin=15*mm)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="ANTACoverTitle", parent=styles["Title"], textColor=colors.HexColor("#218f8a"), alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=20, leading=25, spaceAfter=6))
        styles.add(ParagraphStyle(name="ANTACoverSub", parent=styles["Normal"], textColor=colors.HexColor("#687b80"), alignment=TA_CENTER, fontSize=9, leading=13, spaceAfter=14))
        styles.add(ParagraphStyle(name="ANTACell", parent=styles["BodyText"], fontSize=7.2 if wide else 8, leading=9, wordWrap="CJK"))
        styles.add(ParagraphStyle(name="ANTACellHead", parent=styles["BodyText"], fontName="Helvetica-Bold", textColor=colors.white, fontSize=7.2 if wide else 8, leading=9))
        story = [Paragraph("ANTACARE · RAPPORT PROFESSIONNEL", styles["ANTACoverSub"]), Paragraph(escape(str(title)), styles["ANTACoverTitle"]), Paragraph(escape(str(subtitle)), styles["ANTACoverSub"]), Paragraph(escape(str(intro)), styles["Heading2"]), Spacer(1, 4*mm)]
        story.append(Paragraph(f"Enregistrements : <b>{len(dataframe)}</b> · Généré le {datetime.now():%d/%m/%Y à %H:%M}", styles["Normal"]))
        story.append(Spacer(1, 5*mm))
        if dataframe.empty:
            story.append(Paragraph("Aucune donnée enregistrée pour les critères sélectionnés.", styles["BodyText"]))
        else:
            cols = list(dataframe.columns)
            rows = [[Paragraph(escape(str(c)), styles["ANTACellHead"]) for c in cols]]
            for _, row in dataframe.fillna("").iterrows():
                rows.append([Paragraph(escape(str(v))[:700], styles["ANTACell"]) for v in row.tolist()])
            available = page_size[0] - 24*mm
            col_width = available / max(1, len(cols))
            # For broad tables, keep every column in the printable area.
            table = Table(rows, colWidths=[col_width]*len(cols), repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#218f8a")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#dce9e6")),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f3faf8")]),
                ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
                ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ]))
            story.append(table)
        def footer(canvas, document):
            canvas.saveState()
            w, h = page_size
            canvas.setStrokeColor(colors.HexColor("#dce9e6")); canvas.line(12*mm, 10*mm, w-12*mm, 10*mm)
            canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.HexColor("#687b80"))
            canvas.drawString(12*mm, 6*mm, "ANTACARE · Document confidentiel — vérifier les droits d’accès")
            canvas.drawRightString(w-12*mm, 6*mm, f"Page {document.page}")
            canvas.restoreState()
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return output.getvalue()
    except ImportError:
        st.error("Le module reportlab n'est pas installé. Lancez : py -m pip install reportlab")
        return None

def render_report_downloads(dataframe, title, subtitle, slug):
    """Exports indépendants PDF, Excel et CSV pour chaque sous-unité."""
    st.caption(f"{len(dataframe)} ligne(s) · Les exports sont préparés uniquement pour cette sous-unité.")
    csv_bytes = dataframe.to_csv(index=False).encode("utf-8-sig")
    pdf_bytes = create_pdf_table_report(title, subtitle, dataframe)
    xlsx_bytes = None
    try:
        from io import BytesIO
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name="Rapport")
            pd.DataFrame({"Champ": ["Rapport", "Période", "Généré le"], "Valeur": [title, subtitle, datetime.now().strftime("%d/%m/%Y %H:%M")]}).to_excel(writer, index=False, sheet_name="Informations")
        xlsx_bytes = buffer.getvalue()
    except ImportError:
        st.warning("Pour l’export Excel, installez openpyxl : py -m pip install openpyxl")
    c1, c2, c3 = st.columns(3)
    with c1:
        if pdf_bytes:
            st.download_button("📕 Télécharger le PDF", pdf_bytes, file_name=f"antacare_{slug}.pdf", mime="application/pdf", use_container_width=True, key=f"pdf_{slug}")
    with c2:
        if xlsx_bytes:
            st.download_button("📊 Télécharger Excel", xlsx_bytes, file_name=f"antacare_{slug}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key=f"xlsx_{slug}")
    with c3:
        st.download_button("📄 Télécharger CSV", csv_bytes, file_name=f"antacare_{slug}.csv", mime="text/csv", use_container_width=True, key=f"csv_{slug}")

# ---------------------- Login ----------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("""
    <div class="hero">
      <div class="eyebrow">Espace professionnel sécurisé · Supabase PostgreSQL</div>
      <h1>🌸 ANTACARE</h1>
      <p>Accompagner la vie, protéger la mère, accueillir demain.</p>
      <span class="pill">Suivi maternel</span><span class="pill">Consultations</span><span class="pill">Organisation</span>
    </div>
    """, unsafe_allow_html=True)
    st.write("")
    left, center, right = st.columns([1, 1.15, 1])
    with center:
        st.subheader("Connexion professionnelle")
        with st.form("login_form"):
            username = st.text_input("Identifiant")
            password = st.text_input("Mot de passe", type="password")
            submit = st.form_submit_button("Se connecter", type="primary", use_container_width=True)
        if submit:
            if verify_password(username.strip(), password):
                st.session_state.authenticated = True
                st.session_state.username = username.strip()
                log_action("Connexion", "session")
                st.rerun()
            else:
                st.error("Identifiant ou mot de passe incorrect.")
    st.stop()

# ---------------------- Header / navigation ----------------------
top1, top2 = st.columns([4, 1])
with top1:
    st.markdown("""
    <div class="hero">
      <div class="eyebrow">Espace professionnel · Saint-Louis, Sénégal</div>
      <h1>ANTACARE <span style="font-size:1.15rem;color:#d9799d">✿</span></h1>
      <p>Accompagner la vie, protéger la mère, accueillir demain.</p>
      <span class="pill">Anta Dièye · Sage-femme échographiste</span>
      <span class="pill">Supabase PostgreSQL</span>
    </div>
    """, unsafe_allow_html=True)
with top2:
    st.write("")
    st.write("")
    if st.button("🔒 Déconnexion", use_container_width=True):
        log_action("Déconnexion", "session")
        st.session_state.authenticated = False
        st.session_state.pop("username", None)
        st.rerun()

tabs = st.tabs([
    "🏠 Tableau de bord", "👩🏽‍⚕️ Profil", "🤰 Patientes", "🩺 Consultations",
    "📅 Rendez-vous", "👶 Post-partum", "🩸 Planification familiale",
    "📚 Éducation sanitaire", "🎓 Formations & séminaires", "📄 Rapports", "⚙️ Paramètres"
])

# ---------------------- Dashboard ----------------------
with tabs[0]:
    st.markdown('<div class="section-title">Votre activité en un coup d’œil</div>', unsafe_allow_html=True)
    today = date.today().isoformat()
    month_prefix = date.today().strftime("%Y-%m")
    patients_df = read_df("SELECT * FROM patients")
    visits_today = read_df("SELECT * FROM visits WHERE visit_date=?", (today,))
    appointments_today = read_df("SELECT * FROM appointments WHERE substr(appointment_date,1,10)=?", (today,))
    upcoming = read_df("SELECT * FROM appointments WHERE appointment_date>=? AND status='Prévu' ORDER BY appointment_date LIMIT 8", (datetime.now().isoformat(timespec="minutes"),))
    missed = read_df("SELECT * FROM appointments WHERE substr(appointment_date,1,10)<? AND status='Prévu'", (today,))
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Dossiers patientes", len(patients_df))
    c2.metric("Consultations aujourd’hui", len(visits_today))
    c3.metric("Rendez-vous aujourd’hui", len(appointments_today))
    c4.metric("Rendez-vous en retard", len(missed))
    c5,c6,c7 = st.columns(3)
    c5.metric("Consultations ce mois", len(read_df("SELECT id FROM visits WHERE substr(visit_date,1,7)=?", (month_prefix,))))
    c6.metric("Rendez-vous à venir", len(read_df("SELECT id FROM appointments WHERE appointment_date>=? AND status='Prévu'", (datetime.now().isoformat(timespec="minutes"),))))
    c7.metric("Dossiers créés ce mois", len(read_df("SELECT id FROM patients WHERE substr(created_at,1,7)=?", (month_prefix,))))
    st.markdown("#### Prochains rendez-vous")
    if upcoming.empty:
        st.info("Aucun rendez-vous à venir. Ajoutez-en dans l’onglet Rendez-vous.")
    else:
        upcoming["Patiente"] = upcoming["patient_id"].apply(get_patient_name)
        render_table(upcoming[["Patiente","appointment_date","reason","status"]].rename(columns={"appointment_date":"Date et heure","reason":"Motif","status":"Statut"}))
    st.caption("Les indicateurs sont calculés à partir des enregistrements de cette base locale.")

# ---------------------- Profile ----------------------
with tabs[1]:
    st.markdown('<div class="section-title">Profil professionnel</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="hero">
      <div class="eyebrow">Profil professionnel</div>
      <h1>Anta Dièye</h1>
      <p><b>Sage-femme échographiste</b> · Saint-Louis, Sénégal</p>
      <p style="margin-top:12px">Professionnelle de santé spécialisée en soins obstétricaux et échographie obstétricale, avec une expérience dans les structures sanitaires publiques et communautaires. Compétences en santé maternelle et néonatale, planification familiale, DHIS2 et accompagnement communautaire.</p>
    </div>
    """, unsafe_allow_html=True)
    p1,p2,p3 = st.columns(3)
    p1.markdown("**Coordonnées professionnelles**")
    p1.write("Saint-Louis, Sénégal")
    p1.write("77 474 53 81 · 77 104 86 06")
    p1.write("dieyeanta629@gmail.com")
    p2.markdown("**Diplômes et formations**")
    p2.write("2015–2017 · Licence en Soins Obstétricaux — ESUP Santé Saint-Louis")
    p2.write("2024 · Formation en échographie obstétricale d’urgence et SONU de base — CEFOREP")
    p2.write("2023 · Cours régional de paludologie — PNLP")
    p2.write("2025 · Diplôme d’honneur — Réseau des acteurs communautaires de Djinaky")
    p3.markdown("**Langues et outils**")
    p3.write("Français : bonne maîtrise")
    p3.write("Wolof : bonne maîtrise")
    p3.write("Anglais : notions scolaires")
    p3.write("Word, Excel, PowerPoint, outils numériques et DHIS2")
    with st.expander("Afficher les expériences professionnelles"):
        st.markdown("""
        - **Depuis février 2025** — Poste de Santé de Djinaky, DS Diouloulou, Ziguinchor
        - **Novembre 2021 – décembre 2024** — Poste de Santé de Kafountine, Point focal Badiane Gox
        - **Janvier 2020 – octobre 2021** — District Sanitaire de Mékhé, région de Thiès
        - **Décembre 2018 – décembre 2019** — Poste de Santé de Tassinère Gandiol, Saint-Louis
        - **Juin 2018 – décembre 2018** — Clinique Fara Wade, Saint-Louis (stagiaire)
        - **Octobre 2017 – juin 2018** — EPS Richard Toll, stage de perfectionnement
        """)
    with st.expander("Autres diplômes"):
        st.write("2013–2014 : Licence 1 en Français — Université Gaston Berger de Saint-Louis")
        st.write("2010–2012 : Baccalauréat · 2006–2009 : BFEM · 2000–2005 : Certificat de fin d’études élémentaires")
    st.caption("Les informations personnelles non nécessaires à l’activité clinique, comme l’âge ou la situation matrimoniale, ne sont pas affichées dans cet espace.")

# ---------------------- Patients ----------------------
with tabs[2]:
    st.markdown('<div class="section-title">Dossiers des patientes</div>', unsafe_allow_html=True)
    add_tab, list_tab, preg_tab = st.tabs(["➕ Nouveau dossier", "🔎 Rechercher / consulter", "🤰 Suivi de grossesse"])
    with add_tab:
        with st.form("patient_form", clear_on_submit=True):
            a,b = st.columns(2)
            first = a.text_input("Prénom *")
            last = b.text_input("Nom *")
            c,d = st.columns(2)
            birth = c.date_input("Date de naissance (facultatif)", value=None, min_value=date(1900,1,1), max_value=date.today())
            phone = d.text_input("Téléphone")
            locality = st.text_input("Localité / quartier")
            emergency = st.text_input("Contact à prévenir (si nécessaire)")
            notes = st.text_area("Notes administratives non cliniques")
            saved = st.form_submit_button("Enregistrer le dossier", type="primary")
        if saved:
            if not first.strip() or not last.strip():
                st.error("Le prénom et le nom sont obligatoires.")
            else:
                with get_conn() as conn:
                    code = f"AC-{datetime.now():%y%m%d%H%M%S}"
                    cur = conn.execute("""INSERT INTO patients(patient_code,first_name,last_name,birth_date,phone,locality,emergency_contact,created_at,notes)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (code, first.strip(), last.strip(), birth.isoformat() if birth else None, phone.strip(), locality.strip(), emergency.strip(), datetime.now().isoformat(timespec="seconds"), notes.strip()))
                    pid = cur.lastrowid
                log_action("Création dossier patiente", "patient", pid)
                st.success(f"Dossier créé : {code}")
                st.rerun()
    with list_tab:
        search = st.text_input("Recherche par code, nom, prénom ou téléphone")
        df = read_df("""SELECT id,patient_code AS Code,first_name AS Prénom,last_name AS Nom,birth_date AS Naissance,phone AS Téléphone,locality AS Localité,created_at AS 'Créé le'
        FROM patients WHERE patient_code LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR phone LIKE ? ORDER BY last_name""",
        tuple([f"%{search}%"]*4))
        render_table(df)
        if not df.empty:
            selected_code = st.selectbox("Ouvrir le dossier", df["Code"].tolist(), key="patient_open_code")
            with get_conn() as conn:
                p = conn.execute("SELECT * FROM patients WHERE patient_code=?", (selected_code,)).fetchone()
                visits = conn.execute("SELECT visit_date,visit_type,reason,observations,next_visit FROM visits WHERE patient_id=? ORDER BY visit_date DESC", (p["id"],)).fetchall()
                preg = conn.execute("SELECT * FROM pregnancies WHERE patient_id=? ORDER BY id DESC", (p["id"],)).fetchall()
                post = conn.execute("SELECT * FROM postpartum WHERE patient_id=? ORDER BY id DESC", (p["id"],)).fetchall()
            st.markdown(f"#### {p['last_name']} {p['first_name']} · {p['patient_code']}")
            q1,q2,q3 = st.columns(3)
            q1.write(f"**Naissance :** {p['birth_date'] or 'Non renseignée'}")
            q2.write(f"**Téléphone :** {p['phone'] or 'Non renseigné'}")
            q3.write(f"**Localité :** {p['locality'] or 'Non renseignée'}")
            with st.expander("Historique des consultations"):
                render_table(pd.DataFrame([dict(r) for r in visits]))
            with st.expander("Suivis de grossesse"):
                render_table(pd.DataFrame([dict(r) for r in preg]))
            with st.expander("Suivis post-partum"):
                render_table(pd.DataFrame([dict(r) for r in post]))
    with preg_tab:
        options = get_patient_map()
        if not options:
            st.info("Créez d’abord un dossier patiente.")
        else:
            with st.form("pregnancy_form"):
                chosen = st.selectbox("Patiente", list(options.keys()))
                lmp = st.date_input("Date des dernières règles (si connue)", value=None, min_value=date(2000,1,1), max_value=date.today())
                g1,g2 = st.columns(2)
                gravida = g1.number_input("Gestité (nombre de grossesses)", min_value=0, max_value=30, value=0)
                para = g2.number_input("Parité (nombre d’accouchements)", min_value=0, max_value=30, value=0)
                risk = st.text_area("Antécédents / observations à documenter")
                save_preg = st.form_submit_button("Enregistrer le suivi de grossesse", type="primary")
            if save_preg:
                edd = calc_edd(lmp) if lmp else None
                with get_conn() as conn:
                    cur = conn.execute("INSERT INTO pregnancies(patient_id,lmp_date,edd_date,edd_method,gravida,para,risk_notes,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (options[chosen], lmp.isoformat() if lmp else None, edd.isoformat() if edd else None, "Règle des 280 jours si DDR connue", int(gravida), int(para), risk.strip(), datetime.now().isoformat(timespec="seconds")))
                    pid = cur.lastrowid
                log_action("Ajout suivi de grossesse", "pregnancy", pid)
                st.success(f"Suivi enregistré. Date prévisionnelle calculée : {edd.isoformat() if edd else 'non calculée'}. À confirmer cliniquement.")
                st.rerun()
            preg_df = read_df("""SELECT p.patient_code,p.last_name,p.first_name,g.lmp_date AS DDR,g.edd_date AS 'Date prévisionnelle',g.gravida AS Gestité,g.para AS Parité,g.risk_notes AS Observations
            FROM pregnancies g JOIN patients p ON p.id=g.patient_id ORDER BY g.id DESC""")
            render_table(preg_df)

# ---------------------- Visits ----------------------
with tabs[3]:
    st.markdown('<div class="section-title">Consultations et observations</div>', unsafe_allow_html=True)
    options = get_patient_map()
    if not options:
        st.info("Ajoutez d’abord une patiente dans l’onglet Patientes.")
    else:
        with st.form("visit_form", clear_on_submit=True):
            chosen = st.selectbox("Patiente", list(options.keys()), key="visit_patient")
            vdate = st.date_input("Date de consultation", value=date.today(), key="visit_date")
            vtype = st.selectbox("Type de consultation", ["Consultation prénatale (CPN)","Consultation postnatale (CPoN)","Échographie obstétricale","Consultation de santé reproductive","Planification familiale","Soins obstétricaux","Suivi du nouveau-né","Autre"])
            reason = st.text_input("Motif")
            observations = st.text_area("Observations professionnelles")
            exams = st.text_area("Examens et résultats consignés")
            nextv = st.date_input("Prochain rendez-vous (facultatif)", value=None, min_value=date.today(), key="visit_next")
            referral = st.text_input("Orientation / référence, si nécessaire")
            save_visit = st.form_submit_button("Enregistrer la consultation", type="primary")
        if save_visit:
            with get_conn() as conn:
                cur = conn.execute("INSERT INTO visits(patient_id,visit_date,visit_type,reason,observations,examinations,next_visit,referral,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (options[chosen],vdate.isoformat(),vtype,reason.strip(),observations.strip(),exams.strip(),nextv.isoformat() if nextv else None,referral.strip(),datetime.now().isoformat(timespec="seconds")))
                vid = cur.lastrowid
                if nextv:
                    conn.execute("INSERT INTO appointments(patient_id,appointment_date,reason,status,notes,created_at) VALUES(?,?,?,?,?,?)",
                    (options[chosen],datetime.combine(nextv,datetime.min.time()).isoformat(timespec="minutes"),"Contrôle après consultation","Prévu","Créé depuis une consultation",datetime.now().isoformat(timespec="seconds")))
            log_action("Enregistrement consultation", "visit", vid)
            st.success("Consultation enregistrée.")
            st.rerun()
    st.markdown("#### Historique récent")
    vdf = read_df("""SELECT v.visit_date AS Date,p.patient_code AS Code,p.last_name AS Nom,p.first_name AS Prénom,v.visit_type AS Type,v.reason AS Motif,v.next_visit AS 'Prochain rendez-vous'
    FROM visits v JOIN patients p ON p.id=v.patient_id ORDER BY v.visit_date DESC LIMIT 200""")
    render_table(vdf)

# ---------------------- Appointments ----------------------
with tabs[4]:
    st.markdown('<div class="section-title">Agenda et rendez-vous</div>', unsafe_allow_html=True)
    options = get_patient_map()
    if not options:
        st.info("Ajoutez d’abord une patiente.")
    else:
        with st.form("appointment_form", clear_on_submit=True):
            chosen = st.selectbox("Patiente", list(options.keys()), key="appt_patient")
            appt_date = st.date_input("Date", value=date.today(), key="appt_day")
            appt_time = st.time_input("Heure", value=datetime.now().replace(second=0,microsecond=0).time())
            reason = st.text_input("Motif du rendez-vous")
            status = st.selectbox("Statut", ["Prévu","Réalisé","Absent","Annulé"])
            notes = st.text_area("Notes")
            save_appt = st.form_submit_button("Ajouter le rendez-vous", type="primary")
        if save_appt:
            stamp = datetime.combine(appt_date, appt_time).isoformat(timespec="minutes")
            with get_conn() as conn:
                cur = conn.execute("INSERT INTO appointments(patient_id,appointment_date,reason,status,notes,created_at) VALUES(?,?,?,?,?,?)",
                (options[chosen],stamp,reason.strip(),status,notes.strip(),datetime.now().isoformat(timespec="seconds")))
                aid = cur.lastrowid
            log_action("Création rendez-vous", "appointment", aid)
            st.success("Rendez-vous ajouté.")
            st.rerun()
    apdf = read_df("""SELECT a.id AS ID,p.patient_code AS Code,p.last_name AS Nom,p.first_name AS Prénom,a.appointment_date AS 'Date et heure',a.reason AS Motif,a.status AS Statut,a.notes AS Notes
    FROM appointments a JOIN patients p ON p.id=a.patient_id ORDER BY a.appointment_date DESC LIMIT 300""")
    render_table(apdf)
    if not apdf.empty:
        st.markdown("#### Modifier le statut d’un rendez-vous")
        apt_choices = {f"#{r['ID']} · {r['Nom']} {r['Prénom']} · {r['Date et heure']}": int(r['ID']) for _,r in apdf.iterrows()}
        selected_appt = st.selectbox("Rendez-vous", list(apt_choices.keys()))
        new_status = st.selectbox("Nouveau statut", ["Prévu","Réalisé","Absent","Annulé"], key="new_appt_status")
        if st.button("Mettre à jour le statut"):
            with get_conn() as conn:
                conn.execute("UPDATE appointments SET status=? WHERE id=?", (new_status,apt_choices[selected_appt]))
            log_action("Modification statut rendez-vous", "appointment", apt_choices[selected_appt])
            st.success("Statut mis à jour.")
            st.rerun()

# ---------------------- Postpartum ----------------------
with tabs[5]:
    st.markdown('<div class="section-title">Suivi post-partum et nouveau-né</div>', unsafe_allow_html=True)
    options = get_patient_map()
    if not options:
        st.info("Ajoutez d’abord une patiente.")
    else:
        with st.form("postpartum_form", clear_on_submit=True):
            chosen = st.selectbox("Patiente", list(options.keys()), key="post_patient")
            delivery = st.date_input("Date de l’accouchement", value=None, min_value=date(2000,1,1), max_value=date.today())
            place = st.text_input("Lieu de l’accouchement")
            mother = st.text_area("Suivi postnatal de la mère")
            newborn = st.text_area("Informations de suivi du nouveau-né")
            checkup = st.date_input("Date du prochain contrôle (facultatif)", value=None, min_value=date.today(), key="post_check")
            notes = st.text_area("Notes complémentaires")
            save_post = st.form_submit_button("Enregistrer le suivi", type="primary")
        if save_post:
            with get_conn() as conn:
                cur = conn.execute("INSERT INTO postpartum(patient_id,delivery_date,delivery_place,mother_followup,newborn_followup,next_checkup,notes,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (options[chosen],delivery.isoformat() if delivery else None,place.strip(),mother.strip(),newborn.strip(),checkup.isoformat() if checkup else None,notes.strip(),datetime.now().isoformat(timespec="seconds")))
                pid = cur.lastrowid
                if checkup:
                    conn.execute("INSERT INTO appointments(patient_id,appointment_date,reason,status,notes,created_at) VALUES(?,?,?,?,?,?)",
                    (options[chosen],datetime.combine(checkup,datetime.min.time()).isoformat(timespec="minutes"),"Contrôle postnatal","Prévu","Créé depuis le suivi post-partum",datetime.now().isoformat(timespec="seconds")))
            log_action("Enregistrement suivi post-partum", "postpartum", pid)
            st.success("Suivi enregistré.")
            st.rerun()
    pdf = read_df("""SELECT p.patient_code AS Code,p.last_name AS Nom,p.first_name AS Prénom,x.delivery_date AS Accouchement,x.delivery_place AS Lieu,x.mother_followup AS 'Suivi mère',x.newborn_followup AS 'Suivi nouveau-né',x.next_checkup AS 'Prochain contrôle'
    FROM postpartum x JOIN patients p ON p.id=x.patient_id ORDER BY x.id DESC""")
    render_table(pdf)

# ---------------------- Family planning ----------------------
with tabs[6]:
    st.markdown('<div class="section-title">Planification familiale</div>', unsafe_allow_html=True)
    options = get_patient_map()
    if not options:
        st.info("Ajoutez d’abord une patiente.")
    else:
        with st.form("fp_form", clear_on_submit=True):
            chosen = st.selectbox("Patiente", list(options.keys()), key="fp_patient")
            fdate = st.date_input("Date de consultation", value=date.today(), key="fp_date")
            method = st.selectbox("Méthode(s) abordée(s)", ["Information générale","Implant","DIU","Injectable","Pilule","Préservatif","Méthode naturelle","Autre","Aucune méthode choisie"])
            choice = st.text_area("Information donnée et choix éclairé de la patiente")
            followup = st.date_input("Date de suivi (facultatif)", value=None, min_value=date.today(), key="fp_followup")
            effects = st.text_area("Effets rapportés (si applicable)")
            notes = st.text_area("Notes")
            save_fp = st.form_submit_button("Enregistrer", type="primary")
        if save_fp:
            with get_conn() as conn:
                cur = conn.execute("INSERT INTO family_planning(patient_id,consultation_date,method_discussed,informed_choice,followup_date,reported_effects,notes,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (options[chosen],fdate.isoformat(),method,choice.strip(),followup.isoformat() if followup else None,effects.strip(),notes.strip(),datetime.now().isoformat(timespec="seconds")))
                fid = cur.lastrowid
                if followup:
                    conn.execute("INSERT INTO appointments(patient_id,appointment_date,reason,status,notes,created_at) VALUES(?,?,?,?,?,?)",
                    (options[chosen],datetime.combine(followup,datetime.min.time()).isoformat(timespec="minutes"),"Suivi planification familiale","Prévu","Créé depuis le suivi PF",datetime.now().isoformat(timespec="seconds")))
            log_action("Enregistrement planification familiale", "family_planning", fid)
            st.success("Enregistrement effectué.")
            st.rerun()
    fdf = read_df("""SELECT p.patient_code AS Code,p.last_name AS Nom,p.first_name AS Prénom,f.consultation_date AS Date,f.method_discussed AS 'Méthode abordée',f.followup_date AS 'Suivi',f.reported_effects AS 'Effets rapportés'
    FROM family_planning f JOIN patients p ON p.id=f.patient_id ORDER BY f.consultation_date DESC""")
    render_table(fdf)

# ---------------------- Health education ----------------------
with tabs[7]:
    st.markdown('<div class="section-title">Bibliothèque d’éducation sanitaire</div>', unsafe_allow_html=True)
    st.write("Fiches générales à faire vérifier par une professionnelle responsable avant diffusion. Cette bibliothèque ne constitue pas un protocole clinique.")
    themes = {
        "Grossesse et suivi prénatal": ("FR", "Respecter les rendez-vous prénatals prévus avec l’équipe de santé. Signaler rapidement tout symptôme inhabituel à un professionnel de santé. En cas de saignement important, convulsions, difficulté respiratoire ou perte de connaissance, rechercher une aide médicale urgente."),
        "Alimentation pendant la grossesse": ("FR", "Privilégier une alimentation variée et équilibrée, boire de l’eau potable et suivre les conseils de l’équipe de santé concernant les suppléments et les aliments à éviter."),
        "Allaitement": ("FR", "Demander un accompagnement si la mise au sein est douloureuse ou difficile. Pour toute difficulté d’alimentation ou tout signe inquiétant chez le nouveau-né, contacter rapidement un professionnel de santé."),
        "Post-partum": ("FR", "Assurer le suivi de la mère après l’accouchement et se présenter aux rendez-vous recommandés. Une hémorragie importante, une forte fièvre, des difficultés respiratoires ou un malaise sévère nécessitent une prise en charge urgente."),
        "Nouveau-né": ("FR", "Maintenir le nouveau-né au chaud, suivre les recommandations locales de soins et de vaccination, et demander rapidement une évaluation en cas de difficulté respiratoire, de refus de s’alimenter ou de changement inquiétant."),
        "Planification familiale": ("FR", "La décision contraceptive doit être libre et éclairée. Un professionnel de santé peut expliquer les méthodes disponibles, leurs avantages, leurs limites et les modalités de suivi.")
    }
    for title, (lang, content) in themes.items():
        with st.expander(title):
            st.write(content)
            st.caption("À valider selon les recommandations sanitaires nationales avant toute utilisation.")
    st.info("La version wolof pourra être ajoutée après validation de traductions médicales fiables.")


# ---------------------- Training, seminars and professional development ----------------------
with tabs[8]:
    st.markdown('<div class="section-title">Formations, séminaires et développement professionnel</div>', unsafe_allow_html=True)
    st.write("Centralisez les formations continues, séminaires, congrès, ateliers, webinaires, conférences, stages de perfectionnement et certifications d’Anta Dièye.")
    st.caption("Ce module est un registre de suivi professionnel. N’y stockez pas de documents confidentiels sans protection adaptée.")

    sub_new, sub_list, sub_stats = st.tabs(["➕ Ajouter une activité", "📚 Mon parcours", "📊 Synthèse"])

    with sub_new:
        with st.form("training_event_form", clear_on_submit=True):
            title = st.text_input("Intitulé de l’activité *", placeholder="Ex. : Formation en échographie obstétricale")
            activity_type = st.selectbox("Type d’activité", [
                "Formation", "Séminaire", "Congrès", "Atelier", "Webinaire",
                "Conférence", "Stage de perfectionnement", "Certification",
                "Réunion scientifique", "Sensibilisation", "Autre"
            ])
            topic = st.text_input("Domaine / thématique", placeholder="Ex. : Santé maternelle et néonatale")
            organizer = st.text_input("Organisateur / institution", placeholder="Ex. : CEFOREP, ministère, université…")
            c1, c2 = st.columns(2)
            start_date = c1.date_input("Date de début", value=date.today(), key="training_start")
            end_date = c2.date_input("Date de fin", value=date.today(), key="training_end")
            c3, c4 = st.columns(2)
            location = c3.text_input("Lieu / ville", placeholder="Ex. : Saint-Louis, Dakar ou en ligne")
            fmt = c4.selectbox("Format", ["Présentiel", "En ligne", "Hybride"])
            c5, c6 = st.columns(2)
            participation_status = c5.selectbox("Statut de participation", ["Prévu", "Inscription en cours", "Inscrite", "En cours", "Terminé", "Annulé"])
            certificate_status = c6.selectbox("Attestation / certificat", ["Non applicable", "À demander", "En attente", "Reçu"])
            c7, c8 = st.columns(2)
            hours = c7.number_input("Durée (heures)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
            cost = c8.number_input("Coût / frais de participation", min_value=0.0, max_value=100000000.0, value=0.0, step=1000.0)
            currency = st.selectbox("Devise", ["FCFA", "EUR", "USD", "Autre"])
            link = st.text_input("Lien d’inscription ou ressource en ligne", placeholder="https://…")
            document_name = st.text_input("Nom du document associé", placeholder="Ex. : attestation_formation.pdf (référence uniquement)")
            notes = st.text_area("Notes, acquis, compétences développées ou suites à donner")
            submitted = st.form_submit_button("Enregistrer l’activité", type="primary", use_container_width=True)

        if submitted:
            if not title.strip():
                st.error("L’intitulé de l’activité est obligatoire.")
            elif end_date < start_date:
                st.error("La date de fin ne peut pas être antérieure à la date de début.")
            else:
                with get_conn() as conn:
                    cur = conn.execute("""
                        INSERT INTO training_events
                        (title,activity_type,organizer,topic,start_date,end_date,location,format,
                         participation_status,certificate_status,hours,cost,currency,link,document_name,notes,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        title.strip(), activity_type, organizer.strip(), topic.strip(),
                        start_date.isoformat(), end_date.isoformat(), location.strip(), fmt,
                        participation_status, certificate_status, float(hours), float(cost), currency,
                        link.strip(), document_name.strip(), notes.strip(),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    event_id = cur.lastrowid
                log_action("Ajout formation / séminaire", "training_event", event_id)
                st.success("Activité professionnelle enregistrée.")
                st.rerun()

    with sub_list:
        search_training = st.text_input("Rechercher par intitulé, organisateur, thème ou lieu")
        training_df = read_df("""
            SELECT id AS ID, title AS Intitulé, activity_type AS Type, topic AS Thématique,
                   organizer AS Organisateur, start_date AS Début, end_date AS Fin,
                   location AS Lieu, format AS Format, participation_status AS Statut,
                   certificate_status AS Attestation, hours AS Heures, cost AS Coût,
                   currency AS Devise, link AS Lien, document_name AS Document, notes AS Notes
            FROM training_events
            WHERE title LIKE ? OR organizer LIKE ? OR topic LIKE ? OR location LIKE ?
            ORDER BY start_date DESC, id DESC
        """, tuple([f"%{search_training}%"] * 4))
        render_table(training_df)
        if not training_df.empty:
            event_options = {
                f"#{int(r['ID'])} · {r['Intitulé']} · {r['Début']}": int(r["ID"])
                for _, r in training_df.iterrows()
            }
            selected_event_label = st.selectbox("Sélectionner une activité à mettre à jour", list(event_options.keys()))
            selected_event_id = event_options[selected_event_label]
            u1, u2 = st.columns(2)
            with u1:
                new_participation_status = st.selectbox(
                    "Mettre à jour le statut",
                    ["Prévu", "Inscription en cours", "Inscrite", "En cours", "Terminé", "Annulé"],
                    key="training_status_update"
                )
            with u2:
                new_certificate_status = st.selectbox(
                    "Statut de l’attestation",
                    ["Non applicable", "À demander", "En attente", "Reçu"],
                    key="training_certificate_update"
                )
            if st.button("Mettre à jour cette activité", type="primary"):
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE training_events SET participation_status=?, certificate_status=? WHERE id=?",
                        (new_participation_status, new_certificate_status, selected_event_id)
                    )
                log_action("Mise à jour formation / séminaire", "training_event", selected_event_id)
                st.success("Activité mise à jour.")
                st.rerun()
            st.download_button(
                "⬇️ Exporter le parcours en CSV",
                data=training_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="antacare_formations_seminaires.csv",
                mime="text/csv"
            )

    with sub_stats:
        all_training = read_df("SELECT * FROM training_events")
        now_month = date.today().strftime("%Y-%m")
        total = len(all_training)
        done = int((all_training["participation_status"] == "Terminé").sum()) if total else 0
        planned = int(all_training["participation_status"].isin(["Prévu", "Inscription en cours", "Inscrite"]).sum()) if total else 0
        hours_total = float(all_training["hours"].fillna(0).sum()) if total else 0.0
        cost_total = float(all_training["cost"].fillna(0).sum()) if total else 0.0
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Activités enregistrées", total)
        k2.metric("Terminées", done)
        k3.metric("Prévues / inscriptions", planned)
        k4.metric("Heures de formation", f"{hours_total:g} h")
        st.metric("Coût total déclaré", f"{cost_total:,.0f} " + (all_training["currency"].iloc[0] if total and all_training["currency"].nunique() == 1 else "unités / devises mixtes"))
        if total:
            st.markdown("#### Répartition par type")
            type_counts = all_training.groupby("activity_type").size().reset_index(name="Nombre").sort_values("Nombre", ascending=False)
            st.bar_chart(type_counts.set_index("activity_type"))
            st.markdown("#### Attestations à suivre")
            pending = all_training[all_training["certificate_status"].isin(["À demander", "En attente"])]
            render_table(pending[["title", "organizer", "end_date", "certificate_status"]].rename(columns={
                "title": "Activité", "organizer": "Organisateur", "end_date": "Date de fin", "certificate_status": "Attestation"
            }), "Aucune attestation en attente.")
        else:
            st.info("Aucune formation enregistrée. Utilisez « Ajouter une activité » pour commencer.")


# ---------------------- Reports ----------------------
with tabs[9]:
    st.markdown('<div class="section-title">Centre de rapports & documents</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="hero" style="padding:20px 24px;animation:none;">
      <div class="eyebrow">Bibliothèque documentaire</div>
      <h2 style="font-family:'Playfair Display',serif;margin:.25rem 0;color:#27464b;">Un rapport clair pour chaque unité</h2>
      <p>Consultez, filtrez et téléchargez séparément chaque sous-rapport en PDF, Excel ou CSV. Les PDF comprennent une mise en page professionnelle, un tableau paginé et un pied de page.</p>
    </div>
    """, unsafe_allow_html=True)
    report_date = st.date_input("Période de référence — choisissez une date dans le mois", value=date.today(), key="report_month")
    month_key = report_date.strftime("%Y-%m")
    report_tabs = st.tabs(["📌 Vue générale", "👩🏽‍⚕️ Patientes", "🤰 Grossesses", "🩺 Consultations", "📅 Rendez-vous", "👶 Post-partum", "🩸 Planification familiale", "🎓 Formations", "📚 Éducation sanitaire"])

    # 1. Overview / monthly report
    with report_tabs[0]:
        p_total = read_df("SELECT COUNT(*) AS n FROM patients").iloc[0]["n"]
        v_month = read_df("SELECT * FROM visits WHERE substr(visit_date,1,7)=?", (month_key,))
        a_month = read_df("SELECT status AS Statut, COUNT(*) AS Nombre FROM appointments WHERE substr(appointment_date,1,7)=? GROUP BY status", (month_key,))
        t_month = read_df("SELECT * FROM training_events WHERE substr(COALESCE(start_date,''),1,7)=? OR substr(COALESCE(end_date,''),1,7)=?", (month_key, month_key))
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Dossiers patientes", int(p_total))
        m2.metric("Consultations du mois", len(v_month))
        m3.metric("Rendez-vous du mois", int(read_df("SELECT COUNT(*) AS n FROM appointments WHERE substr(appointment_date,1,7)=?", (month_key,)).iloc[0]["n"]))
        m4.metric("Formations du mois", len(t_month))
        st.markdown("#### Rendez-vous par statut")
        render_table(a_month, "Aucun rendez-vous enregistré pour ce mois.")
        summary_rows = [{"Indicateur":"Période", "Valeur":month_key}, {"Indicateur":"Dossiers patientes au total", "Valeur":int(p_total)}, {"Indicateur":"Consultations du mois", "Valeur":len(v_month)}, {"Indicateur":"Formations / séminaires du mois", "Valeur":len(t_month)}]
        summary_df = pd.DataFrame(summary_rows)
        render_report_downloads(summary_df, "Rapport mensuel d’activité — Synthèse", f"Anta Dièye · {month_key}", f"synthese_{month_key}")

    with report_tabs[1]:
        df = read_df("SELECT patient_code AS 'Code dossier', last_name AS Nom, first_name AS Prénom, birth_date AS 'Date de naissance', phone AS Téléphone, locality AS Localité, emergency_contact AS 'Contact d’urgence', created_at AS 'Date de création' FROM patients ORDER BY last_name, first_name")
        search = st.text_input("Rechercher une patiente par code, nom ou localité", key="rpt_patient_search")
        if search.strip():
            mask = df.astype(str).apply(lambda col: col.str.contains(search.strip(), case=False, na=False)).any(axis=1)
            df = df[mask]
        render_table(df)
        render_report_downloads(df, "Registre des dossiers patientes", "Liste des dossiers enregistrés", "patientes")

    with report_tabs[2]:
        df = read_df("""SELECT p.patient_code AS 'Code dossier', p.last_name AS Nom, p.first_name AS Prénom, g.lmp_date AS 'Dernières règles', g.edd_date AS 'Date prévue accouchement', g.edd_method AS 'Méthode de datation', g.gravida AS Gestité, g.para AS Parité, g.risk_notes AS 'Notes de suivi', g.created_at AS 'Créé le' FROM pregnancies g JOIN patients p ON p.id=g.patient_id ORDER BY g.created_at DESC""")
        render_table(df)
        render_report_downloads(df, "Registre de suivi des grossesses", "Suivi prénatal — données enregistrées", "grossesses")

    with report_tabs[3]:
        df = read_df("""SELECT v.visit_date AS Date, p.patient_code AS 'Code dossier', p.last_name AS Nom, p.first_name AS Prénom, v.visit_type AS Type, v.reason AS Motif, v.observations AS Observations, v.examinations AS Examens, v.next_visit AS 'Prochain rendez-vous', v.referral AS Orientation FROM visits v JOIN patients p ON p.id=v.patient_id WHERE substr(v.visit_date,1,7)=? ORDER BY v.visit_date DESC""", (month_key,))
        render_table(df)
        render_report_downloads(df, "Registre des consultations", f"Période : {month_key}", f"consultations_{month_key}")

    with report_tabs[4]:
        df = read_df("""SELECT a.appointment_date AS Date, p.patient_code AS 'Code dossier', p.last_name AS Nom, p.first_name AS Prénom, a.reason AS Motif, a.status AS Statut, a.notes AS Notes FROM appointments a JOIN patients p ON p.id=a.patient_id WHERE substr(a.appointment_date,1,7)=? ORDER BY a.appointment_date""", (month_key,))
        render_table(df)
        render_report_downloads(df, "Agenda et registre des rendez-vous", f"Période : {month_key}", f"rendez_vous_{month_key}")

    with report_tabs[5]:
        df = read_df("""SELECT p.patient_code AS 'Code dossier', p.last_name AS Nom, p.first_name AS Prénom, x.delivery_date AS 'Date accouchement', x.delivery_place AS 'Lieu accouchement', x.mother_followup AS 'Suivi mère', x.newborn_followup AS 'Suivi nouveau-né', x.next_checkup AS 'Prochain contrôle', x.notes AS Notes FROM postpartum x JOIN patients p ON p.id=x.patient_id ORDER BY x.delivery_date DESC""")
        render_table(df)
        render_report_downloads(df, "Suivi post-partum et nouveau-né", "Registre postnatal", "postpartum_nouveau_ne")

    with report_tabs[6]:
        df = read_df("""SELECT p.patient_code AS 'Code dossier', p.last_name AS Nom, p.first_name AS Prénom, f.consultation_date AS Date, f.method_discussed AS 'Méthode abordée', f.informed_choice AS 'Choix éclairé', f.followup_date AS 'Date de suivi', f.reported_effects AS 'Effets rapportés', f.notes AS Notes FROM family_planning f JOIN patients p ON p.id=f.patient_id ORDER BY f.consultation_date DESC""")
        render_table(df)
        render_report_downloads(df, "Registre de planification familiale", "Suivi et information", "planification_familiale")

    with report_tabs[7]:
        df = read_df("""SELECT title AS Intitulé, activity_type AS Type, topic AS Thématique, organizer AS Organisateur, start_date AS 'Date début', end_date AS 'Date fin', location AS Lieu, format AS Format, participation_status AS Participation, certificate_status AS Attestation, hours AS Heures, cost AS Coût, currency AS Devise, link AS Lien, document_name AS 'Document référencé', notes AS Notes FROM training_events ORDER BY start_date DESC""")
        render_table(df)
        render_report_downloads(df, "Formations, séminaires et développement professionnel", "Parcours de formation continue", "formations_seminaires")

    with report_tabs[8]:
        education_items = [
            {"Thème": title, "Langue": content[0], "Contenu": content[1], "Validation": "À valider selon les recommandations sanitaires nationales avant diffusion"}
            for title, content in themes.items()
        ]
        df = pd.DataFrame(education_items)
        render_table(df)
        render_report_downloads(df, "Bibliothèque d’éducation sanitaire", "Fiches générales — à valider avant diffusion", "education_sanitaire")

    st.warning("Confidentialité : les rapports peuvent contenir des informations sensibles. Téléchargez-les uniquement sur un appareil de confiance et ne les partagez qu’avec les personnes autorisées. ANTACARE reste un prototype local qui nécessite une validation de sécurité avant tout usage clinique réel.")

# ---------------------- Settings ----------------------
with tabs[10]:
    st.markdown('<div class="section-title">Paramètres et sécurité</div>', unsafe_allow_html=True)
    st.warning("Base distante : vérifiez les sauvegardes, les droits d’accès et la conformité avant tout usage clinique réel.")
    st.markdown("#### Modifier le mot de passe")
    with st.form("password_change_form"):
        current = st.text_input("Mot de passe actuel", type="password")
        new1 = st.text_input("Nouveau mot de passe (12 caractères minimum)", type="password")
        new2 = st.text_input("Confirmer le nouveau mot de passe", type="password")
        change = st.form_submit_button("Changer le mot de passe")
    if change:
        if not verify_password(st.session_state.username, current):
            st.error("Le mot de passe actuel est incorrect.")
        elif len(new1) < 12:
            st.error("Choisissez un mot de passe d’au moins 12 caractères.")
        elif new1 != new2:
            st.error("Les deux nouveaux mots de passe ne correspondent pas.")
        else:
            change_password(st.session_state.username, new1)
            st.success("Mot de passe modifié.")
    st.markdown("#### Journal des opérations")
    audit = read_df("SELECT occurred_at AS Date,username AS Utilisateur,action AS Action,object_type AS Objet,object_id AS 'ID objet' FROM audit_log ORDER BY id DESC LIMIT 100")
    render_table(audit)
    st.markdown("#### Base de données et sauvegardes")
    st.write("Stockage : Supabase PostgreSQL (connexion chiffrée TLS vérifiée).")
    st.write(f"Dossier des exports : `{EXPORT_DIR}`")
    st.info("Les sauvegardes de la base distante se configurent dans Supabase (sauvegardes/PITR selon votre offre). Les exports PDF/Excel/CSV ne sont pas une sauvegarde complète de la base.")

st.markdown("---")
st.markdown('<p class="small-note">ANTACARE · PostgreSQL Supabase · Données confidentielles : accès restreint, sauvegardes vérifiées et exports protégés.</p>', unsafe_allow_html=True)
