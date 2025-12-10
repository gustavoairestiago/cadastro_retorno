# 📋 Sistema de Gestão de Pendências KoBoToolbox

Sistema web para gestão de pendências de entrevistas domiciliares usando KoBoToolbox.

## 🚀 Instalação

### 1. Pré-requisitos
- Python 3.8 ou superior
- pip (gerenciador de pacotes Python)

### 2. Configuração do Ambiente

```bash
# Clone ou baixe os arquivos do projeto
# Navegue até a pasta do projeto

# Instale as dependências
pip install -r requirements.txt
```

### 3. Executar a Aplicação

```bash
streamlit run app.py
```

A aplicação abrirá automaticamente no navegador em `http://localhost:8501`

## 👥 Primeiro Acesso

### Login Padrão de Administrador
- **Usuário:** admin
- **Senha:** admin123

⚠️ **IMPORTANTE:** Altere a senha padrão após o primeiro acesso!

## 🔧 Estrutura de Arquivos

```
projeto/
├── app.py                  # Aplicação principal
├── requirements.txt        # Dependências
├── users_config.json       # Configurações (gerado automaticamente)
└── README.md              # Este arquivo
```

## 📖 Como Usar

### Para Administradores:

1. **Login** com credenciais de admin
2. Acesse a aba **"Novo Projeto"**
3. Preencha as informações:
   - Nome do Projeto
   - Dados do Analista (nome, usuário, senha)
   - Configurações KoBoToolbox:
     - URL da instância
     - Token da API (gerado em: https://[instancia]/token/)
     - IDs dos formulários (Master e Revisita)
4. Clique em **"Cadastrar Projeto"**

### Para Analistas de Dados:

1. **Login** com suas credenciais fornecidas pelo admin
2. Clique no botão **"🔄 Atualizar Pendências"**
3. Aguarde o processamento (baixa dados, consolida, gera relatório)
4. Visualize as estatísticas e a lista de pendências
5. **Baixe o Excel** com a lista completa
6. (Opcional) Clique em **"☁️ Atualizar Lista no KoBoToolbox"** para enviar o CSV atualizado para o formulário de revisitas

## 🔐 Segurança

- Senhas são armazenadas com hash SHA256
- Arquivo `users_config.json` contém dados sensíveis
- **Não compartilhe** este arquivo publicamente
- Configure permissões adequadas no servidor

## 📊 Fluxo de Dados

```
Form A (Master)          Form B (Revisita)
      ↓                         ↓
   1ª Visita            Visitas de Retorno
      ↓                         ↓
      └─────────┬───────────────┘
                ↓
         Processamento
                ↓
        ┌───────┴───────┐
        ↓               ↓
   Estatísticas    Lista Pendências
                        ↓
                  ┌─────┴─────┐
                  ↓           ↓
              Excel      Upload KoBo
```

## 🆘 Solução de Problemas

### Erro de conexão com KoBoToolbox
- Verifique o token da API
- Confirme os IDs dos formulários
- Teste a URL da instância no navegador

### Campos não encontrados
- Ajuste o mapeamento de campos em `users_config.json`
- Seção `"campos"` dentro de cada projeto

### Erro ao instalar dependências
```bash
# Use um ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

## 🔄 Atualização da Aplicação

```bash
# Baixe a nova versão do app.py
# Execute novamente
streamlit run app.py
```

O arquivo `users_config.json` será preservado.

## 📝 Customização de Campos

Para ajustar os campos dos formulários, edite o arquivo `users_config.json` na seção de cada projeto:

```json
{
  "campos": {
    "household_id": "nome_do_campo_no_kobo",
    "status_master": "caminho/para/status",
    "endereco": "caminho/para/endereco"
  }
}
```

## 🌐 Deploy em Servidor

### Opção 1: Streamlit Cloud (Gratuito)
1. Faça upload do código no GitHub (sem `users_config.json`)
2. Conecte no https://streamlit.io/cloud
3. Configure variáveis de ambiente se necessário

### Opção 2: Servidor Próprio
```bash
# Com nohup (mantém rodando após logout)
nohup streamlit run app.py --server.port 8501 &

# Configure firewall para liberar a porta
# Configure HTTPS com nginx/apache se necessário
```

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique os logs da aplicação
2. Consulte a documentação do KoBoToolbox
3. Entre em contato com a equipe Core de Dados

---

**Versão:** 1.0  
**Última atualização:** Dezembro 2024