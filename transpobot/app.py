
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv
import mysql.connector
import os

load_dotenv()

app = FastAPI(title="TranspoBot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ──────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "transpobot"),
}

# ══════════════════════════════════════════════════════════════
#  CONNEXION & UTILITAIRES
# ══════════════════════════════════════════════════════════════

def get_db():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"Erreur connexion DB : {str(e)}")

def execute_query(sql: str, params: tuple = ()):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"Erreur SQL : {str(e)}")
    finally:
        cursor.close()
        conn.close()

def execute_write(sql: str, params: tuple = ()):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        conn.commit()
        return cursor.lastrowid, cursor.rowcount
    except mysql.connector.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur SQL : {str(e)}")
    finally:
        cursor.close()
        conn.close()

# ══════════════════════════════════════════════════════════════
#  MODÈLES PYDANTIC
# ══════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)

class IncidentCreate(BaseModel):
    trajet_id: int
    type: str = Field(..., pattern="^(panne|accident|retard|autre)$")
    description: Optional[str] = ""
    gravite: str = Field("faible", pattern="^(faible|moyen|grave)$")

# ══════════════════════════════════════════════════════════════
#  ROUTES API
# ══════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    try:
        conn = get_db()
        conn.close()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {
        "status": "ok",
        "app": "TranspoBot",
        "version": "1.0.0",
        "database": db_status,
    }

@app.post("/api/chat")
def chat(msg: ChatMessage):
    return {
        "answer": "Le module LLM (Text-to-SQL) n'est pas encore intégré. En attente de la branche feature/llm.",
        "data": [],
        "sql": None,
    }

@app.get("/api/stats")
def get_stats():
    queries = {
        "total_trajets":    "SELECT COUNT(*) as n FROM trajets WHERE statut='termine'",
        "trajets_en_cours": "SELECT COUNT(*) as n FROM trajets WHERE statut='en_cours'",
        "vehicules_actifs": "SELECT COUNT(*) as n FROM vehicules WHERE statut='actif'",
        "incidents_ouverts":"SELECT COUNT(*) as n FROM incidents WHERE resolu=FALSE",
        "recette_totale":   "SELECT COALESCE(SUM(recette),0) as n FROM trajets WHERE statut='termine'",
        "total_chauffeurs": "SELECT COUNT(*) as n FROM chauffeurs WHERE disponibilite=TRUE",
    }
    stats = {}
    for key, sql in queries.items():
        result = execute_query(sql)
        stats[key] = result[0]["n"] if result else 0
    return stats

@app.get("/api/stats/recettes-par-ligne")
def get_recettes_par_ligne():
    return execute_query("""
        SELECT l.code, l.nom, l.origine, l.destination,
               COUNT(t.id) AS nb_trajets,
               COALESCE(SUM(t.recette), 0) AS recette_totale,
               COALESCE(AVG(t.nb_passagers), 0) AS moy_passagers
        FROM lignes l
        LEFT JOIN trajets t ON l.id = t.ligne_id AND t.statut = 'termine'
        GROUP BY l.id, l.code, l.nom, l.origine, l.destination
        ORDER BY recette_totale DESC
    """)

@app.get("/api/vehicules")
def get_vehicules():
    return execute_query("SELECT * FROM vehicules ORDER BY immatriculation")

@app.get("/api/vehicules/{vehicule_id}")
def get_vehicule(vehicule_id: int):
    result = execute_query("SELECT * FROM vehicules WHERE id = %s", (vehicule_id,))
    if not result:
        raise HTTPException(status_code=404, detail="Vehicule non trouve")
    return result[0]

@app.get("/api/chauffeurs")
def get_chauffeurs():
    return execute_query("""
        SELECT c.*, v.immatriculation, v.type AS vehicule_type
        FROM chauffeurs c
        LEFT JOIN vehicules v ON c.vehicule_id = v.id
        ORDER BY c.nom
    """)

@app.get("/api/chauffeurs/{chauffeur_id}")
def get_chauffeur(chauffeur_id: int):
    result = execute_query("""
        SELECT c.*, v.immatriculation, v.type AS vehicule_type
        FROM chauffeurs c
        LEFT JOIN vehicules v ON c.vehicule_id = v.id
        WHERE c.id = %s
    """, (chauffeur_id,))
    if not result:
        raise HTTPException(status_code=404, detail="Chauffeur non trouve")
    return result[0]

@app.get("/api/lignes")
def get_lignes():
    return execute_query("""
        SELECT l.*, COUNT(DISTINCT t.id) AS nb_trajets_total
        FROM lignes l
        LEFT JOIN trajets t ON l.id = t.ligne_id
        GROUP BY l.id
        ORDER BY l.code
    """)

@app.get("/api/trajets/recent")
def get_trajets_recent():
    return execute_query("""
        SELECT t.*,
               l.nom AS ligne, l.code AS ligne_code,
               ch.nom AS chauffeur_nom, ch.prenom AS chauffeur_prenom,
               v.immatriculation
        FROM trajets t
        JOIN lignes     l  ON t.ligne_id     = l.id
        JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        JOIN vehicules  v  ON t.vehicule_id  = v.id
        ORDER BY t.date_heure_depart DESC
        LIMIT 20
    """)

@app.get("/api/incidents/recent")
def get_incidents_recent():
    return execute_query("""
        SELECT i.*,
               ch.nom AS chauffeur_nom, ch.prenom AS chauffeur_prenom,
               v.immatriculation, l.nom AS ligne_nom
        FROM incidents i
        JOIN trajets    t  ON i.trajet_id    = t.id
        JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        JOIN vehicules  v  ON t.vehicule_id  = v.id
        JOIN lignes     l  ON t.ligne_id     = l.id
        ORDER BY i.date_incident DESC
        LIMIT 20
    """)

@app.post("/api/incidents")
def create_incident(data: IncidentCreate):
    lastrowid, _ = execute_write(
        "INSERT INTO incidents (trajet_id, type, description, gravite, date_incident, resolu) VALUES (%s, %s, %s, %s, NOW(), FALSE)",
        (data.trajet_id, data.type, data.description, data.gravite)
    )
    return {"success": True, "id": lastrowid}

@app.patch("/api/incidents/{incident_id}/resoudre")
def resoudre_incident(incident_id: int):
    _, rowcount = execute_write("UPDATE incidents SET resolu = TRUE WHERE id = %s", (incident_id,))
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="Incident non trouve")
    return {"success": True}

# ── Servir le frontend si index.html présent ─────────────────
if os.path.exists("index.html"):
    from fastapi.responses import FileResponse
    @app.get("/")
    def serve_frontend():
        return FileResponse("index.html")

# ── Lancement ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
