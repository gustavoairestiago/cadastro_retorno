"""
Sistema de Gestão de Pendências KoBoToolbox - Streamlit App
===========================================================

ESTRUTURA DE ARQUIVOS NECESSÁRIA:
- app.py (este arquivo)
- users_config.json (configuração de usuários e projetos)
- requirements.txt (dependências)

INSTALAÇÃO:
pip install streamlit pandas requests python-dateutil openpyxl

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
import openpyxl

# ==================== CONFIGURAÇÕES ====================

CONFIG_FILE = "users_config.json"
PAGE_SIZE = 10000

# Status que finalizam um caso
STATUS_FINALIZADOS = {"01", "04", "05"}

# ==================== FUNÇÕES DE AUTENTICAÇÃO ====================

def hash_password(password):
    """Gera hash SHA256 da senha."""
    return hashlib.sha256(password.encode()).hexdigest()

def load_users_config():
    """Carrega configuração de usuários do arquivo JSON."""
    if not os.path.exists(CONFIG_FILE):
        # Cria arquivo padrão se não existir
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
        save_users_config(default_config)
        return default_config
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users_config(config):
    """Salva configuração de usuários no arquivo JSON."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

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
            return True, admin, True
    
    # Verifica se é analista de projeto
    for project in config.get("projects", []):
        if project["analyst_username"] == username and project["analyst_password_hash"] == password_hash:
            return True, project, False
    
    return False, None, False

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
        tuple: (df_pendencias, estatisticas, arquivo_excel_bytes)
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
        "total_master": len(df_master) + primeira_entrevista_completa,
        "primeira_completa": primeira_entrevista_completa,
        "abertos": abertos,
        "concluidos_revisita": concluidos,
        "total_revisitas": len(df_revisitas)
    }
    
    # 8. Gerar arquivo Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_pendencias.to_excel(writer, sheet_name='Pendências', index=False)
    
    arquivo_excel = output.getvalue()
    
    # 9. Gerar CSV para upload
    csv_buffer = BytesIO()
    df_pendencias.to_csv(csv_buffer, index=False, encoding='utf-8')
    arquivo_csv = csv_buffer.getvalue()
    
    return df_pendencias, estatisticas, arquivo_excel, arquivo_csv

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
            st.session_state.authenticated = False
            st.session_state.user_data = None
            st.session_state.is_admin = False
            st.rerun()
        
        st.markdown("---")
        
        config = load_users_config()
        
        tab1, tab2, tab3 = st.tabs(["📊 Projetos", "➕ Novo Projeto", "🔑 Gerenciar Admins"])
        
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
                                config["projects"].pop(idx)
                                save_users_config(config)
                                st.success("Projeto removido!")
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
                kobo_token = st.text_input("Token da API*", type="password")
                asset_id_master = st.text_input("ID do Formulário Master*")
                asset_id_revisita = st.text_input("ID do Formulário de Revisita*")
                
                submitted = st.form_submit_button("✅ Cadastrar Projeto", type="primary")
                
                if submitted:
                    if all([project_name, analyst_name, analyst_username, analyst_password, 
                           kobo_token, asset_id_master, asset_id_revisita]):
                        
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
                        st.success("✅ Administrador adicionado!")
                        st.rerun()
                    else:
                        st.error("❌ Preencha todos os campos")
        
        return
    
    # ==================== PAINEL DO ANALISTA ====================
    
    project_data = st.session_state.user_data
    
    st.title("📊 Gestão de Pendências")
    st.markdown(f"**Projeto:** {project_data['project_name']}")
    st.markdown(f"**Analista:** {project_data['analyst_name']}")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🚪 Sair", type="secondary"):
            st.session_state.authenticated = False
            st.session_state.user_data = None
            st.session_state.is_admin = False
            st.rerun()
    
    st.markdown("---")
    
    # Botão principal
    if st.button("🔄 Atualizar Pendências", type="primary", use_container_width=True):
        try:
            with st.spinner("Processando dados..."):
                df_pendencias, stats, arquivo_excel, arquivo_csv = processar_pendencias(project_data)
            
            # Mostrar estatísticas
            st.success("✅ Processamento concluído!")
            
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
            
            # Exibir tabela de pendências
            if not df_pendencias.empty:
                st.subheader("📋 Lista de Pendências")
                st.dataframe(df_pendencias, use_container_width=True, height=400)
                
                # Download Excel
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                nome_arquivo = f"pendencias_{project_data['project_name']}_{timestamp}.xlsx"
                
                st.download_button(
                    label="📥 Baixar Excel",
                    data=arquivo_excel,
                    file_name=nome_arquivo,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )
                
                # Upload para KoBo
                st.markdown("---")
                if st.button("☁️ Atualizar Lista no KoBoToolbox", use_container_width=True):
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
                            
                            st.success("✅ Lista atualizada no KoBoToolbox com sucesso!")
                        except Exception as e:
                            st.error(f"❌ Erro ao atualizar no KoBoToolbox: {str(e)}")
            else:
                st.info("🎉 Não há pendências! Todos os casos foram concluídos.")
        
        except Exception as e:
            st.error(f"❌ Erro ao processar pendências: {str(e)}")
            st.exception(e)

if __name__ == "__main__":
    main()
