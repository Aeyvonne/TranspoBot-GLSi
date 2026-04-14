"""
TranspoBot — Backend FastAPI complet
Projet GLSi L3 — ESP/UCAD
Equipe : M1 Arame Yvonne, M2 Ndeye Khady, M3 Aminata Ndiaye, M4 Ndeye Maty, M5 Mame Dior
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv
import mysql.connector
import os
import re
import json
import httpx

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

LLM_API_KEY  = os.getenv("OPENAI_API_KEY", "ollama")
LLM_MODEL    = os.getenv("LLM_MODEL", "llama3")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")

# ── Schéma de la base ─────────────────────────────────────────
DB_SCHEMA = """
Tables MySQL disponibles :

vehicules(id, immatriculation, type[bus/minibus/taxi], capacite, statut[actif/maintenance/hors_service], kilometrage, date_acquisition)
chauffeurs(id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite, vehicule_id, date_embauche)
lignes(id, code, nom, origine, destination, distance_km, duree_minutes)
tarifs(id, ligne_id, type_client[normal/etudiant/senior], prix)
trajets(id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut[planifie/en_cours/termine/annule], nb_passagers, recette)
incidents(id, trajet_id, type[panne/accident/retard/autre], description, gravite[faible/moyen/grave], date_incident, resolu)

RELATIONS IMPORTANTES :
- incidents N'A PAS de chauffeur_id direct. Passer par : incidents -> trajets -> chauffeurs
- incidents N'A PAS de vehicule_id direct. Passer par : incidents -> trajets -> vehicules
- chauffeurs.vehicule_id -> vehicules.id
- trajets.chauffeur_id -> chauffeurs.id
- trajets.vehicule_id -> vehicules.id
- trajets.ligne_id -> lignes.id
- incidents.trajet_id -> trajets.id
"""

SYSTEM_PROMPT = f"""Tu es TranspoBot, l'assistant IA d'une compagnie de transport urbain au Sénégal.
Tu aides les gestionnaires à interroger la base de données en langage naturel (français ou anglais).

{DB_SCHEMA}

RÈGLES ABSOLUES :
1. Génère UNIQUEMENT des requêtes SELECT. INSERT, UPDATE, DELETE, DROP, ALTER sont INTERDITS.
2. Réponds TOUJOURS avec un objet JSON valide, rien d'autre. Pas de texte avant, pas de markdown.
   Format obligatoire :
   {{"sql": "SELECT ...", "explication": "Réponse claire en français"}}
3. Si la question est impossible à traduire en SQL :
   {{"sql": null, "explication": "Je ne peux pas répondre à cette question avec les données disponibles."}}
4. Utilise des alias lisibles. Exemple : COUNT(*) AS nb_trajets.
5. Ajoute LIMIT 100 à toutes les requêtes sauf si un nombre précis est demandé.
6. Pour les périodes :
   - "cette semaine" = WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
   - "ce mois" = WHERE MONTH(date_heure_depart) = MONTH(NOW())
   - "aujourd'hui" = WHERE DATE(date_heure_depart) = CURDATE()
7. L'explication doit être une réponse directe au gestionnaire.
   BON : "3 véhicules sont actifs en ce moment."
   MAUVAIS : "La requête compte les véhicules dont le statut est actif."
"""

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

def is_safe_sql(sql: str) -> bool:
    sql_clean = sql.strip().upper()
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC"]
    if not sql_clean.startswith("SELECT"):
        return False
    for word in forbidden:
        if word in sql_clean:
            return False
    return True

# ══════════════════════════════════════════════════════════════
#  APPEL LLM
# ══════════════════════════════════════════════════════════════

async def ask_llm(question: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": question},
                ],
                "temperature": 0,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Réponse LLM non parseable : {content[:200]}")

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
        "llm_model": LLM_MODEL,
    }

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    sql = None
    try:
        llm_response = await ask_llm(msg.question)
        sql = llm_response.get("sql")
        explication = llm_response.get("explication", "")

        if not sql:
            return JSONResponse(content={"answer": explication, "data": [], "sql": None})

        if not is_safe_sql(sql):
            return JSONResponse(content={"answer": "Requête refusée pour des raisons de sécurité.", "data": [], "sql": sql})

        data = execute_query(sql)
        return JSONResponse(content={"answer": explication, "data": data, "sql": sql, "count": len(data)})

    except ValueError:
        return JSONResponse(content={"answer": "Je n'ai pas pu interpréter la réponse du LLM. Reformulez votre question.", "data": [], "sql": None})
    except mysql.connector.Error:
        return JSONResponse(content={"answer": "La requête SQL générée est invalide. Reformulez votre question.", "data": [], "sql": sql})
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama n'est pas accessible. Vérifiez qu'il tourne avec 'ollama serve'.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

# ── Servir le frontend ────────────────────────────────────────
if os.path.exists("index.html"):
    @app.get("/")
    def serve_frontend():
        return FileResponse("index.html")

# ── Lancement ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
