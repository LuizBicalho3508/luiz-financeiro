import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
import json
import calendar 
import locale # Para formatação de moeda

# --- Configuração da Página ---
st.set_page_config(layout="wide")


# --- Configurações Iniciais e Autenticação (Usuários) ---
USERS = {"Luiz": "1517", "Iasmin": "1516"}

PORTUGUESE_MONTHS = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]

PAYMENT_STATUS_OPTIONS = ["Pendente", "Pago"] 
MOTO_EXPENSE_TYPES = ["Manutenção Preventiva", "Manutenção Corretiva", "Peça", "Acessório", "Documentação", "Combustível", "Outros"]

# Tenta definir o locale para Português do Brasil
LOCALE_SET_SUCCESS = False
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
    LOCALE_SET_SUCCESS = True
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil.1252') # Windows
        LOCALE_SET_SUCCESS = True
    except locale.Error:
        if 'initial_locale_warning_shown' not in st.session_state:
            print("Aviso: Locale 'pt_BR' não pôde ser configurado. Usando formatação de moeda manual.")
            st.session_state.initial_locale_warning_shown = True 
        LOCALE_SET_SUCCESS = False


# --- Inicialização do Firebase ---
@st.cache_resource 
def initialize_firebase():
    if not firebase_admin._apps: 
        try:
            firebase_creds_json_str = st.secrets.get("FIREBASE_SERVICE_ACCOUNT_JSON")
            if not firebase_creds_json_str:
                st.error("Credenciais Firebase (FIREBASE_SERVICE_ACCOUNT_JSON) não encontradas nos Streamlit Secrets.")
                st.info("Por favor, adicione suas credenciais Firebase JSON como um segredo chamado 'FIREBASE_SERVICE_ACCOUNT_JSON' nas configurações do seu app Streamlit Cloud.")
                st.stop(); return None
            firebase_creds_dict = json.loads(firebase_creds_json_str)
            cred = credentials.Certificate(firebase_creds_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Erro ao inicializar o Firebase: {e}")
            st.info("Verifique se as credenciais Firebase JSON estão corretas e no formato esperado.")
            st.stop(); return None
    return firestore.client()

db = initialize_firebase() 

# --- Inicialização do Estado da Sessão ---
def initialize_app_session_state():
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'user' not in st.session_state: st.session_state.user = None
    if 'editing_transaction' not in st.session_state: st.session_state.editing_transaction = None 
    if 'pending_delete_id' not in st.session_state: st.session_state.pending_delete_id = None 
    if 'editing_moto_transaction' not in st.session_state: st.session_state.editing_moto_transaction = None
    if 'pending_delete_moto_id' not in st.session_state: st.session_state.pending_delete_moto_id = None
    if 'transaction_mode_selection_key' not in st.session_state: st.session_state.transaction_mode_selection_key = "Único"
    if 'last_main_menu_selection' not in st.session_state: st.session_state.last_main_menu_selection = None
    if 'moto_expense_type_key' not in st.session_state: st.session_state.moto_expense_type_key = MOTO_EXPENSE_TYPES[0]


initialize_app_session_state()

# --- Funções Auxiliares de Formatação ---
def format_month_year_for_display(month_year_str):
    if not month_year_str or len(month_year_str) != 7 or month_year_str[4] != '-': return month_year_str 
    try:
        year, month = map(int, month_year_str.split('-'))
        if not (1 <= month <= 12): return month_year_str 
        return f"{PORTUGUESE_MONTHS[month-1]} de {year}"
    except (ValueError, IndexError): return month_year_str 

def parse_display_month_year(display_month_year_str):
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
    global LOCALE_SET_SUCCESS
    if LOCALE_SET_SUCCESS:
        try: return locale.currency(value, grouping=True, symbol='R$ ') 
        except (locale.Error, ValueError): 
            LOCALE_SET_SUCCESS = False 
            if 'pt_BR_runtime_warning_shown' not in st.session_state: 
                print("Aviso: Falha ao usar formatação de moeda do locale em tempo de execução. Usando formatação manual.")
                st.session_state.pt_BR_runtime_warning_shown = True
    try:
        val_float = float(value) 
        formatted_string = f"{val_float:_.2f}".replace('.', ',').replace('_', '.')
        return f"R$ {formatted_string}"
    except Exception: return f"R$ {value:.2f}"


# --- Funções de Autenticação ---
def login_user(username, password):
    if username in USERS and USERS[username] == password:
        st.session_state.logged_in = True
        st.session_state.user = username
        st.session_state.last_main_menu_selection = None 
        st.rerun()
    else: st.error("Usuário ou senha incorretos.")

def logout_user():
    keys_to_clear = ['logged_in', 'user', 'editing_transaction', 'pending_delete_id', 
                     'editing_moto_transaction', 'pending_delete_moto_id', 
                     'last_main_menu_selection', 'my_summary_month_select', 
                     'couple_summary_month_select']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# --- Funções CRUD (Geral e Moto) ---
# ... (Funções CRUD para transações gerais permanecem as mesmas)
# ... (Funções CRUD para transações de moto serão adicionadas abaixo)
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

# --- Funções CRUD para Despesas da Moto ---
def add_moto_transaction(user, date_obj, expense_type, description, amount, mileage, liters=None):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    if not expense_type or not description or amount <= 0:
        st.warning("Preencha todos os campos obrigatórios com valores válidos.")
        return
    try:
        timestamp_obj = datetime.datetime.combine(date_obj, datetime.datetime.min.time())
        doc_ref = db.collection("moto_transactions").document()
        data_to_save = {
            "user": user, "date": timestamp_obj, "expense_type": expense_type,
            "description": description.strip(), "amount": float(amount),
            "mileage": int(mileage) if mileage else None,
            "created_at": firestore.SERVER_TIMESTAMP
        }
        if expense_type == "Combustível" and liters is not None and liters > 0:
            data_to_save["liters"] = float(liters)
        
        doc_ref.set(data_to_save)
        st.success("Despesa da moto adicionada com sucesso!")
    except Exception as e: st.error(f"Erro ao adicionar despesa da moto: {e}")

def get_moto_transactions_df():
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return pd.DataFrame()
    try:
        transactions_ref = db.collection("moto_transactions").order_by("date", direction=firestore.Query.DESCENDING).stream()
        transactions_list = []
        for trans_doc in transactions_ref:
            data = trans_doc.to_dict()
            data["id"] = trans_doc.id
            if 'date' in data and isinstance(data['date'], datetime.datetime):
                data['date'] = data['date'].date()
            transactions_list.append(data)
        
        df = pd.DataFrame(transactions_list)
        if df.empty:
             return pd.DataFrame(columns=["id", "user", "date", "expense_type", "description", "amount", "mileage", "liters"])
        if 'date' in df.columns: df['date'] = pd.to_datetime(df['date'])
        if 'amount' in df.columns: df['amount'] = pd.to_numeric(df['amount'])
        if 'mileage' in df.columns: df['mileage'] = pd.to_numeric(df['mileage'])
        if 'liters' in df.columns: df['liters'] = pd.to_numeric(df['liters'])
        return df
    except Exception as e: st.error(f"Erro ao buscar despesas da moto: {e}"); return pd.DataFrame()

def delete_moto_transaction_from_firestore(transaction_id):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    try:
        db.collection("moto_transactions").document(transaction_id).delete()
        st.success("Despesa da moto excluída com sucesso!")
        st.session_state.pending_delete_moto_id = None
        if st.session_state.get('editing_moto_transaction', {}).get('id') == transaction_id:
            st.session_state.editing_moto_transaction = None
    except Exception as e: st.error(f"Erro ao excluir despesa da moto: {e}")
    st.rerun()

def update_moto_transaction_in_firestore(transaction_id, data_to_update):
    if not db: st.error("Conexão com o banco de dados não estabelecida."); return
    try:
        data_to_update["updated_at"] = firestore.SERVER_TIMESTAMP
        db.collection("moto_transactions").document(transaction_id).update(data_to_update)
        st.success("Despesa da moto atualizada com sucesso!")
        st.session_state.editing_moto_transaction = None
    except Exception as e: st.error(f"Erro ao atualizar despesa da moto: {e}")
    st.rerun()


# --- Funções de Interface (Geral, Moto, Edição) ---
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
                    st.session_state.editing_moto_transaction = None; st.rerun()
        else:
            cols[6].write(""); cols[7].write("") 
    st.markdown("---")

# --- Funções de Interface para Despesas da Moto ---
def display_edit_moto_transaction_form():
    if not st.session_state.get('editing_moto_transaction'): return

    editing_item = st.session_state.editing_moto_transaction
    transaction_id = editing_item['id']
    current_data = editing_item['data']

    st.markdown("---"); st.subheader(f"✏️ Editando Despesa da Moto") 
    
    current_date_val = current_data.get('date')
    if isinstance(current_date_val, pd.Timestamp): current_date_val = current_date_val.date()
    elif isinstance(current_date_val, str):
        try: current_date_val = datetime.datetime.strptime(current_date_val.split(" ")[0], "%Y-%m-%d").date()
        except ValueError: current_date_val = datetime.date.today() 
    elif not isinstance(current_date_val, datetime.date): current_date_val = datetime.date.today() 

    with st.form(key=f"edit_moto_form_{transaction_id}"):
        edited_date = st.date_input("Data do Serviço", value=current_date_val, key=f"edit_moto_date_{transaction_id}")
        current_type_idx = MOTO_EXPENSE_TYPES.index(current_data.get('expense_type', "Outros")) if current_data.get('expense_type') in MOTO_EXPENSE_TYPES else 6
        edited_type = st.selectbox("Tipo de Despesa", MOTO_EXPENSE_TYPES, index=current_type_idx, key=f"edit_moto_type_{transaction_id}")
        edited_description = st.text_area("Descrição", value=current_data.get('description', ''), key=f"edit_moto_desc_{transaction_id}")
        edited_amount = st.number_input("Valor (R$)", value=float(current_data.get('amount', 0.0)),
                                        min_value=0.01, format="%.2f", step=0.01, key=f"edit_moto_amount_{transaction_id}")
        edited_mileage = st.number_input("Quilometragem (KM)", value=int(current_data.get('mileage', 0) or 0),
                                         min_value=0, step=100, key=f"edit_moto_mileage_{transaction_id}")
        
        edited_liters = current_data.get('liters', 0.0)
        if edited_type == "Combustível":
            edited_liters = st.number_input("Litros Abastecidos", value=float(edited_liters or 0.0), min_value=0.0, format="%.2f", step=0.01, key=f"edit_moto_liters_{transaction_id}")

        cols = st.columns(2)
        if cols[0].form_submit_button("Salvar Alterações"):
            if not edited_type or not edited_description or edited_amount <= 0: st.warning("Preencha todos os campos obrigatórios com valores válidos.")
            else:
                data_to_update = {
                    "user": current_data.get('user'), "date": datetime.datetime.combine(edited_date, datetime.datetime.min.time()),
                    "expense_type": edited_type, "description": edited_description.strip(),
                    "amount": float(edited_amount), "mileage": int(edited_mileage) if edited_mileage > 0 else None
                }
                if edited_type == "Combustível" and edited_liters > 0:
                    data_to_update["liters"] = float(edited_liters)
                elif "liters" in data_to_update:
                    del data_to_update["liters"]
                
                update_moto_transaction_in_firestore(transaction_id, data_to_update)
        
        if cols[1].form_submit_button("Cancelar Edição", type="secondary"):
            st.session_state.editing_moto_transaction = None; st.rerun()
    st.markdown("---")

def render_moto_transaction_rows(df_moto_transactions):
    if df_moto_transactions.empty: st.info("Nenhum lançamento para a moto ainda."); return

    st.markdown(
        """<style>.moto-row > div { display: flex; align-items: center; }</style>""", 
        unsafe_allow_html=True
    )
    
    header_cols = st.columns((2, 3, 4, 2, 2, 2, 1, 1)) 
    fields = ['Data', 'Tipo', 'Descrição', 'Valor (R$)', 'KM', 'Litros', 'Editar', 'Excluir']
    for col, field_name in zip(header_cols, fields):
        col.markdown(f"**{field_name}**")

    for index, row in df_moto_transactions.iterrows():
        trans_id = row["id"]
        row_data_for_edit = row.to_dict()
        if isinstance(row_data_for_edit.get('date'), pd.Timestamp):
            row_data_for_edit['date'] = row_data_for_edit['date'].date()
        
        can_edit_delete = row.get('user') == st.session_state.user

        cols = st.columns((2, 3, 4, 2, 2, 2, 1, 1), gap="small") 
        
        cols[0].write(row['date'].strftime('%d/%m/%Y') if pd.notnull(row['date']) else 'N/A')
        cols[1].write(row['expense_type'])
        cols[2].write(row.get('description', ''))
        cols[3].write(format_brazilian_currency(row['amount'])) 
        cols[4].write(f"{row['mileage']:,}".replace(",", ".") if pd.notnull(row['mileage']) and row['mileage'] > 0 else "-")
        cols[5].write(f"{row['liters']:.2f} L" if pd.notnull(row.get('liters')) and row.get('liters') > 0 else "-")

        if can_edit_delete:
            if cols[6].button("✏️", key=f"moto_edit_{trans_id}", help="Editar"):
                st.session_state.editing_moto_transaction = {'id': trans_id, 'data': row_data_for_edit}
                st.session_state.pending_delete_moto_id = None; st.rerun()
            
            if st.session_state.get('pending_delete_moto_id') == trans_id:
                confirm_cols = cols[7].columns([1,1])
                if confirm_cols[0].button("✅", key=f"moto_confirmdel_{trans_id}", help="Confirmar Exclusão"):
                    delete_moto_transaction_from_firestore(trans_id) 
                if confirm_cols[1].button("❌", key=f"moto_canceldel_{trans_id}", help="Cancelar Exclusão"):
                    st.session_state.pending_delete_moto_id = None; st.rerun()
            else:
                if cols[7].button("🗑️", key=f"moto_delete_{trans_id}", help="Excluir"):
                    st.session_state.pending_delete_moto_id = trans_id
                    st.session_state.editing_moto_transaction = None; st.rerun()
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
                    
                    color_map = {"Receita": "blue", "Despesa": "red"}

                    fig_line_history = px.line(monthly_summary, x='month_year', y=['Receita', 'Despesa'],
                                               title='Receitas vs. Despesas Mensais',
                                               labels={'month_year': 'Mês/Ano', 'value': 'Valor (R$)', 'variable': 'Tipo'}, 
                                               markers=True,
                                               color_discrete_map=color_map) 
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

# --- Nova Página: Despesas da Moto ---
def page_moto_expenses():
    st.header("🏍️ Controle de Despesas da Moto")
    display_edit_moto_transaction_form()

    st.subheader("Adicionar Novo Lançamento")
    
    # Seletor do tipo de despesa fora do formulário para UI dinâmica
    moto_expense_type = st.selectbox("Tipo de Despesa", MOTO_EXPENSE_TYPES, key="moto_expense_type_key")

    with st.form("moto_transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            moto_date = st.date_input("Data do Serviço", datetime.date.today(), key="moto_date")
            moto_amount = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", step=0.01, key="moto_amount")
        with col2:
            moto_mileage = st.number_input("Quilometragem (KM)", min_value=0, step=100, key="moto_mileage", help="Opcional: KM no momento do serviço")
            moto_liters = 0.0
            # Campo de litros aparece condicionalmente
            if st.session_state.moto_expense_type_key == "Combustível":
                moto_liters = st.number_input("Litros Abastecidos", min_value=0.0, format="%.2f", step=0.01, key="moto_liters")

        moto_description = st.text_area("Descrição (Ex: Troca de óleo, Pneu traseiro)", key="moto_desc")
        
        submitted = st.form_submit_button("Adicionar Despesa da Moto")
        if submitted:
            add_moto_transaction(
                st.session_state.user,
                moto_date,
                st.session_state.moto_expense_type_key, # Usa o valor do seletor externo
                moto_description,
                moto_amount,
                moto_mileage,
                moto_liters if st.session_state.moto_expense_type_key == "Combustível" else None
            )

    st.markdown("---")
    st.subheader("Histórico de Manutenções e Despesas")
    
    df_moto = get_moto_transactions_df()
    
    if not df_moto.empty:
        total_cost = df_moto['amount'].sum()
        
        df_with_mileage = df_moto.dropna(subset=['mileage'])
        cost_per_km = 0
        km_per_liter = 0
        
        if not df_with_mileage.empty and df_with_mileage['mileage'].nunique() > 1:
            # Filtra apenas para despesas de combustível com quilometragem e litros
            df_fuel_for_calc = df_with_mileage[(df_with_mileage['expense_type'] == 'Combustível') & (df_with_mileage['liters'].notna()) & (df_with_mileage['liters'] > 0)]
            total_fuel_cost = df_fuel_for_calc['amount'].sum()
            total_liters = df_fuel_for_calc['liters'].sum()
            
            # A distância percorrida é calculada com base em todas as entradas de KM
            max_km = df_with_mileage['mileage'].max()
            min_km = df_with_mileage['mileage'].min()
            distance_traveled = max_km - min_km
            
            if distance_traveled > 0:
                # Custo de combustível por KM
                if total_fuel_cost > 0:
                    cost_per_km = total_fuel_cost / distance_traveled
                # Consumo em KM por Litro
                if total_liters > 0:
                    km_per_liter = distance_traveled / total_liters

        col1, col2, col3 = st.columns(3)
        col1.metric("Custo Total com a Moto", format_brazilian_currency(total_cost))
        if cost_per_km > 0:
            col2.metric("Custo Médio de Combustível", f"{format_brazilian_currency(cost_per_km)} / KM")
        else:
            col2.info("Adicione lançamentos de combustível com KM para calcular o custo/KM.")
        
        if km_per_liter > 0:
            col3.metric("Consumo Médio", f"{km_per_liter:.2f} KM / L")
        else:
            col3.info("Adicione lançamentos de combustível com KM e Litros para calcular o KM/L.")

        st.subheader("Gastos por Tipo")
        costs_by_type = df_moto.groupby('expense_type')['amount'].sum().reset_index()
        fig_moto_costs = px.bar(costs_by_type, x='expense_type', y='amount', 
                                title="Distribuição de Custos da Moto",
                                labels={'expense_type': 'Tipo de Despesa', 'amount': 'Valor Gasto (R$)'},
                                text_auto=True)
        fig_moto_costs.update_traces(texttemplate='%{y:,.2f}', textposition='outside')
        st.plotly_chart(fig_moto_costs, use_container_width=True)
        st.markdown("---")

    render_moto_transaction_rows(df_moto)


# --- Lógica Principal da Aplicação ---
def main_app():
    st.sidebar.title(f"Bem-vindo(a), {st.session_state.user}!")
    menu_options = {
        "🏠 Lançar Transação": page_log_transaction,
        "📊 Meu Resumo": page_my_summary,
        "💑 Resumo do Casal": page_couple_summary,
        "🏍️ Despesas da Moto": page_moto_expenses
    }
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
