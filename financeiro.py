import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import smtplib
from email.message import EmailMessage

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

# Função para enviar email (substituir email e senha pelos seus dados ou usar um servidor configurado)
def enviar_alerta_email(destinatario, assunto, mensagem):
    try:
        msg = EmailMessage()
        msg.set_content(mensagem)
        msg["Subject"] = assunto
        msg["From"] = "seuemail@example.com"
        msg["To"] = destinatario

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login("seuemail@example.com", "suasenha")
            server.send_message(msg)
    except:
        pass  # Para evitar quebra se envio falhar

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

    # ==================== DASHBOARD ====================
    if aba == "Dashboard":
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

        pago = df[df['status'] == 'pago']['valor'].sum() if not df.empty else 0
        pendente = df[df['status'] == 'pendente']['valor'].sum() if not df.empty else 0
        receita_final = receita_valor - pago

        col1, col2, col3 = st.columns(3)
        col1.metric("Receita Total", f"R$ {receita_valor:.2f}")
        col2.metric("Despesas Pagas", f"R$ {pago:.2f}")
        col3.metric("Disponível", f"R$ {receita_final:.2f}")

        if pendente > 0:
            st.warning(f"Você tem R$ {pendente:.2f} em despesas pendentes!")
            # enviar_alerta_email("seuemail@exemplo.com", "Despesas Pendentes", f"Você possui R$ {pendente:.2f} pendentes no mês {mes_filtro}/{ano_filtro}.")

        st.markdown("---")

        df_desp = pd.read_sql_query("SELECT data, valor FROM despesas WHERE user_id = ? ORDER BY data", conn, params=(user_id,))
        df_rec = pd.read_sql_query("SELECT data, valor FROM receitas WHERE user_id = ? ORDER BY data", conn, params=(user_id,))
        df_desp['data'] = pd.to_datetime(df_desp['data'])
        df_rec['data'] = pd.to_datetime(df_rec['data'])

        df_desp['mes'] = df_desp['data'].dt.to_period('M')
        df_rec['mes'] = df_rec['data'].dt.to_period('M')

        df_saldo = pd.DataFrame()
        df_saldo['Gastos'] = df_desp.groupby('mes')['valor'].sum()
        df_saldo['Receitas'] = df_rec.groupby('mes')['valor'].sum()
        df_saldo = df_saldo.fillna(0)
        df_saldo['Saldo'] = df_saldo['Receitas'] - df_saldo['Gastos']
        st.subheader("📅 Saldo por mês")
        st.dataframe(df_saldo.reset_index(), use_container_width=True)

        st.download_button("⬇️ Exportar Receitas", df_rec.to_csv(index=False).encode('utf-8'), file_name="receitas.csv", mime='text/csv')
        st.download_button("⬇️ Exportar Despesas", df_desp.to_csv(index=False).encode('utf-8'), file_name="despesas.csv", mime='text/csv')
