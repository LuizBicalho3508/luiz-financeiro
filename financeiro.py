import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt

st.set_page_config(page_title="Controle Financeiro", layout="wide")

# Conexão com o banco de dados
conn = sqlite3.connect("financeiro.db", check_same_thread=False)
cursor = conn.cursor()

# Criação das tabelas
cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS despesas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    data TEXT,
    mes INTEGER,
    despesa TEXT,
    valor REAL,
    status TEXT,
    FOREIGN KEY(user_id) REFERENCES usuarios(id)
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS receitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    data TEXT,
    categoria TEXT,
    valor REAL,
    FOREIGN KEY(user_id) REFERENCES usuarios(id)
)''')
conn.commit()

# Autenticação
if "user_id" not in st.session_state:
    st.title("Login")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        cursor.execute("SELECT * FROM usuarios WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        if user:
            st.session_state.user_id = user[0]
            st.session_state.username = user[1]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos")
    st.markdown("Não tem conta?")
    if st.button("Criar Conta"):
        if not username.strip() or not password.strip():
            st.error("Usuário e senha não podem estar em branco.")
        else:
            try:
                cursor.execute("INSERT INTO usuarios (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                st.success("Conta criada com sucesso! Faça login.")
            except:
                st.error("Nome de usuário já existe.")
else:
    user_id = st.session_state.user_id
    username = st.session_state.username
    st.sidebar.success(f"Logado como: {username}")
    if st.sidebar.button("Deslogar"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    aba = st.sidebar.radio("Menu", ["Dashboard", "Despesas", "Receitas", "Histórico de Receitas"])

    # ==================== RECEITAS ====================
    if aba == "Receitas":
        st.title("Receitas")

        with st.expander("➕ Adicionar Receita"):
            with st.form("form_receita"):
                data_receita = st.date_input("Data da Receita", value=pd.Timestamp.now())
                categoria = st.text_input("Categoria", placeholder="ex: Salário, Venda, Extra")
                valor_receita = st.number_input("Valor", min_value=0.0, step=0.01)
                submitted = st.form_submit_button("Salvar Receita")
                if submitted:
                    cursor.execute("INSERT INTO receitas (user_id, data, categoria, valor) VALUES (?, ?, ?, ?)",
                                   (user_id, str(data_receita), categoria, valor_receita))
                    conn.commit()
                    st.success("Receita adicionada com sucesso!")
                    st.rerun()

        df_receitas = pd.read_sql_query("SELECT id, data, categoria, valor FROM receitas WHERE user_id = ? ORDER BY data DESC", conn, params=(user_id,))
        if not df_receitas.empty:
            df_receitas['data'] = pd.to_datetime(df_receitas['data']).dt.strftime('%d/%m/%Y')
            st.dataframe(df_receitas[['data', 'categoria', 'valor']], use_container_width=True)

            with st.expander("✏️ Editar ou Excluir Receita"):
                receita_id = st.selectbox("Selecione a Receita", df_receitas['id'])
                receita_selecionada = df_receitas[df_receitas['id'] == receita_id].iloc[0]
                nova_data = st.date_input("Nova Data", pd.to_datetime(receita_selecionada['data'], dayfirst=True))
                nova_categoria = st.text_input("Nova Categoria", receita_selecionada['categoria'])
                novo_valor = st.number_input("Novo Valor", value=float(receita_selecionada['valor']), step=0.01)

                if st.button("Atualizar Receita"):
                    cursor.execute("UPDATE receitas SET data = ?, categoria = ?, valor = ? WHERE id = ?",
                                   (str(nova_data), nova_categoria, novo_valor, receita_id))
                    conn.commit()
                    st.success("Receita atualizada!")
                    st.rerun()

                if st.button("Excluir Receita"):
                    cursor.execute("DELETE FROM receitas WHERE id = ?", (receita_id,))
                    conn.commit()
                    st.warning("Receita excluída.")
                    st.rerun()
        else:
            st.info("Nenhuma receita cadastrada ainda.")

    # ==================== HISTÓRICO ====================
    elif aba == "Histórico de Receitas":
        st.title("📖 Histórico de Receitas")
        df_hist = pd.read_sql_query("SELECT * FROM receitas WHERE user_id = ? ORDER BY data DESC", conn, params=(user_id,))
        if not df_hist.empty:
            df_hist['data'] = pd.to_datetime(df_hist['data'])
            filtro_categoria = st.multiselect("Filtrar por categoria", df_hist['categoria'].unique())
            filtro_data = st.date_input("Filtrar por data", [])

            if filtro_categoria:
                df_hist = df_hist[df_hist['categoria'].isin(filtro_categoria)]
            if filtro_data:
                df_hist = df_hist[df_hist['data'].isin(pd.to_datetime(filtro_data))]

            st.dataframe(df_hist[['data', 'categoria', 'valor']], use_container_width=True)

            if st.checkbox("📈 Ver gráfico por categoria"):
                df_sum = df_hist.groupby('categoria')['valor'].sum()
                fig, ax = plt.subplots()
                df_sum.plot(kind='bar', ax=ax)
                ax.set_title("Receitas por Categoria")
                st.pyplot(fig)
        else:
            st.info("Nenhuma receita registrada.")

    # ==================== DESPESAS ====================
    elif aba == "Despesas":
        st.title("Despesas")

        with st.form("form_despesa"):
            data = st.date_input("Data da Despesa", value=pd.Timestamp.now())
            despesa = st.text_input("Descrição")
            valor = st.number_input("Valor", min_value=0.0, step=0.01)
            submitted = st.form_submit_button("Adicionar")
            if submitted:
                mes = data.month
                cursor.execute("INSERT INTO despesas (user_id, data, mes, despesa, valor, status) VALUES (?, ?, ?, ?, ?, 'pendente')",
                               (user_id, str(data), mes, despesa, valor))
                conn.commit()
                st.success("Despesa adicionada!")
                st.rerun()

        df = pd.read_sql_query("SELECT * FROM despesas WHERE user_id = ? ORDER BY data DESC", conn, params=(user_id,))
        if not df.empty:
            df['data'] = pd.to_datetime(df['data']).dt.strftime('%d/%m/%Y')
            df['status'] = df['status'].str.capitalize()
            st.dataframe(df[['data', 'despesa', 'valor', 'status']], use_container_width=True)

            with st.expander("✏️ Editar ou Excluir Despesa"):
                despesa_id = st.selectbox("Selecione a Despesa", df['id'])
                linha = df[df['id'] == despesa_id].iloc[0]
                nova_data = st.date_input("Data", pd.to_datetime(linha['data'], dayfirst=True))
                nova_desc = st.text_input("Descrição", linha['despesa'])
                novo_valor = st.number_input("Valor", value=float(linha['valor']), step=0.01)
                novo_status = st.selectbox("Status", ["pendente", "pago"], index=0 if linha['status'].lower() == "Pendente" else 1)

                if st.button("Atualizar Despesa"):
                    cursor.execute("UPDATE despesas SET data = ?, despesa = ?, valor = ?, status = ?, mes = ? WHERE id = ?",
                                   (str(nova_data), nova_desc, novo_valor, novo_status, nova_data.month, despesa_id))
                    conn.commit()
                    st.success("Despesa atualizada!")
                    st.rerun()

                if st.button("Excluir Despesa"):
                    cursor.execute("DELETE FROM despesas WHERE id = ?", (despesa_id,))
                    conn.commit()
                    st.warning("Despesa excluída.")
                    st.rerun()
        else:
            st.info("Nenhuma despesa registrada.")

    # ==================== DASHBOARD ====================
    elif aba == "Dashboard":
        st.title("📊 Dashboard Financeiro")
        mes_atual = datetime.now().month
        ano_atual = datetime.now().year

        mes_filtro = st.selectbox("Selecione o mês", list(range(1, 13)), index=mes_atual - 1)
        ano_filtro = st.selectbox("Selecione o ano", list(range(2022, datetime.now().year + 1)), index=list(range(2022, datetime.now().year + 1)).index(ano_atual))

        data_inicio = datetime(ano_filtro, mes_filtro, 1)
        if mes_filtro == 12:
            data_fim = datetime(ano_filtro + 1, 1, 1)
        else:
            data_fim = datetime(ano_filtro, mes_filtro + 1, 1)

        cursor.execute("""
            SELECT SUM(valor) FROM receitas 
            WHERE user_id = ? AND DATE(data) BETWEEN ? AND ?
        """, (user_id, data_inicio.date(), (data_fim.date() - pd.Timedelta(days=1))))
        rec = cursor.fetchone()
        receita_valor = rec[0] if rec and rec[0] else 0.0

        df = pd.read_sql_query("SELECT * FROM despesas WHERE user_id = ? AND mes = ?", conn, params=(user_id, mes_filtro))

        if not df.empty:
            pago = df[df['status'] == 'pago']['valor'].sum()
            pendente = df[df['status'] == 'pendente']['valor'].sum()
        else:
            pago = 0
            pendente = 0

        receita_final = receita_valor - pago

        col1, col2, col3 = st.columns(3)
        col1.metric("Receita Total", f"R$ {receita_valor:.2f}")
        col2.metric("Despesas Pagas", f"R$ {pago:.2f}")
        col3.metric("Disponível", f"R$ {receita_final:.2f}")

        if pendente > 0:
            st.warning(f"Você tem R$ {pendente:.2f} em despesas pendentes!")

        st.markdown("---")
        if not df.empty:
            df['data'] = pd.to_datetime(df['data'])
            st.dataframe(df[['data', 'despesa', 'valor', 'status']], use_container_width=True)

            fig, ax = plt.subplots()
            df.groupby('status')['valor'].sum().plot(kind='bar', ax=ax)
            ax.set_title("Total de Despesas por Status")
            st.pyplot(fig)
        else:
            st.info("Sem despesas registradas para este mês.")
