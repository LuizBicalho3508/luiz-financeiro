import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
import json
import calendar # Adicionado para cálculo de datas de parcelas

# --- Configurações Iniciais e Autenticação (Usuários) ---
USERS = {"Luiz": "1517", "Iasmin": "1516"}

# --- Inicialização do Firebase ---
@st.cache_resource
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            firebase_creds_json_str = st.secrets.get("FIREBASE_SERVICE_ACCOUNT_JSON")
            if not firebase_creds_json_str:
                st.error("Credenciais da conta de serviço Firebase não encontradas nos Streamlit Secrets.")
                st.stop()
                return None
            firebase_creds_dict = json.loads(firebase_creds_json_str)
            cred = credentials.Certificate(firebase_creds_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Erro ao inicializar o Firebase: {e}")
            st.stop()
            return None
    return firestore.client()

db = initialize_firebase()

# --- Inicialização do Estado da Sessão ---
def initialize_app_session_state():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'editing_transaction' not in st.session_state:
        st.session_state.editing_transaction = None # {'id': trans_id, 'data': trans_data}
    if 'pending_delete_id' not in st.session_state:
        st.session_state.pending_delete_id = None # trans_id

initialize_app_session_state()

# --- Funções de Autenticação ---
def login_user(username, password):
    if username in USERS and USERS[username] == password:
        st.session_state.logged_in = True
        st.session_state.user = username
        st.rerun()
    else:
        st.error("Usuário ou senha incorretos.")

def logout_user():
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.editing_transaction = None 
    st.session_state.pending_delete_id = None   
    st.rerun()

# --- Funções CRUD para Transações com Firestore ---

def _save_single_transaction_to_firestore_internal(user, date_obj, transaction_type, category, description, amount):
    """Helper interno para salvar um único documento de transação no Firestore. Assume que 'db' está disponível."""
    timestamp_obj = datetime.datetime.combine(date_obj, datetime.datetime.min.time())
    doc_ref = db.collection("transactions").document() # Firestore gera ID automaticamente
    doc_ref.set({
        "user": user,
        "date": timestamp_obj, 
        "type": transaction_type,
        "category": category.strip().capitalize(),
        "description": description.strip(),
        "amount": float(amount), 
        "month_year": date_obj.strftime("%Y-%m"), 
        "created_at": firestore.SERVER_TIMESTAMP 
    })

def add_transaction(user, date_obj, transaction_type, category, description, amount, is_recurring, num_installments):
    """Adiciona uma transação única ou uma série de transações parceladas."""
    if not db:
        st.error("Conexão com o banco de dados não estabelecida.")
        return
    if not category or amount <= 0:
        st.warning("Preencha a categoria e um valor positivo para a parcela.")
        return

    try:
        if is_recurring and num_installments > 1:
            original_description = description # Salva a descrição original
            amount_per_installment = amount 

            for i in range(num_installments):
                current_month_offset = i 
                
                year_of_installment = date_obj.year + (date_obj.month - 1 + current_month_offset) // 12
                month_of_installment = (date_obj.month - 1 + current_month_offset) % 12 + 1
                
                day_of_installment = min(date_obj.day, calendar.monthrange(year_of_installment, month_of_installment)[1])
                
                current_installment_date = datetime.date(year_of_installment, month_of_installment, day_of_installment)

                installment_description = f"{original_description} (Parcela {i+1}/{num_installments})" if original_description else f"Parcela {i+1}/{num_installments} de {category}"
                
                _save_single_transaction_to_firestore_internal(
                    user, current_installment_date, transaction_type, category, 
                    installment_description, amount_per_installment
                )
            st.success(f"{num_installments} parcelas de '{category}' adicionadas com sucesso!")
        else:
            final_description = description 
            if is_recurring and num_installments == 1: 
                 # Usa 'description' que é a descrição original passada para a função
                 final_description = f"{description} (Parcela 1/1)" if description else f"Parcela 1/1 de {category}"

            _save_single_transaction_to_firestore_internal(
                user, date_obj, transaction_type, category, final_description, amount
            )
            # Evita mensagem duplicada se já foi mostrada para múltiplas parcelas
            if not (is_recurring and num_installments > 1): 
                st.success(f"{transaction_type} '{category}' adicionada com sucesso!")
    except Exception as e:
        st.error(f"Erro ao adicionar transação(ões): {e}")


def get_transactions_df():
    if not db:
        st.error("Conexão com o banco de dados não estabelecida.")
        return pd.DataFrame()
    try:
        transactions_ref = db.collection("transactions").order_by("date", direction=firestore.Query.DESCENDING).stream()
        transactions_list = []
        for trans_doc in transactions_ref:
            data = trans_doc.to_dict()
            data["id"] = trans_doc.id
            if 'date' in data and isinstance(data['date'], datetime.datetime):
                data['date'] = data['date'].date() 
            transactions_list.append(data)
        
        df = pd.DataFrame(transactions_list)
        if df.empty:
             return pd.DataFrame(columns=["id", "user", "date", "type", "category", "description", "amount", "month_year"])

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'])
        return df
    except Exception as e:
        st.error(f"Erro ao buscar transações: {e}")
        return pd.DataFrame()

def delete_transaction_from_firestore(transaction_id):
    if not db:
        st.error("Conexão com o banco de dados não estabelecida.")
        return
    try:
        db.collection("transactions").document(transaction_id).delete()
        st.success("Transação excluída com sucesso!")
        st.session_state.pending_delete_id = None
        if st.session_state.get('editing_transaction', {}).get('id') == transaction_id:
            st.session_state.editing_transaction = None
    except Exception as e:
        st.error(f"Erro ao excluir transação: {e}")
    st.rerun()

def update_transaction_in_firestore(transaction_id, data_to_update):
    if not db:
        st.error("Conexão com o banco de dados não estabelecida.")
        return
    try:
        data_to_update["updated_at"] = firestore.SERVER_TIMESTAMP
        db.collection("transactions").document(transaction_id).update(data_to_update)
        st.success("Transação atualizada com sucesso!")
        st.session_state.editing_transaction = None
    except Exception as e:
        st.error(f"Erro ao atualizar transação: {e}")
    st.rerun()

# --- Funções de Interface para Edição/Exclusão ---
def display_edit_transaction_form():
    if not st.session_state.get('editing_transaction'):
        return

    editing_item = st.session_state.editing_transaction
    transaction_id = editing_item['id']
    current_data = editing_item['data']

    st.markdown("---")
    st.subheader(f"✏️ Editando Transação") 
    
    current_date_val = current_data.get('date')
    if isinstance(current_date_val, pd.Timestamp):
        current_date_val = current_date_val.date()
    elif isinstance(current_date_val, str):
        try:
            current_date_val = datetime.datetime.strptime(current_date_val.split(" ")[0], "%Y-%m-%d").date()
        except ValueError:
            current_date_val = datetime.date.today() 
    elif not isinstance(current_date_val, datetime.date):
         current_date_val = datetime.date.today() 

    with st.form(key=f"edit_form_{transaction_id}"):
        edited_date = st.date_input("Data", value=current_date_val, key=f"edit_date_{transaction_id}")
        
        tipos = ["Receita", "Despesa", "Investimento"]
        current_type_idx = tipos.index(current_data.get('type', "Despesa")) if current_data.get('type') in tipos else 1
        edited_type = st.selectbox("Tipo", tipos, index=current_type_idx, key=f"edit_type_{transaction_id}")
        
        edited_category = st.text_input("Categoria", value=current_data.get('category', ''), key=f"edit_category_{transaction_id}")
        edited_description = st.text_area("Descrição", value=current_data.get('description', ''), key=f"edit_desc_{transaction_id}")
        edited_amount = st.number_input("Valor (R$)", value=float(current_data.get('amount', 0.0)),
                                        min_value=0.01, format="%.2f", step=0.01, key=f"edit_amount_{transaction_id}")

        cols = st.columns(2)
        if cols[0].form_submit_button("Salvar Alterações"):
            if not edited_category or edited_amount <= 0:
                st.warning("Categoria e valor positivo são obrigatórios.")
            else:
                data_to_update = {
                    "user": current_data.get('user'), 
                    "date": datetime.datetime.combine(edited_date, datetime.datetime.min.time()),
                    "type": edited_type,
                    "category": edited_category.strip().capitalize(),
                    "description": edited_description.strip(),
                    "amount": float(edited_amount),
                    "month_year": edited_date.strftime("%Y-%m")
                }
                update_transaction_in_firestore(transaction_id, data_to_update)
        
        if cols[1].form_submit_button("Cancelar Edição", type="secondary"):
            st.session_state.editing_transaction = None
            st.rerun()
    st.markdown("---")

def render_transaction_rows(df_transactions, list_id_prefix=""):
    if df_transactions.empty:
        st.info("Nenhuma transação para exibir.")
        return

    st.markdown(
        """
        <style>
            .transaction-row > div { display: flex; align-items: center; }
            .transaction-row .stButton button { padding: 0.25rem 0.5rem; line-height: 1.2; font-size: 0.9rem; }
        </style>
        """, unsafe_allow_html=True
    )
    
    header_cols = st.columns((3, 2, 2, 3, 2, 1, 1)) 
    fields = ['Data', 'Tipo', 'Categoria', 'Descrição', 'Valor (R$)', 'Editar', 'Excluir']
    for col, field_name in zip(header_cols, fields):
        col.markdown(f"**{field_name}**")

    for index, row in df_transactions.iterrows():
        trans_id = row["id"]
        row_data_for_edit = row.to_dict()
        if isinstance(row_data_for_edit.get('date'), pd.Timestamp):
            row_data_for_edit['date'] = row_data_for_edit['date'].date()
        
        can_edit_delete = row.get('user') == st.session_state.user

        cols = st.columns((3, 2, 2, 3, 2, 1, 1), gap="small")
        
        cols[0].write(row['date'].strftime('%d/%m/%Y') if pd.notnull(row['date']) else 'N/A')
        cols[1].write(row['type'])
        cols[2].write(row['category'])
        cols[3].write(row.get('description', '')[:30] + '...' if len(row.get('description', '')) > 30 else row.get('description', '')) 
        cols[4].write(f"R$ {row['amount']:.2f}")

        if can_edit_delete:
            if cols[5].button("✏️", key=f"{list_id_prefix}_edit_{trans_id}", help="Editar"):
                st.session_state.editing_transaction = {'id': trans_id, 'data': row_data_for_edit}
                st.session_state.pending_delete_id = None 
                st.rerun()
            
            if st.session_state.get('pending_delete_id') == trans_id:
                confirm_cols = cols[6].columns([1,1])
                if confirm_cols[0].button("✅", key=f"{list_id_prefix}_confirmdel_{trans_id}", help="Confirmar Exclusão"):
                    delete_transaction_from_firestore(trans_id) 
                if confirm_cols[1].button("❌", key=f"{list_id_prefix}_canceldel_{trans_id}", help="Cancelar Exclusão"):
                    st.session_state.pending_delete_id = None
                    st.rerun()
            else:
                if cols[6].button("🗑️", key=f"{list_id_prefix}_delete_{trans_id}", help="Excluir"):
                    st.session_state.pending_delete_id = trans_id
                    st.session_state.editing_transaction = None 
                    st.rerun()
        else:
            cols[5].write("") 
            cols[6].write("") 
    st.markdown("---")


# --- Páginas da Aplicação ---
def page_login():
    st.title("Controle Financeiro do Casal")
    st.subheader("Login")
    with st.form("login_form"):
        username = st.text_input("Usuário", key="login_username")
        password = st.text_input("Senha", type="password", key="login_password")
        if st.form_submit_button("Entrar"):
            login_user(username, password)

# Callback para forçar o recarregamento da UI quando o modo de transação muda
def force_rerun_on_mode_change():
    st.rerun()

def page_log_transaction():
    st.header(f"Olá, {st.session_state.user}! Registre uma nova transação:")
    display_edit_transaction_form() 

    with st.form("transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            transaction_date = st.date_input("Data da Transação (ou 1ª Parcela)", datetime.date.today(), key="trans_date_input")
            transaction_type = st.selectbox("Tipo", ["Receita", "Despesa", "Investimento"], key="trans_type_select")
        with col2:
            common_categories = {
                "Receita": ["Salário", "Freelance", "Rendimentos", "Outros"],
                "Despesa": ["Moradia", "Alimentação", "Transporte", "Saúde", "Lazer", "Educação", "Vestuário", "Contas", "Outros"],
                "Investimento": ["Ações", "Fundos Imobiliários", "Renda Fixa", "Criptomoedas", "Outros"]
            }
            category_options = common_categories.get(transaction_type, ["Outros"])
            category = st.text_input("Categoria (ex: Salário, Alimentação, Ações)", key="trans_category_input", placeholder="Ou digite uma nova")
            st.caption(f"Sugestões: {', '.join(category_options)}")
            
        description = st.text_area("Descrição (Opcional)", key="trans_desc_area")
        amount = st.number_input("Valor (R$) (por parcela, se recorrente)", min_value=0.01, format="%.2f", step=0.01, key="trans_amount_input")
        
        st.markdown("---") 
        
        # Usar st.radio para tipo de lançamento com on_change callback
        # O valor do radio é armazenado em st.session_state.trans_mode_radio_key
        current_transaction_mode = st.radio(
            "Tipo de Lançamento:",
            ("Único", "Parcelado"),
            horizontal=True,
            key="trans_mode_radio_key", # Chave para o estado da sessão do radio
            on_change=force_rerun_on_mode_change # Callback para forçar recarregamento
        )
        
        num_installments = 1
        is_recurring_flag = False

        # A lógica condicional agora usa o valor do radio button (que foi atualizado após o rerun)
        if current_transaction_mode == "Parcelado":
            is_recurring_flag = True
            num_installments = st.number_input("Número Total de Parcelas", min_value=1, value=2, step=1, key="trans_num_parcelas_input")
        
        if st.form_submit_button("Adicionar Transação"):
            add_transaction(
                st.session_state.user, 
                transaction_date, 
                transaction_type, 
                category, 
                description, 
                amount,
                is_recurring_flag, 
                num_installments 
            )
    
    st.markdown("---")
    st.subheader("Últimas Transações Lançadas por Você:")
    all_trans_df = get_transactions_df()
    if not all_trans_df.empty:
        user_recent_df = all_trans_df[all_trans_df['user'] == st.session_state.user].sort_values(by="date", ascending=False).head(10)
        render_transaction_rows(user_recent_df, "recent")
    else:
        st.info("Nenhuma transação registrada no banco de dados.")

def display_summary_charts_and_data(df_period, df_full_history_for_user_or_couple, title_prefix=""):
    if df_period.empty:
        st.info(f"{title_prefix}Nenhuma transação encontrada para o período selecionado.")
    else:
        receitas = df_period[df_period['type'] == 'Receita']['amount'].sum()
        despesas = df_period[df_period['type'] == 'Despesa']['amount'].sum()
        investimentos_periodo = df_period[df_period['type'] == 'Investimento']['amount'].sum() 
        saldo = receitas - (despesas + investimentos_periodo) 

        st.subheader(f"{title_prefix}Resumo do Mês Selecionado")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Receitas", f"R$ {receitas:,.2f}")
        col2.metric("Despesas", f"R$ {despesas:,.2f}")
        col3.metric("Investimentos", f"R$ {investimentos_periodo:,.2f}") 
        col4.metric("Saldo Final", f"R$ {saldo:,.2f}", delta_color=("inverse" if saldo < 0 else "normal"))
        st.markdown("---")

        st.subheader(f"{title_prefix}Composição Receita vs. Despesa (Mês Selecionado)")
        
        chart_values = []
        chart_names = []
        chart_colors = []
        chart_title = "Situação Financeira do Mês"

        if receitas == 0 and despesas == 0:
            st.info(f"{title_prefix}Sem dados de receita ou despesa para este período.")
        elif receitas == 0 and despesas > 0:
            chart_values = [despesas]
            chart_names = ['Despesas (Sem Receita)']
            chart_colors = ['crimson']
            chart_title = "Situação Financeira: Déficit (Sem Receita)"
        elif receitas > 0:
            if despesas <= receitas:
                chart_values = [despesas, receitas - despesas]
                chart_names = ['Despesas Cobertas', 'Saldo Positivo da Receita']
                chart_colors = ['sandybrown', 'lightgreen'] 
                chart_title = "Receita vs. Despesa: Saldo Positivo"
                if despesas == 0 and (receitas - despesas) == 0: 
                    pass
                elif despesas == 0 : 
                     chart_values = [receitas - despesas]
                     chart_names = ['Saldo Positivo da Receita']
                     chart_colors = ['lightgreen']
                elif (receitas - despesas) == 0: 
                     chart_values = [despesas]
                     chart_names = ['Despesas (Cobriram 100% da Receita)']
                     chart_colors = ['sandybrown']
            else: 
                chart_values = [receitas, despesas - receitas] 
                chart_names = ['Receita (Totalmente Coberta por Despesas)', 'Despesa Excedente (Déficit)']
                chart_colors = ['lightcoral', 'crimson'] 
                chart_title = "Receita vs. Despesa: Déficit"
        
        if chart_values and sum(chart_values) > 0: 
            fig_comp = px.pie(values=chart_values, 
                                names=chart_names, 
                                title=chart_title,
                                color_discrete_sequence=chart_colors)
            fig_comp.update_traces(textposition='inside', textinfo='percent+label+value', hole=.3 if len(chart_values)>1 else 0)
            st.plotly_chart(fig_comp, use_container_width=True)
        elif not (receitas == 0 and despesas == 0) : 
            st.info(f"{title_prefix}Dados insuficientes ou zerados para o gráfico de pizza de composição.")
        
        st.markdown("---")

    if not df_full_history_for_user_or_couple.empty:
        st.subheader(f"{title_prefix}Histórico Mensal (Últimos 12 Meses de Dados)")
        
        df_history_copy = df_full_history_for_user_or_couple.copy()
        if 'date' in df_history_copy.columns:
             df_history_copy['month_year'] = pd.to_datetime(df_history_copy['date']).dt.strftime('%Y-%m')
        
        available_months_sorted = sorted(df_history_copy['month_year'].unique(), reverse=True)
        last_12_months = available_months_sorted[:12]

        if last_12_months:
            history_12m_df = df_history_copy[df_history_copy['month_year'].isin(last_12_months)]
            history_12m_df_filtered = history_12m_df[history_12m_df['type'].isin(['Receita', 'Despesa'])]
            
            if not history_12m_df_filtered.empty:
                monthly_summary = history_12m_df_filtered.groupby(['month_year', 'type'])['amount'].sum().unstack(fill_value=0).reset_index()
                
                if 'Receita' not in monthly_summary.columns:
                    monthly_summary['Receita'] = 0
                if 'Despesa' not in monthly_summary.columns:
                    monthly_summary['Despesa'] = 0
                
                monthly_summary = monthly_summary.sort_values(by='month_year')

                fig_line_history = px.line(monthly_summary, x='month_year', y=['Receita', 'Despesa'],
                                           title='Receitas vs. Despesas Mensais',
                                           labels={'month_year': 'Mês/Ano', 'value': 'Valor (R$)', 'variable': 'Tipo'},
                                           markers=True)
                fig_line_history.update_layout(yaxis_title='Valor (R$)', xaxis_title='Mês/Ano')
                st.plotly_chart(fig_line_history, use_container_width=True)
            else:
                st.info(f"{title_prefix}Não há dados de Receita ou Despesa no histórico de 12 meses.")
        else:
            st.info(f"{title_prefix}Não há dados suficientes para o histórico de 12 meses.")
    else:
        st.info(f"{title_prefix}Nenhuma transação no histórico para exibir gráfico de linha.")
    
    st.markdown("---")
    st.subheader(f"{title_prefix}Detalhes das Transações do Período Selecionado")
    if not df_period.empty:
        render_transaction_rows(df_period.sort_values(by="date", ascending=False), f"{title_prefix.lower().replace(' ', '_').replace('-', '')}_summary_period")
    else:
        st.info(f"{title_prefix}Nenhuma transação para exibir detalhes neste período.")


def page_my_summary():
    st.header(f"Meu Resumo Financeiro - {st.session_state.user}")
    display_edit_transaction_form() 
    
    df_all_transactions_system = get_transactions_df() 
    if df_all_transactions_system.empty:
        st.info("Nenhuma transação no banco de dados. Comece adicionando algumas!")
        return

    df_user_full_history = df_all_transactions_system[df_all_transactions_system['user'] == st.session_state.user].copy()
    if df_user_full_history.empty:
        st.info("Você ainda não registrou transações.")
        return
    
    if 'date' in df_user_full_history.columns: 
         df_user_full_history['month_year'] = pd.to_datetime(df_user_full_history['date']).dt.strftime('%Y-%m')

    available_months_user = sorted(df_user_full_history['month_year'].unique(), reverse=True)
    if not available_months_user:
        st.info("Nenhuma transação sua com data válida para resumo.")
        return
        
    selected_month = st.selectbox("Selecione o Mês/Ano para o resumo detalhado:", available_months_user, key="my_summary_month_select")
    if selected_month:
        df_period_user = df_user_full_history[df_user_full_history['month_year'] == selected_month]
        display_summary_charts_and_data(df_period_user, df_user_full_history, "Meu ")

def page_couple_summary():
    st.header("Resumo Financeiro do Casal")
    display_edit_transaction_form() 

    df_all_transactions_system = get_transactions_df() 
    if df_all_transactions_system.empty:
        st.info("Nenhuma transação registrada no banco de dados.")
        return

    if 'date' in df_all_transactions_system.columns: 
        df_all_transactions_system['month_year'] = pd.to_datetime(df_all_transactions_system['date']).dt.strftime('%Y-%m')

    available_months_couple = sorted(df_all_transactions_system['month_year'].unique(), reverse=True)
    if not available_months_couple:
        st.info("Nenhuma transação com data válida para resumo.")
        return

    selected_month = st.selectbox("Selecione o Mês/Ano para o resumo detalhado:", available_months_couple, key="couple_summary_month_select")
    if selected_month:
        df_period_couple = df_all_transactions_system[df_all_transactions_system['month_year'] == selected_month]
        display_summary_charts_and_data(df_period_couple, df_all_transactions_system, "Casal - ")

# --- Lógica Principal da Aplicação ---
def main_app():
    st.sidebar.title(f"Bem-vindo(a), {st.session_state.user}!")
    menu_options = {
        "🏠 Lançar Transação": page_log_transaction,
        "📊 Meu Resumo": page_my_summary,
        "💑 Resumo do Casal": page_couple_summary
    }
    selection = st.sidebar.radio("Menu", list(menu_options.keys()), key="main_menu_selection")
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout"):
        logout_user()

    page_function = menu_options[selection]
    page_function() 

    st.sidebar.markdown("---")
    st.sidebar.info("Dados armazenados no Firebase Firestore.")

# --- Ponto de Entrada ---
if not db:
    st.error("Falha na conexão com o banco de dados. A aplicação não pode iniciar.")
elif not st.session_state.get('logged_in', False):
    page_login()
else:
    main_app()
