import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
import json
import calendar 
import locale # Para formatação de moeda

# --- Configurações Iniciais e Autenticação (Usuários) ---
USERS = {"Luiz": "1517", "Iasmin": "1516"}

PORTUGUESE_MONTHS = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]

PAYMENT_STATUS_OPTIONS = ["Pendente", "Pago"] # Opções de status

# Tenta definir o locale para Português do Brasil para formatação de moeda
LOCALE_SET_SUCCESS = False
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
    LOCALE_SET_SUCCESS = True
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil.1252') # Windows
        LOCALE_SET_SUCCESS = True
    except locale.Error:
        if 'initial_locale_warning_shown' not in st.session_state: # Guarded warning
            st.warning("Locale 'pt_BR' não pôde ser configurado. Usando formatação de moeda manual.")
            st.session_state.initial_locale_warning_shown = True
        LOCALE_SET_SUCCESS = False # Explicitamente define como False se ambas as tentativas falharem


# --- Inicialização do Firebase ---
@st.cache_resource # Cache para evitar reinicializações desnecessárias
def initialize_firebase():
    """Inicializa a conexão com o Firebase usando as credenciais dos secrets."""
    if not firebase_admin._apps: # Verifica se já foi inicializado
        try:
            firebase_creds_json_str = st.secrets.get("FIREBASE_SERVICE_ACCOUNT_JSON")
            if not firebase_creds_json_str:
                st.error("Credenciais Firebase (FIREBASE_SERVICE_ACCOUNT_JSON) não encontradas nos Streamlit Secrets.")
                st.info("Por favor, adicione suas credenciais Firebase JSON como um segredo chamado 'FIREBASE_SERVICE_ACCOUNT_JSON' nas configurações do seu app Streamlit Cloud.")
                st.stop() 
                return None
            
            firebase_creds_dict = json.loads(firebase_creds_json_str)
            cred = credentials.Certificate(firebase_creds_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Erro ao inicializar o Firebase: {e}")
            st.info("Verifique se as credenciais Firebase JSON estão corretas e no formato esperado.")
            st.stop() 
            return None
    
    db_client = firestore.client()
    return db_client

db = initialize_firebase() 

# --- Inicialização do Estado da Sessão ---
def initialize_app_session_state():
    """Inicializa as variáveis de estado da sessão necessárias."""
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'editing_transaction' not in st.session_state:
        st.session_state.editing_transaction = None 
    if 'pending_delete_id' not in st.session_state:
        st.session_state.pending_delete_id = None 
    if 'transaction_mode_selection_key' not in st.session_state:
        st.session_state.transaction_mode_selection_key = "Único"
    if 'last_main_menu_selection' not in st.session_state:
        st.session_state.last_main_menu_selection = None

initialize_app_session_state()

# --- Funções Auxiliares de Formatação ---
def format_month_year_for_display(month_year_str): # "YYYY-MM"
    """Converte 'YYYY-MM' para 'Nome do Mês de YYYY'."""
    if not month_year_str or len(month_year_str) != 7 or month_year_str[4] != '-':
        return month_year_str 
    try:
        year, month = map(int, month_year_str.split('-'))
        if not (1 <= month <= 12):
            return month_year_str 
        return f"{PORTUGUESE_MONTHS[month-1]} de {year}"
    except (ValueError, IndexError):
        return month_year_str 

def parse_display_month_year(display_month_year_str): # "Nome do Mês de YYYY"
    """Converte 'Nome do Mês de YYYY' de volta para 'YYYY-MM'."""
    try:
        parts = display_month_year_str.split(" de ")
        if len(parts) != 2: return None
        month_name_pt, year_str = parts[0], parts[1]
        if month_name_pt not in PORTUGUESE_MONTHS: return None
        month_num = PORTUGUESE_MONTHS.index(month_name_pt) + 1
        year_num = int(year_str)
        return f"{year_num:04d}-{month_num:02d}"
    except Exception: return None

def format_brazilian_currency(value):
    """Formata um valor numérico como moeda brasileira (R$)."""
    global LOCALE_SET_SUCCESS
    if LOCALE_SET_SUCCESS:
        try:
            return locale.currency(value, grouping=True, symbol='R$ ') 
        except (locale.Error, ValueError):
            LOCALE_SET_SUCCESS = False 
            if 'pt_BR_runtime_warning_shown' not in st.session_state:
                st.warning("Falha ao usar formatação de moeda do locale em tempo de execução. Usando formatação manual.")
                st.session_state.pt_BR_runtime_warning_shown = True
            # Fall through to manual formatting

    # Fallback manual
    try:
        val_float = float(value) # Garante que é float
        s = f"{val_float:.2f}"
        parts = s.split('.')
        integer_part = parts[0]
        decimal_part = parts[1] if len(parts) > 1 else "00"
        
        sign = ""
        if integer_part.startswith('-'):
            sign = "-"
            integer_part = integer_part[1:]

        integer_part_with_thousands = ""
        for i, digit in enumerate(reversed(integer_part)):
            if i != 0 and i % 3 == 0:
                integer_part_with_thousands = "." + integer_part_with_thousands
            integer_part_with_thousands = digit + integer_part_with_thousands
        
        return f"R$ {sign}{integer_part_with_thousands},{decimal_part}" # Adicionado espaço após R$
    except Exception: 
        return f"R$ {value:.2f}" # Fallback mais simples


# --- Funções de Autenticação ---
def login_user(username, password):
    if username in USERS and USERS[username] == password:
        st.session_state.logged_in = True
        st.session_state.user = username
        st.session_state.last_main_menu_selection = None 
        st.rerun()
    else: st.error("Usuário ou senha incorretos.")

def logout_user():
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.editing_transaction = None 
    st.session_state.pending_delete_id = None
    st.session_state.last_main_menu_selection = None 
    if "my_summary_month_select" in st.session_state: del st.session_state.my_summary_month_select
    if "couple_summary_month_select" in st.session_state: del st.session_state.couple_summary_month_select
    st.rerun()

# --- Funções CRUD para Transações com Firestore ---
def _save_single_transaction_to_firestore_internal(user, date_obj, transaction_type, category, description, amount, payment_status=None):
    if not db: st.error("Conexão com o banco de dados falhou ao salvar."); return
    timestamp_obj = datetime.datetime.combine(date_obj, datetime.datetime.min.time())
    doc_ref = db.collection("transactions").document() 
    data_to_save = {
        "user": user, "date": timestamp_obj, "type": transaction_type,
        "category": category.strip().capitalize(), "description": description.strip(),
        "amount": float(amount), "month_year": date_obj.strftime("%Y-%m"), 
        "created_at": firestore.SERVER_TIMESTAMP 
    }
    if transaction_type == "Despesa":
        data_to_save["status_pagamento"] = payment_status if payment_status else "Pendente"
    doc_ref.set(data_to_save)

def add_transaction(user, date_obj, transaction_type, category, description, amount, is_recurring, num_installments, payment_status=None):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    if not category or amount <= 0: st.warning("Preencha a categoria e um valor positivo para a parcela."); return

    try:
        if is_recurring and num_installments > 1:
            original_description = description 
            amount_per_installment = amount 
            for i in range(num_installments):
                current_month_offset = i 
                year_of_installment = date_obj.year + (date_obj.month - 1 + current_month_offset) // 12
                month_of_installment = (date_obj.month - 1 + current_month_offset) % 12 + 1
                day_of_installment = min(date_obj.day, calendar.monthrange(year_of_installment, month_of_installment)[1])
                current_installment_date = datetime.date(year_of_installment, month_of_installment, day_of_installment)
                installment_description = f"{original_description} (Parcela {i+1}/{num_installments})" if original_description else f"Parcela {i+1}/{num_installments} de {category}"
                current_payment_status_for_installment = payment_status if i == 0 and transaction_type == "Despesa" else "Pendente"
                if transaction_type != "Despesa": current_payment_status_for_installment = None
                _save_single_transaction_to_firestore_internal(
                    user, current_installment_date, transaction_type, category, 
                    installment_description, amount_per_installment, current_payment_status_for_installment
                )
            st.success(f"{num_installments} parcelas de '{category}' adicionadas com sucesso!")
        else:
            final_description = description 
            if is_recurring and num_installments == 1: 
                 final_description = f"{description} (Parcela 1/1)" if description else f"Parcela 1/1 de {category}"
            current_payment_status = payment_status if transaction_type == "Despesa" else None
            _save_single_transaction_to_firestore_internal(
                user, date_obj, transaction_type, category, final_description, amount, current_payment_status
            )
            if not (is_recurring and num_installments > 1): 
                st.success(f"{transaction_type} '{category}' adicionada com sucesso!")
    except Exception as e: st.error(f"Erro ao adicionar transação(ões): {e}")

def get_transactions_df():
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return pd.DataFrame()
    try:
        transactions_ref = db.collection("transactions").order_by("date", direction=firestore.Query.DESCENDING).stream()
        transactions_list = []
        for trans_doc in transactions_ref:
            data = trans_doc.to_dict()
            data["id"] = trans_doc.id
            if 'date' in data and isinstance(data['date'], datetime.datetime):
                data['date'] = data['date'].date() 
            if data.get('type') == "Despesa" and 'status_pagamento' not in data:
                data['status_pagamento'] = "Pendente"
            transactions_list.append(data)
        
        df = pd.DataFrame(transactions_list)
        if df.empty:
             return pd.DataFrame(columns=["id", "user", "date", "type", "category", "description", "amount", "month_year", "status_pagamento"])
        if 'date' in df.columns: df['date'] = pd.to_datetime(df['date'])
        if 'amount' in df.columns: df['amount'] = pd.to_numeric(df['amount'])
        return df
    except Exception as e: st.error(f"Erro ao buscar transações: {e}"); return pd.DataFrame()

def delete_transaction_from_firestore(transaction_id):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    try:
        db.collection("transactions").document(transaction_id).delete()
        st.success("Transação excluída com sucesso!")
        st.session_state.pending_delete_id = None
        if st.session_state.get('editing_transaction', {}).get('id') == transaction_id:
            st.session_state.editing_transaction = None
    except Exception as e: st.error(f"Erro ao excluir transação: {e}")
    st.rerun()

def update_transaction_in_firestore(transaction_id, data_to_update):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    try:
        data_to_update["updated_at"] = firestore.SERVER_TIMESTAMP
        db.collection("transactions").document(transaction_id).update(data_to_update)
        st.success("Transação atualizada com sucesso!")
        st.session_state.editing_transaction = None
    except Exception as e: st.error(f"Erro ao atualizar transação: {e}")
    st.rerun()

def update_payment_status_in_firestore(transaction_id, new_status):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    try:
        db.collection("transactions").document(transaction_id).update({
            "status_pagamento": new_status,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        st.success(f"Status da despesa atualizado para {new_status}!")
    except Exception as e: st.error(f"Erro ao atualizar status do pagamento: {e}")
    st.rerun()

# --- Funções de Interface para Edição/Exclusão ---
def display_edit_transaction_form():
    if not st.session_state.get('editing_transaction'): return

    editing_item = st.session_state.editing_transaction
    transaction_id = editing_item['id']
    current_data = editing_item['data']

    st.markdown("---"); st.subheader(f"✏️ Editando Transação") 
    
    current_date_val = current_data.get('date')
    if isinstance(current_date_val, pd.Timestamp): current_date_val = current_date_val.date()
    elif isinstance(current_date_val, str):
        try: current_date_val = datetime.datetime.strptime(current_date_val.split(" ")[0], "%Y-%m-%d").date()
        except ValueError: current_date_val = datetime.date.today() 
    elif not isinstance(current_date_val, datetime.date): current_date_val = datetime.date.today() 

    with st.form(key=f"edit_form_{transaction_id}"):
        edited_date = st.date_input("Data", value=current_date_val, key=f"edit_date_{transaction_id}")
        tipos = ["Receita", "Despesa", "Investimento"]
        current_type_idx = tipos.index(current_data.get('type', "Despesa")) if current_data.get('type') in tipos else 1
        edited_type = st.selectbox("Tipo", tipos, index=current_type_idx, key=f"edit_type_{transaction_id}")
        edited_category = st.text_input("Categoria", value=current_data.get('category', ''), key=f"edit_category_{transaction_id}")
        edited_description = st.text_area("Descrição", value=current_data.get('description', ''), key=f"edit_desc_{transaction_id}")
        edited_amount = st.number_input("Valor (R$)", value=float(current_data.get('amount', 0.0)),
                                        min_value=0.01, format="%.2f", step=0.01, key=f"edit_amount_{transaction_id}")
        
        edited_payment_status = current_data.get('status_pagamento', "Pendente")
        if edited_type == "Despesa":
            current_status_idx = PAYMENT_STATUS_OPTIONS.index(edited_payment_status) if edited_payment_status in PAYMENT_STATUS_OPTIONS else 0
            edited_payment_status = st.selectbox("Status do Pagamento", PAYMENT_STATUS_OPTIONS, index=current_status_idx, key=f"edit_status_{transaction_id}")

        cols = st.columns(2)
        if cols[0].form_submit_button("Salvar Alterações"):
            if not edited_category or edited_amount <= 0: st.warning("Categoria e valor positivo são obrigatórios.")
            else:
                data_to_update = {
                    "user": current_data.get('user'), "date": datetime.datetime.combine(edited_date, datetime.datetime.min.time()),
                    "type": edited_type, "category": edited_category.strip().capitalize(),
                    "description": edited_description.strip(), "amount": float(edited_amount),
                    "month_year": edited_date.strftime("%Y-%m")
                }
                if edited_type == "Despesa":
                    data_to_update["status_pagamento"] = edited_payment_status
                elif "status_pagamento" in data_to_update: 
                    del data_to_update["status_pagamento"]
                update_transaction_in_firestore(transaction_id, data_to_update)
        
        if cols[1].form_submit_button("Cancelar Edição", type="secondary"):
            st.session_state.editing_transaction = None; st.rerun()
    st.markdown("---")

def render_transaction_rows(df_transactions, list_id_prefix=""):
    if df_transactions.empty: st.info("Nenhuma transação para exibir."); return

    st.markdown(
        """<style>.transaction-row > div { display: flex; align-items: center; }
           .transaction-row .stButton button { padding: 0.25rem 0.5rem; line-height: 1.2; font-size: 0.9rem; margin-top: 5px !important; width: 100%;}
           .status-text { font-size: 0.85rem; color: #555; margin-bottom: -2px; display: block; text-align: center;}
        </style>""", 
        unsafe_allow_html=True
    )
    
    header_cols = st.columns((2, 2, 2, 3, 2, 2, 1, 1)) 
    fields = ['Data', 'Tipo', 'Categoria', 'Descrição', 'Valor (R$)', 'Status Pag.', 'Editar', 'Excluir']
    for col, field_name in zip(header_cols, fields):
        col.markdown(f"**{field_name}**")

    for index, row in df_transactions.iterrows():
        trans_id = row["id"]
        row_data_for_edit = row.to_dict()
        if isinstance(row_data_for_edit.get('date'), pd.Timestamp):
            row_data_for_edit['date'] = row_data_for_edit['date'].date()
        
        can_edit_delete = row.get('user') == st.session_state.user
        is_expense = row.get('type') == "Despesa"
        payment_status = row.get('status_pagamento', "Pendente") if is_expense else ""

        cols = st.columns((2, 2, 2, 3, 2, 2, 1, 1), gap="small") 
        
        cols[0].write(row['date'].strftime('%d/%m/%Y') if pd.notnull(row['date']) else 'N/A')
        cols[1].write(row['type'])
        cols[2].write(row['category'])
        cols[3].write(row.get('description', '')[:25] + '...' if len(row.get('description', '')) > 25 else row.get('description', '')) 
        cols[4].write(format_brazilian_currency(row['amount'])) 

        status_col_content = cols[5]
        if is_expense and can_edit_delete:
            status_col_content.markdown(f"<div class='status-text'>Status: {payment_status}</div>", unsafe_allow_html=True)
            button_label = "Pagar" if payment_status == "Pendente" else "Pendente" 
            new_status_on_click = "Pago" if payment_status == "Pendente" else "Pendente"
            if status_col_content.button(button_label, key=f"{list_id_prefix}_status_{trans_id}", help=f"Clique para marcar como {new_status_on_click}"):
                update_payment_status_in_firestore(trans_id, new_status_on_click)
        elif is_expense:
            status_col_content.write(payment_status)
        else:
            status_col_content.write("-") 

        if can_edit_delete:
            if cols[6].button("✏️", key=f"{list_id_prefix}_edit_{trans_id}", help="Editar"):
                st.session_state.editing_transaction = {'id': trans_id, 'data': row_data_for_edit}
                st.session_state.pending_delete_id = None; st.rerun()
            
            if st.session_state.get('pending_delete_id') == trans_id:
                confirm_cols = cols[7].columns([1,1])
                if confirm_cols[0].button("✅", key=f"{list_id_prefix}_confirmdel_{trans_id}", help="Confirmar Exclusão"):
                    delete_transaction_from_firestore(trans_id) 
                if confirm_cols[1].button("❌", key=f"{list_id_prefix}_canceldel_{trans_id}", help="Cancelar Exclusão"):
                    st.session_state.pending_delete_id = None; st.rerun()
            else:
                if cols[7].button("🗑️", key=f"{list_id_prefix}_delete_{trans_id}", help="Excluir"):
                    st.session_state.pending_delete_id = trans_id
                    st.session_state.editing_transaction = None; st.rerun()
        else:
            cols[6].write(""); cols[7].write("") 
    st.markdown("---")

# --- Páginas da Aplicação ---
def page_login():
    st.title("Controle Financeiro do Casal"); st.subheader("Login")
    with st.form("login_form"):
        username = st.text_input("Usuário", key="login_username")
        password = st.text_input("Senha", type="password", key="login_password")
        if st.form_submit_button("Entrar"): login_user(username, password)

def page_log_transaction():
    st.header(f"Olá, {st.session_state.user}! Registre uma nova transação:")
    display_edit_transaction_form() 
    st.radio("Tipo de Lançamento:", ("Único", "Parcelado"), horizontal=True, key="transaction_mode_selection_key")

    with st.form("transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            transaction_date_val = st.date_input("Data da Transação (ou 1ª Parcela)", datetime.date.today(), key="form_trans_date")
            transaction_type_val = st.selectbox("Tipo", ["Receita", "Despesa", "Investimento"], key="form_trans_type")
        with col2:
            common_categories = {"Receita": ["Salário", "Freelance", "Rendimentos", "Outros"],
                                 "Despesa": ["Moradia", "Alimentação", "Transporte", "Saúde", "Lazer", "Educação", "Vestuário", "Contas", "Outros"],
                                 "Investimento": ["Ações", "Fundos Imobiliários", "Renda Fixa", "Criptomoedas", "Outros"]}
            category_options = common_categories.get(transaction_type_val, ["Outros"]) 
            category_val = st.text_input("Categoria", key="form_trans_category", placeholder="Ou digite uma nova")
            st.caption(f"Sugestões: {', '.join(category_options)}")
        
        description_val = st.text_area("Descrição (Opcional)", key="form_trans_desc")
        amount_val = st.number_input("Valor (R$) (por parcela, se recorrente)", min_value=0.01, format="%.2f", step=0.01, key="form_trans_amount")
        
        payment_status_val = "Pendente" 
        if transaction_type_val == "Despesa":
            payment_status_val = st.radio("Status do Pagamento:", PAYMENT_STATUS_OPTIONS, index=0, horizontal=True, key="form_payment_status")

        st.markdown("---") 
        num_installments_val = 1
        is_recurring_flag_val = False
        if st.session_state.transaction_mode_selection_key == "Parcelado":
            is_recurring_flag_val = True
            num_installments_val = st.number_input("Número Total de Parcelas", min_value=1, 
                                                   value=st.session_state.get("form_num_installments_val", 2), 
                                                   step=1, key="form_num_installments_val")
        submitted = st.form_submit_button("Adicionar Transação")
        if submitted:
            add_transaction(st.session_state.user, transaction_date_val, transaction_type_val, 
                            category_val, description_val, amount_val,
                            is_recurring_flag_val, num_installments_val,
                            payment_status_val if transaction_type_val == "Despesa" else None) 
    
    st.markdown("---"); st.subheader("Últimas Transações Lançadas por Você:")
    all_trans_df = get_transactions_df()
    if not all_trans_df.empty:
        user_recent_df = all_trans_df[all_trans_df['user'] == st.session_state.user].sort_values(by="date", ascending=False).head(10)
        render_transaction_rows(user_recent_df, "recent")
    else: st.info("Nenhuma transação registrada no banco de dados.")

def display_summary_charts_and_data(df_period, df_full_history_for_user_or_couple, selected_month_internal, title_prefix=""):
    if df_period.empty:
        st.info(f"{title_prefix}Nenhuma transação encontrada para {format_month_year_for_display(selected_month_internal)}.")
    else:
        receitas = df_period[df_period['type'] == 'Receita']['amount'].sum()
        despesas_total = df_period[df_period['type'] == 'Despesa']['amount'].sum()
        investimentos_periodo = df_period[df_period['type'] == 'Investimento']['amount'].sum() 
        saldo = receitas - (despesas_total + investimentos_periodo) 

        st.subheader(f"{title_prefix}Resumo de {format_month_year_for_display(selected_month_internal)}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Receitas", format_brazilian_currency(receitas))
        col2.metric("Despesas", format_brazilian_currency(despesas_total)) 
        col3.metric("Investimentos", format_brazilian_currency(investimentos_periodo)) 
        col4.metric("Saldo Final", format_brazilian_currency(saldo), delta_color=("inverse" if saldo < 0 else "normal"))
        st.markdown("---")
        st.subheader(f"{title_prefix}Composição Receita vs. Despesa ({format_month_year_for_display(selected_month_internal)})")
        chart_values, chart_names, chart_colors, chart_title = [], [], [], "Situação Financeira do Mês"
        if receitas == 0 and despesas_total == 0:
            st.info(f"{title_prefix}Sem dados de receita ou despesa para este período.")
        elif receitas == 0 and despesas_total > 0:
            chart_values, chart_names, chart_colors = [despesas_total], ['Despesas (Sem Receita)'], ['crimson']
            chart_title = "Situação Financeira: Déficit (Sem Receita)"
        elif receitas > 0:
            if despesas_total <= receitas:
                chart_values = [despesas_total, receitas - despesas_total]
                chart_names = ['Despesas Cobertas', 'Saldo Positivo da Receita']
                chart_colors = ['sandybrown', 'lightgreen'] 
                chart_title = "Receita vs. Despesa: Saldo Positivo"
                if despesas_total == 0 and (receitas - despesas_total) == 0: pass
                elif despesas_total == 0 : chart_values, chart_names, chart_colors = [receitas - despesas_total], ['Saldo Positivo da Receita'], ['lightgreen']
                elif (receitas - despesas_total) == 0: chart_values, chart_names, chart_colors = [despesas_total], ['Despesas (Cobriram 100% da Receita)'], ['sandybrown']
            else: 
                chart_values = [receitas, despesas_total - receitas]
                chart_names = ['Receita (Coberta)', 'Despesa Excedente (Déficit)']
                chart_colors = ['lightcoral', 'crimson'] 
                chart_title = "Receita vs. Despesa: Déficit"
        if chart_values and sum(chart_values) > 0: 
            fig_comp = px.pie(values=chart_values, names=chart_names, title=chart_title, color_discrete_sequence=chart_colors)
            fig_comp.update_traces(textposition='inside', textinfo='percent+label+value', hole=.3 if len(chart_values)>1 else 0)
            st.plotly_chart(fig_comp, use_container_width=True)
        elif not (receitas == 0 and despesas_total == 0) : st.info(f"{title_prefix}Dados insuficientes ou zerados para o gráfico.")
        st.markdown("---")

    if not df_full_history_for_user_or_couple.empty and selected_month_internal:
        st.subheader(f"{title_prefix}Histórico Mensal (12 Meses até {format_month_year_for_display(selected_month_internal)})")
        df_history_copy = df_full_history_for_user_or_couple.copy()
        if 'date' in df_history_copy.columns:
             df_history_copy['month_year'] = pd.to_datetime(df_history_copy['date']).dt.strftime('%Y-%m')
        all_available_months_sorted_chronologically = sorted(list(df_history_copy['month_year'].unique()))
        try:
            end_index = all_available_months_sorted_chronologically.index(selected_month_internal)
            start_index = max(0, end_index - 11) 
            months_for_history_chart = all_available_months_sorted_chronologically[start_index : end_index + 1]
            if months_for_history_chart:
                history_df_for_chart = df_history_copy[df_history_copy['month_year'].isin(months_for_history_chart)]
                history_df_filtered = history_df_for_chart[history_df_for_chart['type'].isin(['Receita', 'Despesa'])]
                if not history_df_filtered.empty:
                    monthly_summary = history_df_filtered.groupby(['month_year', 'type'])['amount'].sum().unstack(fill_value=0).reset_index()
                    if 'Receita' not in monthly_summary.columns: monthly_summary['Receita'] = 0
                    if 'Despesa' not in monthly_summary.columns: monthly_summary['Despesa'] = 0
                    monthly_summary = monthly_summary.sort_values(by='month_year') 
                    fig_line_history = px.line(monthly_summary, x='month_year', y=['Receita', 'Despesa'],
                                               title='Receitas vs. Despesas Mensais',
                                               labels={'month_year': 'Mês/Ano', 'value': 'Valor (R$)', 'variable': 'Tipo'}, markers=True)
                    fig_line_history.update_layout(yaxis_title='Valor (R$)', xaxis_title='Mês/Ano')
                    st.plotly_chart(fig_line_history, use_container_width=True)
                else: st.info(f"{title_prefix}Não há dados de Receita ou Despesa no período de 12 meses até {format_month_year_for_display(selected_month_internal)}.")
            else: st.info(f"{title_prefix}Não há dados suficientes para o histórico de 12 meses até {format_month_year_for_display(selected_month_internal)}.")
        except ValueError: st.info(f"{title_prefix}Mês selecionado ({format_month_year_for_display(selected_month_internal)}) não encontrado nos dados históricos para o gráfico de linha.")
    elif not df_full_history_for_user_or_couple.empty: st.info(f"{title_prefix}Selecione um mês para ver o histórico de 12 meses correspondente.")
    else: st.info(f"{title_prefix}Nenhuma transação no histórico para exibir gráfico de linha.")
    st.markdown("---")
    st.subheader(f"{title_prefix}Detalhes das Transações de {format_month_year_for_display(selected_month_internal) if selected_month_internal else 'Período Não Selecionado'}")
    if not df_period.empty: 
        render_transaction_rows(df_period.sort_values(by="date", ascending=False), f"{title_prefix.lower().replace(' ', '_').replace('-', '')}_summary_period")
    elif selected_month_internal: 
        st.info(f"{title_prefix}Nenhuma transação para exibir detalhes em {format_month_year_for_display(selected_month_internal)}.")

def page_my_summary():
    st.header(f"Meu Resumo Financeiro - {st.session_state.user}")
    display_edit_transaction_form() 
    selectbox_key = "my_summary_month_select" 
    current_menu_page = st.session_state.get("main_menu_selection")
    df_all_transactions_system = get_transactions_df() 
    if df_all_transactions_system.empty: st.info("Nenhuma transação no banco de dados."); return
    df_user_full_history = df_all_transactions_system[df_all_transactions_system['user'] == st.session_state.user].copy()
    if df_user_full_history.empty: st.info("Você ainda não registrou transações."); return
    if 'date' in df_user_full_history.columns: df_user_full_history['month_year'] = pd.to_datetime(df_user_full_history['date']).dt.strftime('%Y-%m')
    current_calendar_month_internal = datetime.date.today().strftime("%Y-%m")
    available_months_internal = sorted(list(df_user_full_history['month_year'].unique()), reverse=False) 
    display_options, internal_to_display_map, display_to_internal_map = [], {}, {} 
    all_possible_months_internal = set(available_months_internal)
    all_possible_months_internal.add(current_calendar_month_internal) 
    for month_internal in sorted(list(all_possible_months_internal), reverse=True): 
        formatted_month = format_month_year_for_display(month_internal)
        display_options.append(formatted_month)
        internal_to_display_map[month_internal] = formatted_month
        display_to_internal_map[formatted_month] = month_internal
    if not display_options: st.info("Nenhum período disponível para seleção."); return
    default_display_value = format_month_year_for_display(current_calendar_month_internal)
    if st.session_state.get("last_main_menu_selection") != current_menu_page or selectbox_key not in st.session_state:
        st.session_state[selectbox_key] = default_display_value
    elif st.session_state.get(selectbox_key) not in display_options and display_options:
         st.session_state[selectbox_key] = display_options[0]
    selected_month_display = st.selectbox("Selecione o Mês/Ano para o resumo detalhado:", options=display_options, key=selectbox_key)
    selected_month_internal = display_to_internal_map.get(selected_month_display)
    if selected_month_internal:
        df_period_user = df_user_full_history[df_user_full_history['month_year'] == selected_month_internal]
        display_summary_charts_and_data(df_period_user, df_user_full_history, selected_month_internal, "Meu ")
    elif display_options : 
        st.warning("Mês selecionado não encontrado. Exibindo o mais recente disponível.")
        selected_month_internal_fallback = display_to_internal_map.get(display_options[0])
        if selected_month_internal_fallback:
            df_period_user = df_user_full_history[df_user_full_history['month_year'] == selected_month_internal_fallback]
            display_summary_charts_and_data(df_period_user, df_user_full_history, selected_month_internal_fallback, "Meu ")

def page_couple_summary():
    st.header("Resumo Financeiro do Casal")
    display_edit_transaction_form() 
    selectbox_key = "couple_summary_month_select"
    current_menu_page = st.session_state.get("main_menu_selection")
    df_all_transactions_system = get_transactions_df() 
    if df_all_transactions_system.empty: st.info("Nenhuma transação registrada no banco de dados."); return
    if 'date' in df_all_transactions_system.columns: df_all_transactions_system['month_year'] = pd.to_datetime(df_all_transactions_system['date']).dt.strftime('%Y-%m')
    current_calendar_month_internal = datetime.date.today().strftime("%Y-%m")
    available_months_internal = sorted(list(df_all_transactions_system['month_year'].unique()), reverse=False)
    display_options, internal_to_display_map, display_to_internal_map = [], {}, {}
    all_possible_months_internal = set(available_months_internal)
    all_possible_months_internal.add(current_calendar_month_internal)
    for month_internal in sorted(list(all_possible_months_internal), reverse=True):
        formatted_month = format_month_year_for_display(month_internal)
        display_options.append(formatted_month)
        internal_to_display_map[month_internal] = formatted_month
        display_to_internal_map[formatted_month] = month_internal
    if not display_options: st.info("Nenhum período disponível para seleção."); return
    default_display_value = format_month_year_for_display(current_calendar_month_internal)
    if st.session_state.get("last_main_menu_selection") != current_menu_page or selectbox_key not in st.session_state:
        st.session_state[selectbox_key] = default_display_value
    elif st.session_state.get(selectbox_key) not in display_options and display_options:
        st.session_state[selectbox_key] = display_options[0]
    selected_month_display = st.selectbox("Selecione o Mês/Ano para o resumo detalhado:", options=display_options, key=selectbox_key)
    selected_month_internal = display_to_internal_map.get(selected_month_display)
    if selected_month_internal:
        df_period_couple = df_all_transactions_system[df_all_transactions_system['month_year'] == selected_month_internal]
        display_summary_charts_and_data(df_period_couple, df_all_transactions_system, selected_month_internal, "Casal - ")
    elif display_options:
        st.warning("Mês selecionado não encontrado. Exibindo o mais recente disponível.")
        selected_month_internal_fallback = display_to_internal_map.get(display_options[0])
        if selected_month_internal_fallback:
            df_period_couple = df_all_transactions_system[df_all_transactions_system['month_year'] == selected_month_internal_fallback]
            display_summary_charts_and_data(df_period_couple, df_all_transactions_system, selected_month_internal_fallback, "Casal - ")

# --- Lógica Principal da Aplicação ---
def main_app():
    st.sidebar.title(f"Bem-vindo(a), {st.session_state.user}!")
    menu_options = {"🏠 Lançar Transação": page_log_transaction, "📊 Meu Resumo": page_my_summary, "💑 Resumo do Casal": page_couple_summary}
    selection = st.sidebar.radio("Menu", list(menu_options.keys()), key="main_menu_selection")
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout"): logout_user()
    page_function = menu_options[selection]
    page_function() 
    st.session_state.last_main_menu_selection = selection 
    st.sidebar.markdown("---"); st.sidebar.info("Dados armazenados no Firebase Firestore.")

# --- Ponto de Entrada ---
if not db: st.error("Falha na conexão com o banco de dados. A aplicação não pode iniciar.")
elif not st.session_state.get('logged_in', False): page_login()
else: main_app()
