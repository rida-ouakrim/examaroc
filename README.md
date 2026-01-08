# 📚 Plateforme d'Examens Bac National

Une application Streamlit complète pour générer, corriger et suivre les examens du Bac National avec l'aide de l'IA.

## ✨ Fonctionnalités

- ✅ **Authentification sécurisée** avec code d'accès
- 📝 **Génération automatique d'examens** via n8n + IA
- 💬 **Trois sections** : Compréhension, Langue, Rédaction
- 🤖 **Correction automatique** par IA (OpenAI/LLM)
- 📊 **Affichage détaillé des résultats** avec feedback par question
- 🔁 **Relance de correction** possible après modification des réponses
- 📈 **Suivi des performances** par étudiant

## 🛠️ Stack Technique

- **Frontend**: Streamlit (Python)
- **Backend**: Supabase (PostgreSQL)
- **Workflow d'IA**: n8n
- **Authentification**: Code d'accès personnalisé

## 🚀 Installation Locale

### Prérequis
- Python 3.10+
- Git
- Un compte Supabase

### Étapes

```bash
# 1. Cloner le repo
git clone https://github.com/YOUR_USERNAME/examaroc.git
cd examaroc

# 2. Créer l'environnement virtuel
python -m venv venv

# 3. Activer l'environnement
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 4. Installer les dépendances
pip install -r requirements.txt

# 5. Créer le fichier .env
cp .env.example .env
# Éditer .env et ajouter vos clés:
# SUPABASE_URL=...
# SUPABASE_KEY=...
# N8N_WEBHOOK=...
# N8N_CORRECTION_WEBHOOK=...

# 6. Lancer l'app
streamlit run app.py
```

L'app sera disponible sur `http://localhost:8501`

## 🔐 Variables d'environnement

Créez un fichier `.env` avec:

```env
SUPABASE_URL=votre_url_supabase
SUPABASE_KEY=votre_clé_supabase
N8N_WEBHOOK=http://localhost:5678/webhook-test/generation
N8N_CORRECTION_WEBHOOK=http://localhost:5678/webhook-test/correction
```

## 📦 Structure du projet

```
examaroc/
├── app.py                 # Application principale Streamlit
├── requirements.txt       # Dépendances Python
├── .env.example          # Template des variables d'environnement
├── .gitignore            # Fichiers à ignorer dans Git
└── README.md             # Ce fichier
```

## 🔄 Flux de l'Application

1. **Login** → Authentification avec nom + code d'accès
2. **Dashboard** → Liste des examens disponibles
3. **Génération** → Sélectionner filière et durée
4. **Attente** → Polling jusqu'à génération complète
5. **Examen** → Remplissage des 3 sections
6. **Soumission** → Envoi au webhook n8n
7. **Correction** → Attente des résultats de l'IA
8. **Résultats** → Affichage avec feedback détaillé

## 📊 Schéma de la Base de Données

### Table: `exams_streamlit`
- `id` (UUID)
- `student_id` (string)
- `exam_content` (JSON)
- `student_responses` (JSON)
- `status` (string: pending, ready, submitted, resubmitted)
- `created_at` (timestamp)

### Table: `exam_results`
- `id` (UUID)
- `exam_id` (UUID)
- `student_id` (string)
- `score_total` (float)
- `max_score` (float)
- `feedback_general` (text)
- `detailed_correction` (JSON)
- `created_at` (timestamp)

### Table: `access_codes`
- `code` (string, unique)
- `active` (boolean)
- `created_at` (timestamp)

## 🎯 Code d'accès de test

Pour tester l'application en développement:
- **Code**: `EXAM2024`

## 🌐 Déploiement sur Streamlit Cloud

### Étapes

1. **Pousser sur GitHub**
   ```bash
   git add .
   git commit -m "Initial commit: Plateforme d'examens"
   git push origin main
   ```

2. **Créer un compte Streamlit Cloud**
   - Aller sur https://streamlit.io/cloud
   - Se connecter avec GitHub

3. **Déployer l'app**
   - Cliquer "New app"
   - Sélectionner le repo `examaroc`
   - Branche: `main`
   - Main file path: `app.py`
   - Cliquer "Deploy"

4. **Configurer les secrets**
   - Dans Streamlit Cloud, aller à "Settings" → "Secrets"
   - Ajouter les variables d'environnement:
   ```
   SUPABASE_URL = "..."
   SUPABASE_KEY = "..."
   N8N_WEBHOOK = "..."
   N8N_CORRECTION_WEBHOOK = "..."
   ```

## 🔒 Sécurité

- ✅ Les secrets sont stockés dans Streamlit Cloud Secrets (pas dans le code)
- ✅ Le `.env` est ignoré par Git
- ✅ Authentification par code d'accès
- ✅ Données stockées dans Supabase (HTTPS)

## 📝 Exemple d'utilisation

1. Accéder à l'app déployée
2. Entrer: Nom = "Ahmed Benali", Code = "EXAM2024"
3. Cliquer "🚀 Générer un nouvel examen"
4. Attendre la génération (~30s)
5. Remplir l'examen
6. Cliquer "🏁 Terminer"
7. Voir les résultats avec corrections détaillées

## 🤝 Support

Pour des questions ou des bugs, créer une issue sur GitHub.

## 📄 Licence

MIT License - Libre d'utilisation

---

**Développé avec ❤️ pour les étudiants du Bac National**
