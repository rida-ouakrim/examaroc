import streamlit as st
import requests
import time
from supabase import create_client
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timezone

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
if 'is_waiting' not in st.session_state:
    st.session_state.is_waiting = False
if 'correction_data' not in st.session_state:
    st.session_state.correction_data = None
if 'exam_json' not in st.session_state:
    st.session_state.exam_json = None
if 'generation_start_time' not in st.session_state:
    st.session_state.generation_start_time = None

# --- HELPER: Normalize exam data structure from n8n ---
def normalize_exam_data(data):
    """Normalize differences between n8n output and Streamlit app expectations."""
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
    
    if not isinstance(data, dict):
        return data

    # Extract exam_content if it's a wrapper from n8n
    if 'exam_content' in data:
        data = data['exam_content']

    # 1. Normalize Comprehension
    if 'comprehension' in data:
        comp = data['comprehension']
        # text vs texte
        if 'text' in comp and 'texte' not in comp:
            comp['texte'] = comp['text']
        # questions vs exercices
        if 'questions' in comp and 'exercices' not in comp:
            if isinstance(comp['questions'], list):
                if len(comp['questions']) > 0 and 'questions' in comp['questions'][0]:
                    comp['exercices'] = comp['questions']
                else:
                    # Group questions by instruction
                    groups = []
                    current_instr = None
                    current_group = None
                    for q in comp['questions']:
                        # Ensure question has a stable ID with comp_ prefix
                        q_id = q.get('id', '')
                        if not q_id.startswith('comp_'):
                             q_id = f"comp_gen_{len(groups)}_{q_id or len(groups)}"
                        q['id'] = q_id
                        
                        instr = q.get('instruction', 'Questions')
                        if instr != current_instr:
                            current_instr = instr
                            current_group = {"id": str(len(groups)+1), "consigne": instr, "questions": []}
                            groups.append(current_group)
                        current_group['questions'].append(q)
                    comp['exercices'] = groups
        
        # Normalize nested question keys in Comprehension
        if 'exercices' in comp:
            for ex in comp['exercices']:
                if 'questions' in ex:
                    for q in ex['questions']:
                        if 'question_text' in q and 'question' not in q:
                            q['question'] = q['question_text']

    # 2. Normalize Language
    if 'language' in data:
        lang = data['language']
        if 'questions' in lang and 'exercices' not in lang:
             if isinstance(lang['questions'], list):
                if len(lang['questions']) > 0 and ('questions' in lang['questions'][0] or 'details' in lang['questions'][0]):
                    lang['exercices'] = lang['questions']
                else:
                    # Group questions by instruction
                    groups = []
                    current_instr = None
                    current_group = None
                    for q in lang['questions']:
                        # Ensure question has a stable ID with lang_ prefix
                        q_id = q.get('id', '')
                        if not q_id.startswith('lang_'):
                            q_id = f"lang_gen_{len(groups)}_{q_id or len(groups)}"
                        q['id'] = q_id
                        
                        instr = q.get('instruction', 'Language Tasks')
                        if instr != current_instr:
                            current_instr = instr
                            current_group = {"id": str(len(groups)+1), "consigne": instr, "questions": []}
                            groups.append(current_group)
                        current_group['questions'].append(q)
                    lang['exercices'] = groups
        
        # Normalize nested question keys in Language
        if 'exercices' in lang:
            for ex in lang['exercices']:
                for key in ['questions', 'details']:
                    if key in ex:
                        for q in ex[key]:
                            if 'question_text' in q and 'question' not in q:
                                q['question'] = q['question_text']

    # 3. Normalize Writing
    if 'writing' in data:
        writ = data['writing']
        # topics vs sujets
        if 'topics' in writ and 'sujets' not in writ:
            writ['sujets'] = writ['topics']
        
        if 'sujets' in writ:
            for sujet in writ['sujets']:
                # Ensure prefixed ID
                s_id = sujet.get('id', '')
                if not s_id.startswith('writing_'):
                    sujet['id'] = f"writing_{s_id or '1'}"
                # question_text vs sujet
                if 'question_text' in sujet and 'sujet' not in sujet:
                    sujet['sujet'] = sujet['question_text']
                # instruction vs type
                if 'instruction' in sujet and 'type' not in sujet:
                    sujet['type'] = sujet['instruction']

    return data

# --- HELPER: resolve student answer from correction item or from session_state fallbacks ---
def _resolve_student_answer(item):
    try:
        if isinstance(item, dict):
            # Check if the student answer is directly available
            if item.get('student_answer'):
                return item.get('student_answer')

            # Attempt to retrieve the answer from session state using the item ID
            item_id = item.get('id')
            if item_id and item_id in st.session_state:
                return st.session_state.get(item_id)

            # Handle legacy keys for language exercises
            if item_id and item_id.startswith('lang_'):
                ex = item_id[len('lang_'):]
                k_new = f"lang_{ex}_0"
                k_old = f"lang_match_{ex}"
                for k in (k_new, k_old):
                    if k in st.session_state:
                        return st.session_state.get(k)

    except Exception as e:
        st.error(f"Erreur lors de la récupération de la réponse: {str(e)}")
    return 'N/A'

def render_correction_item(item):
    """Render a single correction item with a professional comparison UI."""
    status = item.get('status', 'unknown')
    status_icon = "✅" if status == "correct" else "⚠️" if status == "partial" else "❌"
    color = "#28a745" if status == "correct" else "#ffc107" if status == "partial" else "#dc3545"
    bg_color = "#f0fff4" if status == "correct" else "#fffbeb" if status == "partial" else "#fff5f5"
    
    q_id = item.get('id', '?')
    points_earned = item.get('points_earned', 0)
    points_reserved = item.get('points_reserved') or item.get('points', 0)
    
    with st.container():
        st.markdown(f"""
        <div style="border-left: 5px solid {color}; background-color: {bg_color}; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span style="font-weight: bold; font-size: 1.1rem;">{status_icon} Question {q_id}</span>
                <span style="background-color: {color}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem;">
                    {points_earned} / {points_reserved} pts
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Details inside columns
        col_q, col_fb = st.columns([1, 1])
        
        with col_q:
            st.markdown("**❓ Question / Instruction :**")
            instruction = item.get('instruction')
            question_text = item.get('question')
            if instruction:
                st.caption(f"_{instruction}_")
            st.info(question_text if question_text else "Question non disponible")
            
            st.markdown("**👤 Votre Réponse :**")
            student_ans = item.get('student_answer') or _resolve_student_answer(item)
            st.code(student_ans if student_ans else "Pas de réponse", language=None)
            
        with col_fb:
            st.markdown("**🎯 Réponse Correcte :**")
            correct_ans = item.get('correct_answer', 'N/A')
            st.success(correct_ans if correct_ans else "N/A")
            
            st.markdown("**💡 Remarque du Prof IA :**")
            remark = item.get('ai_remark') or item.get('explanation') or "Pas de feedback spécifique."
            st.warning(remark)
        
        st.divider()

# --- FONCTION D'AUTHENTIFICATION ---
def verify_access_code(full_name, access_code):
    """Vérifier le code d'accès."""
    try:
        # Chercher dans une table 'access_codes'
        res = supabase.table("access_codes").select("*").eq("code", access_code).eq("active", True).execute()
        if res.data:
            st.session_state.authenticated = True
            st.session_state.user_name = full_name
            st.session_state.user_email = f"{full_name.lower().replace(' ', '.')}@exam.local"
            st.session_state.current_user = st.session_state.user_email
            return True
    except:
        pass
    
    # Fallback: codes de test
    if access_code == "EXAM2024":
        st.session_state.authenticated = True
        st.session_state.user_name = full_name
        st.session_state.user_email = f"{full_name.lower().replace(' ', '.')}@exam.local"
        st.session_state.current_user = st.session_state.user_email
        return True
    return False

def login_page():
    """Page de connexion professionnelle."""
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

# --- Custom CSS for Moroccan Exam Style ---
st.markdown("""
<style>
.exam-paper {
    background-color: white;
    padding: 40px;
    border: 1px solid #ddd;
    border-radius: 8px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    font-family: 'Times New Roman', Times, serif;
}
.instr-bold {
    font-weight: 900;
    font-size: 1.1rem;
    text-transform: uppercase;
    margin-top: 25px;
    margin-bottom: 10px;
    color: #1a1a1a;
}
.question-row {
    margin-left: 20px;
    margin-bottom: 15px;
}
.points-tag {
    font-weight: normal;
    font-style: italic;
    color: #555;
}
/* Hide default Streamlit padding for better paper look */
.block-container {
    padding-top: 2rem !important;
}
</style>
""", unsafe_allow_html=True)

# --- HELPER: Save current answers to Supabase ---
def save_answers():
    """Extract answers from session state and save to Supabase in real-time."""
    if st.session_state.get('current_exam_id'):
        user_answers = {}
        for key in st.session_state.keys():
            if any(key.startswith(prefix) for prefix in ["ans_", "lang_", "writing_", "comp_"]):
                user_answers[key] = st.session_state[key]
        
        if user_answers:
            try:
                supabase.table("exams_streamlit").update({
                    "student_responses": user_answers
                }).eq("id", st.session_state.current_exam_id).execute()
            except Exception:
                pass # Silent fail during typing to avoid interrupting the user

# --- PAGE PRINCIPALE ---
if not st.session_state.authenticated:
    login_page()
    st.stop()

# --- UI HEADER PROFESSIONNELLE ---
col_header1, col_header2, col_header3 = st.columns([3, 2, 1])
with col_header1:
    st.markdown("## 📚 Plateforme d'Examens")
with col_header2:
    st.markdown(f"**Utilisateur:** {st.session_state.user_name}")
with col_header3:
    if st.button("🚪 Déconnexion", key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.user_name = None
        st.session_state.user_email = None
        st.session_state.current_exam_id = None
        st.rerun()

st.divider()

# --- INITIALISER LES PARAMÈTRES ---
student_id = st.session_state.user_email

# --- INTERFACE PRINCIPALE ---
if not st.session_state.get('exam_json') and not st.session_state.get('correction_data'):
    tab_exams, tab_create = st.tabs(["📋 Mes Examens", "🆕 Générer un Examen"])

    with tab_exams:
        st.subheader("Vos Examens Disponibles")
        
        try:
            res = supabase.table("exams_streamlit").select("id, created_at, status").eq("student_id", student_id).order("created_at", desc=True).execute()
            exams = res.data if res.data else []
            
            if not exams:
                st.info("📭 Aucun examen trouvé. Générez-en un nouveau pour commencer!")
            else:
                for idx, exam in enumerate(exams):
                    col1, col2, col3 = st.columns([2, 1, 1])
                    
                    status_emoji = "✅" if exam['status'] == 'ready' else "⏳" if exam['status'] == 'submitted' else "📝"
                    
                    with col1:
                        st.markdown(f"{status_emoji} **Examen du {exam['created_at'][:10]}** - Status: `{exam['status']}`")
                    
                    with col2:
                        if exam['status'] == 'ready' and st.button("📖 Ouvrir", key=f"load_{idx}"):
                            full_exam = supabase.table("exams_streamlit").select("*").eq("id", exam['id']).execute()
                            if full_exam.data:
                                st.session_state.exam_json = full_exam.data[0].get('exam_content')
                                st.session_state.current_exam_id = exam['id']
                                st.session_state.current_user = student_id
                                
                                saved_answers = full_exam.data[0].get('student_responses') or {}
                                if isinstance(saved_answers, dict) and saved_answers:
                                    for k, v in saved_answers.items():
                                        if isinstance(k, str) and k.startswith('lang_match_'):
                                            ex = k[len('lang_match_'):]
                                            new_k = f"lang_{ex}_0"
                                            st.session_state[new_k] = v
                                        else:
                                            st.session_state[k] = v
                                
                                try:
                                    res_corr = supabase.table("exam_results").select("*").eq("exam_id", exam['id']).eq("student_id", student_id).order("created_at", desc=True).limit(1).execute()
                                    if res_corr.data:
                                        st.session_state.correction_data = res_corr.data[0]
                                except:
                                    pass
                                
                                st.success("✅ Examen chargé!")
                                st.rerun()
                    
                    with col3:
                        sub_col1, sub_col2 = st.columns(2)
                        with sub_col1:
                            if exam['status'] in ['submitted', 'ready'] and st.button("🔍 Voir", key=f"view_{idx}"):
                                res_corr = supabase.table("exam_results").select("*").eq("exam_id", exam['id']).eq("student_id", student_id).order("created_at", desc=True).limit(1).execute()
                                if res_corr.data:
                                    st.session_state.correction_data = res_corr.data[0]
                                    st.session_state.current_exam_id = exam['id']
                                    st.session_state.current_user = student_id
                                    st.rerun()
                                else:
                                    st.info("⏳ Aucune correction disponible.")
                        
                        with sub_col2:
                            if st.button("🗑️", key=f"delete_{idx}"):
                                st.session_state[f"confirm_delete_{exam['id']}"] = True
                        
                        if st.session_state.get(f"confirm_delete_{exam['id']}"):
                            st.warning("Supprimer cet examen ?")
                            c1, c2 = st.columns(2)
                            if c1.button("✅ Oui", key=f"yes_{idx}"):
                                try:
                                    supabase.table("exam_results").delete().eq("exam_id", exam['id']).execute()
                                    supabase.table("exams_streamlit").delete().eq("id", exam['id']).execute()
                                    st.session_state[f"confirm_delete_{exam['id']}"] = False
                                    st.success("Examen supprimé")
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erreur deletion: {e}")
                            if c2.button("❌ Non", key=f"no_{idx}"):
                                st.session_state[f"confirm_delete_{exam['id']}"] = False
                                st.rerun()
                                
        except Exception as e:
            st.error(f"⚠️ Erreur: {str(e)}")

    with tab_create:
        st.subheader("Générer un Nouvel Examen")
        
        col1, col2 = st.columns(2)
        with col1:
            filiere = st.selectbox("📚 Sélectionner la Filière", ["Science Physique", "SVT", "Sciences Math"])
        with col2:
            st.info("⏱️ Durée : **120 minutes** (Fixe)")
            duration = 120
        
        if st.button("🚀 Générer un nouvel examen", use_container_width=True):
            with st.spinner("Génération de votre examen..."):
                # Clear previous state
                st.session_state.exam_json = None
                st.session_state.correction_data = None
                st.session_state.current_exam_id = None
                st.session_state.generation_start_time = datetime.now(timezone.utc).isoformat()
                
                payload = {
                    "student_id": student_id,
                    "filiere": filiere,
                    "duration": duration
                }
                try:
                    response = requests.post(N8N_WEBHOOK, json=payload)
                    if response.status_code == 200:
                        raw_data = response.json()
                        exam_data = normalize_exam_data(raw_data)
                        st.session_state.exam_json = exam_data
                        
                        # Persist to Supabase immediately
                        try:
                            res_insert = supabase.table("exams_streamlit").insert({
                                "student_id": student_id,
                                "exam_content": exam_data,
                                "status": "ready"
                            }).execute()
                            if res_insert.data:
                                st.session_state.current_exam_id = res_insert.data[0]['id']
                            
                            st.success("✅ Examen généré et sauvegardé!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e_supa:
                            st.error(f"Examen généré mais erreur de sauvegarde: {e_supa}")
                            # Still show the exam even if save failed
                            st.rerun()
                    else:
                        st.error(f"Erreur n8n ({response.status_code}): {response.text}")
                except Exception as e:
                    st.error(f"Erreur lors de la génération: {str(e)}")

# --- LOGIQUE D'ATTENTE DE GÉNÉRATION (SUPPRIMÉE CAR SYNC) ---

# --- AFFICHAGE DE L'EXAMEN ---
if st.session_state.get("exam_json") and not st.session_state.get('correction_data'):
    import json
    
    # Bouton retour
    if st.button("← Retour aux examens"):
        st.session_state.exam_json = None
        st.session_state.current_exam_id = None
        st.rerun()
    
    data = st.session_state.exam_json
    
    # Apply normalization (handles both direct n8n response and loaded from supa)
    data = normalize_exam_data(data)

    if isinstance(data, str):
        try:
            # Clean possible markdown block
            cleaned_data = data.strip()
            if cleaned_data.startswith("```json"):
                cleaned_data = cleaned_data[7:]
            if cleaned_data.endswith("```"):
                cleaned_data = cleaned_data[:-3]
            data = json.loads(cleaned_data.strip())
            # Re-normalize after parsing string
            data = normalize_exam_data(data)
        except Exception as e:
            st.error(f"❌ Erreur lors du chargement de l'examen: {str(e)}")
            with st.expander("Détails techniques"):
                st.code(data)
            st.stop()

    # Re-check for list after string parsing (if string was a list)
    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    if not isinstance(data, dict):
        st.error("❌ Données d'examen invalides (Format non-dict)")
        with st.expander("🔍 Voir les données reçues (DEBUG)"):
            st.write(f"Type: `{type(data)}`")
            st.write(data)
        st.stop()
    
    if not any(k in data for k in ['comprehension', 'language', 'writing']):
        st.warning("⚠️ L'examen semble vide ou mal structuré.")
        with st.expander("Voir le contenu reçu"):
            st.json(data)
    
    title = data['info'].get('title') if 'info' in data else 'Examen'
    st.title(title)
    
    # Info examen
    if 'info' in data:
        col1, col2, col3 = st.columns(3)
        if 'duration' in data['info']:
            col1.metric("⏱️ Durée", data['info']['duration'])
        if 'total_points' in data['info']:
            col2.metric("📊 Points Total", data['info']['total_points'])
    
    # Onglets
    t1, t2, t3 = st.tabs(["I. COMPREHENSION (15 pts)", "II. LANGUAGE (15 pts)", "III. WRITING (10 pts)"])

    with t1:
        if 'comprehension' in data:
            comp = data['comprehension']
            if 'texte' in comp:
                st.markdown(f'<div style="background-color: #f9f9f9; padding: 20px; border-left: 5px solid #333; margin-bottom: 30px;">{comp["texte"]}</div>', unsafe_allow_html=True)
            
            if 'exercices' in comp:
                for idx_ex, exercice in enumerate(comp['exercices']):
                    abc = chr(65 + idx_ex) # A, B, C...
                    consigne = exercice.get('consigne', '').upper()
                    st.markdown(f'<div class="instr-bold">{abc}. {consigne}</div>', unsafe_allow_html=True)
                    
                    for q_idx, question in enumerate(exercice.get('questions', [])):
                        q_text = question.get('question', '')
                        q_id = question.get('id', f"comp_{idx_ex}_{q_idx}")
                        points = question.get('points', 0)
                        
                        st.markdown(f"**{q_idx + 1}.** {q_text} <span class='points-tag'>({points} pt{'s' if points > 1 else ''})</span>", unsafe_allow_html=True)
                        st.text_area("Réponse:", key=q_id, height=100, on_change=save_answers, label_visibility="collapsed")

    with t2:
        if 'language' in data:
            lang = data['language']
            
            if 'exercices' in lang:
                for idx_ex, exercice in enumerate(lang['exercices']):
                    abc = chr(65 + idx_ex) # A, B, C...
                    consigne = exercice.get('consigne', '').upper()
                    st.markdown(f'<div class="instr-bold">{abc}. {consigne}</div>', unsafe_allow_html=True)
                    
                    # Handle both 'details' (standard) and 'questions' (n8n variant)
                    qs = exercice.get('details') or exercice.get('questions') or []
                    for q_idx, q_item in enumerate(qs):
                        q_text = q_item.get('question', '')
                        q_id = q_item.get('id', f"lang_{idx_ex}_{q_idx}")
                        points = q_item.get('points', 0)
                        
                        st.markdown(f"**{q_idx + 1}.** {q_text} <span class='points-tag'>({points} pt{'s' if points > 1 else ''})</span>", unsafe_allow_html=True)
                        st.text_area("Réponse:", key=q_id, height=80, on_change=save_answers, label_visibility="collapsed")
                    
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
                        
                        # Assuming points for matching are at the exercise level or default to 0
                        matching_points = exercice['matching'].get('points', 0)
                        q_instr = exercice['matching'].get('instruction', '')
                        
                        if q_instr:
                            st.markdown(f"**{q_instr.upper()}**")
                        st.markdown(f"**Q:** Match the expressions with their functions <span class='points-tag'>({matching_points} pts)</span>", unsafe_allow_html=True)
                        st.text_area("Réponse (e.g., 1-A, 2-B):", key=f"lang_match_{idx_ex}_0", height=100, on_change=save_answers, label_visibility="collapsed")

    with t3:
        if 'writing' in data:
            writing = data['writing']
            
            if 'sujets' in writing:
                for idx_sujet, sujet in enumerate(writing['sujets']):
                    sujet_id = sujet.get('id', '?')
                    sujet_type = sujet.get('type', sujet.get('instruction', 'WRITING')).upper()
                    points = sujet.get('points', 0)
                    
                    abc = chr(65 + idx_sujet)
                    st.markdown(f'<div class="instr-bold">{abc}. {sujet_type} ({points} pts)</div>', unsafe_allow_html=True)
                    st.markdown(f"**{sujet.get('sujet', sujet.get('question_text', 'Pas de description'))}**")
                    st.text_area("Votre réponse:", key=sujet_id, height=300, on_change=save_answers, label_visibility="collapsed")
    
    # SOUMISSION
    st.divider()
    col_submit, col_info = st.columns([3, 2])
    
    with col_submit:
        if st.button("🏁 Terminer l'examen et voir ma note", use_container_width=True):
            if not st.session_state.get('current_exam_id'):
                st.error("❌ Erreur: Aucun examen n'est chargé.")
            else:
                user_answers = {}
                for key in st.session_state.keys():
                    if any(key.startswith(prefix) for prefix in ["ans_", "lang_", "writing_", "comp_"]):
                        user_answers[key] = st.session_state[key]
                
                if len(user_answers) == 0:
                    st.warning("⚠️ Veuillez répondre à au moins une question.")
                else:
                    try:
                        supabase.table("exams_streamlit").update({
                            "student_responses": user_answers,
                            "status": "submitted"
                        }).eq("id", st.session_state.current_exam_id).execute()
                        
                        webhook_correction = os.getenv("N8N_CORRECTION_WEBHOOK", "https://n8n.faysal.me/webhook/correction-exam")
                        requests.post(webhook_correction, json={
                            "student_id": st.session_state.current_user,
                            "exam_id": st.session_state.current_exam_id,
                            "answers": user_answers,
                            "action": "start_correction"
                        })
                        
                        st.session_state.waiting_for_correction = True
                        st.info("⏳ Correction en cours... Veuillez patienter.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erreur: {str(e)}")
    
    with col_info:
        st.info("💡 Cliquez sur 'Terminer' pour soumettre vos réponses.")

# --- ATTENTE DE CORRECTION ---
if st.session_state.get("waiting_for_correction"):
    placeholder = st.empty()
    
    with placeholder.container():
        st.warning("⏳ Correction en cours...")
        with st.spinner("Vérification des résultats..."):
            found = False
            for i in range(30):
                res = supabase.table("exam_results") \
                    .select("*") \
                    .eq("student_id", st.session_state.current_user) \
                    .eq("exam_id", st.session_state.current_exam_id) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute()
                
                if res.data:
                    st.session_state.correction_data = res.data[0]
                    st.session_state.waiting_for_correction = False
                    found = True
                    break
                
                time.sleep(3)
            
            if found:
                placeholder.empty()
                st.balloons()
                st.rerun()
            else:
                st.error("Délai dépassé. Veuillez réessayer.")
                st.session_state.waiting_for_correction = False

# --- AFFICHAGE DES RÉSULTATS ---
if st.session_state.get('correction_data'):
    # Lazy load exam_content if missing (e.g. when view is clicked directly from dashboard)
    if not st.session_state.get('exam_json') and st.session_state.get('current_exam_id'):
        try:
            res_exam = supabase.table("exams_streamlit").select("exam_content").eq("id", st.session_state.current_exam_id).execute()
            if res_exam.data:
                st.session_state.exam_json = res_exam.data[0].get('exam_content')
        except:
            pass

    if st.button("← Retour"):
        st.session_state.correction_data = None
        st.session_state.exam_json = None
        st.rerun()
    
    resultat = st.session_state.get('correction_data')
    if isinstance(resultat, str):
        try:
            resultat = json.loads(resultat)
        except:
            pass
    
    if isinstance(resultat, dict):
        if 'detailed_correction' in resultat and isinstance(resultat['detailed_correction'], str):
            try:
                resultat['detailed_correction'] = json.loads(resultat['detailed_correction'])
            except:
                pass
    
    st.balloons()
    st.success("### 🎉 Correction Terminée!")
    
    corrections = resultat.get('results') or resultat.get('detailed_correction') or []
    
    score_total = resultat.get('score_total') if resultat.get('score_total') is not None else sum(item.get('points_earned', 0) for item in corrections)
    max_score = resultat.get('max_score') if resultat.get('max_score') is not None else 40
    try:
        percentage = (float(score_total) / float(max_score) * 100) if float(max_score) > 0 else 0
    except:
        percentage = 0
    
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        try:
            st.metric(f"📊 Note", f"{float(score_total):.1f} / {float(max_score):.1f}")
        except:
            st.metric(f"📊 Note", f"{score_total} / {max_score}")

    with col2:
        convert = st.checkbox("Convertir la note sur 20", value=False)
        if convert:
            try:
                score_on_20 = (float(score_total) / float(max_score) * 20) if float(max_score) > 0 else 0
                st.metric("🔢 Note /20", f"{score_on_20:.1f}/20")
            except:
                st.warning("Impossible de convertir")
        else:
            st.write("")

    with col3:
        st.metric("📈 Pourcentage", f"{percentage:.1f}%")
    
    st.divider()

    # Actions
    with st.expander("⚙️ Actions", expanded=False):
        saved_rs = resultat.get('student_responses') or resultat.get('student_answers')
        if isinstance(saved_rs, dict) and saved_rs:
            if st.button("✏️ Charger les réponses pour modification"):
                for k, v in saved_rs.items():
                    if isinstance(k, str) and k.startswith('lang_match_'):
                        ex = k[len('lang_match_'):]
                        new_k = f"lang_{ex}_0"
                        st.session_state[new_k] = v
                    else:
                        st.session_state[k] = v
                st.session_state.correction_data = None
                st.success("✅ Réponses chargées.")
                st.rerun()

        if st.button("🔁 Relancer la correction"):
            user_answers = {}
            for key in st.session_state.keys():
                if any(key.startswith(prefix) for prefix in ["ans_", "lang_", "writing_", "comp_", "lang_match_"]):
                    user_answers[key] = st.session_state[key]

            if len(user_answers) == 0:
                st.warning("⚠️ Aucune réponse à relancer.")
            else:
                try:
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
                    st.info("⏳ Relance demandée...")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur: {e}")

    # Feedback général
    feedback = resultat.get('feedback_general', 'Pas de feedback')
    with st.expander("💡 Conseils du prof IA", expanded=True):
        st.info(feedback)
    
    st.divider()
    
    # Détails par section (Onglets)
    if corrections:
        comp_items = [item for item in corrections if str(item.get('id', '')).startswith('comp_')]
        lang_items = [item for item in corrections if str(item.get('id', '')).startswith('lang_')]
        writing_items = [item for item in corrections if str(item.get('id', '')).startswith('writing_')]
        other_items = [item for item in corrections if item not in comp_items and item not in lang_items and item not in writing_items]
        
        tab_titles = ["📖 Reading", "🔤 Language", "✍️ Writing"]
        if other_items:
            tab_titles.append("📝 Others")
        
        tabs = st.tabs(tab_titles)
        
        # --- TAB: READING ---
        with tabs[0]:
            # Afficher le texte de lecture s'il est disponible dans exam_json
            if st.session_state.get('exam_json'):
                data = st.session_state.get('exam_json')
                if isinstance(data, str):
                    try:
                        data = json.loads(data.strip("`json\n"))
                    except:
                        data = None
                
                if isinstance(data, dict) and 'comprehension' in data and 'texte' in data['comprehension']:
                    with st.expander("📖 Lire le texte à nouveau", expanded=False):
                        st.info(data['comprehension']['texte'])
            
            if comp_items:
                for item in comp_items:
                    render_correction_item(item)
            else:
                st.info("Aucune question de compréhension trouvée.")

        # --- TAB: LANGUAGE ---
        with tabs[1]:
            if lang_items:
                for item in lang_items:
                    render_correction_item(item)
            else:
                st.info("Aucune question de langue trouvée.")

        # --- TAB: WRITING ---
        with tabs[2]:
            if writing_items:
                for item in writing_items:
                    render_correction_item(item)
            else:
                st.info("Aucune section de rédaction trouvée.")

        # --- TAB: OTHERS (if any) ---
        if other_items:
            with tabs[3]:
                for item in other_items:
                    render_correction_item(item)
        
        st.divider()
        
        # Résumé
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
