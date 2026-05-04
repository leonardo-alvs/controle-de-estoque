import streamlit as st
import pandas as pd
import hashlib
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# =========================================
# ⚙️ CONFIG
# =========================================
st.set_page_config(page_title="Sistema de Estoque", layout="wide")

DATABASE_URL = st.secrets["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# =========================================
# 🧩 DB HELPERS
# =========================================
def query_df(sql, params=None):
    with SessionLocal() as session:
        result = session.execute(text(sql), params or {})
        return pd.DataFrame(result.fetchall(), columns=result.keys())

def execute(sql, params=None):
    with SessionLocal() as session:
        session.execute(text(sql), params or {})
        session.commit()

# =========================================
# 🔐 AUTENTICAÇÃO
# =========================================
def autenticar(email, senha):
    senha_hash = hashlib.sha256(senha.encode()).hexdigest()

    df = query_df("""
        SELECT * FROM users
        WHERE email = :email
        AND password_hash = :senha
        AND active = true
    """, {"email": email, "senha": senha_hash})

    return df.iloc[0] if not df.empty else None

# =========================================
# 📦 PRODUTOS
# =========================================
def get_produtos():
    return query_df("SELECT * FROM products ORDER BY name")

def inserir_produto(nome, categoria_id, unit_id):
    execute("""
        INSERT INTO products (name, category_id, unit_id)
        VALUES (:nome, :categoria_id, :unit_id)
    """, {
        "nome": nome,
        "categoria_id": categoria_id,
        "unit_id": unit_id
    })

# =========================================
# 📂 CATEGORIAS / UNIDADES
# =========================================
def get_categorias():
    return query_df("SELECT * FROM categories ORDER BY name")

def get_unidades():
    return query_df("SELECT * FROM units ORDER BY name")

# =========================================
# 🔄 ESTOQUE
# =========================================
def atualizar_estoque(product_id, location, quantidade):
    execute("""
        INSERT INTO stock_balance (product_id, location, quantity)
        VALUES (:product_id, :location, :quantidade)
        ON CONFLICT (product_id, location)
        DO UPDATE SET
            quantity = stock_balance.quantity + :quantidade,
            updated_at = NOW()
    """, {
        "product_id": product_id,
        "location": location,
        "quantidade": quantidade
    })

def inserir_movimentacao(data):
    execute("""
        INSERT INTO stock_movements (
            date, type, product_id, quantity, origin, destination
        )
        VALUES (
            :date, :type, :product_id, :quantity, :origin, :destination
        )
    """, data)

    if data["type"] == "Entrada":
        atualizar_estoque(data["product_id"], data["destination"], data["quantity"])

    elif data["type"] == "Saída":
        atualizar_estoque(data["product_id"], data["origin"], -data["quantity"])

# =========================================
# 🔐 LOGIN UI
# =========================================
if "logado" not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("Login")

    email = st.text_input("Email")
    senha = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        user = autenticar(email, senha)
        if user is not None:
            st.session_state.logado = True
            st.session_state.user = user
            st.rerun()
        else:
            st.error("Credenciais inválidas")

    st.stop()

# =========================================
# 🏠 APP
# =========================================
st.sidebar.title("Menu")

pagina = st.sidebar.radio("Ir para", [
    "Dashboard",
    "Produtos",
    "Movimentações"
])

# =========================================
# 📊 DASHBOARD
# =========================================
if pagina == "Dashboard":
    st.title("Dashboard")

    df_prod = get_produtos()
    df_mov = query_df("SELECT * FROM stock_movements")

    col1, col2 = st.columns(2)

    col1.metric("Produtos", len(df_prod))
    col2.metric("Movimentações", len(df_mov))

# =========================================
# 📦 PRODUTOS
# =========================================
elif pagina == "Produtos":
    st.title("Produtos")

    df_prod = get_produtos()
    st.dataframe(df_prod)

    st.subheader("Novo Produto")

    categorias = get_categorias()
    unidades = get_unidades()

    nome = st.text_input("Nome")

    categoria = st.selectbox(
        "Categoria",
        categorias["name"] if not categorias.empty else []
    )

    unidade = st.selectbox(
        "Unidade",
        unidades["name"] if not unidades.empty else []
    )

    if st.button("Salvar Produto"):
        cat_id = categorias[categorias["name"] == categoria]["id"].values[0]
        uni_id = unidades[unidades["name"] == unidade]["id"].values[0]

        inserir_produto(nome, cat_id, uni_id)
        st.success("Produto cadastrado!")
        st.rerun()

# =========================================
# 🔄 MOVIMENTAÇÕES
# =========================================
elif pagina == "Movimentações":
    st.title("Movimentações")

    df_prod = get_produtos()

    produto = st.selectbox("Produto", df_prod["name"])

    tipo = st.selectbox("Tipo", ["Entrada", "Saída"])

    quantidade = st.number_input("Quantidade", min_value=0.0)

    origem = st.text_input("Origem")
    destino = st.text_input("Destino")

    if st.button("Lançar"):
        prod_id = df_prod[df_prod["name"] == produto]["id"].values[0]

        inserir_movimentacao({
            "date": pd.Timestamp.now(),
            "type": tipo,
            "product_id": prod_id,
            "quantity": quantidade,
            "origin": origem,
            "destination": destino
        })

        st.success("Movimentação registrada!")
        st.rerun()

    df_mov = query_df("SELECT * FROM stock_movements ORDER BY date DESC")
    st.dataframe(df_mov)
