# 🚌 TranspoBot — Projet GLSi L3 ESP/UCAD

> Application web de gestion de transport urbain avec assistant IA conversationnel (Text-to-SQL)

---

##  Équipe & Rôles

| Membre | Rôle | Branche Git |
|--------|------|-------------|
| **Arame Yvonne** |  Chef de projet + BDD MySQL | `feature/bdd` |
| **Ndeye Khady** |  Backend FastAPI (Python) | `feature/backend` |
| **Aminata Ndiaye** |  Intégration LLM (Text-to-SQL) | `feature/llm` |
| **Ndeye Maty** |  Frontend (HTML/CSS/JS) | `feature/frontend` |
| **Mame Dior** |  Déploiement + Rapport + PowerPoint | `feature/ deploiement` |

---

##  Structure du projet

```
TranspoBot_GLSi_Starter/
├── README.md                    # Documentation du projet
├── .gitignore                   # Fichiers exclus de Git
└── transpobot/
    ├── app.py                   # Backend FastAPI (Python) — M2
    ├── schema.sql               # Schéma + données de test MySQL — M1
    ├── index.html               # Interface web frontend — M4
    ├── requirements.txt         # Dépendances Python
    └── .env.example             # Variables d'environnement (modèle)
```

---

##  Technologies

- **Backend** : Python 3.11+ / FastAPI
- **Base de données** : MySQL 8.x
- **LLM** : OpenAI GPT-4o-mini (ou Ollama / LLaMA3 en local)
- **Frontend** : HTML / CSS / JavaScript vanilla
- **Déploiement** : Railway.app ou Render.com

---

##  Démarrage rapide

### 1. Cloner le dépôt
```bash
git clone https://github.com/TranspoBot-GLSi/transpobot.git
cd transpobot
```

### 2. Créer la base de données
```bash
mysql -u root -p < transpobot/schema.sql
```

### 3. Configurer l'environnement
```bash
cp transpobot/.env.example transpobot/.env
# Éditer .env avec vos valeurs (clé API, config MySQL...)
```

### 4. Installer les dépendances Python
```bash
pip install -r transpobot/requirements.txt
```

### 5. Lancer le backend
```bash
cd transpobot
python app.py
# API disponible sur http://localhost:8000
```

### 6. Ouvrir le frontend
Ouvrir `transpobot/index.html` dans un navigateur
_(ou configurer la variable `API_URL` dans index.html avec l'adresse du backend)_

---

## 🔌 Endpoints API

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/api/chat` | Question en langage naturel → SQL → résultats |
| `GET` | `/api/stats` | Statistiques tableau de bord (KPI) |
| `GET` | `/api/vehicules` | Liste des véhicules |
| `GET` | `/api/chauffeurs` | Liste des chauffeurs |
| `GET` | `/api/trajets/recent` | 20 derniers trajets |
| `GET` | `/health` | Vérification de l'état de l'API |

---

##  Exemples de dialogues IA

```
Utilisateur : "Combien de trajets cette semaine ?"
→ SQL : SELECT COUNT(*) FROM trajets WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND statut='termine'
→ Réponse : "5 trajets terminés cette semaine."

Utilisateur : "Quel chauffeur a le plus d'incidents ?"
→ SQL : SELECT c.nom, c.prenom, COUNT(i.id) as nb FROM incidents i JOIN trajets t ON i.trajet_id=t.id JOIN chauffeurs c ON t.chauffeur_id=c.id GROUP BY c.id ORDER BY nb DESC LIMIT 1
→ Réponse : "Ibrahima FALL avec 2 incidents."

Utilisateur : "Quels véhicules sont en maintenance ?"
→ SQL : SELECT immatriculation, kilometrage FROM vehicules WHERE statut='maintenance'
→ Réponse : "DK-9012-EF (78 000 km) est en maintenance."
```

---

## 🌿 Workflow Git — Règles du groupe

```bash
# 1. Toujours partir de principal à jour
git checkout principal
git pull

# 2. Travailler sur sa propre branche
git checkout feature/m?-votre-role

# 3. Committer régulièrement avec des messages clairs
git add .
git commit -m "feat: description de ce que tu as fait"

# 4. Pousser et créer une Pull Request vers principal
git push origin feature/m?-votre-role
```

>  **Ne jamais pousser directement sur `principal`**
> Toujours créer une Pull Request — M1 (Arame Yvonne) valide les merges.

### Convention des commits
```
feat:   nouvelle fonctionnalité
fix:    correction de bug
style:  changements CSS/UI
db:     modifications base de données
docs:   documentation
deploy: déploiement
```

---

##  Variables d'environnement (.env)

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=votre_mot_de_passe
DB_NAME=transpobot

OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
```
-

##  Livrables — Deadline : 16 avril

| Livrable | Responsable | Format | Statut |
|----------|-------------|--------|--------|
| Lien plateforme déployée | M5 Mame Dior | URL en ligne |  |
| Lien interface de chat IA | M5 Mame Dior | URL chat fonctionnel |  |
| Rapport de conception | M5 compile tout | PDF, 15-25 pages |  |
| Présentation PowerPoint | M5 Mame Dior | PPTX, 10-15 slides |  |
| Code source | M1 Arame Yvonne | GitHub |  |
| Script SQL commenté | M1 Arame Yvonne | Fichier .sql |  |

---

##  Grille d'évaluation

| Critère | Détail | Points |
|---------|--------|--------|
| Modélisation BDD | MCD, MLD, script SQL correct | /20 |
| Backend fonctionnel | API REST opérationnelle | /20 |
| Intégration LLM | Text-to-SQL précis, prompt sécurisé | /25 |
| Interface web | UX claire, tableau de bord, chat intégré | /15 |
| Déploiement | Application accessible en ligne | /10 |
| Rapport | Qualité, complétude, clarté | /20 |
| Présentation/démo | Communication, maîtrise technique | /15 |
| Bonus | Fonctionnalités supplémentaires | +10 |
| **TOTAL** | | **/125** |

---

##  Contact enseignant

**Pr. Ahmath Bamba MBACKE**
ahmathbamba.mbacke@esp.sn | +221 77 575 64 90

---

> *Toute aide IA (ChatGPT, Claude, Copilot…) doit être déclarée dans le rapport.*
