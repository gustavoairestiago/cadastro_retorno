"""
Sistema de Gestão de Pendências KoBoToolbox - Streamlit App
===========================================================

ESTRUTURA DE ARQUIVOS NECESSÁRIA:
- app.py (este arquivo)
- users_config.json (configuração de usuários e projetos)
- audit_logs.json (logs de auditoria)
- processing_history.json (histórico de processamentos)
- requirements.txt (dependências)

INSTALAÇÃO:
pip install streamlit pandas requests python-dateutil openpyxl plotly

EXECUÇÃO:
streamlit run app.py
"""

import streamlit as st
import pandas as pd
import requests
import json
import time
import os
from datetime import datetime, timezone
from dateutil import parser as dtparser
from io import BytesIO
import hashlib
import shutil
import plotly.express as px
import plotly.graph_objects as go

# ==================== CONFIGURAÇÕES ====================

CONFIG_FILE = "users_config.json"
AUDIT_LOG_FILE = "audit_logs.json"
HISTORY_FILE = "processing_history.json"
BACKUP_DIR = "backups"
PAGE_SIZE = 10000

# Status que finalizam um caso
STATUS_FINALIZADOS = {"01", "04", "05"}

# Criar diretórios necessários
os.makedirs(BACKUP_DIR, exist_ok=True)

# ==================== FUNÇÕES DE PERSISTÊNCIA ====================

def ensure_file_exists(filepath, default_content):
    """Garante que arquivo existe, criando com conteúdo padrão se necessário."""
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_content, f, indent=2, ensure_ascii=False)

def backup_config():
    """Faz backup do arquivo de configuração antes de modificar."""
    if os.path.exists(CONFIG_FILE):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"config_{timestamp}.json")
        shutil.copy(CONFIG_FILE, backup_path)
        # Manter apenas os 10 backups mais recentes
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("config_")])
        if len(backups) > 10:
            for old_backup in backups[:-10]:
                os.remove(os.path.join(BACKUP_DIR, old_backup))

# ==================== FUNÇÕES DE AUDITORIA ====================

def log_audit(user, action, details):
    """
    Registra ação no log de auditoria.
    
    Args:
        user: username do usuário
        action: tipo de ação (login, upload_kobo, create_project, etc)
        details: dict com detalhes adicionais
    """
    ensure_file_exists(AUDIT_LOG_FILE, [])
    
    try:
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except:
        logs = []
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "user": user,
        "action": action,
        "details": details
    }
    
    logs.append(log_entry)
    
    # Manter apenas os últimos 1000 logs
    if len(logs) > 1000:
        logs = logs[-1000:]
    
    with open(AUDIT_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

def get_recent_logs(limit=50):
    """Retorna logs mais recentes."""
    ensure_file_exists(AUDIT_LOG_FILE, [])
    
    try:
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            logs = json.load(f)
        return logs[-limit:][::-1]  # Últimos logs, ordem reversa
    except:
        return []

# ==================== FUNÇÕES DE HISTÓRICO ====================

def save_processing_history(project_name, stats, user):
    """Salva histórico de processamento."""
    ensure_file_exists(HISTORY_FILE, {})
    
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except:
        history = {}
    
    if project_name not in history:
        history[project_name] = []
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "user": user,
        "stats": stats
    }
    
    history[project_name].append(entry)
    
    # Manter apenas últimos 100 registros por projeto
    if len(history[project_name]) > 100:
        history[project_name] = history[project_name][-100:]
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def get_project_history(project_name):
    """Retorna histórico de um projeto."""
    ensure_file_exists(HISTORY_FILE, {})
    
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
        return history.get(project_name, [])
    except:
        return []

# ==================== FUNÇÕES DE AUTENTICAÇÃO ====================

def hash_password(password):
    """Gera hash SHA256 da senha."""
    return hashlib.sha256(password.encode()).hexdigest()

def load_users_config():
    """Carrega configuração de usuários do arquivo JSON."""
    default_config = {
        "admins": [
            {
                "username": "admin",
                "password_hash": hash_password("admin123"),
                "name": "Administrador"
            }
        ],
        "projects": []
    }
    
    ensure_file_exists(CONFIG_FILE, default_config)
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Erro ao carregar configuração: {e}")
        return default_config

def save_users_config(config):
    """Salva configuração de usuários no arquivo JSON."""
    backup_config()  # Backup antes de salvar
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    # Forçar leitura do disco na próxima vez
    if 'config_cache' in st.session_state:
        del st.session_state['config_cache']

def authenticate_user(username, password):
    """
    Autentica usuário e retorna suas informações.
    
    Returns:
        tuple: (is_authenticated, user_data, is_admin)
    """
    config = load_users_config()
    password_hash = hash_password(password)
    
    # Verifica se é admin
    for admin in config.get("admins", []):
        if admin["username"] == username and admin["password_hash"] == password_hash:
            log_audit(username, "login", {"role": "admin", "success": True})
            return True, admin, True
    
    # Verifica se é analista de projeto
    for project in config.get("projects", []):
        if project["analyst_username"] == username and project["analyst_password_hash"] == password_hash:
            log_audit(username, "login", {"role": "analyst", "project": project["project_name"], "success": True})
            return True, project, False
    
    log_audit(username, "login", {"success": False})
    return False, None, False

# ==================== FUNÇÕES DE VALIDAÇÃO KOBO ====================

def validar_conexao_kobo(base_url, token, asset_id_master, asset_id_revisita):
    """
    Valida credenciais e IDs dos formulários KoBoToolbox.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json"
    }
    
    try:
        # Testa conexão geral
        response = requests.get(f"{base_url}/api/v2/assets/", headers=headers, timeout=10)
        if not response.ok:
            return False, f"Erro na autenticação: Token inválido ou URL incorreta (Status {response.status_code})"
        
        # Testa Form Master
        response = requests.get(f"{base_url}/api/v2/assets/{asset_id_master}/", headers=headers, timeout=10)
        if not response.ok:
            return False, f"Formulário Master não encontrado (ID: {asset_id_master})"
        
        # Testa Form Revisita
        response = requests.get(f"{base_url}/api/v2/assets/{asset_id_revisita}/", headers=headers, timeout=10)
        if not response.ok:
            return False, f"Formulário de Revisita não encontrado (ID: {asset_id_revisita})"
        
        return True, "Conexão validada com sucesso!"
    
    except requests.exceptions.Timeout:
        return False, "Timeout: Servidor KoBo não respondeu a tempo"
    except requests.exceptions.ConnectionError:
        return False, "Erro de conexão: Verifique a URL e sua conexão com a internet"
    except Exception as e:
        return False, f"Erro inesperado: {str(e)}"

# ==================== FUNÇÕES DO KOBO ====================

def baixar_dados_kobo(base_url, token, asset_id):
    """Baixa dados de um formulário KoBoToolbox."""
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json"
    }
    
    url = f"{base_url}/api/v2/assets/{asset_id}/data/"
    params = {"format": "json", "page_size": PAGE_SIZE}
    resultados = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    page = 1
    while True:
        status_text.text(f"Baixando página {page}...")
        
        try:
            resposta = requests.get(url, headers=headers, params=params, timeout=60)
            
            if not resposta.ok:
                raise RuntimeError(f"Erro HTTP {resposta.status_code}: {resposta.text}")
            
            dados = resposta.json()
            resultados.extend(dados.get("results", []))
            
            if not dados.get("next"):
                break
            
            url = dados["next"]
            params = None
            page += 1
            time.sleep(0.15)
            
        except Exception as e:
            raise RuntimeError(f"Erro ao baixar dados: {str(e)}")
    
    progress_bar.progress(100)
    status_text.text(f"✅ {len(resultados)} submissões baixadas")
    
    if resultados:
        df = pd.json_normalize(resultados, max_level=1)
    else:
        df = pd.DataFrame()
    
    for col in ["_id", "_uuid", "_submission_time"]:
        if col not in df.columns:
            df[col] = None
    
    return df

def processar_revisitas(df_revisitas, campos):
    """Consolida revisitas por domicílio."""
    if df_revisitas.empty:
        return pd.DataFrame({
            "household_id": [],
            "finalizado": [],
            "ultima_revisita": [],
            "tentativas": []
        })
    
    if "_submission_time" in df_revisitas.columns:
        df_revisitas["_submission_dt"] = pd.to_datetime(
            df_revisitas["_submission_time"].apply(
                lambda s: dtparser.parse(s).astimezone(timezone.utc) if pd.notna(s) else pd.NaT
            ),
            errors="coerce"
        )
    else:
        df_revisitas["_submission_dt"] = pd.NaT
    
    campo_status = campos.get("status_revisita", "info_gerais/status")
    df_revisitas["_finalizado"] = (
        df_revisitas[campo_status]
        .astype(str)
        .str.lower()
        .isin(STATUS_FINALIZADOS)
    )
    
    agregacao = {
        "_finalizado": "max",
        "_submission_dt": "max"
    }
    
    campo_tentativa = campos.get("tentativa_n", "tentativa_n")
    if campo_tentativa in df_revisitas.columns:
        agregacao[campo_tentativa] = "max"
    
    df_agregado = (
        df_revisitas
        .groupby("household_id", dropna=False)
        .agg(agregacao)
        .reset_index()
        .rename(columns={
            "_finalizado": "finalizado",
            "_submission_dt": "ultima_revisita",
            campo_tentativa: "tentativas"
        })
    )
    
    return df_agregado

def criar_label_endereco(row, campos):
    """Cria label com índice e endereço."""
    idx = str(row["_index_sel"])
    
    partes = []
    for campo_nome in ["endereco", "numero", "modificador", "complemento"]:
        campo = campos.get(campo_nome, "")
        if campo and campo in row.index:
            valor = row[campo]
            if pd.notna(valor) and str(valor).strip():
                partes.append(str(valor))
    
    endereco_completo = ", ".join(partes)
    return f"{idx} — {endereco_completo}" if endereco_completo else idx

def gerenciar_midia_kobo(base_url, token, asset_id, nome_arquivo):
    """Remove arquivo de mídia existente com o mesmo nome."""
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    url = f"{base_url}/api/v2/assets/{asset_id}/files.json"
    
    resposta = requests.get(url, headers=headers, timeout=60)
    
    if not resposta.ok:
        return
    
    arquivos = resposta.json()
    
    for item in arquivos.get("results", []):
        tipo = item.get("file_type") or item.get("data_type")
        if tipo != "form_media":
            continue
        
        nomes = {
            str(item.get("filename", "")).strip().lower(),
            str((item.get("metadata") or {}).get("filename", "")).strip().lower()
        }
        
        if nome_arquivo.lower() in nomes:
            uid = item.get("uid") or item.get("id")
            if uid:
                url_delete = f"{base_url}/api/v2/assets/{asset_id}/files/{uid}.json"
                requests.delete(url_delete, headers=headers, timeout=60)

def fazer_upload_midia(base_url, token, asset_id, arquivo_bytes, nome_arquivo):
    """Faz upload de arquivo como mídia do formulário."""
    url = f"{base_url}/api/v2/assets/{asset_id}/files.json"
    headers_upload = {"Authorization": f"Token {token}"}
    
    files = {"content": (nome_arquivo, arquivo_bytes, "text/csv")}
    data = {
        "file_type": "form_media",
        "description": "Lista de pendências atualizada automaticamente",
        "metadata": json.dumps({"filename": nome_arquivo})
    }
    
    resposta = requests.post(url, headers=headers_upload, files=files, data=data, timeout=120)
    
    if not resposta.ok:
        raise RuntimeError(f"Erro no upload [{resposta.status_code}]: {resposta.text}")
def processar_pendencias(project_config):
    """
    Processa pendências de um projeto específico.
    
    Returns:
        tuple: (df_pendencias, estatisticas, arquivo_excel_bytes, arquivo_csv_bytes)
    """
    base_url = project_config["kobo_base_url"]
    token = project_config["kobo_token"]
    asset_id_master = project_config["asset_id_master"]
    asset_id_revisita = project_config["asset_id_revisita"]
    campos = project_config.get("campos", {})
    
    # 1. Baixar dados
    st.subheader("📥 Baixando dados dos formulários")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Formulário Master (1ª visita)**")
        df_master = baixar_dados_kobo(base_url, token, asset_id_master)
    
    with col2:
        st.write("**Formulário de Revisitas**")
        df_revisitas = baixar_dados_kobo(base_url, token, asset_id_revisita)
    
    # 2. Validar campos
    campo_household_id = campos.get("household_id", "household_id")
    if campo_household_id not in df_master.columns:
        raise RuntimeError(f"Campo '{campo_household_id}' não encontrado no formulário Master")
    
    # 3. Processar revisitas
    st.subheader("🔄 Processando dados")
    df_revisitas_agregado = processar_revisitas(df_revisitas, campos)
    
    # 4. Limpar duplicatas do Master
    if "_submission_time" in df_master.columns:
        df_master["_submission_dt"] = pd.to_datetime(
            df_master["_submission_time"].apply(
                lambda s: dtparser.parse(s).astimezone(timezone.utc) if pd.notna(s) else pd.NaT
            ),
            errors="coerce"
        )
        df_master = df_master.sort_values("_submission_dt")
    
    df_master = df_master.drop_duplicates(subset=[campo_household_id], keep="last")
    
    # Remove casos já finalizados na primeira visita
    campo_status_master = campos.get("status_master", "info_gerais/status")
    primeira_entrevista_completa = 0
    if campo_status_master in df_master.columns:
        primeira_entrevista_completa = (df_master[campo_status_master] == "01").sum()
        df_master = df_master[df_master[campo_status_master] != "01"]
    
    # 5. Consolidar dados
    idx_col = "_index" if "_index" in df_master.columns and df_master["_index"].notna().any() else "_id"
    
    colunas_interesse = [campo_household_id, idx_col]
    for campo in ["censo", "subsetor", "tipo_imovel", "tipo_logradouro", "endereco", 
                  "numero", "modificador", "complemento", "referencia"]:
        campo_completo = campos.get(campo, f"info_gerais/{campo}")
        if campo_completo in df_master.columns:
            colunas_interesse.append(campo_completo)
    
    df_base = df_master[colunas_interesse].copy()
    df_base = df_base.rename(columns={idx_col: "_index_sel"})
    
    df_consolidado = df_base.merge(
        df_revisitas_agregado,
        how="left",
        left_on=campo_household_id,
        right_on="household_id"
    )
    
    df_consolidado["finalizado"] = df_consolidado["finalizado"].fillna(False).astype(bool)
    df_consolidado["status_consolidado"] = df_consolidado["finalizado"].apply(
        lambda x: "Concluído" if x else "Aberto"
    )
    
    # 6. Filtrar pendências
    df_pendencias = df_consolidado[df_consolidado["status_consolidado"] == "Aberto"].copy()
    
    df_pendencias["name"] = df_pendencias["_index_sel"].astype(str)
    df_pendencias["label"] = df_pendencias.apply(lambda row: criar_label_endereco(row, campos), axis=1)
    
    if "ultima_revisita" in df_pendencias.columns:
        df_pendencias["ultima_revisita"] = (
            pd.to_datetime(df_pendencias["ultima_revisita"])
            .dt.strftime("%Y-%m-%d %H:%M:%S")
        )
    
    # 7. Preparar estatísticas
    abertos = len(df_pendencias)
    concluidos = (df_consolidado["status_consolidado"] == "Concluído").sum()
    
    estatisticas = {
        "total_master": int(len(df_master) + primeira_entrevista_completa),
        "primeira_completa": int(primeira_entrevista_completa),
        "abertos": int(abertos),
        "concluidos_revisita": int(concluidos),
        "total_revisitas": int(len(df_revisitas))
    }
    
    # 8. Gerar arquivo Excel (com fallback para CSV se openpyxl não estiver disponível)
    arquivo_excel = None
    try:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_pendencias.to_excel(writer, sheet_name='Pendências', index=False)
        arquivo_excel = output.getvalue()
    except ImportError:
        st.warning("⚠️ Biblioteca openpyxl não encontrada. Download disponível apenas em CSV.")
    
    # 9. Gerar CSV para upload
    csv_buffer = BytesIO()
    df_pendencias.to_csv(csv_buffer, index=False, encoding='utf-8')
    arquivo_csv = csv_buffer.getvalue()
    
    return df_pendencias, estatisticas, arquivo_excel, arquivo_csv

# ==================== FUNÇÕES DE VISUALIZAÇÃO ====================

def criar_dashboard_graficos(history_data, stats):
    """Cria dashboard com gráficos de evolução."""
    if not history_data or len(history_data) < 0:
        st.info("📊 Dashboard de evolução estará disponível após mais processamentos.")
        return
    
    # Preparar dados para gráficos
    df_history = pd.DataFrame(history_data)
    df_history['date'] = pd.to_datetime(df_history['date'])
    
    # Extrair estatísticas
    df_history['pendentes'] = df_history['stats'].apply(lambda x: x.get('abertos', 0))
    df_history['concluidos'] = df_history['stats'].apply(lambda x: x.get('concluidos_revisita', 0))
    df_history['total'] = df_history['stats'].apply(lambda x: x.get('total_master', 0))
    
    # Gráfico 1: Evolução de Pendências
    col1, col2 = st.columns(2)
    
    with col1:
        fig_line = px.line(
            df_history, 
            x='date', 
            y='pendentes',
            title='📉 Evolução de Pendências ao Longo do Tempo',
            labels={'date': 'Data', 'pendentes': 'Número de Pendências'},
            markers=True
        )
        fig_line.update_traces(line_color='#FF4B4B')
        st.plotly_chart(fig_line, use_container_width=True)
    
    with col2:
        # Gráfico 2: Status Atual (Pizza)
        fig_pie = go.Figure(data=[go.Pie(
            labels=['Pendentes', 'Concluídas em Revisita', 'Completas 1ª Visita'],
            values=[stats['abertos'], stats['concluidos_revisita'], stats['primeira_completa']],
            hole=0.4,
            marker_colors=['#FF4B4B', '#00CC88', '#0068C9']
        )])
        fig_pie.update_layout(title_text='📊 Distribuição de Status Atual')
        st.plotly_chart(fig_pie, use_container_width=True)
    
    # Gráfico 3: Barras comparativas
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=df_history['date'],
        y=df_history['pendentes'],
        name='Pendentes',
        marker_color='#FF4B4B'
    ))
    fig_bar.add_trace(go.Bar(
        x=df_history['date'],
        y=df_history['concluidos'],
        name='Concluídos',
        marker_color='#00CC88'
    ))
    fig_bar.update_layout(
        title='📊 Comparação: Pendentes vs Concluídos',
        xaxis_title='Data',
        yaxis_title='Quantidade',
        barmode='group'
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# ==================== INTERFACE STREAMLIT ====================

def main():
    st.set_page_config(
        page_title="Sistema de Pendências KoBoToolbox",
        page_icon="📋",
        layout="wide"
    )
    
    # Inicializar estado da sessão
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user_data' not in st.session_state:
        st.session_state.user_data = None
    if 'is_admin' not in st.session_state:
        st.session_state.is_admin = False
    
    # ==================== TELA DE LOGIN ====================
    
    if not st.session_state.authenticated:
        st.title("🔐 Sistema de Gestão de Pendências KoBoToolbox")
        st.markdown("---")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            st.subheader("Login")
            
            username = st.text_input("Usuário", key="login_username")
            password = st.text_input("Senha", type="password", key="login_password")
            
            if st.button("Entrar", type="primary", use_container_width=True):
                if username and password:
                    authenticated, user_data, is_admin = authenticate_user(username, password)
                    
                    if authenticated:
                        st.session_state.authenticated = True
                        st.session_state.user_data = user_data
                        st.session_state.is_admin = is_admin
                        st.rerun()
                    else:
                        st.error("❌ Usuário ou senha incorretos")
                else:
                    st.warning("⚠️ Preencha usuário e senha")
        
        return
    
    # ==================== PAINEL ADMINISTRATIVO ====================
    
    if st.session_state.is_admin:
        st.title("👨‍💼 Painel Administrativo")
        st.markdown(f"**Bem-vindo(a), {st.session_state.user_data['name']}!**")
        
        if st.button("🚪 Sair", type="secondary"):
            log_audit(st.session_state.user_data['username'], "logout", {})
            st.session_state.authenticated = False
            st.session_state.user_data = None
            st.session_state.is_admin = False
            st.rerun()
        
        st.markdown("---")
        
        config = load_users_config()
        
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Projetos", "➕ Novo Projeto", "🔑 Gerenciar Admins", "📜 Logs de Auditoria"])
        
        # TAB 1: Listar Projetos
        with tab1:
            st.subheader("Projetos Cadastrados")
            
            if not config.get("projects"):
                st.info("Nenhum projeto cadastrado ainda.")
            else:
                for idx, project in enumerate(config["projects"]):
                    with st.expander(f"🗂️ {project['project_name']}", expanded=False):
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.write(f"**Analista:** {project['analyst_name']}")
                            st.write(f"**Usuário:** {project['analyst_username']}")
                            st.write(f"**URL KoBo:** {project['kobo_base_url']}")
                            st.write(f"**Form Master ID:** {project['asset_id_master']}")
                            st.write(f"**Form Revisita ID:** {project['asset_id_revisita']}")
                        
                        with col2:
                            if st.button("🗑️ Remover", key=f"remove_{idx}"):
                                log_audit(
                                    st.session_state.user_data['username'],
                                    "delete_project",
                                    {"project_name": project['project_name']}
                                )
                                config["projects"].pop(idx)
                                save_users_config(config)
                                st.success("Projeto removido!")
                                time.sleep(1)
                                st.rerun()
        
        # TAB 2: Novo Projeto
        with tab2:
            st.subheader("Cadastrar Novo Projeto")
            
            with st.form("new_project_form"):
                project_name = st.text_input("Nome do Projeto*")
                analyst_name = st.text_input("Nome do Analista*")
                analyst_username = st.text_input("Usuário do Analista*")
                analyst_password = st.text_input("Senha do Analista*", type="password")
                
                st.markdown("**Configurações KoBoToolbox**")
                kobo_base_url = st.selectbox(
                    "URL da Instância KoBo*",
                    ["https://eu.kobotoolbox.org", "https://kf.kobotoolbox.org", 
                     "https://kobo.humanitarianresponse.info"]
                )
                kobo_token = st.text_input("Token da API*", type="password", 
                                          help="Gere em: https://[instancia]/token/")
                asset_id_master = st.text_input("ID do Formulário Master*",
                                               help="Encontre em: KoBo > Formulário > Detalhes do projeto")
                asset_id_revisita = st.text_input("ID do Formulário de Revisita*",
                                                 help="Encontre em: KoBo > Formulário > Detalhes do projeto")
                
                col_submit, col_validate = st.columns([1, 1])
                
                with col_validate:
                    validar = st.form_submit_button("🔍 Validar Conexão", type="secondary")
                
                with col_submit:
                    submitted = st.form_submit_button("✅ Cadastrar Projeto", type="primary")
                
                if validar:
                    if all([kobo_base_url, kobo_token, asset_id_master, asset_id_revisita]):
                        with st.spinner("Validando conexão com KoBoToolbox..."):
                            is_valid, message = validar_conexao_kobo(
                                kobo_base_url, kobo_token, asset_id_master, asset_id_revisita
                            )
                            
                            if is_valid:
                                st.success(f"✅ {message}")
                            else:
                                st.error(f"❌ {message}")
                    else:
                        st.warning("⚠️ Preencha as configurações do KoBo para validar")
                
                if submitted:
                    if all([project_name, analyst_name, analyst_username, analyst_password, 
                           kobo_token, asset_id_master, asset_id_revisita]):
                        
                        # Validar antes de cadastrar
                        with st.spinner("Validando credenciais..."):
                            is_valid, message = validar_conexao_kobo(
                                kobo_base_url, kobo_token, asset_id_master, asset_id_revisita
                            )
                        
                        if not is_valid:
                            st.error(f"❌ Validação falhou: {message}")
                            st.warning("⚠️ Corrija as credenciais antes de cadastrar o projeto.")
                        else:
                            new_project = {
                                "project_name": project_name,
                                "analyst_name": analyst_name,
                                "analyst_username": analyst_username,
                                "analyst_password_hash": hash_password(analyst_password),
                                "kobo_base_url": kobo_base_url,
                                "kobo_token": kobo_token,
                                "asset_id_master": asset_id_master,
                                "asset_id_revisita": asset_id_revisita,
                                "campos": {
                                    "household_id": "household_id",
                                    "status_master": "info_gerais/status",
                                    "status_revisita": "info_gerais/status",
                                    "tentativa_n": "tentativa_n",
                                    "censo": "info_gerais/setor_censo",
                                    "subsetor": "info_gerais/subsetor",
                                    "tipo_imovel": "info_gerais/tipo_imovel",
                                    "tipo_logradouro": "info_gerais/tipo_logradouro",
                                    "endereco": "info_gerais/endereco_name",
                                    "numero": "info_gerais/numero",
                                    "modificador": "info_gerais/modificador",
                                    "complemento": "info_gerais/complemento",
                                    "referencia": "referencia"
                                }
                            }
                            
                            config["projects"].append(new_project)
                            save_users_config(config)
                            
                            log_audit(
                                st.session_state.user_data['username'],
                                "create_project",
                                {
                                    "project_name": project_name,
                                    "analyst_username": analyst_username
                                }
                            )
                            
                            st.success(f"✅ Projeto '{project_name}' cadastrado com sucesso!")
                            time.sleep(2)
                            st.rerun()
                    else:
                        st.error("❌ Preencha todos os campos obrigatórios")
        
        # TAB 3: Gerenciar Admins
        with tab3:
            st.subheader("Administradores")
            
            for idx, admin in enumerate(config.get("admins", [])):
                st.write(f"👤 **{admin['name']}** (usuário: {admin['username']})")
            
            st.markdown("---")
            st.subheader("Adicionar Novo Administrador")
            
            with st.form("new_admin_form"):
                admin_name = st.text_input("Nome do Admin*")
                admin_username = st.text_input("Usuário*")
                admin_password = st.text_input("Senha*", type="password")
                
                submitted = st.form_submit_button("➕ Adicionar Admin")
                
                if submitted:
                    if all([admin_name, admin_username, admin_password]):
                        new_admin = {
                            "username": admin_username,
                            "password_hash": hash_password(admin_password),
                            "name": admin_name
                        }
                        
                        if "admins" not in config:
                            config["admins"] = []
                        
                        config["admins"].append(new_admin)
                        save_users_config(config)
                        
                        log_audit(
                            st.session_state.user_data['username'],
                            "create_admin",
                            {"new_admin_username": admin_username}
                        )
                        
                        st.success("✅ Administrador adicionado!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Preencha todos os campos")
        
        # TAB 4: Logs de Auditoria
        with tab4:
            st.subheader("📜 Logs de Auditoria")
            
            logs = get_recent_logs(100)
            
            if logs:
                # Filtros
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    users = list(set([log['user'] for log in logs]))
                    selected_user = st.selectbox("Filtrar por Usuário", ["Todos"] + users)
                
                with col2:
                    actions = list(set([log['action'] for log in logs]))
                    selected_action = st.selectbox("Filtrar por Ação", ["Todas"] + actions)
                
                with col3:
                    limit = st.number_input("Mostrar últimos N logs", min_value=10, max_value=100, value=50)
                
                # Filtrar logs
                filtered_logs = logs[:limit]
                if selected_user != "Todos":
                    filtered_logs = [log for log in filtered_logs if log['user'] == selected_user]
                if selected_action != "Todas":
                    filtered_logs = [log for log in filtered_logs if log['action'] == selected_action]
                
                # Exibir logs
                for log in filtered_logs:
                    timestamp = datetime.fromisoformat(log['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
                    
                    action_icons = {
                        "login": "🔐",
                        "logout": "🚪",
                        "create_project": "➕",
                        "delete_project": "🗑️",
                        "create_admin": "👨‍💼",
                        "process_pendencias": "🔄",
                        "upload_kobo": "☁️"
                    }
                    
                    icon = action_icons.get(log['action'], "📝")
                    
                    with st.expander(f"{icon} {timestamp} - {log['user']} - {log['action']}"):
                        st.json(log['details'])
            else:
                st.info("Nenhum log registrado ainda.")
        
        return
    
    # ==================== PAINEL DO ANALISTA ====================
    
    project_data = st.session_state.user_data
    
    st.title("📊 Gestão de Pendências")
    st.markdown(f"**Projeto:** {project_data['project_name']}")
    st.markdown(f"**Analista:** {project_data['analyst_name']}")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🚪 Sair", type="secondary"):
            log_audit(project_data['analyst_username'], "logout", {})
            st.session_state.authenticated = False
            st.session_state.user_data = None
            st.session_state.is_admin = False
            st.rerun()
    
    st.markdown("---")
    
    # Inicializar estados da sessão para controlar upload
    if 'pendencias_processadas' not in st.session_state:
        st.session_state.pendencias_processadas = False
    if 'dados_pendencias' not in st.session_state:
        st.session_state.dados_pendencias = None
    if 'upload_sucesso' not in st.session_state:
        st.session_state.upload_sucesso = False
    
    # Botão principal
    if st.button("🔄 Atualizar Pendências", type="primary", use_container_width=True):
        st.session_state.upload_sucesso = False  # Reset do estado de upload
        try:
            with st.spinner("Processando dados..."):
                df_pendencias, stats, arquivo_excel, arquivo_csv = processar_pendencias(project_data)
            
            # Armazenar dados na sessão
            st.session_state.pendencias_processadas = True
            st.session_state.dados_pendencias = {
                'df_pendencias': df_pendencias,
                'stats': stats,
                'arquivo_excel': arquivo_excel,
                'arquivo_csv': arquivo_csv
            }
            
            # Salvar no histórico
            save_processing_history(
                project_data['project_name'],
                stats,
                project_data['analyst_username']
            )
            
            # Log de auditoria
            log_audit(
                project_data['analyst_username'],
                "process_pendencias",
                {
                    "project": project_data['project_name'],
                    "pendencias": stats['abertos'],
                    "concluidos": stats['concluidos_revisita']
                }
            )
            
            st.success("✅ Processamento concluído!")
        
        except Exception as e:
            st.error(f"❌ Erro ao processar pendências: {str(e)}")
            st.exception(e)
            st.session_state.pendencias_processadas = False
    
    # Exibir resultados se já foram processados
    if st.session_state.pendencias_processadas and st.session_state.dados_pendencias:
        dados = st.session_state.dados_pendencias
        df_pendencias = dados['df_pendencias']
        stats = dados['stats']
        arquivo_excel = dados['arquivo_excel']
        arquivo_csv = dados['arquivo_csv']
        
        # Botão de upload para KoBo no topo
        st.markdown("---")
        col_upload1, col_upload2 = st.columns([2, 1])
        
        with col_upload1:
            if st.button("☁️ Atualizar Lista no KoBoToolbox", use_container_width=True, type="secondary", key="btn_upload_kobo"):
                with st.spinner("Enviando para KoBoToolbox..."):
                    try:
                        gerenciar_midia_kobo(
                            project_data["kobo_base_url"],
                            project_data["kobo_token"],
                            project_data["asset_id_revisita"],
                            "pendencias.csv"
                        )
                        
                        fazer_upload_midia(
                            project_data["kobo_base_url"],
                            project_data["kobo_token"],
                            project_data["asset_id_revisita"],
                            arquivo_csv,
                            "pendencias.csv"
                        )
                        
                        # Log de auditoria
                        log_audit(
                            project_data['analyst_username'],
                            "upload_kobo",
                            {
                                "project": project_data['project_name'],
                                "records_uploaded": len(df_pendencias)
                            }
                        )
                        
                        st.session_state.upload_sucesso = True
                        st.rerun()  # Atualiza a página para mostrar mensagem de sucesso
                        
                    except Exception as e:
                        st.error(f"❌ Erro ao atualizar no KoBoToolbox: {str(e)}")
        
        with col_upload2:
            st.metric("Pendências a enviar", len(df_pendencias))
        
        # Mensagem de sucesso do upload (persistente)
        if st.session_state.upload_sucesso:
            st.success("✅ Lista atualizada no KoBoToolbox com sucesso!")
            st.info(f"📋 {len(df_pendencias)} pendências enviadas para o formulário de revisitas.")
        
        st.markdown("---")
        st.subheader("📈 Estatísticas")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Master", stats["total_master"])
        
        with col2:
            st.metric("Completas 1ª Visita", stats["primeira_completa"])
        
        with col3:
            st.metric("Concluídas Revisita", stats["concluidos_revisita"])
        
        with col4:
            st.metric("Pendentes", stats["abertos"], 
                     delta=f"-{stats['concluidos_revisita']}" if stats['concluidos_revisita'] > 0 else None,
                     delta_color="inverse")
        
        # Dashboard com gráficos
        st.markdown("---")
        st.subheader("📊 Dashboard de Evolução")
        history = get_project_history(project_data['project_name'])
        criar_dashboard_graficos(history, stats)
        
        # Exibir tabela de pendências
        st.markdown("---")
        if not df_pendencias.empty:
            st.subheader("📋 Lista de Pendências")
            st.dataframe(df_pendencias, use_container_width=True, height=400)
            
            # Timestamp para nome do arquivo
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Download Excel (se disponível)
            if arquivo_excel:
                nome_arquivo_excel = f"pendencias_{project_data['project_name']}_{timestamp}.xlsx"
                st.download_button(
                    label="📥 Baixar Excel",
                    data=arquivo_excel,
                    file_name=nome_arquivo_excel,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )
            
            # Download CSV (sempre disponível)
            nome_arquivo_csv = f"pendencias_{project_data['project_name']}_{timestamp}.csv"
            st.download_button(
                label="📥 Baixar CSV" if arquivo_excel else "📥 Baixar Relatório (CSV)",
                data=arquivo_csv,
                file_name=nome_arquivo_csv,
                mime="text/csv",
                type="secondary" if arquivo_excel else "primary",
                use_container_width=True
            )
        else:
            st.info("🎉 Não há pendências! Todos os casos foram concluídos.")
            
if __name__ == "__main__":
    main()
