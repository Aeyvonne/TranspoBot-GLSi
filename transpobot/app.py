"""
TranspoBot — Backend FastAPI complet + IA avancée
Projet GLSi L3 — ESP/UCAD
Equipe : M1 Arame Yvonne, M2 Ndeye Khady, M3 Aminata Ndiaye, M4 Ndeye Maty, M5 Mame Dior
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, cast
from dotenv import load_dotenv
import mysql.connector
import os
import re
import json
import httpx

load_dotenv()

app = FastAPI(title="TranspoBot API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ──────────────────────────────────────────────
DB_CONFIG = {
   
    "host":     os.getenv("DB_HOST", "localhost"),
     "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "transpobot"),
}

LLM_API_KEY  = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")

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
7. L'explication doit être une réponse directe au gestionnaire avec les chiffres clés.
   BON : "Il y a 6 véhicules actifs en ce moment."
   BON : "Mamadou DIOP est le chauffeur avec le plus de recettes : 387 500 FCFA."
   MAUVAIS : "Voici les chauffeurs disponibles."
   MAUVAIS : "La requête compte les véhicules dont le statut est actif."
8. Si la question demande une liste, résume en une phrase le nombre total trouvé.
   Exemple : "8 chauffeurs sont disponibles en ce moment."
"""

# ══════════════════════════════════════════════════════════════
#  CONNEXION & UTILITAIRES
# ══════════════════════════════════════════════════════════════

def get_db():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"Erreur connexion DB : {str(e)}")

def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        for row in rows:
            for key, val in row.items():
                if hasattr(val, 'isoformat'):
                    row[key] = val.isoformat()
                elif hasattr(val, '__float__') and not isinstance(val, (int, float, bool)):
                    row[key] = float(val)
        return rows
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
#  APPEL LLM (générique)
# ══════════════════════════════════════════════════════════════

async def ask_llm(question: str) -> dict:
    """Appel LLM pour le chatbot SQL — retourne {sql, explication}."""
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


async def ask_llm_libre(system: str, user: str) -> str:
    """Appel LLM libre — retourne du texte brut (résumé, conseil, etc.)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "temperature": 0.4,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

# ══════════════════════════════════════════════════════════════
#  COLLECTE DE DONNÉES POUR L'IA
# ══════════════════════════════════════════════════════════════

def collecter_donnees_situation() -> dict:
    """Collecte toutes les données pertinentes pour les résumés / alertes IA."""

    trajets_semaine = execute_query("""
        SELECT COUNT(*) AS n FROM trajets
        WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
    """)[0]["n"]

    incidents_graves_ouverts = execute_query("""
        SELECT i.id, i.type, i.description, i.date_incident,
               v.immatriculation, ch.nom, ch.prenom
        FROM incidents i
        JOIN trajets t ON i.trajet_id = t.id
        JOIN vehicules v ON t.vehicule_id = v.id
        JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        WHERE i.resolu = FALSE AND i.gravite = 'grave'
        ORDER BY i.date_incident DESC
        LIMIT 10
    """)

    tous_incidents_ouverts = execute_query("""
        SELECT COUNT(*) AS n FROM incidents WHERE resolu = FALSE
    """)[0]["n"]

    vehicules_maintenance = execute_query("""
        SELECT id, immatriculation, statut, kilometrage,
               DATEDIFF(NOW(), date_acquisition) AS jours_depuis_acquisition
        FROM vehicules
        WHERE statut IN ('maintenance', 'hors_service')
    """)

    # Durée en maintenance estimée via dernier trajet
    vehicules_maintenance_detail = []
    for v in vehicules_maintenance:
        dernier_trajet = execute_query("""
            SELECT MAX(date_heure_arrivee) AS dernier
            FROM trajets WHERE vehicule_id = %s
        """, (v["id"],))
        dernier = dernier_trajet[0]["dernier"] if dernier_trajet else None
        vehicules_maintenance_detail.append({
            **v,
            "dernier_trajet": str(dernier) if dernier else "inconnu"
        })

    recette_semaine = execute_query("""
        SELECT COALESCE(SUM(recette), 0) AS total
        FROM trajets
        WHERE statut = 'termine'
          AND date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
    """)[0]["total"]

    recette_semaine_precedente = execute_query("""
        SELECT COALESCE(SUM(recette), 0) AS total
        FROM trajets
        WHERE statut = 'termine'
          AND date_heure_depart >= DATE_SUB(NOW(), INTERVAL 14 DAY)
          AND date_heure_depart < DATE_SUB(NOW(), INTERVAL 7 DAY)
    """)[0]["total"]

    chauffeurs_indisponibles = execute_query("""
        SELECT COUNT(*) AS n FROM chauffeurs WHERE disponibilite = FALSE
    """)[0]["n"]

    total_chauffeurs = execute_query(
        "SELECT COUNT(*) AS n FROM chauffeurs"
    )[0]["n"]

    lignes_actives = execute_query("""
        SELECT l.code, l.nom, COUNT(t.id) AS nb_trajets_semaine
        FROM lignes l
        LEFT JOIN trajets t ON l.id = t.ligne_id
            AND t.date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY l.id, l.code, l.nom
        ORDER BY nb_trajets_semaine DESC
        LIMIT 5
    """)

    taux_ponctualite = execute_query("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN TIMESTAMPDIFF(MINUTE, date_heure_arrivee,
                ADDTIME(date_heure_depart, SEC_TO_TIME(l.duree_minutes*60))) <= 5
                THEN 1 ELSE 0 END) AS a_lheure
        FROM trajets t
        JOIN lignes l ON t.ligne_id = l.id
        WHERE t.statut = 'termine'
          AND t.date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
          AND t.date_heure_arrivee IS NOT NULL
    """)

    return {
        "trajets_semaine": trajets_semaine,
        "incidents_graves_ouverts": incidents_graves_ouverts,
        "tous_incidents_ouverts": tous_incidents_ouverts,
        "vehicules_maintenance": vehicules_maintenance_detail,
        "recette_semaine": float(recette_semaine),
        "recette_semaine_precedente": float(recette_semaine_precedente),
        "chauffeurs_indisponibles": chauffeurs_indisponibles,
        "total_chauffeurs": total_chauffeurs,
        "lignes_actives": lignes_actives,
        "taux_ponctualite": taux_ponctualite[0] if taux_ponctualite else {},
    }

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
#  ROUTES API — EXISTANTES
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
        "version": "2.0.0",
        "database": db_status,
        "llm_model": LLM_MODEL,
    }

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    sql = None
    try:
        # Détection mots-clés résumé/bilan/rapport
        question_lower = msg.question.lower()
        mots_resume = ["résumé", "resume", "bilan", "rapport", "synthèse", "synthese", "récapitulatif", "recapitulatif", "ce qui s'est passé", "ce qui s est passe"]
        if any(mot in question_lower for mot in mots_resume):
            result = await ia_resume()
            return JSONResponse(content={
                "answer": result["resume"],
                "data": [],
                "sql": None,
                "type": "resume"
            })

        # Détection mots-clés alertes
        mots_alertes = ["alerte", "anomalie", "problème", "probleme", "risque", "danger"]
        if any(mot in question_lower for mot in mots_alertes):
            result = await ia_alertes()
            return JSONResponse(content={
                "answer": f"{result['total']} alerte(s) détectée(s). Consultez le tableau de bord pour les détails.",
                "data": result["alertes"],
                "sql": None,
                "type": "alertes"
            })

        # Détection mots-clés conseils
        mots_conseils = ["conseil", "recommandation", "optimisation", "amélioration", "amelioration", "suggestion"]
        if any(mot in question_lower for mot in mots_conseils):
            result = await ia_conseils()
            return JSONResponse(content={
                "answer": f"{len(result['conseils'])} conseil(s) généré(s) pour optimiser vos opérations.",
                "data": result["conseils"],
                "sql": None,
                "type": "conseils"
            })

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
    except httpx.ReadTimeout:
        return JSONResponse(content={"answer": "Le modèle IA a mis trop de temps à répondre. Reformulez votre question plus simplement.", "data": [], "sql": None})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return JSONResponse(content={"answer": "Limite API atteinte (429). Vérifiez votre crédit OpenAI ou utilisez Ollama.", "data": [], "sql": None})
        raise HTTPException(status_code=500, detail=str(e))
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama n'est pas accessible. Vérifiez qu'il tourne avec 'ollama serve'.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
def get_stats():
    queries = {
        "total_trajets":    "SELECT COUNT(*) as n FROM trajets WHERE statut='termine'",
        "trajets_en_cours": "SELECT COUNT(*) as n FROM trajets WHERE statut='en_cours'",
        "vehicules_actifs": "SELECT COUNT(*) as n FROM vehicules WHERE statut='actif'",
        "vehicules_maintenance": "SELECT COUNT(*) as n FROM vehicules WHERE statut='maintenance'",
        "vehicules_hors_service": "SELECT COUNT(*) as n FROM vehicules WHERE statut='hors_service'",
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

# ══════════════════════════════════════════════════════════════
#  IA AVANCÉE — NOUVELLES ROUTES
# ══════════════════════════════════════════════════════════════

# ── 1. RÉSUMÉ AUTOMATIQUE DE LA SITUATION ─────────────────────
@app.get("/api/ia/resume")
async def ia_resume():
    """
    Génère un résumé narratif de la situation de la semaine.
    Le LLM reçoit les données réelles et produit un texte de briefing.
    """
    donnees = collecter_donnees_situation()

    # Calcul taux de ponctualité
    tp = donnees["taux_ponctualite"]
    if tp and tp.get("total", 0) > 0:
        ponctualite_pct = round(tp["a_lheure"] / tp["total"] * 100)
    else:
        ponctualite_pct = None

    # Variation recette
    rec_s = donnees["recette_semaine"]
    rec_prev = donnees["recette_semaine_precedente"]
    variation_recette = round(((rec_s - rec_prev) / rec_prev * 100) if rec_prev > 0 else 0, 1)

    context = f"""
Voici les données réelles de la compagnie de transport pour cette semaine :

- Trajets effectués cette semaine : {donnees['trajets_semaine']}
- Incidents graves non résolus : {len(donnees['incidents_graves_ouverts'])}
- Total incidents non résolus : {donnees['tous_incidents_ouverts']}
- Véhicules en maintenance/hors service : {len(donnees['vehicules_maintenance'])}
  Détail : {json.dumps(donnees['vehicules_maintenance'], ensure_ascii=False, default=str)}
- Recette cette semaine : {rec_s:,.0f} FCFA
- Variation vs semaine précédente : {'+' if variation_recette >= 0 else ''}{variation_recette}%
- Chauffeurs indisponibles : {donnees['chauffeurs_indisponibles']} sur {donnees['total_chauffeurs']}
- Taux de ponctualité : {f'{ponctualite_pct}%' if ponctualite_pct is not None else 'données insuffisantes'}
- Top lignes actives : {json.dumps(donnees['lignes_actives'], ensure_ascii=False)}
- Incidents graves détaillés : {json.dumps(donnees['incidents_graves_ouverts'], ensure_ascii=False, default=str)}
"""

    system = """Tu es le directeur adjoint d'une compagnie de transport urbain au Sénégal.
Tu dois rédiger un briefing hebdomadaire concis et professionnel pour le directeur général.
Format : 3 à 5 phrases. Commence par "Cette semaine :".
Mentionne les chiffres clés, les problèmes critiques et la tendance générale.
Utilise un ton factuel et direct. Langue : français."""

    try:
        resume = await ask_llm_libre(system, context)
        return {
            "resume": resume,
            "donnees": {
                "trajets_semaine": donnees["trajets_semaine"],
                "incidents_graves": len(donnees["incidents_graves_ouverts"]),
                "vehicules_maintenance": len(donnees["vehicules_maintenance"]),
                "recette_semaine": rec_s,
                "variation_recette_pct": variation_recette,
                "ponctualite_pct": ponctualite_pct,
            }
        }
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama non accessible.")


# ── 2. DÉTECTION PROACTIVE D'ANOMALIES ────────────────────────
@app.get("/api/ia/alertes")
async def ia_alertes():
    """
    Analyse les données et détecte les anomalies critiques.
    Retourne une liste d'alertes priorisées avec niveau de gravité.
    """
    donnees = collecter_donnees_situation()

    # Données supplémentaires pour l'analyse
    chauffeurs_incidents = execute_query("""
        SELECT ch.nom, ch.prenom, COUNT(i.id) AS nb_incidents
        FROM chauffeurs ch
        JOIN trajets t ON t.chauffeur_id = ch.id
        JOIN incidents i ON i.trajet_id = t.id
        WHERE i.date_incident >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY ch.id, ch.nom, ch.prenom
        HAVING nb_incidents >= 2
        ORDER BY nb_incidents DESC
        LIMIT 5
    """)

    lignes_sans_trajet = execute_query("""
        SELECT l.code, l.nom
        FROM lignes l
        LEFT JOIN trajets t ON l.id = t.ligne_id
            AND t.date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        WHERE t.id IS NULL
    """)

    vehicules_haut_km = execute_query("""
        SELECT immatriculation, kilometrage, statut
        FROM vehicules
        WHERE kilometrage > 200000 AND statut = 'actif'
        ORDER BY kilometrage DESC
        LIMIT 5
    """)

    context = f"""
Analyse ces données et identifie les anomalies et risques :

INCIDENTS :
- Incidents graves non résolus : {len(donnees['incidents_graves_ouverts'])}
- Détail : {json.dumps(donnees['incidents_graves_ouverts'], ensure_ascii=False, default=str)}

FLOTTE :
- Véhicules en maintenance : {json.dumps(donnees['vehicules_maintenance'], ensure_ascii=False, default=str)}
- Véhicules à haut kilométrage actifs : {json.dumps(vehicules_haut_km, ensure_ascii=False)}

CHAUFFEURS :
- Chauffeurs avec incidents répétés ce mois : {json.dumps(chauffeurs_incidents, ensure_ascii=False)}
- Chauffeurs indisponibles : {donnees['chauffeurs_indisponibles']}/{donnees['total_chauffeurs']}

OPÉRATIONS :
- Lignes sans trajet cette semaine : {json.dumps(lignes_sans_trajet, ensure_ascii=False)}
- Recette : {donnees['recette_semaine']:,.0f} FCFA (variation : {round(((donnees['recette_semaine'] - donnees['recette_semaine_precedente']) / donnees['recette_semaine_precedente'] * 100) if donnees['recette_semaine_precedente'] > 0 else 0, 1)}%)
"""

    system = """Tu es un système d'analyse de risques pour une compagnie de transport.
Génère une liste JSON d'alertes priorisées.
Format OBLIGATOIRE (JSON pur, aucun texte avant ou après) :
[
  {
    "niveau": "critique|warning|info",
    "categorie": "flotte|chauffeur|incident|finance|operation",
    "titre": "Titre court (max 60 car.)",
    "detail": "Explication en 1-2 phrases avec chiffres précis.",
    "action": "Action recommandée concrète."
  }
]
Maximum 6 alertes. Trier par niveau (critique en premier)."""

    try:
        raw = await ask_llm_libre(system, context)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        alertes = json.loads(match.group()) if match else []
        return {"alertes": alertes, "total": len(alertes)}
    except Exception as e:
        return {"alertes": [], "total": 0, "error": str(e)}


# ── 3. PRÉDICTIONS ET RISQUES ─────────────────────────────────
@app.get("/api/ia/predictions")
async def ia_predictions():
    """
    Prédit les risques à court terme : pannes probables, lignes sous-performantes,
    besoins en chauffeurs.
    """
    vehicules_stats = execute_query("""
        SELECT v.immatriculation, v.kilometrage, v.statut, v.type,
               COUNT(i.id) AS nb_incidents_total,
               SUM(CASE WHEN i.type='panne' THEN 1 ELSE 0 END) AS nb_pannes,
               MAX(t.date_heure_depart) AS dernier_trajet
        FROM vehicules v
        LEFT JOIN trajets t ON t.vehicule_id = v.id
        LEFT JOIN incidents i ON i.trajet_id = t.id
        GROUP BY v.id, v.immatriculation, v.kilometrage, v.statut, v.type
        ORDER BY v.kilometrage DESC
    """)

    lignes_perf = execute_query("""
        SELECT l.code, l.nom,
               COUNT(t.id) AS nb_trajets,
               COALESCE(AVG(t.nb_passagers), 0) AS moy_passagers,
               COALESCE(SUM(t.recette), 0) AS recette,
               l.distance_km
        FROM lignes l
        LEFT JOIN trajets t ON l.id = t.ligne_id
            AND t.statut = 'termine'
            AND t.date_heure_depart >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY l.id, l.code, l.nom, l.distance_km
        ORDER BY recette ASC
    """)

    tendance_trajets = execute_query("""
        SELECT DATE(date_heure_depart) AS jour, COUNT(*) AS nb
        FROM trajets
        WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 14 DAY)
        GROUP BY DATE(date_heure_depart)
        ORDER BY jour
    """)

    context = f"""
Données pour l'analyse prédictive :

VÉHICULES (kilométrage + historique pannes) :
{json.dumps(vehicules_stats, ensure_ascii=False, default=str)}

PERFORMANCE LIGNES (30 derniers jours) :
{json.dumps(lignes_perf, ensure_ascii=False, default=str)}

TENDANCE TRAJETS (14 derniers jours) :
{json.dumps(tendance_trajets, ensure_ascii=False, default=str)}
"""

    system = """Tu es un analyste IA spécialisé dans la prédiction des risques de transport.
Génère une analyse prédictive au format JSON pur :
{
  "vehicules_a_risque": [
    {"immatriculation": "...", "risque": "...", "probabilite": "faible|moyen|élevé", "raison": "..."}
  ],
  "lignes_sous_performantes": [
    {"code": "...", "nom": "...", "probleme": "...", "recommandation": "..."}
  ],
  "tendance_globale": "hausse|stable|baisse",
  "prevision_semaine": "Phrase de prévision pour la semaine prochaine.",
  "recommandations_prioritaires": ["action1", "action2", "action3"]
}
Basé uniquement sur les données fournies. JSON pur, aucun texte autour."""

    try:
        raw = await ask_llm_libre(system, context)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        predictions = json.loads(match.group()) if match else {}
        return predictions
    except Exception as e:
        return {"error": str(e)}


# ── 4. CONSEILS D'OPTIMISATION ────────────────────────────────
@app.get("/api/ia/conseils")
async def ia_conseils():
    """
    Génère des conseils d'optimisation opérationnelle personnalisés
    basés sur les performances réelles des 30 derniers jours.
    """
    perf_globale = execute_query("""
        SELECT
            COUNT(*) AS total_trajets,
            SUM(recette) AS recette_totale,
            AVG(nb_passagers) AS moy_passagers,
            SUM(CASE WHEN statut='annule' THEN 1 ELSE 0 END) AS trajets_annules,
            SUM(CASE WHEN statut='termine' THEN 1 ELSE 0 END) AS trajets_termines
        FROM trajets
        WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    """)

    meilleurs_chauffeurs = execute_query("""
        SELECT ch.nom, ch.prenom,
               COUNT(t.id) AS nb_trajets,
               COALESCE(SUM(t.recette), 0) AS recette_generee,
               COALESCE(AVG(t.nb_passagers), 0) AS moy_passagers,
               COUNT(i.id) AS nb_incidents
        FROM chauffeurs ch
        JOIN trajets t ON t.chauffeur_id = ch.id
        LEFT JOIN incidents i ON i.trajet_id = t.id
        WHERE t.date_heure_depart >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY ch.id, ch.nom, ch.prenom
        ORDER BY recette_generee DESC
        LIMIT 5
    """)

    heures_pic = execute_query("""
        SELECT HOUR(date_heure_depart) AS heure, COUNT(*) AS nb_trajets,
               AVG(nb_passagers) AS moy_passagers
        FROM trajets
        WHERE statut = 'termine'
          AND date_heure_depart >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY HOUR(date_heure_depart)
        ORDER BY nb_trajets DESC
        LIMIT 5
    """)

    context = f"""
Performance des 30 derniers jours :

GLOBAL :
{json.dumps(perf_globale, ensure_ascii=False, default=str)}

TOP 5 CHAUFFEURS :
{json.dumps(meilleurs_chauffeurs, ensure_ascii=False, default=str)}

HEURES DE POINTE :
{json.dumps(heures_pic, ensure_ascii=False, default=str)}
"""

    system = """Tu es un consultant en optimisation de transport urbain au Sénégal.
Génère 4 à 5 conseils pratiques et actionnables au format JSON pur :
[
  {
    "titre": "Titre court et percutant",
    "categorie": "planification|flotte|rh|revenue|securite",
    "conseil": "Explication détaillée avec justification basée sur les données (2-3 phrases).",
    "impact_estime": "Description de l'impact attendu.",
    "priorite": "haute|moyenne|faible"
  }
]
Conseils spécifiques au contexte sénégalais (Dakar, transport urbain). JSON pur."""

    try:
        raw = await ask_llm_libre(system, context)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        conseils = json.loads(match.group()) if match else []
        return {"conseils": conseils}
    except Exception as e:
        return {"conseils": [], "error": str(e)}


# ── 5. ANALYSE D'UN CHAUFFEUR ─────────────────────────────────
@app.get("/api/ia/analyse-chauffeur/{chauffeur_id}")
async def ia_analyse_chauffeur(chauffeur_id: int):
    """
    Génère une fiche d'analyse complète d'un chauffeur :
    performance, incidents, fiabilité, recommandations.
    """
    chauffeur = execute_query("""
        SELECT c.*, v.immatriculation, v.type AS vehicule_type
        FROM chauffeurs c
        LEFT JOIN vehicules v ON c.vehicule_id = v.id
        WHERE c.id = %s
    """, (chauffeur_id,))
    if not chauffeur:
        raise HTTPException(status_code=404, detail="Chauffeur non trouvé")

    stats = execute_query("""
        SELECT COUNT(*) AS nb_trajets,
               COALESCE(SUM(recette), 0) AS recette_totale,
               COALESCE(AVG(nb_passagers), 0) AS moy_passagers,
               COALESCE(AVG(TIMESTAMPDIFF(MINUTE, date_heure_depart, date_heure_arrivee)), 0) AS duree_moy_min,
               SUM(CASE WHEN statut='annule' THEN 1 ELSE 0 END) AS trajets_annules
        FROM trajets
        WHERE chauffeur_id = %s
          AND date_heure_depart >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    """, (chauffeur_id,))

    incidents = execute_query("""
        SELECT i.type, i.gravite, i.description, i.resolu, i.date_incident
        FROM incidents i
        JOIN trajets t ON i.trajet_id = t.id
        WHERE t.chauffeur_id = %s
          AND i.date_incident >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        ORDER BY i.date_incident DESC
    """, (chauffeur_id,))

    context = f"""
Analyse ce chauffeur :

PROFIL :
{json.dumps(chauffeur[0], ensure_ascii=False, default=str)}

STATISTIQUES (30 derniers jours) :
{json.dumps(stats[0] if stats else {}, ensure_ascii=False, default=str)}

INCIDENTS (90 derniers jours) :
{json.dumps(incidents, ensure_ascii=False, default=str)}
"""

    system = """Tu es un responsable RH de transport. Génère une évaluation professionnelle au format JSON pur :
{
  "note_globale": 1-10,
  "points_forts": ["point1", "point2"],
  "points_amelioration": ["point1", "point2"],
  "evaluation": "Paragraphe d'évaluation globale (3-4 phrases).",
  "recommandation": "maintien|formation|surveillance|promotion",
  "justification_recommandation": "Phrase courte."
}
JSON pur, aucun texte autour."""

    try:
        raw = await ask_llm_libre(system, context)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        analyse = json.loads(match.group()) if match else {}
        return {
            "chauffeur": chauffeur[0],
            "stats_30j": stats[0] if stats else {},
            "nb_incidents_90j": len(incidents),
            "analyse_ia": analyse
        }
    except Exception as e:
        return {"error": str(e)}


# ── 6. RAPPORT HEBDOMADAIRE COMPLET ───────────────────────────
@app.get("/api/ia/rapport-hebdomadaire")
async def ia_rapport_hebdomadaire():
    """
    Agrège résumé + alertes + prédictions en un seul appel.
    Endpoint pratique pour le tableau de bord.
    """
    try:
        donnees = collecter_donnees_situation()

        tp = donnees["taux_ponctualite"]
        ponctualite_pct = round(tp["a_lheure"] / tp["total"] * 100) if tp and tp.get("total", 0) > 0 else None
        rec_s = donnees["recette_semaine"]
        rec_prev = donnees["recette_semaine_precedente"]
        variation = round(((rec_s - rec_prev) / rec_prev * 100) if rec_prev > 0 else 0, 1)

        context = f"""
Données hebdomadaires complètes :
- Trajets : {donnees['trajets_semaine']}
- Incidents graves non résolus : {len(donnees['incidents_graves_ouverts'])}
- Tous incidents ouverts : {donnees['tous_incidents_ouverts']}
- Véhicules en maintenance : {json.dumps(donnees['vehicules_maintenance'], ensure_ascii=False, default=str)}
- Recette : {rec_s:,.0f} FCFA ({'+' if variation >= 0 else ''}{variation}% vs semaine précédente)
- Chauffeurs indisponibles : {donnees['chauffeurs_indisponibles']}/{donnees['total_chauffeurs']}
- Ponctualité : {f'{ponctualite_pct}%' if ponctualite_pct is not None else 'N/A'}
- Top lignes : {json.dumps(donnees['lignes_actives'], ensure_ascii=False)}
"""

        system = """Génère un rapport hebdomadaire JSON complet pour une compagnie de transport :
{
  "resume_executif": "Briefing en 3-4 phrases pour le DG.",
  "score_sante_flotte": 0-100,
  "score_performance": 0-100,
  "alertes": [{"niveau": "critique|warning|info", "message": "..."}],
  "points_positifs": ["..."],
  "points_negatifs": ["..."],
  "objectif_semaine_prochaine": "Un objectif prioritaire concret."
}
JSON pur."""

        raw = await ask_llm_libre(system, context)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        rapport = json.loads(match.group()) if match else {}

        return {
            **rapport,
            "kpis": {
                "trajets_semaine": donnees["trajets_semaine"],
                "recette_semaine": rec_s,
                "variation_recette_pct": variation,
                "incidents_graves_ouverts": len(donnees["incidents_graves_ouverts"]),
                "vehicules_en_maintenance": len(donnees["vehicules_maintenance"]),
                "ponctualite_pct": ponctualite_pct,
            }
        }
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama non accessible.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Servir le frontend ────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_BASE_DIR, "index.html")

@app.get("/")
def serve_frontend():
    if not os.path.exists(_INDEX):
        raise HTTPException(status_code=404, detail="index.html introuvable")
    return FileResponse(_INDEX)

# ── Lancement ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)