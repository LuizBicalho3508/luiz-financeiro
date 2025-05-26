import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
import json # Para analisar o JSON dos secrets

# --- Configurações Iniciais e Autenticação (Usuários) ---
USERS = {"Luiz": "1517", "Iasmin": "1516"}

# --- Inicialização do Firebase ---
@st.cache_resource # Usar st.cache_resource para objetos de cliente como o db
def initialize_firebase():
    """Inicializa o Firebase Admin SDK usando credenciais dos Streamlit Secrets."""
    if not firebase_admin._apps: # Evita reinicializar se já estiver inicializado
        try:
            firebase_creds_json_str = st.secrets.get("FIREBASE_SERVICE_ACCOUNT_JSON")
            if not firebase_creds_json_str:
                st.error("Credenciais da conta de serviço Firebase não encontradas nos Streamlit Secrets.")
                st.stop()
                return None

            # Analisa a string JSON para um dicionário
            firebase_creds_dict = json.loads(firebase_creds_json_str)
            
            cred = credentials.Certificate(firebase_creds_dict)
            firebase_admin.initialize_app(cred)
            # st.success("Firebase inicializado com sucesso!") # Opcional: para depuração
        except Exception as e:
            st.error(f"Erro ao inicializar o Firebase: {e}")
            st.stop()
            return None
    
    db = firestore.client()
    return db

db = initialize_firebase() # Tenta inicializar o Firebase

# Inicializa o estado da sessão para login se ainda não existir
def initialize_login_session_state():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user' not in st.session_state:
        st.session_state.user = None

initialize_login_session_state()

def login_user(username, password):
    """Verifica as credenciais do usuário."""
    if username in USERS and USERS[username] == password:
        st.session_state.logged_in = True
        st.session_state.user = username
        st.rerun()
    else:
        st.error("Usuário ou senha incorretos.")

def logout_user():
    """Faz logout do usuário."""
    st.session_state.logged_in = False
    st.session_state.user = None
    st.rerun()

# --- Gerenciamento de Dados com Firestore ---
def add_transaction(user, date_obj, transaction_type, category, description, amount):
    """Adiciona uma nova transação ao Firestore."""
    if not db:
        st.error("Conexão com o banco de dados não estabelecida. Não é possível adicionar transação.")
        return
    if not category:
        st.warning("Por favor, preencha a categoria.")
        return
    if amount <= 0:
        st.warning("O valor da transação deve ser positivo.")
        return

    try:
        # Converte datetime.date para datetime.datetime para compatibilidade com Firestore Timestamp
        timestamp_obj = datetime.datetime.combine(date_obj, datetime.datetime.min.time())

        doc_ref = db.collection("transactions").document() # Firestore gera ID automaticamente
        doc_ref.set({
            "user": user,
            "date": timestamp_obj, # Armazena como Timestamp do Firestore
            "type": transaction_type,
            "category": category.strip().capitalize(),
            "description": description.strip(),
            "amount": float(amount), # Garante que o valor é float
            "month_year": date_obj.strftime("%Y-%m"), # String YYYY-MM para facilitar agrupamento/query
            "created_at": firestore.SERVER_TIMESTAMP # Opcional: timestamp do servidor
        })
        st.success(f"{transaction_type} adicionada com sucesso ao banco de dados!")
    except Exception as e:
        st.error(f"Erro ao adicionar transação ao Firestore: {e}")


def get_transactions_df():
    """Busca todas as transações do Firestore e retorna como DataFrame."""
    if not db:
        st.error("Conexão com o banco de dados não estabelecida. Não é possível buscar transações.")
        return pd.DataFrame(columns=["user", "date", "type", "category", "description", "amount", "month_year"])

    try:
        transactions_ref = db.collection("transactions").order_by("date", direction=firestore.Query.DESCENDING).stream()
        transactions_list = []
        for trans_doc in transactions_ref:
            data = trans_doc.to_dict()
            data["id"] = trans_doc.id # Opcional: se precisar do ID do documento
            
            # Converte Timestamp do Firestore para objeto date do Python para o DataFrame
            if 'date' in data and isinstance(data['date'], datetime.datetime):
                data['date'] = data['date'].date()
            transactions_list.append(data)

        if not transactions_list:
            return pd.DataFrame(columns=["user", "date", "type", "category", "description", "amount", "month_year"])

        df = pd.DataFrame(transactions_list)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']) # Assegura que é datetime para o Pandas
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'])
        return df
    except Exception as e:
        st.error(f"Erro ao buscar transações do Firestore: {e}")
        return pd.DataFrame(columns=["user", "date", "type", "category", "description", "amount", "month_year"])


# --- Páginas da Aplicação (Interface do Usuário - sem grandes mudanças aqui) ---

def page_login():
    """Página de Login."""
    st.title("Controle Financeiro do Casal")
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Usuário", key="login_username")
        password = st.text_input("Senha", type="password", key="login_password")
        login_button = st.form_submit_button("Entrar")

        if login_button:
            login_user(username, password)

def page_log_transaction():
    """Página para registrar novas transações."""
    st.header(f"Olá, {st.session_state.user}! Registre uma nova transação:")

    with st.form("transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            transaction_date = st.date_input("Data da Transação", datetime.date.today(), key="trans_date")
            transaction_type = st.selectbox("Tipo", ["Receita", "Despesa", "Investimento"], key="trans_type")
        with col2:
            common_categories = {
                "Receita": ["Salário", "Freelance", "Rendimentos", "Outros"],
                "Despesa": ["Moradia", "Alimentação", "Transporte", "Saúde", "Lazer", "Educação", "Vestuário", "Contas", "Outros"],
                "Investimento": ["Ações", "Fundos Imobiliários", "Renda Fixa", "Criptomoedas", "Outros"]
            }
            category_options = common_categories.get(transaction_type, ["Outros"])
            category = st.text_input("Categoria (ex: Salário, Alimentação, Ações)", key="trans_category", placeholder="Ou digite uma nova")
            st.caption(f"Sugestões: {', '.join(category_options)}")
            
        description = st.text_area("Descrição (Opcional)", key="trans_desc")
        amount = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", step=0.01, key="trans_amount")
        
        submitted = st.form_submit_button("Adicionar Transação")

        if submitted:
            add_transaction(
                st.session_state.user,
                transaction_date, # Este é um objeto datetime.date
                transaction_type,
                category,
                description,
                amount
            )
    
    st.markdown("---")
    st.subheader("Últimas Transações Lançadas por Você (do Banco de Dados):")
    user_df_all = get_transactions_df() # Pega todos os dados do DB
    if not user_df_all.empty:
        user_df_filtered = user_df_all[user_df_all['user'] == st.session_state.user].sort_values(by="date", ascending=False).head(10)
        if not user_df_filtered.empty:
            st.dataframe(user_df_filtered[['date', 'type', 'category', 'description', 'amount']].rename(columns={
                'date': 'Data', 'type': 'Tipo', 'category': 'Categoria', 'description': 'Descrição', 'amount': 'Valor (R$)'
            }), use_container_width=True)
        else:
            st.info("Você ainda não lançou nenhuma transação no banco de dados.")
    else:
        st.info("Nenhuma transação registrada no banco de dados.")


def display_summary(df_period, title_prefix=""):
    """Exibe o resumo financeiro para o DataFrame e período fornecidos."""
    if df_period.empty:
        st.info(f"{title_prefix}Nenhuma transação encontrada para este período.")
        return

    receitas = df_period[df_period['type'] == 'Receita']['amount'].sum()
    despesas = df_period[df_period['type'] == 'Despesa']['amount'].sum()
    investimentos = df_period[df_period['type'] == 'Investimento']['amount'].sum()
    
    saldo = receitas - (despesas + investimentos)

    st.subheader(f"{title_prefix}Resumo do Mês")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Receitas Totais", f"R$ {receitas:,.2f}")
    col2.metric("Despesas Totais", f"R$ {despesas:,.2f}")
    col3.metric("Investimentos Totais", f"R$ {investimentos:,.2f}")
    col4.metric("Saldo Final", f"R$ {saldo:,.2f}", delta_color=("inverse" if saldo < 0 else "normal"))

    st.markdown("---")

    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.subheader(f"{title_prefix}Distribuição de Despesas")
        despesas_df = df_period[df_period['type'] == 'Despesa']
        if not despesas_df.empty:
            fig_despesas = px.pie(despesas_df, values='amount', names='category', title='Despesas por Categoria')
            fig_despesas.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_despesas, use_container_width=True)
        else:
            st.info(f"{title_prefix}Nenhuma despesa registrada neste período.")

    with col_chart2:
        st.subheader(f"{title_prefix}Distribuição de Receitas")
        receitas_df = df_period[df_period['type'] == 'Receita']
        if not receitas_df.empty:
            fig_receitas = px.pie(receitas_df, values='amount', names='category', title='Receitas por Categoria')
            fig_receitas.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_receitas, use_container_width=True)
        else:
            st.info(f"{title_prefix}Nenhuma receita registrada neste período.")
    
    if investimentos > 0:
        st.subheader(f"{title_prefix}Distribuição de Investimentos")
        investimentos_df = df_period[df_period['type'] == 'Investimento']
        if not investimentos_df.empty:
            fig_invest = px.pie(investimentos_df, values='amount', names='category', title='Investimentos por Categoria')
            fig_invest.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_invest, use_container_width=True)

    st.subheader(f"{title_prefix}Todas as Transações do Período")
    st.dataframe(df_period[['date', 'user', 'type', 'category', 'description', 'amount']].rename(columns={
        'date': 'Data', 'user': 'Usuário', 'type': 'Tipo', 'category': 'Categoria', 
        'description': 'Descrição', 'amount': 'Valor (R$)'
    }).sort_values(by="date"), use_container_width=True)


def page_my_summary():
    st.header(f"Meu Resumo Financeiro - {st.session_state.user}")
    df_all_transactions = get_transactions_df()
    if df_all_transactions.empty:
        st.info("Nenhuma transação registrada no banco de dados. Comece adicionando algumas!")
        return

    df_user = df_all_transactions[df_all_transactions['user'] == st.session_state.user].copy() # .copy() para evitar SettingWithCopyWarning
    if df_user.empty:
        st.info("Você ainda não registrou nenhuma transação.")
        return

    # Assegura que 'month_year' existe e está correto se não veio do DB ou foi alterado
    if 'date' in df_user.columns:
         df_user['month_year'] = df_user['date'].dt.strftime('%Y-%m')


    available_months = sorted(df_user['month_year'].unique(), reverse=True)
    if not available_months:
        st.info("Nenhuma transação sua encontrada com data válida para exibir o resumo.")
        return
        
    selected_month = st.selectbox("Selecione o Mês/Ano para o resumo:", available_months)
    if selected_month:
        df_period_user = df_user[df_user['month_year'] == selected_month]
        display_summary(df_period_user)


def page_couple_summary():
    st.header("Resumo Financeiro do Casal")
    df_all_transactions = get_transactions_df()
    if df_all_transactions.empty:
        st.info("Nenhuma transação registrada no banco de dados.")
        return

    # Assegura que 'month_year' existe e está correto
    if 'date' in df_all_transactions.columns:
        df_all_transactions['month_year'] = df_all_transactions['date'].dt.strftime('%Y-%m')


    available_months = sorted(df_all_transactions['month_year'].unique(), reverse=True)
    if not available_months:
        st.info("Nenhuma transação encontrada com data válida para exibir o resumo.")
        return

    selected_month = st.selectbox("Selecione o Mês/Ano para o resumo:", available_months, key="couple_month_select")
    if selected_month:
        df_period_couple = df_all_transactions[df_all_transactions['month_year'] == selected_month]
        display_summary(df_period_couple, title_prefix="Casal - ")


# --- Lógica Principal da Aplicação (Roteamento) ---
def main_app():
    st.sidebar.title(f"Bem-vindo(a), {st.session_state.user}!")
    menu_options = {
        "🏠 Lançar Transação": page_log_transaction,
        "📊 Meu Resumo": page_my_summary,
        "💑 Resumo do Casal": page_couple_summary
    }
    selection = st.sidebar.radio("Menu", list(menu_options.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout"):
        logout_user()

    page_function = menu_options[selection]
    page_function()

    st.sidebar.markdown("---")
    st.sidebar.info(
        """
        **Persistência de Dados:**
        Os dados agora são armazenados no Firebase Firestore e persistirão entre sessões.
        """
    )

# --- Ponto de Entrada da Aplicação ---
if not db: # Se o DB não inicializou, não prossiga com a lógica de login/app
    st.warning("A aplicação não pôde ser iniciada devido a um problema com a configuração do banco de dados.")
elif not st.session_state.get('logged_in', False): # Use .get para segurança
    page_login()
else:
    main_app()
