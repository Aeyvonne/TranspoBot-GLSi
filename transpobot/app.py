"""
TranspoBot — Backend FastAPI
Projet GLSi L3 — ESP/UCAD
Configuré pour Ollama (LLaMA3) en local
"""

# ── AJOUT 1 : charger le fichier .env automatiquement ──────────
from dotenv import load_dotenv
load_dotenv()
# ───────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
import os
import re
import json
import httpx

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

LLM_API_KEY  = os.getenv("OPENAI_API_KEY", "ollama")   # "ollama" par défaut
LLM_MODEL    = os.getenv("LLM_MODEL", "llama3.2")       # MODIFIÉ : llama3.2
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")  # MODIFIÉ : Ollama

# ── Schéma de la base (pour le prompt système) ─────────────────
DB_SCHEMA = """
Tables MySQL disponibles :

vehicules(id, immatriculation, type[bus/minibus/taxi], capacite, statut[actif/maintenance/hors_service], kilometrage, date_acquisition)
chauffeurs(id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite, vehicule_id, date_embauche)
lignes(id, code, nom, origine, destination, distance_km, duree_minutes)
tarifs(id, ligne_id, type_client[normal/etudiant/senior], prix)
trajets(id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut[planifie/en_cours/termine/annule], nb_passagers, recette)
incidents(id, trajet_id, type[panne/accident/retard/autre], description, gravite[faible/moyen/grave], date_incident, resolu)
"""

# ── AJOUT 2 : Prompt amélioré pour LLaMA (plus explicite) ──────
SYSTEM_PROMPT = f"""Tu es TranspoBot, l'assistant IA d'une compagnie de transport urbain au Sénégal.
Tu aides les gestionnaires à interroger la base de données en langage naturel (français ou anglais).

{DB_SCHEMA}

RÈGLES ABSOLUES — Tu dois les respecter à chaque réponse :

1. Génère UNIQUEMENT des requêtes SELECT. Les commandes INSERT, UPDATE, DELETE, DROP, ALTER sont STRICTEMENT INTERDITES.

2. Réponds TOUJOURS avec un objet JSON valide, rien d'autre. Pas de texte avant, pas de texte après, pas de markdown, pas de ```json```.
    Format obligatoire :
    {{"sql": "SELECT ...", "explication": "Réponse claire en français pour le gestionnaire"}}

3. Si la question est hors base de données ou impossible à traduire en SQL, réponds exactement :
    {{"sql": null, "explication": "Je ne peux pas répondre à cette question avec les données disponibles."}}

4. Utilise des alias lisibles. Exemple : COUNT(*) AS nb_trajets, SUM(recette) AS recette_totale.

5. Ajoute LIMIT 100 à toutes les requêtes sauf si un nombre précis est demandé.

6. Pour les périodes :
    - "cette semaine" = WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
    - "ce mois" = WHERE MONTH(date_heure_depart) = MONTH(NOW())
    - "aujourd'hui" = WHERE DATE(date_heure_depart) = CURDATE()

7. L'explication doit être une réponse directe au gestionnaire, pas une description de la requête.
    BON : "3 véhicules sont actifs en ce moment."
    MAUVAIS : "La requête compte les véhicules dont le statut est actif."

RAPPEL : Réponds UNIQUEMENT avec le JSON. Aucun autre texte.
"""
# ───────────────────────────────────────────────────────────────

# ── Connexion MySQL ────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def execute_query(sql: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

# ── AJOUT 3 : Sécurité — bloquer tout ce qui n'est pas SELECT ──
def is_safe_sql(sql: str) -> bool:
    """Vérifie que la requête est bien un SELECT et rien d'autre."""
    sql_clean = sql.strip().upper()
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC"]
    if not sql_clean.startswith("SELECT"):
        return False
    for word in forbidden:
        if word in sql_clean:
            return False
    return True
# ───────────────────────────────────────────────────────────────

# ── Appel LLM ─────────────────────────────────────────────────
async def ask_llm(question: str) -> dict:
    # MODIFIÉ : timeout augmenté à 60s car Ollama local est plus lent qu'OpenAI
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
            timeout=60,  # MODIFIÉ : 60s au lieu de 30s pour Ollama
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]

        # MODIFIÉ : extraction JSON plus robuste pour LLaMA
        # LLaMA peut ajouter du texte avant/après le JSON
        content = content.strip()

        # Supprimer les blocs markdown si LLaMA en génère
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)

        # Extraire le premier objet JSON trouvé
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Réponse LLM non parseable : {content[:200]}")

# ── Routes API ─────────────────────────────────────────────────
class ChatMessage(BaseModel):
    question: str

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    """Point d'entrée principal : question → SQL → résultats"""
    from fastapi.responses import JSONResponse
    sql = None
    try:
        llm_response = await ask_llm(msg.question)
        sql = llm_response.get("sql")
        explication = llm_response.get("explication", "")

        if not sql:
            return JSONResponse(
                content={"answer": explication, "data": [], "sql": None},
                media_type="application/json; charset=utf-8"
            )

        # Vérification sécurité avant exécution
        if not is_safe_sql(sql):
            return JSONResponse(
                content={
                    "answer": "Requête refusée pour des raisons de sécurité (opération non autorisée).",
                    "data": [],
                    "sql": sql
                },
                media_type="application/json; charset=utf-8"
            )

        data = execute_query(sql)
        return JSONResponse(
            content={
                "answer": explication,
                "data": data,
                "sql": sql,
                "count": len(data),
            },
            media_type="application/json; charset=utf-8"
        )

    except ValueError:
        return JSONResponse(
            content={
                "answer": "Je n'ai pas pu interpréter la réponse du LLM. Essayez de reformuler votre question.",
                "data": [],
                "sql": None
            },
            media_type="application/json; charset=utf-8"
        )
    except mysql.connector.Error:
        return JSONResponse(
            content={
                "answer": "La requête SQL générée est invalide. Essayez de reformuler votre question.",
                "data": [],
                "sql": sql
            },
            media_type="application/json; charset=utf-8"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama n'est pas accessible. Vérifiez qu'il tourne avec 'ollama serve'."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/stats")
def get_stats():
    """Tableau de bord — statistiques rapides"""
    stats = {}
    queries = {
        "total_trajets":     "SELECT COUNT(*) as n FROM trajets WHERE statut='termine'",
        "trajets_en_cours":  "SELECT COUNT(*) as n FROM trajets WHERE statut='en_cours'",
        "vehicules_actifs":  "SELECT COUNT(*) as n FROM vehicules WHERE statut='actif'",
        "incidents_ouverts": "SELECT COUNT(*) as n FROM incidents WHERE resolu=FALSE",
        "recette_totale":    "SELECT COALESCE(SUM(recette),0) as n FROM trajets WHERE statut='termine'",
    }
    for key, sql in queries.items():
        result = execute_query(sql)
        stats[key] = result[0]["n"] if result else 0
    return stats


@app.get("/api/vehicules")
def get_vehicules():
    return execute_query("SELECT * FROM vehicules ORDER BY immatriculation")

@app.get("/api/chauffeurs")
def get_chauffeurs():
    return execute_query("""
        SELECT c.*, v.immatriculation
        FROM chauffeurs c
        LEFT JOIN vehicules v ON c.vehicule_id = v.id
        ORDER BY c.nom
    """)

@app.get("/api/trajets/recent")
def get_trajets_recent():
    return execute_query("""
        SELECT t.*, l.nom as ligne, ch.nom as chauffeur_nom, v.immatriculation
        FROM trajets t
        JOIN lignes l ON t.ligne_id = l.id
        JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        JOIN vehicules v ON t.vehicule_id = v.id
        ORDER BY t.date_heure_depart DESC
        LIMIT 20
    """)

@app.get("/health")
def health():
    return {"status": "ok", "app": "TranspoBot", "llm": LLM_MODEL}

# ── Lancement ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)