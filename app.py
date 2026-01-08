import streamlit as st
import requests
import time
from supabase import create_client
import os
from dotenv import load_dotenv
import json

# --- Load environment variables ---
load_dotenv()

# --- CREDENTIALS ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
N8N_WEBHOOK = os.getenv("N8N_WEBHOOK")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("❌ Erreur: SUPABASE_URL ou SUPABASE_KEY manquants. Vérifiez le fichier .env")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Plateforme d'Examens - Bac National", layout="wide", initial_sidebar_state="collapsed")

# --- CSS personnalisé ---
st.markdown("""
<style>
    .main { padding-top: 2rem; }
    .login-container { max-width: 500px; margin: 5rem auto; padding: 2rem; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    .dashboard-header { text-align: center; margin-bottom: 2rem; }
    .exam-card { padding: 1.5rem; border-radius: 8px; border-left: 4px solid #1f77b4; background: #f8f9fa; margin-bottom: 1rem; }
    .exam-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
</style>
""", unsafe_allow_html=True)

# --- GESTION DE L'ÉTAT ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_name' not in st.session_state:
    st.session_state.user_name = None
if 'user_email' not in st.session_state:
    st.session_state.user_email = None
if 'waiting_for_correction' not in st.session_state:
    st.session_state.waiting_for_correction = False
if 'correction_ready' not in st.session_state:
    st.session_state.correction_ready = False
if 'current_exam_id' not in st.session_state:
    st.session_state.current_exam_id = None
if 'current_user' not in st.session_state:
    st.session_state.current_user = None

# Helper: resolve student answer from correction item or from session_state fallbacks
def _resolve_student_answer(item):
    try:
        # prefer explicit student_answer in the correction item
        if isinstance(item, dict) and item.get('student_answer'):
            return item.get('student_answer')

        # try using the item's id as a key in session_state
        item_id = None
        if isinstance(item, dict):
            item_id = item.get('id')

        if item_id and item_id in st.session_state:
            return st.session_state.get(item_id)

        # special fallback for language matching legacy keys
        if item_id and item_id.startswith('lang_'):
            ex = item_id[len('lang_'):]
            # try new-style key
            k_new = f"lang_{ex}_0"
            k_old = f"lang_match_{ex}"
            for k in (k_new, k_old):
                if k in st.session_state:
                    return st.session_state.get(k)

    except Exception:
        pass
    return 'N/A'

# --- Helper: retrieve question and associated text from exam_json given an item id ---
def _get_question_and_text(item_id, exam_json):
    # For comprehension: comp_{ex_id}_{q_idx}
    if item_id.startswith('comp_') and 'comprehension' in exam_json:
        comp = exam_json['comprehension']
        ex_id = item_id.split('_')[1]
        q_idx = int(item_id.split('_')[2])
        # Find the right exercice
        for exercice in comp.get('exercices', []):
            if str(exercice.get('id')) == ex_id:
                questions = exercice.get('questions', [])
                if 0 <= q_idx < len(questions):
                    q = questions[q_idx]
                    texte = comp.get('texte', None)
                    return q.get('question', 'Question non disponible'), texte or 'Texte non disponible'
    # For language: lang_{ex_id}_{q_idx} or lang_free_{ex_id}_{q_idx}
    if (item_id.startswith('lang_') or item_id.startswith('lang_free_')) and 'language' in exam_json:
        lang = exam_json['language']
        ex_id = item_id.split('_')[1]
        q_idx = int(item_id.split('_')[2]) if '_' in item_id else 0
        for exercice in lang.get('exercices', []):
            if str(exercice.get('id')) == ex_id:
                # details or questions
                if 'details' in exercice and 0 <= q_idx < len(exercice['details']):
                    q = exercice['details'][q_idx]
                    return q.get('question', 'Question non disponible'), None
                if 'questions' in exercice and 0 <= q_idx < len(exercice['questions']):
                    q = exercice['questions'][q_idx]
                    return q.get('question', 'Question non disponible'), None
    # For writing: writing_{sujet_id}
    if item_id.startswith('writing_') and 'writing' in exam_json:
        writing = exam_json['writing']
        sujet_id = item_id.split('_')[1]
        for sujet in writing.get('sujets', []):
            if str(sujet.get('id')) == sujet_id:
                return sujet.get('sujet', 'Sujet non disponible'), None
    return 'Question non disponible', 'Texte non disponible'

# --- FONCTION D'AUTHENTIFICATION ---
def verify_access_code(full_name, access_code):
    """Vérifier le code d'accès auprès de Supabase."""
    try:
        # Chercher dans une table 'access_codes' ou stocker une liste autorisée
        # Pour maintenant, utiliser une liste simple ou interroger la DB
        res = supabase.table("access_codes").select("*").eq("code", access_code).eq("active", True).execute()
        if res.data:
            st.session_state.authenticated = True
            st.session_state.user_name = full_name
            st.session_state.user_email = f"{full_name.lower().replace(' ', '.')}@exam.local"
            st.session_state.current_user = st.session_state.user_email
            return True
        return False
    except Exception as e:
        # Fallback: codes de test
        if access_code == "EXAM2024":
            st.session_state.authenticated = True
            st.session_state.user_name = full_name
            st.session_state.user_email = f"{full_name.lower().replace(' ', '.')}@exam.local"
            st.session_state.current_user = st.session_state.user_email
            return True
        return False

def login_page():
    """Page de connexion."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='dashboard-header'>", unsafe_allow_html=True)
        st.image("https://blogger.googleusercontent.com/img/a/AVvXsEiBCmVLoZVRiG934gD1HPA0zumw8Ul6ZIvR7OU6V-Du18tpBVNfGZg1pGnKRCPUCi5YrVPRBs7CM5aqu_IxK-AYa5ijLSQ1K58aOTXocRTP5NuJ8HzceZNhk6NuxGVX8spFn05pdcGjQAiJ5uCeLIdWlDRPYl2mwLWDFQF4o2dJ1r6U009QtbY94ESL=s16000", width=150)
        st.markdown("## 📚 Plateforme d'Examens Bac National")
        st.markdown("Accès sécurisé aux examens", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.divider()

        with st.form("login_form"):
            full_name = st.text_input("👤 Nom Complet", placeholder="Ex: Ahmed Benali")
            access_code = st.text_input("🔐 Code d'Accès", type="password", placeholder="Entrez votre code")
            submit = st.form_submit_button("🚀 Se Connecter", use_container_width=True)

            if submit:
                if not full_name or not access_code:
                    st.error("❌ Veuillez remplir tous les champs")
                elif verify_access_code(full_name, access_code):
                    st.success(f"✅ Bienvenue {full_name}!")
                    st.balloons()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Code d'accès invalide. Veuillez réessayer.")

# --- PAGE PRINCIPALE ---
if not st.session_state.authenticated:
    login_page()
    st.stop()

    except Exception:
        pass
    return 'N/A'

# --- UI SIDEBAR ---
with st.sidebar:
    st.image("https://blogger.googleusercontent.com/img/a/AVvXsEiBCmVLoZVRiG934gD1HPA0zumw8Ul6ZIvR7OU6V-Du18tpBVNfGZg1pGnKRCPUCi5YrVPRBs7CM5aqu_IxK-AYa5ijLSQ1K58aOTXocRTP5NuJ8HzceZNhk6NuxGVX8spFn05pdcGjQAiJ5uCeLIdWlDRPYl2mwLWDFQF4o2dJ1r6U009QtbY94ESL=s16000", width=100)
    st.title("Générateur d'Examens")
    student_id = st.text_input("ID Étudiant", "user_123456")
    filiere = st.selectbox("Filière", ["Science Physique", "SVT", "Sciences Math"])
    
    # Divider
    st.divider()
    st.subheader("📋 Examens Existants")
    
    # Charger les examens existants pour cet étudiant
    try:
        res = supabase.table("exams_streamlit").select("id, created_at, status").eq("student_id", student_id).order("created_at", desc=True).execute()
        exams = res.data if res.data else []
        
        if exams:
            # Créer une liste d'affichage pour le selectbox
            exam_options = [f"📌 {exam['created_at'][:10]} ({exam['status']})" for exam in exams]
            selected_exam_idx = st.selectbox("Charger un examen:", range(len(exam_options)), format_func=lambda x: exam_options[x])
            
            if st.button("✅ Charger cet examen"):
                # Charger l'examen complet avec son contenu
                full_exam = supabase.table("exams_streamlit").select("*").eq("id", exams[selected_exam_idx]['id']).execute()
                if full_exam.data:
                    st.session_state.exam_json = full_exam.data[0].get('exam_content')
                    st.session_state.current_exam_id = exams[selected_exam_idx]['id']
                    # S'assurer que l'ID étudiant est stocké pour l'envoi des webhooks
                    # Utiliser l'ID stocké dans la ligne d'examen si présent (plus fiable)
                    exam_row_student_id = full_exam.data[0].get('student_id') if full_exam.data and isinstance(full_exam.data[0], dict) else None
                    st.session_state.current_user = exam_row_student_id or student_id
                    # Si des réponses étudiantes sont déjà enregistrées, les charger dans la session
                    saved_answers = full_exam.data[0].get('student_responses') or full_exam.data[0].get('student_answers') or {}
                    if isinstance(saved_answers, dict) and saved_answers:
                        # Charger les réponses dans session_state. Migrer d'anciennes clés 'lang_match_...' vers 'lang_{id}_0'
                        for k, v in saved_answers.items():
                            if isinstance(k, str) and k.startswith('lang_match_'):
                                ex = k[len('lang_match_'):]
                                new_k = f"lang_{ex}_0"
                                st.session_state[new_k] = v
                            else:
                                st.session_state[k] = v

                        st.info(f"✅ {len(saved_answers)} réponses précédemment enregistrées chargées.")
                    # Vérifier si une correction existe déjà dans la table `exam_results`
                    try:
                        res_corr = supabase.table("exam_results")\
                            .select("*")\
                            .eq("exam_id", st.session_state.current_exam_id)\
                            .eq("student_id", st.session_state.current_user)\
                            .order("created_at", desc=True).limit(1).execute()
                        if res_corr.data:
                            st.session_state.correction_data = res_corr.data[0]
                            # Si la ligne de résultat contient les réponses de l'étudiant, les charger pour permettre modification
                            saved_from_result = res_corr.data[0].get('student_responses') or res_corr.data[0].get('student_answers')
                            if isinstance(saved_from_result, dict) and saved_from_result:
                                for k, v in saved_from_result.items():
                                    st.session_state[k] = v
                                st.info(f"✅ {len(saved_from_result)} réponses (de la dernière correction) chargées pour modification.")
                            st.success("✅ Une correction existe déjà pour cet examen. Affichage des résultats.")
                            st.rerun()
                    except Exception as e:
                        st.warning(f"Impossible de vérifier les résultats existants: {str(e)}")
                    st.success("Examen chargé !")
                    st.rerun()
        else:
            st.info("Aucun examen trouvé pour cet étudiant.")
    except Exception as e:
        st.warning(f"⚠️ Erreur lors du chargement des examens: {str(e)}")
    
    st.divider()
    
    if st.button("🚀 Générer un nouvel Examen"):
        payload = {"student_id": student_id, "filiere": filiere}
        requests.post(N8N_WEBHOOK, json=payload)
        st.session_state.is_waiting = True
        st.session_state.current_user = student_id

    # Bouton manuel pour vérifier/afficher une correction déjà enregistrée
    if st.button("🔍 Voir la correction enregistrée"):
        if not st.session_state.get('current_exam_id'):
            st.warning("Aucun examen sélectionné. Chargez d'abord un examen.")
        else:
            # Debug: afficher les IDs utilisés
            st.info(f"Debug: recherche de correction pour exam_id={st.session_state.get('current_exam_id')} student_id={st.session_state.get('current_user')}")
            try:
                res_corr = supabase.table("exam_results")\
                    .select("*")\
                    .eq("exam_id", st.session_state.current_exam_id)\
                    .eq("student_id", st.session_state.current_user)\
                    .order("created_at", desc=True).limit(1).execute()
                # Afficher le résultat brut pour debug
                st.write("Debug: réponse brute de la requête:")
                st.write(res_corr)
                if res_corr.data:
                    # montrer le contenu de la ligne
                    st.write("Debug: contenu de res_corr.data[0]:")
                    st.json(res_corr.data[0])
                    st.session_state.correction_data = res_corr.data[0]
                    # Charger les réponses contenues dans la correction (si présentes)
                    saved_from_result = res_corr.data[0].get('student_responses') or res_corr.data[0].get('student_answers')
                    if isinstance(saved_from_result, dict) and saved_from_result:
                        for k, v in saved_from_result.items():
                            if isinstance(k, str) and k.startswith('lang_match_'):
                                ex = k[len('lang_match_'):]
                                new_k = f"lang_{ex}_0"
                                st.session_state[new_k] = v
                            else:
                                st.session_state[k] = v
                        st.info(f"✅ {len(saved_from_result)} réponses (de la dernière correction) chargées pour modification.")
                    st.success("✅ Correction trouvée et chargée.")
                    st.rerun()
                else:
                    st.info("Aucune correction trouvée pour cet examen et cet étudiant.")
            except Exception as e:
                st.error(f"Erreur lors de la recherche de la correction: {e}")

# --- LOGIQUE D'ATTENTE ---
if st.session_state.get("is_waiting"):
    with st.status("Génération de l'examen en cours par l'IA...", expanded=True) as status:
        while True:
            # On cherche l'examen le plus récent pour cet étudiant
            res = supabase.table("exams_streamlit").select("*").eq("student_id", st.session_state.current_user).order("created_at", desc=True).limit(1).execute()
            
            if res.data and res.data[0]['status'] == 'ready':
                st.session_state.exam_json = res.data[0]['exam_content']
                st.session_state.is_waiting = False
                status.update(label="Examen prêt !", state="complete", expanded=False)
                break
            time.sleep(3) # On vérifie toutes les 3 secondes
        st.rerun()

# --- AFFICHAGE DE L'EXAMEN ---
if st.session_state.get("exam_json"):
    # Nettoyage automatique du JSON si nécessaire
    import json
    data = st.session_state.exam_json
    if isinstance(data, str):
        try:
            data = json.loads(data.strip("`json\n"))
        except json.JSONDecodeError as e:
            st.error(f"❌ Erreur JSON: {str(e)}")
            st.json({"raw_data": data})
            st.stop()

    # Vérification de la structure des données
    if not isinstance(data, dict):
        st.error("❌ Les données ne sont pas un dictionnaire valide")
        st.write("Type reçu:", type(data))
        st.stop()
    
    # Affichage diagnostic des données
    with st.expander("📊 Afficher les données brutes"):
        st.json(data)
    
    # Essayer d'afficher le titre
    if 'info' in data and 'title' in data['info']:
        title = data['info']['title']
    else:
        title = 'Examen'
    
    st.title(title)
    
    # Afficher les infos
    if 'info' in data:
        col1, col2, col3 = st.columns(3)
        if 'duration' in data['info']:
            col1.metric("⏱️ Durée", data['info']['duration'])
        if 'total_points' in data['info']:
            col2.metric("📊 Points Total", data['info']['total_points'])
    
    # Créer les onglets
    t1, t2, t3 = st.tabs(["📖 Reading", "🔤 Language", "✍️ Writing"])

    with t1:
        # Section Comprehension/Reading
        if 'comprehension' in data:
            comp = data['comprehension']
            
            # Afficher le texte
            if 'texte' in comp:
                st.info(comp['texte'])
            
            # Afficher les exercices
            if 'exercices' in comp:
                for exercice in comp['exercices']:
                    ex_id = exercice.get('id', '?')
                    st.markdown(f"### Exercice {ex_id}")
                    st.markdown(f"**{exercice.get('consigne', '')}**")
                    
                    for q_idx, question in enumerate(exercice.get('questions', [])):
                        q_text = question.get('question', '')
                        points = question.get('points', 0)
                        st.markdown(f"**Q:** {q_text} _(points: {points})_")
                        st.text_area("Réponse:", key=f"comp_{ex_id}_{q_idx}", height=100)

    with t2:
        # Section Language
        if 'language' in data:
            lang = data['language']
            
            if 'exercices' in lang:
                for exercice in lang['exercices']:
                    ex_id = exercice.get('id', '?')
                    st.markdown(f"### Exercice {ex_id}")
                    st.markdown(f"**{exercice.get('consigne', '')}**")
                    
                    # Si c'est un matching exercise
                    if 'matching' in exercice:
                        st.write("**Matching Exercise:**")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("**Expressions:**")
                            for expr in exercice['matching'].get('expressions', []):
                                st.write(f"- {expr['id']}. {expr['text']}")
                        with col2:
                            st.write("**Fonctions:**")
                            for func in exercice['matching'].get('fonctions', []):
                                st.write(f"- {func['id']}. {func['text']}")
                        # Use unified lang key format for matching exercises
                        st.text_input("Réponses (ex: 1-a, 2-b...)", key=f"lang_{ex_id}_0")
                    
                    # Si c'est des questions normales
                    if 'details' in exercice:
                        for q_idx, detail in enumerate(exercice['details']):
                            q_text = detail.get('question', '')
                            points = detail.get('points', 0)
                            st.markdown(f"**Q:** {q_text} _(points: {points})_")
                            st.text_area("Réponse:", key=f"lang_{ex_id}_{q_idx}", height=80)
                    
                    # Si c'est des réponses libres
                    if 'questions' in exercice:
                        for q_idx, question in enumerate(exercice['questions']):
                            q_text = question.get('question', '')
                            points = question.get('points', 0)
                            st.markdown(f"**Q:** {q_text} _(points: {points})_")
                            st.text_area("Réponse:", key=f"lang_free_{ex_id}_{q_idx}", height=100)

    with t3:
        # Section Writing
        if 'writing' in data:
            writing = data['writing']
            
            if 'sujets' in writing:
                for sujet in writing['sujets']:
                    sujet_id = sujet.get('id', '?')
                    sujet_type = sujet.get('type', '?')
                    points = sujet.get('points', 0)
                    
                    st.markdown(f"### Sujet {sujet_id}: {sujet_type} _(points: {points})_")
                    st.markdown(f"**{sujet.get('sujet', 'Pas de description')}**")
                    st.text_area("Votre réponse:", key=f"writing_{sujet_id}", height=250)
    
    # --- BOUTON DE SOUMISSION ---
    st.divider()
    
    col_submit, col_info = st.columns([3, 2])
    
    with col_submit:
        if st.button("🏁 Terminer l'examen et voir ma note", use_container_width=True):
            # Validation: s'assurer que l'exam_id est défini
            if not st.session_state.get('current_exam_id'):
                st.error("❌ Erreur: Aucun examen n'est actuellement chargé. Veuillez charger un examen d'abord.")
            else:
                # 1. Collecte dynamique des réponses
                user_answers = {}
                for key in st.session_state.keys():
                    # On récupère toutes les clés de réponses (y compris lang_match_ pour compatibilité arrière)
                    if any(key.startswith(prefix) for prefix in ["ans_", "lang_", "writing_", "comp_"]):
                        user_answers[key] = st.session_state[key]
                
                if len(user_answers) == 0:
                    st.warning("⚠️ Vous n'avez répondu à aucune question.")
                else:
                    try:
                        # Debug: afficher les IDs pour troubleshooting
                        st.info(f"Debug: Soumission avec exam_id={st.session_state.current_exam_id} student_id={st.session_state.current_user}")
                        
                        # 2. Enregistrement des réponses dans Supabase
                        supabase.table("exams_streamlit").update({
                            "student_responses": user_answers,
                            "status": "submitted"
                        }).eq("id", st.session_state.current_exam_id).execute()
                        
                        # 3. Appel du Webhook n8n de correction
                        webhook_correction = os.getenv("N8N_CORRECTION_WEBHOOK", "http://localhost:5678/webhook-test/correction")
                        requests.post(webhook_correction, json={
                            "student_id": st.session_state.current_user,
                            "exam_id": st.session_state.current_exam_id,
                            "action": "start_correction"
                        })
                        
                        st.session_state.waiting_for_correction = True
                        st.info("⏳ Correction en cours par l'IA... Veuillez patienter quelques secondes.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erreur lors de l'envoi : {str(e)}")
                        st.write(f"Debug - exam_id: {st.session_state.current_exam_id}")
                        st.write(f"Debug - student_id: {st.session_state.current_user}")
    
    with col_info:
        st.info("💡 Cliquez sur 'Terminer' pour soumettre vos réponses et obtenir votre note.")

# --- LOGIQUE D'ATTENTE DE LA CORRECTION ---
if st.session_state.get("waiting_for_correction"):
    # On crée un conteneur vide pour mettre à jour le message d'attente
    placeholder = st.empty()
    
    with placeholder.container():
        st.warning("⏳ Votre copie est entre les mains du prof IA... Analyse du Writing en cours.")
        # On peut ajouter un spinner ou une barre de progression
        with st.spinner("Vérification des résultats dans Supabase..."):
            
            found = False
            # On tente de vérifier pendant 90 secondes (30 itérations de 3s)
            for i in range(30):
                # Requête vers la table des résultats
                res = supabase.table("exam_results") \
                    .select("*") \
                    .eq("student_id", st.session_state.current_user) \
                    .eq("exam_id", st.session_state.current_exam_id) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute()
                
                if res.data:
                    # On a trouvé le résultat !
                    st.session_state.correction_data = res.data[0]
                    st.session_state.waiting_for_correction = False
                    found = True
                    break
                
                # Attendre 3 secondes avant la prochaine vérification
                time.sleep(3)
            
            if found:
                placeholder.empty() # On efface le message d'attente
                st.balloons()
                st.rerun() # On recharge pour afficher les résultats
            else:
                st.error("Délai de correction dépassé. Veuillez rafraîchir la page ou vérifier n8n.")
                st.session_state.waiting_for_correction = False

    progress_placeholder = st.empty()
# --- AFFICHAGE DES RÉSULTATS (POLLING) OR READY ---
if st.session_state.get("waiting_for_correction") or st.session_state.get('correction_data'):
    # Si on attend la correction, afficher le message d'attente
    if st.session_state.get("waiting_for_correction"):
        st.divider()
        st.subheader("⏳ Correction en cours...")

    progress_placeholder = st.empty()
    
    # On récupère les résultats prêts (soit depuis la session, soit depuis la table)
    try:
        # Si la correction a déjà été récupérée par le polling, on l'utilise
        resultat = st.session_state.get('correction_data')
        res = None
        if not resultat:
            res = supabase.table("exam_results")\
                    .select("*")\
                    .eq("student_id", st.session_state.current_user)\
                    .order("created_at", desc=True).limit(1).execute()
            if res.data:
                resultat = res.data[0]
        
        if resultat:
            # Si Supabase a renvoyé une chaîne JSON, la parser en dict
            if isinstance(resultat, str):
                import json
                try:
                    resultat = json.loads(resultat)
                except Exception:
                    # leave as is; will raise later
                    pass
            # Normaliser detailed_correction si c'est une string
            if isinstance(resultat, dict):
                if 'detailed_correction' in resultat and isinstance(resultat['detailed_correction'], str):
                    import json
                    try:
                        resultat['detailed_correction'] = json.loads(resultat['detailed_correction'])
                    except Exception:
                        # leave as is
                        pass
            # Vérifier que c'est pour le bon examen
            if isinstance(resultat, dict) and (resultat.get("exam_id") == st.session_state.current_exam_id or not st.session_state.current_exam_id):
                st.session_state.waiting_for_correction = False
                progress_placeholder.empty()
                
                st.balloons()
                st.success("### 🎉 Correction terminée !")
                
                # === RÉSUMÉ DES NOTES ===
                corrections = resultat.get('detailed_correction', [])
                
                # Calculer score total et max — préférer les valeurs renvoyées par le worker (exam_results)
                # Eviter toute conversion automatique : afficher la note telle qu'elle est stockée dans la table.
                score_total = resultat.get('score_total') if resultat.get('score_total') is not None else sum(item.get('points_earned', 0) for item in corrections)
                max_score = resultat.get('max_score') if resultat.get('max_score') is not None else 40
                # Pourcentage basé sur les valeurs stockées
                try:
                    percentage = (float(score_total) / float(max_score) * 100) if float(max_score) > 0 else 0
                except Exception:
                    percentage = 0
                
                # Affichage du score avec belle mise en page
                col1, col2, col3 = st.columns([1, 1, 1])
                
                with col1:
                    # Afficher la note telle qu'elle est stockée
                    try:
                        st.metric(f"📊 Note (stockée)", f"{float(score_total):.1f} / {float(max_score):.1f}")
                    except Exception:
                        st.metric(f"📊 Note (stockée)", f"{score_total} / {max_score}")

                # Optionnel : conversion explicite sur 20 (non automatique)
                with col2:
                    convert = st.checkbox("Convertir la note sur 20", value=False)
                    if convert:
                        try:
                            score_on_20 = (float(score_total) / float(max_score) * 20) if float(max_score) > 0 else 0
                            st.metric("🔢 Note /20 (convertie)", f"{score_on_20:.1f}/20")
                        except Exception:
                            st.warning("Impossible de convertir la note sur 20")
                    else:
                        st.write("")

                with col3:
                    st.metric("📈 Pourcentage", f"{percentage:.1f}%")
                
                st.divider()

                # === ACTIONS : recharger / relancer ===
                with st.expander("⚙️ Actions", expanded=False):
                    # Charger les dernières réponses enregistrées dans la correction pour modification
                    saved_rs = resultat.get('student_responses') or resultat.get('student_answers')
                    if isinstance(saved_rs, dict) and saved_rs:
                        if st.button("✏️ Charger les dernières réponses pour modification"):
                            for k, v in saved_rs.items():
                                st.session_state[k] = v
                            st.success("✅ Réponses chargées. Modifiez-les puis cliquez sur 'Terminer l'examen...' pour relancer la correction.")
                            st.rerun()

                    # Relancer la correction immédiatement avec les réponses courantes
                    if st.button("🔁 Relancer la correction maintenant"):
                        if not st.session_state.get('current_exam_id'):
                            st.error("❌ Erreur: Aucun examen n'est chargé. Impossible de relancer.")
                        else:
                            # Collecter les réponses actuelles dans la session
                            user_answers = {}
                            for key in st.session_state.keys():
                                if any(key.startswith(prefix) for prefix in ["ans_", "lang_", "writing_", "comp_", "lang_match_"]):
                                    user_answers[key] = st.session_state[key]

                            if len(user_answers) == 0:
                                st.warning("⚠️ Vous n'avez répondu à aucune question. Impossible de relancer la correction.")
                            else:
                                try:
                                    st.info(f"Debug: Relance avec exam_id={st.session_state.current_exam_id} student_id={st.session_state.current_user}")
                                    
                                    supabase.table("exams_streamlit").update({
                                        "student_responses": user_answers,
                                        "status": "resubmitted"
                                    }).eq("id", st.session_state.current_exam_id).execute()

                                    webhook_correction = os.getenv("N8N_CORRECTION_WEBHOOK", "http://localhost:5678/webhook-test/correction")
                                    requests.post(webhook_correction, json={
                                        "student_id": st.session_state.current_user,
                                        "exam_id": st.session_state.current_exam_id,
                                        "action": "start_correction"
                                    })

                                    st.session_state.waiting_for_correction = True
                                    st.info("⏳ Relance de la correction demandée. Veuillez patienter...")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erreur lors de la relance: {e}")
                                    st.write(f"Debug - exam_id: {st.session_state.current_exam_id}")
                                    st.write(f"Debug - student_id: {st.session_state.current_user}")

                # === FEEDBACK GÉNÉRAL ===
                feedback = resultat.get('feedback_general', 'Pas de feedback')
                with st.expander("💡 Conseils du prof IA", expanded=True):
                    st.info(feedback)
                
                st.divider()
                
                # === DÉTAILS PAR SECTION ===
                if corrections:
                    # Grouper par section (comp, lang, writing)
                    comp_items = [item for item in corrections if item['id'].startswith('comp_')]
                    lang_items = [item for item in corrections if item['id'].startswith('lang_')]
                    writing_items = [item for item in corrections if item['id'].startswith('writing_')]
                    
                    # ===== SECTION COMPREHENSION =====
                    if comp_items:
                        st.subheader("📖 Section Compréhension")
                        comp_score = sum(item.get('points_earned', 0) for item in comp_items)
                        comp_max = sum(item.get('points_earned', 0) + (1 if item.get('status') == 'correct' else 0.5 if item.get('status') == 'partial' else 0) for item in comp_items if item.get('status') in ['correct', 'partial'])
                        
                        st.progress(comp_score / max(comp_max, 1) if comp_max > 0 else 0)
                        st.caption(f"Score: {comp_score:.1f}/{comp_max:.1f} pts")
                        
                        for item in comp_items:
                            status = item.get('status', 'unknown')
                            status_icon = "✅" if status == "correct" else "⚠️" if status == "partial" else "❌"
                            points = item.get('points_earned', 0)

                            with st.expander(f"{status_icon} {item['id']} - {points} pts", expanded=False):
                                left, right = st.columns([2, 3])
                                with left:
                                    st.markdown("**Votre réponse :**")
                                    student_answer = _resolve_student_answer(item)
                                    st.text_area("", value=student_answer, key=f"view_{item['id']}", height=120)
                                    st.caption(f"Statut: {status} • Points: {points}")
                                with right:
                                    if item.get('correct_answer'):
                                        st.markdown("**Réponse attendue :**")
                                        st.success(item.get('correct_answer'))
                                    st.markdown("**Explication / Remarques du prof IA :**")
                                    st.info(item.get('explanation', 'N/A'))
                    
                    # ===== SECTION LANGUAGE =====
                    if lang_items:
                        st.subheader("🔤 Section Langue")
                        lang_score = sum(item.get('points_earned', 0) for item in lang_items)
                        lang_max = sum(item.get('points_earned', 0) + (1 if item.get('status') == 'correct' else 0.5 if item.get('status') == 'partial' else 0) for item in lang_items if item.get('status') in ['correct', 'partial'])
                        
                        st.progress(lang_score / max(lang_max, 1) if lang_max > 0 else 0)
                        st.caption(f"Score: {lang_score:.1f}/{lang_max:.1f} pts")
                        
                        for item in lang_items:
                            status = item.get('status', 'unknown')
                            status_icon = "✅" if status == "correct" else "⚠️" if status == "partial" else "❌"
                            points = item.get('points_earned', 0)

                            with st.expander(f"{status_icon} {item['id']} - {points} pts", expanded=False):
                                left, right = st.columns([2, 3])
                                with left:
                                    st.markdown("**Votre réponse :**")
                                    student_answer = _resolve_student_answer(item)
                                    st.text_area("", value=student_answer, key=f"view_{item['id']}", height=100)
                                    st.caption(f"Statut: {status} • Points: {points}")
                                with right:
                                    if item.get('correct_answer'):
                                        st.markdown("**Réponse attendue :**")
                                        st.success(item.get('correct_answer'))
                                    st.markdown("**Explication / Remarques :**")
                                    st.info(item.get('explanation', 'N/A'))
                    
                    # ===== SECTION WRITING =====
                    if writing_items:
                        st.subheader("✍️ Section Rédaction")
                        writing_score = sum(item.get('points_earned', 0) for item in writing_items)
                        writing_max = sum(item.get('points_earned', 0) + (1 if item.get('status') == 'correct' else 2 if item.get('status') == 'partial' else 0) for item in writing_items if item.get('status') in ['correct', 'partial'])
                        
                        st.progress(writing_score / max(writing_max, 1) if writing_max > 0 else 0)
                        st.caption(f"Score: {writing_score:.1f}/{writing_max:.1f} pts")
                        
                        for item in writing_items:
                            status = item.get('status', 'unknown')
                            status_icon = "✅" if status == "correct" else "⚠️" if status == "partial" else "❌"
                            points = item.get('points_earned', 0)

                            with st.expander(f"{status_icon} {item['id']} - {points} pts", expanded=False):
                                left, right = st.columns([2, 3])
                                with left:
                                    # Afficher la question et le texte associé
                                    question, texte = _get_question_and_text(item['id'], data if 'data' in locals() else st.session_state.get('exam_json', {}))
                                    st.markdown("**Question :**")
                                    st.info(question)
                                    if texte and texte != 'Texte non disponible':
                                        st.markdown("**Texte associé :**")
                                        st.write(texte)
                                    st.markdown("**Votre réponse (extrait) :**")
                                    student_answer = _resolve_student_answer(item)
                                    st.text_area("", value=student_answer, key=f"view_{item['id']}", height=200)
                                    st.caption(f"Statut: {status} • Points: {points}")
                                with right:
                                    st.markdown("**Conseils & Remarques du prof IA :**")
                                    st.warning(item.get('explanation', 'N/A'))
                    
                    st.divider()
                    
                    # === RÉSUMÉ FINAL ===
                    st.subheader("📝 Résumé de votre performance")
                    col_res1, col_res2, col_res3 = st.columns(3)
                    
                    correct_count = len([item for item in corrections if item.get('status') == 'correct'])
                    partial_count = len([item for item in corrections if item.get('status') == 'partial'])
                    incorrect_count = len([item for item in corrections if item.get('status') == 'incorrect'])
                    
                    with col_res1:
                        st.metric("✅ Correctes", correct_count)
                    with col_res2:
                        st.metric("⚠️ Partielles", partial_count)
                    with col_res3:
                        st.metric("❌ Incorrectes", incorrect_count)
                    
                    if convert:
                        st.info(f"💪 Note convertie : **{score_on_20:.1f}/20**")
                    else:
                        st.info(f"💪 Note stockée : **{score_total}/{max_score}** ({percentage:.1f}%)")
                else:
                    st.info("Les détails de correction seront disponibles bientôt.")
        else:
            progress_placeholder.progress(0.5)
            time.sleep(2)
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de la récupération des résultats: {str(e)}")