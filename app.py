import streamlit as st
import pandas as pd
import os
import hashlib
import base64
import io
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

try:
    from reportlab.lib.pagesizes import A4, landscape as rl_landscape
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import cm as rl_cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

# --- 1. CONFIGURAÇÃO E ESTÉTICA GOMAP ---

# Detecta logo ANTES do set_page_config para usar como favicon/ícone no celular
LOGO_GOMAP = None
LOGO_BASE64 = None
for _nome in ["logogomap.png", "LogoGomap.png", "LOGOGOMAP.png", "logo_gomap.png", "logo.png"]:
    if os.path.exists(_nome):
        LOGO_GOMAP = _nome
        break
if not LOGO_GOMAP:
    for f in os.listdir("."):
        if f.lower().endswith((".png", ".jpg", ".jpeg")) and "logo" in f.lower():
            LOGO_GOMAP = f
            break
if LOGO_GOMAP:
    with open(LOGO_GOMAP, "rb") as _img:
        LOGO_BASE64 = base64.b64encode(_img.read()).decode()

st.set_page_config(
    page_title="GOMAP Engenharia",
    layout="wide",
    page_icon=LOGO_GOMAP if LOGO_GOMAP else "🏗️",
)

AZUL_GOMAP = "#1a365d"
AZUL_CLARO = "#2a5298"

# Desativa tradução automática do navegador (Chrome, Edge, etc.)
st.markdown("""
<meta name="google" content="notranslate">
<meta name="microsoft" content="notranslate">
<script>
(function() {
    var h = document.documentElement;
    h.setAttribute('lang', 'pt-BR');
    h.setAttribute('translate', 'no');
    var obs = new MutationObserver(function() {
        if (h.getAttribute('translate') !== 'no') h.setAttribute('translate', 'no');
        if (h.getAttribute('lang') !== 'pt-BR') h.setAttribute('lang', 'pt-BR');
        // Propaga translate=no para todos os elementos novos
        document.querySelectorAll(':not([translate])').forEach(function(el) {
            el.setAttribute('translate', 'no');
        });
    });
    obs.observe(document.body || h, { childList: true, subtree: true, attributes: true });
})();
</script>
""", unsafe_allow_html=True)

# --- SISTEMA DE USUÁRIOS E BASE POSTGRESQL ---
# Definição de perfis e permissões
PERFIS = {
    "admin": {
        "descricao": "Administrador — Permissão total",
        "cadastros": True, "lancamentos": True, "relatorios": True,
        "estoque": True, "usuarios": True, "excluir": True, "locacoes": True
    },
    "gerenciamento": {
        "descricao": "Gerenciamento — Tudo exceto criar usuários",
        "cadastros": True, "lancamentos": True, "relatorios": True,
        "estoque": True, "usuarios": False, "excluir": True, "locacoes": True
    },
    "lancamentos": {
        "descricao": "Lançamentos — Somente movimentações",
        "cadastros": False, "lancamentos": True, "relatorios": False,
        "estoque": True, "usuarios": False, "excluir": False, "locacoes": False
    },
    "visualizacao": {
        "descricao": "Visualização — Somente consultas",
        "cadastros": False, "lancamentos": False, "relatorios": True,
        "estoque": True, "usuarios": False, "excluir": False, "locacoes": False
    },
}

def get_permissao(perfil, acao):
    """Retorna True se o perfil tem permissão para a ação"""
    if perfil in PERFIS:
        return PERFIS[perfil].get(acao, False)
    return False


def get_db_url():
    postgresql = None
    if hasattr(st, "secrets"):
        try:
            postgresql = st.secrets.get("postgresql")
        except Exception:
            postgresql = None
    if isinstance(postgresql, dict) and "uri" in postgresql:
        return postgresql["uri"]
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    raise RuntimeError(
        "DATABASE_URL não configurada. Defina st.secrets['postgresql']['uri'] ou a variável de ambiente DATABASE_URL."
    )

DB_URL = get_db_url()
ENGINE = create_engine(DB_URL, future=True)

TABLE_CONFIG = {
    "users": {
        "table": "users",
        "key": "id",
        "cols": {
            "usuario": "email",
            "senha_hash": "password_hash",
            "nome": "name",
            "perfil": "role",
            "ativo": "active",
        },
    },
    "cat": {
        "table": "categories",
        "key": "id",
        "cols": {"Nome": "name"},
    },
    "unid": {
        "table": "units",
        "key": "id",
        "cols": {"Nome": "name"},
    },
    "obras": {
        "table": "projects",
        "key": "id",
        "cols": {"Nome_Obra": "name"},
    },
    "equip": {
        "table": "equipments",
        "key": "id",
        "cols": {"Nome_Equipamento": "name"},
    },
    "forn": {
        "table": "suppliers",
        "key": "id",
        "cols": {
            "Nome_Fornecedor": "name",
            "CNPJ": "cnpj",
            "Insc_Estadual": "state_registration",
            "Telefone": "phone",
            "Celular": "mobile",
            "Email": "email",
            "Contato": "contact",
            "Endereco": "address",
            "Bairro": "district",
            "Cidade": "city",
            "Estado": "state",
            "CEP": "zip_code",
            "Observacao": "notes",
            "Data_Cadastro": "created_at",
        },
    },
    "prod": {
        "table": "products",
        "key": "id",
        "cols": {
            "Material": "name",
            "Categoria": "category_id",
            "Unidade": "unit_id",
        },
    },
    "mov": {
        "table": "stock_movements",
        "key": "id",
        "cols": {
            "Data": "date",
            "Tipo": "type",
            "Material": "product_id",
            "Categoria": "category_id",
            "Unidade": "unit_id",
            "Origem": "origin",
            "Destino": "destination",
            "Qtd": "quantity",
            "Valor_Unit": "unit_value",
            "Valor_Total": "total_value",
            "Fornecedor": "supplier_id",
            "Data_NF": "invoice_date",
            "Num_NF": "invoice_number",
            "Observacao": "notes",
            "Usuario": "created_by",
        },
    },
    "loc": {
        "table": "rentals",
        "key": "id",
        "cols": {
            "Descricao": "description",
            "Qtd": "quantity",
            "Valor": "value",
            "Fornecedor": "supplier_id",
            "Contrato": "contract",
            "Data_Inicio": "start_date",
            "Data_Devolucao": "return_date",
            "Obra": "project_id",
            "Periodo_Inicio": "period_start",
            "Periodo_Final": "period_end",
            "Venc_Boleto": "boleto_due_date",
            "Valor_Periodo": "period_value",
            "Observacao": "notes",
            "Status": "status",
            "Usuario": "created_by",
        },
    },
}

_UNID_DEFAULTS = ["un", "Lata", "Sc", "Kg", "m", "m²", "m³", "L", "pç", "cx"]


def _execute_query(sql, params=None):
    with ENGINE.begin() as conn:
        return conn.execute(text(sql), params or {})


def _get_or_create_id(table, name_col, name_value, fallback_columns=None):
    if not name_value or pd.isna(name_value):
        return None
    name_value = str(name_value).strip()
    if name_value == "":
        return None
    sql = f"SELECT id FROM {table} WHERE {name_col} = :value LIMIT 1"
    with ENGINE.begin() as conn:
        existing = conn.execute(text(sql), {"value": name_value}).scalar_one_or_none()
        if existing:
            return str(existing)
        insert_cols = [name_col]
        insert_params = {name_col: name_value}
        if fallback_columns:
            for col, val in fallback_columns.items():
                insert_cols.append(col)
                insert_params[col] = val
        cols = ", ".join(insert_cols)
        vals = ", ".join(f":{c}" for c in insert_cols)
        result = conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING id"), insert_params)
        return str(result.scalar_one())


def _get_user_id(user_value):
    if not user_value or pd.isna(user_value):
        return None
    user_value = str(user_value).strip()
    if user_value == "":
        return None
    with ENGINE.begin() as conn:
        sql = text("SELECT id FROM users WHERE name = :value OR email = :value LIMIT 1")
        result = conn.execute(sql, {"value": user_value}).scalar_one_or_none()
        return str(result) if result else None


def _fk_valido(v):
    """Retorna True se v é um ID válido (não None, não vazio, não NaN)."""
    if v is None or v == "":
        return False
    try:
        return not pd.isna(v)
    except TypeError:
        return True


def _resolve_fk(db_col, row):
    if db_col == "category_id":
        if _fk_valido(row.get("category_id")):
            return row.get("category_id")
        return _get_or_create_id("categories", "name", row.get("Categoria"))
    if db_col == "unit_id":
        if _fk_valido(row.get("unit_id")):
            return row.get("unit_id")
        return _get_or_create_id("units", "name", row.get("Unidade"))
    if db_col == "supplier_id":
        if _fk_valido(row.get("supplier_id")):
            return row.get("supplier_id")
        return _get_or_create_id("suppliers", "name", row.get("Fornecedor"), fallback_columns={"email": str(row.get("Fornecedor", "")).strip()})
    if db_col == "project_id":
        if _fk_valido(row.get("project_id")):
            return row.get("project_id")
        return _get_or_create_id("projects", "name", row.get("Obra"))
    if db_col == "product_id":
        if _fk_valido(row.get("product_id")):
            return row.get("product_id")
        return _get_or_create_id("products", "name", row.get("Material"))
    if db_col == "created_by":
        return _get_user_id(row.get("Usuario"))
    return None


def _normalize_id_column(df, key="id"):
    if key in df.columns:
        df[key] = df[key].astype(str).replace({"nan": "", "None": ""})
    return df


def _insert_row(table, data):
    if not data:
        return None
    cols = ", ".join(data.keys())
    vals = ", ".join(f":{k}" for k in data.keys())
    sql = f"INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING id"
    with ENGINE.begin() as conn:
        result = conn.execute(text(sql), data)
        return str(result.scalar_one())


def _update_row(table, data, row_id):
    if not data:
        return
    assignments = ", ".join(f"{col} = :{col}" for col in data.keys())
    sql = f"UPDATE {table} SET {assignments} WHERE id = :id"
    params = data.copy()
    params["id"] = row_id
    with ENGINE.begin() as conn:
        conn.execute(text(sql), params)


def _delete_ids(table, ids):
    ids = [str(i) for i in ids if i]
    if not ids:
        return
    placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": value for i, value in enumerate(ids)}
    sql = f"DELETE FROM {table} WHERE id IN ({placeholders})"
    with ENGINE.begin() as conn:
        conn.execute(text(sql), params)


def _load_table(table_name, columns, joins=None, order_by=None):
    sql = f"SELECT {columns} FROM {table_name}"
    if joins:
        sql += f" {joins}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    df = pd.read_sql_query(text(sql), ENGINE)
    import re
    # Extrai nomes de colunas renomeadas (após AS)
    col_names = []
    for col in columns.split(","):
        col = col.strip()
        parts = re.split(r'\s+AS\s+', col, flags=re.IGNORECASE)
        if len(parts) > 1:
            col_names.append(parts[-1].strip())
        else:
            col_names.append(col.strip())
    if df.empty:
        df = pd.DataFrame(columns=col_names)
    else:
        # Normaliza colunas retornadas pelo SQL para o caso esperado
        renames = {}
        for actual in df.columns:
            for expected in col_names:
                if actual.lower() == expected.lower():
                    renames[actual] = expected
                    break
        if renames:
            df = df.rename(columns=renames)
    return df


def _sync_unidades():
    """Sincroniza unidades de produtos para a tabela units no PostgreSQL."""
    if st.session_state.get("_unid_synced"):
        return
    st.session_state["_unid_synced"] = True
    try:
        df_prod = load("prod")
        df_unid = load("unid")
        existing_upper = set()
        if "Nome" in df_unid.columns:
            existing_upper = set(df_unid["Nome"].dropna().astype(str).str.upper().tolist())
        to_add = []
        if "Unidade" in df_prod.columns:
            for u in df_prod["Unidade"].dropna().unique():
                su = str(u).strip()
                if su and su.upper() not in existing_upper:
                    to_add.append(su.upper())
                    existing_upper.add(su.upper())
        for unit in to_add:
            _insert_row("units", {"name": unit})
    except Exception:
        pass

def _get_column_safe(df, col_name, default=None):
    """Extrai coluna de DataFrame com segurança, retornando lista vazia se coluna não existe."""
    if col_name not in df.columns:
        return [] if default is None else default
    return df[col_name].dropna().unique().tolist()

def _concat_safe(df_list):
    """Concatena DataFrames garantindo que todos tenham as mesmas colunas."""
    if not df_list:
        return pd.DataFrame()
    # Coleta todas as colunas de todos os DataFrames
    all_cols = set()
    for df in df_list:
        all_cols.update(df.columns)
    # Garante que todos os DataFrames tenham todas as colunas
    aligned_dfs = []
    for df in df_list:
        for col in all_cols:
            if col not in df.columns:
                df[col] = None
        aligned_dfs.append(df)
    return pd.concat(aligned_dfs, ignore_index=True)

def load_usuarios():
    df = pd.read_sql_query(
        text(
            "SELECT id, email AS usuario, password_hash AS senha_hash, name AS nome, role AS perfil, active AS ativo "
            "FROM users ORDER BY email"
        ),
        ENGINE,
    )
    df["ativo"] = df["ativo"].astype(bool)
    return _normalize_id_column(df)


def save_usuarios(df):
    _save_table(df, "users")


def verificar_login(usuario, senha):
    df = load_usuarios()
    row = df[(df["usuario"] == usuario) & (df["ativo"] == True)]
    if len(row) > 0:
        if row.iloc[0]["senha_hash"] == hashlib.sha256(senha.encode()).hexdigest():
            return True, {"nome": row.iloc[0]["nome"], "perfil": row.iloc[0]["perfil"], "id": row.iloc[0]["id"]}
    return False, None


def _build_db_record(row, cfg):
    import numpy as np
    record = {}
    for app_col, db_col in cfg["cols"].items():
        if app_col not in row:
            continue
        value = row[app_col]
        if pd.isna(value):
            value = None
        elif isinstance(value, np.bool_):
            value = bool(value)
        elif isinstance(value, np.integer):
            value = int(value)
        elif isinstance(value, np.floating):
            value = float(value)
        if db_col.endswith("_id") or db_col == "created_by":
            record[db_col] = _resolve_fk(db_col, row)
        else:
            record[db_col] = value
    return record


def _save_table(df, key):
    cfg = TABLE_CONFIG[key]
    table = cfg["table"]
    df_copy = df.copy()
    if "id" in df_copy.columns:
        df_copy["id"] = df_copy["id"].astype(str).replace({"nan": "", "None": ""})
    current_ids = pd.read_sql_query(text(f"SELECT id FROM {table}"), ENGINE)["id"].astype(str).tolist()
    keep_ids = set()
    for _, row in df_copy.iterrows():
        row_id = str(row.get("id", "") or "").strip()
        if row_id.lower() in ("nan", "none"):
            row_id = ""
        data = _build_db_record(row, cfg)
        if row_id and row_id in current_ids:
            _update_row(table, data, row_id)
            keep_ids.add(row_id)
        else:
            if row_id:
                data["id"] = row_id
            new_id = _insert_row(table, data)
            if new_id:
                keep_ids.add(new_id)
    to_delete = [rid for rid in current_ids if rid not in keep_ids]
    if to_delete:
        _delete_ids(table, to_delete)


def load(k):
    if k == "cat":
        return _load_table("categories", "id, name AS Nome", order_by="name")
    if k == "unid":
        return _load_table("units", "id, name AS Nome", order_by="name")
    if k == "obras":
        return _load_table("projects", "id, name AS Nome_Obra", order_by="name")
    if k == "equip":
        return _load_table("equipments", "id, name AS Nome_Equipamento", order_by="name")
    if k == "forn":
        return _load_table(
            "suppliers",
            "id, name AS Nome_Fornecedor, cnpj AS CNPJ, state_registration AS Insc_Estadual, phone AS Telefone, mobile AS Celular, email AS Email, contact AS Contato, address AS Endereco, district AS Bairro, city AS Cidade, state AS Estado, zip_code AS CEP, notes AS Observacao, created_at AS Data_Cadastro",
            order_by="name",
        )
    if k == "prod":
        return _load_table(
            "products p",
            "p.id, p.name AS Material, c.name AS Categoria, u.name AS Unidade, p.category_id, p.unit_id",
            joins="LEFT JOIN categories c ON p.category_id = c.id LEFT JOIN units u ON p.unit_id = u.id",
            order_by="p.name",
        )
    if k == "mov":
        return _load_table(
            "stock_movements m",
            "m.id, m.date AS Data, m.type AS Tipo, p.name AS Material, c.name AS Categoria, u.name AS Unidade, m.origin AS Origem, m.destination AS Destino, m.quantity AS Qtd, m.unit_value AS Valor_Unit, m.total_value AS Valor_Total, s.name AS Fornecedor, m.invoice_date AS Data_NF, m.invoice_number AS Num_NF, m.notes AS Observacao, usr.name AS Usuario, m.product_id, m.category_id, m.unit_id, m.supplier_id, m.created_by",
            joins=(
                "LEFT JOIN products p ON m.product_id = p.id "
                "LEFT JOIN categories c ON m.category_id = c.id "
                "LEFT JOIN units u ON m.unit_id = u.id "
                "LEFT JOIN suppliers s ON m.supplier_id = s.id "
                "LEFT JOIN users usr ON m.created_by = usr.id"
            ),
            order_by="m.date DESC, m.id",
        )
    if k == "loc":
        return _load_table(
            "rentals r",
            "r.id, r.description AS Descricao, r.quantity AS Qtd, r.value AS Valor, s.name AS Fornecedor, r.contract AS Contrato, r.start_date AS Data_Inicio, r.return_date AS Data_Devolucao, p.name AS Obra, r.period_start AS Periodo_Inicio, r.period_end AS Periodo_Final, r.boleto_due_date AS Venc_Boleto, r.period_value AS Valor_Periodo, r.notes AS Observacao, r.status AS Status, usr.name AS Usuario, r.supplier_id, r.project_id, r.created_by",
            joins=(
                "LEFT JOIN suppliers s ON r.supplier_id = s.id "
                "LEFT JOIN projects p ON r.project_id = p.id "
                "LEFT JOIN users usr ON r.created_by = usr.id"
            ),
            order_by="r.start_date DESC, r.id",
        )
    raise KeyError(f"Chave de tabela desconhecida: {k}")


def save(df, k):
    if k not in TABLE_CONFIG:
        raise KeyError(f"Chave de tabela desconhecida: {k}")
    _save_table(df, k)


def _sv(v):
    """Converte valor do DataFrame para string segura (trata NaN)"""
    if pd.isna(v) if not isinstance(v, str) else False:
        return ""
    s = str(v)
    return "" if s in ("nan", "None", "NaT") else s

def fmt_datas(df, cols=None):
    """Converte colunas de data para exibição no formato DD/MM/YYYY"""
    df_d = df.copy()
    _date_cols = cols or ["Data", "Data_Inicio", "Data_Devolucao",
                          "Periodo_Inicio", "Periodo_Final", "Venc_Boleto", "Data_NF"]
    for c in _date_cols:
        if c in df_d.columns:
            df_d[c] = pd.to_datetime(df_d[c], errors="coerce").dt.strftime("%d/%m/%Y").fillna("")
    return df_d

COLS_MOV_USER = ["Data", "Tipo", "Material", "Categoria", "Unidade",
                 "Origem", "Destino", "Qtd", "Valor_Unit", "Valor_Total",
                 "Fornecedor", "Data_NF", "Num_NF", "Observacao", "Usuario"]

def cols_mov_user(df):
    """Filtra DataFrame de movimentações deixando apenas colunas visíveis ao usuário
    (oculta FKs internos: id, product_id, category_id, unit_id, supplier_id, created_by)."""
    return df[[c for c in COLS_MOV_USER if c in df.columns]]

# --- CSS CUSTOMIZADO COMPLETO ---
st.markdown(f"""
    <style>
        /* ===== SIDEBAR AZUL ESCURO ===== */
        [data-testid="stSidebar"] {{
            background-color: {AZUL_GOMAP};
            min-width: 220px;
            padding-top: 8px;
        }}
        [data-testid="stSidebar"] * {{
            color: white !important;
        }}

        /* Botões Laterais: SEM contorno, alinhados à esquerda */
        [data-testid="stSidebar"] .stButton > button {{
            background-color: transparent !important;
            border: none !important;
            outline: none !important;
            box-shadow: none !important;
            text-align: left !important;
            padding: 6px 10px !important;
            margin: 0 !important;
            width: 100%;
            color: white !important;
            font-size: 15px;
            border-radius: 6px;
            transition: background-color 0.2s;
            display: flex !important;
            justify-content: flex-start !important;
            align-items: center !important;
        }}
        [data-testid="stSidebar"] .stButton > button * {{
            text-align: left !important;
            justify-content: flex-start !important;
        }}
        [data-testid="stSidebar"] .stButton {{
            text-align: left !important;
        }}
        [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {{
            justify-content: flex-start !important;
        }}
        [data-testid="stSidebar"] .stButton > button:hover {{
            background-color: rgba(255,255,255,0.15) !important;
            color: white !important;
            border: none !important;
        }}
        [data-testid="stSidebar"] .stButton > button:focus,
        [data-testid="stSidebar"] .stButton > button:active {{
            background-color: rgba(255,255,255,0.25) !important;
            color: white !important;
            border: none !important;
            outline: none !important;
            box-shadow: none !important;
        }}
        /* Remove gap entre botões da sidebar */
        [data-testid="stSidebar"] .stElementContainer {{
            margin-bottom: -8px !important;
        }}

        /* ===== BOTÕES CENTRAIS (PAINEL) ===== */
        .stMainBlockContainer .stButton > button,
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button {{
            background-color: {AZUL_GOMAP};
            color: white !important;
            border-radius: 8px;
            font-weight: bold;
            height: 3em;
            border: 2px solid {AZUL_GOMAP};
            transition: all 0.2s;
        }}
        .stMainBlockContainer .stButton > button:hover,
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button:hover {{
            background-color: {AZUL_CLARO} !important;
            color: white !important;
            border: 2px solid {AZUL_CLARO} !important;
        }}
        .stMainBlockContainer .stButton > button:focus,
        .stMainBlockContainer .stButton > button:active,
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button:focus,
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button:active {{
            background-color: {AZUL_CLARO} !important;
            color: white !important;
            border: 2px solid {AZUL_GOMAP} !important;
            outline: none !important;
            box-shadow: 0 0 0 2px rgba(26,54,93,0.3) !important;
        }}
        /* Fix para botões primary (type="primary") */
        .stMainBlockContainer .stButton > button[kind="primary"],
        .stMainBlockContainer .stButton > button[data-testid="stBaseButton-primary"],
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button[kind="primary"],
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button[data-testid="stBaseButton-primary"] {{
            background-color: {AZUL_GOMAP} !important;
            color: white !important;
        }}
        .stMainBlockContainer .stButton > button[kind="primary"]:focus,
        .stMainBlockContainer .stButton > button[kind="primary"]:active,
        .stMainBlockContainer .stButton > button[data-testid="stBaseButton-primary"]:focus,
        .stMainBlockContainer .stButton > button[data-testid="stBaseButton-primary"]:active,
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button[kind="primary"]:focus,
        .stMainBlockContainer [data-testid="stFormSubmitButton"] > button[kind="primary"]:active {{
            background-color: {AZUL_CLARO} !important;
            color: white !important;
        }}

        /* ===== CABEÇALHO TÍTULO + LOGO ===== */
        .header-bar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 5px 0 10px 0;
            border-bottom: 3px solid {AZUL_GOMAP};
            margin-bottom: 10px;
            gap: 15px;
        }}
        .header-bar .h-title {{
            color: {AZUL_GOMAP};
            font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
            font-weight: 800;
            font-size: 28px;
            letter-spacing: -0.3px;
            white-space: nowrap;
        }}
        .header-bar img {{
            height: 40px;
            object-fit: contain;
        }}

        /* ===== DASHBOARD — HEADER DE SAUDAÇÃO ===== */
        .dash-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 20px;
            background: linear-gradient(135deg, {AZUL_GOMAP} 0%, {AZUL_CLARO} 100%);
            border-radius: 12px;
            margin-bottom: 18px;
        }}
        .dash-greeting {{
            color: white;
            font-size: 21px;
            font-weight: 700;
        }}
        .dash-date {{
            color: rgba(255,255,255,0.82);
            font-size: 13px;
            margin-top: 3px;
        }}
        .dash-subtitle {{
            color: rgba(255,255,255,0.7);
            font-size: 13px;
            text-align: right;
            line-height: 1.5;
        }}

        /* ===== METRIC CARDS ===== */
        .metric-card {{
            background: white;
            border-radius: 12px;
            padding: 16px 12px;
            text-align: center;
            border-top: 4px solid {AZUL_GOMAP};
            box-shadow: 0 2px 10px rgba(0,0,0,0.07);
            margin-bottom: 10px;
            position: relative;
            min-height: 118px;
        }}
        .metric-badge {{
            position: absolute;
            top: -9px;
            right: -9px;
            background: #e53e3e;
            color: white;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            font-size: 11px;
            font-weight: bold;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        }}
        .metric-icon {{
            font-size: 26px;
            margin-bottom: 4px;
        }}
        .metric-value {{
            font-size: 30px;
            font-weight: 800;
            line-height: 1;
        }}
        .metric-label {{
            font-size: 11px;
            color: #718096;
            margin-top: 5px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
        }}

        /* ===== ACTION CARDS ===== */
        .action-card {{
            background: white;
            border-radius: 12px;
            padding: 18px 16px 14px 16px;
            border-left: 5px solid {AZUL_GOMAP};
            box-shadow: 0 2px 10px rgba(0,0,0,0.07);
            margin-bottom: 8px;
            position: relative;
            min-height: 108px;
        }}
        .action-alert {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: #e53e3e;
            color: white;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
        }}
        .action-icon {{
            font-size: 26px;
            margin-bottom: 5px;
        }}
        .action-title {{
            font-size: 13px;
            font-weight: 800;
            margin-bottom: 3px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .action-subtitle {{
            font-size: 11px;
            color: #718096;
        }}

        /* ===== STATUS PILLS (estilo Jira) ===== */
        .status-pill {{
            display: inline-block;
            padding: 2px 9px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 7px;
        }}
        .sp-ok      {{ background:#c6f6d5; color:#276749; }}
        .sp-warn    {{ background:#fefcbf; color:#744210; }}
        .sp-danger  {{ background:#fed7d7; color:#9b2c2c; }}
        .sp-info    {{ background:#bee3f8; color:#2a4365; }}
        .sp-neutral {{ background:#e2e8f0; color:#4a5568; }}

        /* ===== TELA DE LOGIN ===== */
        .login-box {{
            max-width: 420px;
            margin: 60px auto;
            padding: 40px 35px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            border-top: 5px solid {AZUL_GOMAP};
        }}
        .login-title {{
            color: {AZUL_GOMAP};
            text-align: center;
            font-size: 22px;
            font-weight: 800;
            margin-bottom: 5px;
        }}
        .login-sub {{
            color: {AZUL_GOMAP};
            text-align: center;
            font-size: 22px;
            font-weight: 800;
            margin-bottom: 20px;
        }}

        /* ===== MÉTRICAS ===== */
        [data-testid="stMetric"] {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.06);
            border-left: 4px solid {AZUL_GOMAP};
        }}

        /* ===== DATAFRAMES ===== */
        .stDataFrame {{
            border-radius: 8px;
            overflow: hidden;
        }}

        /* ===== INFO DO USUÁRIO NA SIDEBAR ===== */
        .user-info {{
            background: rgba(255,255,255,0.1);
            padding: 10px 12px;
            border-radius: 8px;
            margin-bottom: 10px;
            font-size: 13px;
        }}

        /* ===== BOTÕES CANCELAR E EXCLUIR (vermelho) ===== */
        [data-testid="stHorizontalBlock"]:has([data-testid="column"]:nth-child(3)) > [data-testid="column"]:nth-child(2) .stButton > button {{
            background-color: #dc3545 !important;
            border-color: #dc3545 !important;
            color: white !important;
        }}
        [data-testid="stHorizontalBlock"]:has([data-testid="column"]:nth-child(3)) > [data-testid="column"]:nth-child(2) .stButton > button:hover,
        [data-testid="stHorizontalBlock"]:has([data-testid="column"]:nth-child(3)) > [data-testid="column"]:nth-child(2) .stButton > button:focus,
        [data-testid="stHorizontalBlock"]:has([data-testid="column"]:nth-child(3)) > [data-testid="column"]:nth-child(2) .stButton > button:active {{
            background-color: #c82333 !important;
            border-color: #bd2130 !important;
            color: white !important;
        }}
        [data-testid="stExpander"] .stButton > button[kind="secondary"],
        [data-testid="stExpander"] .stButton > button[data-testid="stBaseButton-secondary"] {{
            background-color: #dc3545 !important;
            border-color: #dc3545 !important;
            color: white !important;
        }}
        [data-testid="stExpander"] .stButton > button[kind="secondary"]:hover,
        [data-testid="stExpander"] .stButton > button[kind="secondary"]:focus,
        [data-testid="stExpander"] .stButton > button[kind="secondary"]:active,
        [data-testid="stExpander"] .stButton > button[data-testid="stBaseButton-secondary"]:hover,
        [data-testid="stExpander"] .stButton > button[data-testid="stBaseButton-secondary"]:focus,
        [data-testid="stExpander"] .stButton > button[data-testid="stBaseButton-secondary"]:active {{
            background-color: #c82333 !important;
            border-color: #bd2130 !important;
            color: white !important;
        }}
        /* ===== OCULTAR ÂNCORA AUTOMÁTICA DOS SUBTÍTULOS (ícone 🔗) ===== */
        [data-testid="stHeaderActionElements"] {{
            display: none !important;
        }}

        /* ===== LINK "ABRIR EM NOVA ABA" NA SIDEBAR ===== */
        .sidebar-newtab-link a {{
            color: rgba(255,255,255,0.45) !important;
            text-decoration: none !important;
            font-size: 17px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            height: 100% !important;
            padding-top: 2px !important;
            transition: color 0.2s !important;
        }}
        .sidebar-newtab-link a:hover {{
            color: rgba(255,255,255,0.95) !important;
        }}

        /* ===== LABELS DOS CAMPOS — FUNDO AZUL / TEXTO BRANCO ===== */
        div[data-testid="stSelectbox"] > label,
        div[data-testid="stDateInput"] > label,
        div[data-testid="stTextInput"] > label,
        div[data-testid="stNumberInput"] > label,
        div[data-testid="stTextArea"] > label,
        div[data-testid="stTimeInput"] > label {{
            background-color: #00527C !important;
            color: white !important;
            padding: 4px 10px !important;
            border-radius: 5px !important;
            display: inline-block !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            margin-bottom: 4px !important;
            min-width: 60px !important;
        }}
    </style>
""", unsafe_allow_html=True)

def _sv(v):
    """Converte valor do DataFrame para string segura (trata NaN)"""
    if pd.isna(v) if not isinstance(v, str) else False:
        return ""
    s = str(v)
    return "" if s in ("nan", "None", "NaT") else s

def fmt_datas(df, cols=None):
    """Converte colunas de data para exibição no formato DD/MM/YYYY"""
    df_d = df.copy()
    _date_cols = cols or ["Data", "Data_Inicio", "Data_Devolucao",
                          "Periodo_Inicio", "Periodo_Final", "Venc_Boleto", "Data_NF"]
    for c in _date_cols:
        if c in df_d.columns:
            df_d[c] = pd.to_datetime(df_d[c], errors="coerce").dt.strftime("%d/%m/%Y").fillna("")
    return df_d

def gerar_html_relatorio(titulo, df_exibir, metricas=None):
    """Gera HTML formatado para impressão/exportação de relatórios GOMAP."""
    logo_html = f'<img src="data:image/png;base64,{LOGO_BASE64}" style="height:48px;">' if LOGO_BASE64 else ""
    _fmtv = lambda v: "" if str(v) in ("nan", "None", "NaT", "<NA>") else str(v)
    rows_html = "".join(
        "<tr>" + "".join(f"<td>{_fmtv(v)}</td>" for v in row) + "</tr>"
        for row in df_exibir.itertuples(index=False, name=None)
    )
    cols_html = "".join(f"<th>{c}</th>" for c in df_exibir.columns)
    metricas_html = ""
    if metricas:
        metricas_html = '<div class="metricas">' + "".join(
            f'<div class="metrica"><b>{k}</b><br>{v}</div>' for k, v in metricas.items()
        ) + "</div>"
    usuario = st.session_state.get("usuario_nome", "")
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><title>{titulo}</title><style>
body{{font-family:Arial,sans-serif;margin:20px;font-size:12px;}}
.header{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #1a365d;padding-bottom:12px;margin-bottom:15px;}}
.header h1{{color:#1a365d;font-size:18px;margin:0 0 14px 0;font-weight:bold;}}
.header h2{{color:#2a5298;font-size:13px;margin:0;font-weight:normal;}}
.metricas{{display:flex;gap:12px;margin:10px 0 14px 0;flex-wrap:wrap;}}
.metrica{{background:#f0f4f8;padding:8px 12px;border-left:4px solid #1a365d;border-radius:4px;min-width:90px;}}
table{{width:100%;border-collapse:collapse;margin-top:6px;}}
th{{background:#1a365d;color:white;padding:6px 8px;text-align:left;font-size:11px;}}
td{{padding:5px 8px;border-bottom:1px solid #ddd;font-size:11px;}}
tr:nth-child(even){{background:#f9f9f9;}}
.footer{{margin-top:18px;font-size:10px;color:#888;border-top:1px solid #ddd;padding-top:6px;}}
@media print{{.no-print{{display:none!important;}}}}
</style></head><body>
<div class="header">
  <div><h1>GOMAP Engenharia e Construções</h1><h2>{titulo}</h2></div>
  {logo_html}
</div>
<p style="font-size:10px;color:#888;margin:0 0 8px 0;">Gerado em: {datetime.today().strftime('%d/%m/%Y %H:%M')} | Usuário: {usuario}</p>
{metricas_html}
<table><thead><tr>{cols_html}</tr></thead><tbody>{rows_html}</tbody></table>
<div class="footer">GOMAP Engenharia e Construções — Sistema de Controle de Estoque e Materiais</div>
</body></html>"""

def gerar_pdf_relatorio(titulo, df_exibir, metricas=None):
    """Gera PDF formatado para exportação de relatórios GOMAP."""
    if not REPORTLAB_OK:
        return b""
    buffer = io.BytesIO()
    pagesize = rl_landscape(A4) if len(df_exibir.columns) > 5 else A4
    doc = SimpleDocTemplate(buffer, pagesize=pagesize,
                            leftMargin=1.5*rl_cm, rightMargin=1.5*rl_cm,
                            topMargin=2*rl_cm, bottomMargin=2*rl_cm)
    COR_AZUL      = rl_colors.HexColor("#1a365d")
    COR_AZUL_CLARO = rl_colors.HexColor("#2a5298")
    COR_CINZA     = rl_colors.HexColor("#f0f4f8")
    story = []
    usuario = st.session_state.get("usuario_nome", "")
    story.append(Paragraph("GOMAP Engenharia e Construções",
        ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=14, textColor=COR_AZUL, spaceAfter=14)))
    story.append(Paragraph(titulo,
        ParagraphStyle('h2', fontName='Helvetica', fontSize=10, textColor=COR_AZUL_CLARO, spaceAfter=2)))
    story.append(Paragraph(
        f"Gerado em: {datetime.today().strftime('%d/%m/%Y %H:%M')} | Usuário: {usuario}",
        ParagraphStyle('info', fontName='Helvetica', fontSize=8, textColor=rl_colors.grey, spaceAfter=4)))
    story.append(Spacer(1, 0.3*rl_cm))
    page_w = pagesize[0] - 3*rl_cm
    if metricas:
        met_items = [f"{k}: {v}" for k, v in metricas.items()]
        n = max(len(met_items), 1)
        met_table = Table([met_items], colWidths=[page_w / n] * n)
        met_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COR_CINZA),
            ('FONTSIZE',   (0, 0), (-1, -1), 9),
            ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING',  (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LINEBELOW',  (0, 0), (-1, -1), 2, COR_AZUL),
        ]))
        story.append(met_table)
        story.append(Spacer(1, 0.4*rl_cm))
    _fmtv = lambda v: "" if str(v) in ("nan", "None", "NaT", "<NA>") else str(v)
    header = list(df_exibir.columns)
    # Nomes curtos para exibição no PDF (sem underscores, abreviados onde necessário)
    _RENAME_PDF = {
        "Unidade": "Un.", "Valor_Unit": "Vl.Un.", "Valor_Total": "Vl.Tot.",
        "Num_NF": "Num NF", "Data_NF": "Data NF", "Observacao": "Observação",
        "Situacao": "Situação", "Data_Inicio": "Dt. Início",
        "Data_Devolucao": "Dt. Devol.", "Periodo_Inicio": "Per. Início",
        "Periodo_Final": "Per. Fim", "Venc_Boleto": "Venc. Bol.",
        "Nome_Fornecedor": "Fornecedor", "Nome_Equipamento": "Equip.",
        "Nome_Obra": "Obra", "Dias_Vencer": "Dias/Venc", "Qtd Total": "Qtd",
    }
    header_display = [_RENAME_PDF.get(c, c) for c in header]
    # Estilos de célula com quebra de linha automática
    st_hdr  = ParagraphStyle('hdr',  fontName='Helvetica-Bold', fontSize=7,
                             textColor=rl_colors.white,       leading=9)
    st_cell = ParagraphStyle('cell', fontName='Helvetica',      fontSize=7,
                             textColor=rl_colors.black,       leading=9)
    # Larguras por tipo de coluna — classificação pelo nome original, escala proporcional
    COLS_NARROW = {"Unidade", "Entrada", "Saída", "Saldo", "Qtd", "Valor",
                   "Valor_Unit", "Valor_Total", "Num_NF", "Qtd Total"}
    COLS_MEDIUM = {"Local", "Categoria", "Tipo", "Data", "Status",
                   "Origem", "Destino", "Data_NF", "Data_Inicio",
                   "Data_Devolucao", "Periodo_Inicio", "Periodo_Final",
                   "Venc_Boleto", "Usuario", "Situacao", "Dias_Vencer"}
    COLS_WIDE   = {"Material", "Descricao", "Nome", "Nome_Fornecedor",
                   "Nome_Equipamento", "Fornecedor", "Observacao",
                   "Contrato", "Obra", "Nome_Obra"}
    _desired = []
    for c in header:
        if c in COLS_NARROW:   _desired.append(1.8 * rl_cm)
        elif c in COLS_MEDIUM: _desired.append(3.0 * rl_cm)
        elif c in COLS_WIDE:   _desired.append(3.5 * rl_cm)
        else:                  _desired.append(3.0 * rl_cm)
    _total = sum(_desired)
    _scale = (page_w / _total) if _total > page_w else 1.0
    col_widths = [w * _scale for w in _desired]
    # Construir dados com Paragraphs — cabeçalhos com nomes curtos
    data = [[Paragraph(c, st_hdr) for c in header_display]]
    for row in df_exibir.itertuples(index=False, name=None):
        data.append([Paragraph(_fmtv(v), st_cell) for v in row])
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ('BACKGROUND',   (0, 0), (-1, 0), COR_AZUL),
        ('ALIGN',        (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('LINEBELOW',    (0, 0), (-1, -1), 0.3, rl_colors.lightgrey),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), COR_CINZA))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, 0.5*rl_cm))
    story.append(Paragraph(
        "GOMAP Engenharia e Construções — Sistema de Controle de Estoque e Materiais",
        ParagraphStyle('footer', fontName='Helvetica', fontSize=8, textColor=rl_colors.grey)))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def aplicar_filtro_periodo(df, coluna_data, periodo, data_ini=None, data_fim=None):
    """Filtra DataFrame por período na coluna de data especificada."""
    if periodo == "Todo o período":
        return df
    df = df.copy()
    df[coluna_data] = pd.to_datetime(df[coluna_data], errors="coerce")
    hoje = pd.Timestamp(datetime.today().date())
    if periodo == "Últimos 7 dias":
        return df[df[coluna_data] >= hoje - pd.Timedelta(days=7)]
    elif periodo == "Últimos 30 dias":
        return df[df[coluna_data] >= hoje - pd.Timedelta(days=30)]
    elif periodo == "Últimos 90 dias":
        return df[df[coluna_data] >= hoje - pd.Timedelta(days=90)]
    elif periodo == "Este mês":
        return df[(df[coluna_data].dt.month == hoje.month) & (df[coluna_data].dt.year == hoje.year)]
    elif periodo == "Este ano":
        return df[df[coluna_data].dt.year == hoje.year]
    elif periodo == "Personalizado" and data_ini and data_fim:
        return df[(df[coluna_data] >= pd.Timestamp(data_ini)) & (df[coluna_data] <= pd.Timestamp(data_fim))]
    return df

# --- 3. NAVEGAÇÃO ---
if 'pagina' not in st.session_state:
    st.session_state.pagina = st.query_params.get("pagina", "Início")
_sync_unidades()
if 'logado' not in st.session_state:
    st.session_state.logado = False
if 'usuario_nome' not in st.session_state:
    st.session_state.usuario_nome = ""
if 'usuario_perfil' not in st.session_state:
    st.session_state.usuario_perfil = ""
if 'usuario_login' not in st.session_state:
    st.session_state.usuario_login = ""


def ir_para(nova):
    st.session_state.pagina = nova
    st.query_params["pagina"] = nova
    st.rerun()

def page_header(titulo):
    """Renderiza o título da página + botão 🏠 Painel Principal na mesma linha."""
    ph1, ph2 = st.columns([5, 1])
    ph1.subheader(titulo)
    _ph_key = f"phbtn_{st.session_state.get('pagina', titulo)}"
    if ph2.button("🏠 Painel Principal", use_container_width=True, key=_ph_key):
        ir_para("Início")


def _menu_btn(label, pagina, permitido=True):
    """Renderiza botão de navegação + ícone ↗ para abrir em nova aba."""
    if not permitido:
        return
    _c1, _c2 = st.columns([0.84, 0.16])
    if _c1.button(label, use_container_width=True, key=f"nav_{pagina}"):
        ir_para(pagina)
    _c2.markdown(
        f'<div class="sidebar-newtab-link">'
        f'<a href="/?pagina={pagina}" target="_blank" title="Abrir em nova aba">↗</a>'
        f'</div>',
        unsafe_allow_html=True
    )


# ╔══════════════════════════════════════════════════════════╗
# ║                    TELA DE LOGIN                         ║
# ╚══════════════════════════════════════════════════════════╝
if not st.session_state.logado:
    st.markdown("")
    st.markdown("")

    col_l, col_center, col_r = st.columns([1, 2, 1])
    with col_center:
        # Logo no login
        if LOGO_BASE64:
            st.markdown(f'<div style="text-align:center;margin-bottom:10px;"><img src="data:image/png;base64,{LOGO_BASE64}" style="height:70px;"></div>', unsafe_allow_html=True)
        
        st.markdown('<div class="login-sub">Controle de Estoque e Ferramentas</div>', unsafe_allow_html=True)

        with st.form("login_form", border=True):
            usuario_input = st.text_input("👤 Usuário", placeholder="Digite seu usuário")
            senha_input = st.text_input("🔒 Senha", type="password", placeholder="Digite sua senha")

            if st.form_submit_button("🔐 ENTRAR NO SISTEMA", use_container_width=True, type="primary"):
                if usuario_input and senha_input:
                    ok, dados = verificar_login(usuario_input.lower().strip(), senha_input)
                    if ok:
                        st.session_state.logado = True
                        st.session_state.usuario_nome = dados["nome"]
                        st.session_state.usuario_perfil = dados["perfil"]
                        st.session_state.usuario_login = usuario_input.lower().strip()
                        st.rerun()
                    else:
                        st.error("❌ Usuário ou senha incorretos.")
                else:
                    st.warning("Preencha usuário e senha.")

        st.markdown("")
        st.markdown("")


# ╔══════════════════════════════════════════════════════════╗
# ║                   SISTEMA LOGADO                         ║
# ╚══════════════════════════════════════════════════════════╝
else:
    # --- CABEÇALHO HTML (título + logo base64) ---
    _logo_img = f'<img src="data:image/png;base64,{LOGO_BASE64}">' if LOGO_BASE64 else ""
    st.markdown(f'<div class="header-bar"><span class="h-title">Controle de Estoque de Materiais e Ferramentas</span>{_logo_img}</div>', unsafe_allow_html=True)

    # --- MENU LATERAL ---
    with st.sidebar:
        st.markdown("""
            <div style="text-align:center; padding: 0; margin: -15px 0 0 0; line-height: 1.1;">
                <span style="font-size:36px; font-weight:900; color:white; letter-spacing:2px;">GOMAP</span><br>
                <span style="font-size:15px; color:rgba(255,255,255,0.7); letter-spacing:0.5px;">Engenharia e Construções</span>
            </div>
            <div style="height:15px;"></div>
        """, unsafe_allow_html=True)
        _perfil = st.session_state.usuario_perfil
        _perfil_desc = PERFIS.get(_perfil, {}).get("descricao", _perfil)
        st.markdown(f'<div class="user-info">👤 {st.session_state.usuario_nome}<br>📋 {_perfil_desc}</div>', unsafe_allow_html=True)
        st.markdown("### MENU")
        _menu_btn("📊 Painel Principal", "Início")
        _menu_btn("📝 Cadastros", "Cadastros", get_permissao(_perfil, "cadastros"))
        _menu_btn("🔄 Movimentação", "Movimentação", get_permissao(_perfil, "lancamentos"))
        _menu_btn("📜 Relatórios", "Relatórios", get_permissao(_perfil, "relatorios"))
        _menu_btn("📦 Estoque Atual", "Estoque", get_permissao(_perfil, "estoque"))
        _menu_btn("🏗️ Locações", "Locacoes", get_permissao(_perfil, "locacoes"))
        _menu_btn("👥 Usuários", "Usuarios", get_permissao(_perfil, "usuarios"))
        st.markdown("---")
        if st.button("🚪 Sair do Sistema", use_container_width=True):
            st.session_state.logado = False
            st.session_state.usuario_nome = ""
            st.session_state.usuario_perfil = ""
            st.session_state.usuario_login = ""
            st.rerun()


    # ══════════════════════════════════════════════════════
    #              PÁGINA: PAINEL PRINCIPAL
    # ══════════════════════════════════════════════════════
    if st.session_state.pagina == "Início":
        # ── Saudação personalizada ──────────────────────────────────────
        _hora = datetime.now().hour
        _saudacao = "Bom dia" if _hora < 12 else ("Boa tarde" if _hora < 18 else "Boa noite")
        _data_fmt = datetime.today().strftime("%d/%m/%Y  —  %H:%M")
        _usr_nome = st.session_state.get("usuario_nome", "")
        st.markdown(f"""
        <div class="dash-header">
            <div>
                <div class="dash-greeting">{_saudacao}, <b>{_usr_nome}</b>! 👋</div>
                <div class="dash-date">📅 {_data_fmt}</div>
            </div>
            <div class="dash-subtitle">Painel de Controle<br>GOMAP Engenharia</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Carregar dados ──────────────────────────────────────────────
        df_mov   = load("mov")
        df_prod  = load("prod")
        df_obras = load("obras")
        df_loc   = load("loc")

        # ── Calcular métricas ───────────────────────────────────────────
        entradas = df_mov[df_mov["Tipo"].isin(["Compra", "Entrada"])]["Qtd"].sum() if len(df_mov) > 0 else 0
        saidas   = df_mov[df_mov["Tipo"] == "Saída"]["Qtd"].sum() if len(df_mov) > 0 else 0
        saldo    = entradas - saidas
        loc_ativas = (len(df_loc[df_loc["Status"] == "Ativo"])
                      if len(df_loc) > 0 and "Status" in df_loc.columns else 0)

        # Boletos de locações vencendo em ≤7 dias
        loc_vencendo = 0
        if len(df_loc) > 0 and "Venc_Boleto" in df_loc.columns and "Status" in df_loc.columns:
            _df_la = df_loc[df_loc["Status"] == "Ativo"].copy()
            _df_la["Venc_Boleto"] = pd.to_datetime(_df_la["Venc_Boleto"], errors="coerce")
            _hoje_ts = pd.Timestamp(datetime.today().date())
            _dias = (_df_la["Venc_Boleto"] - _hoje_ts).dt.days
            loc_vencendo = int((_dias.between(0, 7)).sum())

        # ── Metric cards ────────────────────────────────────────────────
        def _mc(icon, value, label, color=None, badge=None, status=None, st_type="neutral"):
            c = color or AZUL_GOMAP
            b = f'<div class="metric-badge">{badge}</div>' if badge else ""
            s = (f'<div class="status-pill sp-{st_type}">{status}</div>'
                 if status else "")
            return (f'<div class="metric-card" style="border-top-color:{c};">'
                    f'{b}<div class="metric-icon">{icon}</div>'
                    f'<div class="metric-value" style="color:{c};">{value}</div>'
                    f'<div class="metric-label">{label}</div>{s}</div>')

        _loc_color = "#e53e3e" if loc_vencendo > 0 else "#38a169"
        _saldo_color = "#e53e3e" if saldo < 0 else AZUL_CLARO
        _saldo_st = ("NEGATIVO", "danger") if saldo < 0 else ("POSITIVO", "ok")
        _loc_st = ("VENCENDO", "danger") if loc_vencendo > 0 else ("EM DIA", "ok")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.markdown(_mc("📦", len(df_prod),   "Produtos",
                        status="CADASTROS", st_type="info"),          unsafe_allow_html=True)
        m2.markdown(_mc("🏗️", len(df_obras),  "Obras",
                        status="ATIVO", st_type="ok"),                unsafe_allow_html=True)
        m3.markdown(_mc("📋", len(df_mov),    "Lançamentos",
                        status="HISTÓRICO", st_type="neutral"),       unsafe_allow_html=True)
        m4.markdown(_mc("📊", f"{saldo:.0f}", "Saldo Geral",
                        color=_saldo_color,
                        status=_saldo_st[0], st_type=_saldo_st[1]),  unsafe_allow_html=True)
        m5.markdown(_mc("🔑", loc_ativas,     "Locações Ativas",
                        color=_loc_color,
                        badge=loc_vencendo if loc_vencendo > 0 else None,
                        status=_loc_st[0], st_type=_loc_st[1]),
                    unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Action cards ─────────────────────────────────────────────────
        _CARDS = [
            ("📝", "CADASTROS",   "Produtos, Categorias, Obras",     "#1a365d", "Cadastros"),
            ("🔄", "LANÇAMENTOS", "Entrada / Saída / Transferência",  "#2a5298", "Movimentação"),
            ("🔑", "LOCAÇÕES",    "Equipamentos Locados",             _loc_color, "Locacoes"),
            ("📜", "RELATÓRIOS",  "Consultas e Filtros",              "#d69e2e", "Relatórios"),
        ]
        col_a, col_b, col_c, col_d = st.columns(4)
        for _col, (_icon, _title, _sub, _color, _page) in zip(
                [col_a, col_b, col_c, col_d], _CARDS):
            with _col:
                _alerta = (f'<div class="action-alert">{loc_vencendo} vencendo</div>'
                           if _page == "Locacoes" and loc_vencendo > 0 else "")
                st.markdown(
                    f'<div class="action-card" style="border-left-color:{_color};">'
                    f'{_alerta}'
                    f'<div class="action-icon" style="color:{_color};">{_icon}</div>'
                    f'<div class="action-title" style="color:{_color};">{_title}</div>'
                    f'<div class="action-subtitle">{_sub}</div></div>',
                    unsafe_allow_html=True)
                if st.button("Acessar →", use_container_width=True, key=f"dash_btn_{_page}"):
                    ir_para(_page)

        # ── Gráficos Plotly ──────────────────────────────────────────────
        if PLOTLY_OK:
            st.markdown("<br>", unsafe_allow_html=True)
            _CORES = {
                "Compra":       "#1a365d",
                "Entrada":      "#38a169",
                "Saída":        "#e53e3e",
                "Transferência":"#d69e2e",
            }
            gcol_l, gcol_m, gcol_r = st.columns([4, 4, 3])

            with gcol_l:
                st.markdown("**📊 Distribuição por Tipo**")
                if len(df_mov) > 0:
                    _df_tipo = df_mov.groupby("Tipo")["Qtd"].sum().reset_index()
                    _df_tipo.columns = ["Tipo", "Quantidade"]
                    _fig_donut = px.pie(
                        _df_tipo, values="Quantidade", names="Tipo",
                        hole=0.55, color="Tipo", color_discrete_map=_CORES,
                    )
                    _fig_donut.update_layout(
                        margin=dict(t=10, b=30, l=0, r=0), height=280,
                        legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    _fig_donut.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(_fig_donut, use_container_width=True)
                else:
                    st.info("Sem movimentações registradas.")

            with gcol_m:
                st.markdown("**📈 Volume — Últimos 7 dias**")
                if len(df_mov) > 0:
                    _df_m = df_mov.copy()
                    _df_m["Data"] = pd.to_datetime(_df_m["Data"], errors="coerce")
                    _df_m = _df_m.dropna(subset=["Data"])
                    _hoje7 = pd.Timestamp(datetime.today().date())
                    _df_m = _df_m[_df_m["Data"] >= _hoje7 - pd.Timedelta(days=7)]
                    if len(_df_m) > 0:
                        _df_m["Dia"] = _df_m["Data"].dt.strftime("%d/%m")
                        _df_diario = _df_m.groupby(["Dia", "Tipo"])["Qtd"].sum().reset_index()
                        _df_diario.columns = ["Dia", "Tipo", "Quantidade"]
                        _fig_bar = px.bar(
                            _df_diario, x="Dia", y="Quantidade", color="Tipo",
                            color_discrete_map=_CORES, barmode="stack",
                        )
                        _fig_bar.update_layout(
                            margin=dict(t=10, b=30, l=0, r=0), height=280,
                            legend=dict(orientation="h", y=-0.28, x=0.5, xanchor="center"),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            xaxis=dict(showgrid=False, type="category"),
                            yaxis=dict(gridcolor="rgba(0,0,0,0.06)"),
                        )
                        st.plotly_chart(_fig_bar, use_container_width=True)
                    else:
                        st.info("Sem movimentações nos últimos 7 dias.")
                else:
                    st.info("Sem movimentações registradas.")

            with gcol_r:
                st.markdown("**🔑 Locações — Risco de Vencimento**")
                _max_gauge = max(loc_ativas, 1)
                _pct_venc = round(loc_vencendo / _max_gauge * 100)
                _gauge_bar = ("#e53e3e" if _pct_venc > 50
                              else "#d69e2e" if _pct_venc > 20
                              else "#38a169")
                _fig_gauge = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=loc_vencendo,
                    number={"suffix": f"/{loc_ativas}", "font": {"size": 26, "color": _gauge_bar}},
                    title={"text": "Vencendo em 7 dias", "font": {"size": 12, "color": "#4a5568"}},
                    gauge={
                        "axis": {"range": [0, _max_gauge], "tickwidth": 1,
                                 "tickcolor": "#718096", "tickfont": {"size": 10}},
                        "bar": {"color": _gauge_bar, "thickness": 0.28},
                        "bgcolor": "white",
                        "borderwidth": 0,
                        "steps": [
                            {"range": [0, _max_gauge * 0.3], "color": "#c6f6d5"},
                            {"range": [_max_gauge * 0.3, _max_gauge * 0.7], "color": "#fefcbf"},
                            {"range": [_max_gauge * 0.7, _max_gauge], "color": "#fed7d7"},
                        ],
                        "threshold": {
                            "line": {"color": "#c53030", "width": 3},
                            "thickness": 0.8,
                            "value": loc_vencendo,
                        },
                    },
                ))
                _fig_gauge.update_layout(
                    margin=dict(t=50, b=10, l=20, r=20), height=280,
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(_fig_gauge, use_container_width=True)

        # ── Últimos 7 Lançamentos ────────────────────────────────────────
        if len(df_mov) > 0:
            st.divider()
            _df_mov7 = df_mov.copy()
            _df_mov7["Data"] = pd.to_datetime(_df_mov7["Data"], errors="coerce")
            _df_mov7 = _df_mov7.sort_values("Data", ascending=False).head(7)
            st.markdown(f"**📋 Últimos 7 Lançamentos**")
            _cols_user = [c for c in ["Data", "Tipo", "Material", "Categoria", "Unidade",
                                      "Origem", "Destino", "Qtd", "Valor_Unit", "Valor_Total",
                                      "Fornecedor", "Data_NF", "Num_NF", "Observacao", "Usuario"]
                          if c in _df_mov7.columns]
            st.dataframe(fmt_datas(_df_mov7[_cols_user]), use_container_width=True, hide_index=True)


    # ══════════════════════════════════════════════════════
    #              PÁGINA: CADASTROS
    # ══════════════════════════════════════════════════════
    elif st.session_state.pagina == "Cadastros":
        _tem_acesso = get_permissao(st.session_state.usuario_perfil, "cadastros")
        page_header("📝 Gestão de Cadastros")
        tab_prod, tab_cat, tab_obras_t, tab_unid, tab_equip_t, tab_forn = st.tabs(
            ["Produtos", "Categorias", "Obras", "Unid/Medida", "Equipamentos (Locação)", "Fornecedores"])
        if not _tem_acesso:
            with tab_prod:
                st.error("⛔ Seu perfil não tem permissão para acessar Cadastros.")
                if st.button("🏠 Voltar ao Painel"): ir_para("Início")
            st.stop()

        def _render_generic_cad(tab_menu, tab_key, tab_col, ref_keys=None):
            # ref_keys: lista de (chave_tabela, coluna) que referenciam este campo
            # Ex: [("prod", "Unidade"), ("mov", "Unidade")]
            _nome_singular = tab_menu[:-1] if tab_menu.endswith('s') else tab_menu
            _gk = st.session_state.get(f"gen_form_key_{tab_key}", 0)
            with st.container(border=True):
                st.markdown(f"**Cadastro de {_nome_singular}**")
                novo_val = st.text_input(f"Nome da {_nome_singular}",
                                         key=f"gen_nome_{tab_key}_{_gk}")
                b_inc, b_can, b_sai = st.columns(3)
                if b_inc.button(f"✅ Incluir {tab_menu}", type="primary", use_container_width=True, key=f"inc_{tab_key}"):
                    if novo_val:
                        df = load(tab_key)
                        save(_concat_safe([df, pd.DataFrame([{tab_col: novo_val.strip()}])]), tab_key)
                        st.success(f"✅ '{novo_val.strip()}' adicionado!")
                        st.session_state[f"gen_form_key_{tab_key}"] = _gk + 1
                        st.rerun()
                    else:
                        st.warning("Preencha o nome.")
                if b_can.button("❌ Cancelar", use_container_width=True, key=f"can_{tab_key}"):
                    st.session_state[f"gen_form_key_{tab_key}"] = _gk + 1
                    st.rerun()
                if b_sai.button("🏠 Voltar ao Painel", use_container_width=True, key=f"sai_{tab_key}"):
                    ir_para("Início")
            df_view = load(tab_key)
            if len(df_view) > 0:
                busca_gen = st.text_input(
                    f"🔍 Pesquisar / Localizar em {tab_menu}:",
                    key=f"busca_{tab_key}",
                    placeholder="Digite para filtrar em tempo real...")
                _termo = busca_gen.strip()
                if _termo:
                    df_view_s = df_view[df_view[tab_col].astype(str).str.contains(_termo, case=False, na=False)]
                    st.markdown(f"**{len(df_view_s)} resultado(s) encontrado(s) de {len(df_view)} registro(s)**")
                else:
                    df_view_s = df_view.sort_values(tab_col, key=lambda x: x.str.lower())
                    st.markdown(f"**{len(df_view)} registro(s) — ordenado(s) alfabeticamente**")

                _df_ver = st.session_state.get(f"df_ver_{tab_key}", 0)
                event = st.dataframe(
                    df_view_s[[tab_col]].reset_index(drop=True),
                    width='stretch',
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"df_sel_{tab_key}_{_df_ver}"
                )
                sel_rows = event.selection.rows if hasattr(event, "selection") else []

                # ── Exportar relação ──────────────────────────────────────
                _df_exp = df_view_s[[tab_col]].reset_index(drop=True)
                _titulo_exp = f"Relação de {tab_menu}"
                _met_exp = {"Total": str(len(_df_exp))}
                if REPORTLAB_OK:
                    st.download_button(
                        f"🖨️ Imprimir / Exportar PDF — {tab_menu}",
                        gerar_pdf_relatorio(_titulo_exp, _df_exp, _met_exp),
                        file_name=f"relacao_{tab_key}.pdf", mime="application/pdf",
                        use_container_width=True, key=f"dl_pdf_{tab_key}"
                    )
                else:
                    st.download_button(
                        f"🖨️ Imprimir / Exportar HTML — {tab_menu}",
                        gerar_html_relatorio(_titulo_exp, _df_exp, _met_exp),
                        file_name=f"relacao_{tab_key}.html", mime="text/html",
                        use_container_width=True, key=f"dl_html_{tab_key}"
                    )

                def _limpar_selecao():
                    st.session_state[f"df_ver_{tab_key}"] = _df_ver + 1
                    st.session_state.pop(f"busca_{tab_key}", None)

                if sel_rows and get_permissao(st.session_state.usuario_perfil, "excluir"):
                    sel_local = sel_rows[0]
                    sel_idx = df_view_s.index[sel_local]
                    sel_val = _sv(df_view.loc[sel_idx, tab_col])

                    # Verifica uso em outras tabelas
                    in_use_count = 0
                    if ref_keys:
                        for rk, rc in ref_keys:
                            df_ref = load(rk)
                            if rc in df_ref.columns:
                                in_use_count += int((df_ref[rc].astype(str) == sel_val).sum())

                    st.markdown(
                        f'<div translate="no" style="background-color:#dff0fb;padding:0.75rem 1rem;'
                        f'border-radius:0.5rem;border-left:5px solid #2196F3;margin:0.5rem 0;font-size:1rem;">'
                        f'📌 Selecionado: <strong>{sel_val}</strong></div>',
                        unsafe_allow_html=True
                    )
                    col_alt, col_del = st.columns(2)

                    with col_alt:
                        with st.expander("✏️ Alterar"):
                            alt_val = st.text_input("Novo nome", value=sel_val,
                                                    key=f"alt_val_{tab_key}_{sel_idx}")
                            if st.button("💾 Salvar", type="primary", use_container_width=True,
                                         key=f"save_alt_{tab_key}"):
                                if alt_val.strip():
                                    old_val = sel_val
                                    df_view.loc[sel_idx, tab_col] = alt_val.strip()
                                    save(df_view, tab_key)
                                    if ref_keys and old_val != alt_val.strip():
                                        for rk, rc in ref_keys:
                                            df_ref = load(rk)
                                            if rc in df_ref.columns:
                                                df_ref[rc] = df_ref[rc].replace(old_val, alt_val.strip())
                                                save(df_ref, rk)
                                        st.success(f"✅ '{old_val}' → '{alt_val.strip()}' (atualizado também nos registros associados)")
                                    else:
                                        st.success(f"✅ '{alt_val.strip()}' salvo!")
                                    _limpar_selecao()
                                    st.rerun()
                                else:
                                    st.warning("Preencha o novo nome.")

                    with col_del:
                        with st.expander("🗑️ Excluir"):
                            if in_use_count > 0:
                                st.error(f"⛔ Não é possível excluir: **{sel_val}** está associado a {in_use_count} registro(s).")
                            else:
                                st.warning(f"Excluir **{sel_val}**?")
                                if st.button("🗑️ Confirmar", type="primary", use_container_width=True,
                                             key=f"del_{tab_key}"):
                                    df_view = df_view.drop(sel_idx).reset_index(drop=True)
                                    save(df_view, tab_key)
                                    _limpar_selecao()
                                    st.success("Excluído!")
                                    st.rerun()
                elif not sel_rows:
                    st.caption("💡 Clique em uma linha da tabela para selecionar e editar/excluir.")

        with tab_prod:

            # --- Dialogs de cadastro rápido (não perde dados digitados) ---
            @st.dialog("➕ Nova Categoria")
            def dialog_nova_categoria():
                nova_cat = st.text_input("Nome da Categoria")
                if st.button("✅ Salvar Categoria", type="primary", use_container_width=True):
                    if nova_cat:
                        df = load("cat")
                        save(_concat_safe([df, pd.DataFrame([{"Nome": nova_cat.strip()}])]), "cat")
                        st.success(f"✅ Categoria '{nova_cat.strip()}' criada!")
                        st.rerun()
                    else:
                        st.warning("Digite o nome da categoria.")

            @st.dialog("➕ Nova Unidade")
            def dialog_nova_unidade():
                nova_un = st.text_input("Nome da Unidade")
                if st.button("✅ Salvar Unidade", type="primary", use_container_width=True):
                    if nova_un:
                        df = load("unid")
                        save(_concat_safe([df, pd.DataFrame([{"Nome": nova_un.strip().upper()}])]), "unid")
                        st.success(f"✅ Unidade '{nova_un.upper()}' criada!")
                        st.rerun()
                    else:
                        st.warning("Digite o nome da unidade.")

            @st.dialog("➕ Nova Obra")
            def dialog_nova_obra():
                nova_ob = st.text_input("Nome da Obra")
                if st.button("✅ Salvar Obra", type="primary", use_container_width=True):
                    if nova_ob:
                        df = load("obras")
                        save(_concat_safe([df, pd.DataFrame([{"Nome_Obra": nova_ob.strip().upper()}])]), "obras")
                        st.success(f"✅ Obra '{nova_ob.upper()}' criada!")
                        st.rerun()
                    else:
                        st.warning("Digite o nome da obra.")

            # --- Formulário de Produto (com limpeza automática após incluir) ---
            _pk = st.session_state.get("prod_form_key", 0)
            with st.container(border=True):
                n_prod = st.text_input("Descrição do Material", key=f"prod_nome_{_pk}")

                c1, c2 = st.columns(2)
                cats = sorted(_get_column_safe(load("cat"), "Nome"))
                uns = _get_column_safe(load("unid"), "Nome")
                cat_prod = c1.selectbox("Categoria", ["--- Selecione ---"] + cats, key=f"prod_cat_{_pk}")
                un_prod = c2.selectbox("Unidade", sorted(uns) if uns else ["un"], key=f"prod_un_{_pk}")

                # Botões de cadastro rápido (abrem popup sem perder dados)
                st.caption("Não encontrou? Cadastre rapidamente:")
                qc1, qc2, qc3 = st.columns(3)
                if qc1.button("➕ Nova Categoria", use_container_width=True):
                    dialog_nova_categoria()
                if qc2.button("➕ Nova Unidade", use_container_width=True):
                    dialog_nova_unidade()
                if qc3.button("➕ Nova Obra", use_container_width=True):
                    dialog_nova_obra()

                st.markdown("---")
                b_inc, b_can, b_sai = st.columns(3)
                if b_inc.button("✅ Incluir Produto", type="primary", use_container_width=True):
                    if n_prod and cat_prod != "--- Selecione ---":
                        df = load("prod")
                        novo = pd.DataFrame([{"Material": n_prod.strip(), "Categoria": cat_prod, "Unidade": un_prod}])
                        save(_concat_safe([df, novo]), "prod")
                        st.success(f"✅ Produto '{n_prod.upper()}' cadastrado!")
                        st.session_state.prod_form_key = _pk + 1
                        st.rerun()
                    else:
                        st.warning("Preencha a descrição e selecione uma categoria.")
                if b_can.button("❌ Cancelar", use_container_width=True, key="can_prod"):
                    st.session_state.prod_form_key = _pk + 1
                    st.rerun()
                if b_sai.button("🏠 Voltar ao Painel", use_container_width=True, key="sai_prod"):
                    ir_para("Início")

            # Tabela de produtos com pesquisa dinâmica, alterar e excluir
            df_prod = load("prod")
            for _col in ["Material", "Categoria", "Unidade"]:
                if _col not in df_prod.columns:
                    df_prod[_col] = ""
            if len(df_prod) > 0:
                _sorted_mats = ["--- Mostrar Todos ---"] + sorted(
                    df_prod["Material"].dropna().unique().tolist())
                busca_prod = st.selectbox(
                    "🔍 Pesquisar / Localizar Produto (digite para filtrar em tempo real):",
                    _sorted_mats, key="busca_prod",
                    help="Clique e comece a digitar — os itens são filtrados instantaneamente")
                if busca_prod != "--- Mostrar Todos ---":
                    df_prod_s = df_prod[df_prod["Material"] == busca_prod]
                    st.markdown(f"**1 resultado encontrado de {len(df_prod)} produto(s)**")
                else:
                    df_prod_s = df_prod.sort_values("Material")
                    st.markdown(f"**{len(df_prod)} produto(s) — ordenado(s) alfabeticamente**")

                cols_exibir = [c for c in ["Material", "Categoria", "Unidade"] if c in df_prod_s.columns]
                _prod_tbl_v = st.session_state.get("_prod_tbl_v", 0)
                _evt_prod = st.dataframe(
                    df_prod_s[cols_exibir],
                    width='stretch',
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"df_prod_tbl_{_prod_tbl_v}"
                )
                _prod_sel_rows = _evt_prod.selection.rows if hasattr(_evt_prod, "selection") else []

                # ── Exportar relação de produtos ──────────────────────────
                _df_exp_prod = df_prod_s[cols_exibir].reset_index(drop=True)
                _met_prod = {"Total de Produtos": str(len(_df_exp_prod))}
                if REPORTLAB_OK:
                    st.download_button(
                        "🖨️ Imprimir / Exportar PDF — Produtos",
                        gerar_pdf_relatorio("Relação de Produtos", _df_exp_prod, _met_prod),
                        file_name="relacao_produtos.pdf", mime="application/pdf",
                        use_container_width=True, key="dl_pdf_prod"
                    )
                else:
                    st.download_button(
                        "🖨️ Imprimir / Exportar HTML — Produtos",
                        gerar_html_relatorio("Relação de Produtos", _df_exp_prod, _met_prod),
                        file_name="relacao_produtos.html", mime="text/html",
                        use_container_width=True, key="dl_html_prod"
                    )

                def _limpar_prod_sel():
                    st.session_state["_prod_tbl_v"] = _prod_tbl_v + 1

                if _prod_sel_rows and get_permissao(st.session_state.usuario_perfil, "excluir"):
                    _sel_display = _prod_sel_rows[0]
                    _sel_orig_idx = df_prod_s.index[_sel_display]
                    row_sel = df_prod.loc[_sel_orig_idx]
                    _sel_mat = _sv(row_sel["Material"])

                    st.markdown(
                        f'<div translate="no" style="background-color:#dff0fb;padding:0.75rem 1rem;'
                        f'border-radius:0.5rem;border-left:5px solid #2196F3;margin:0.5rem 0;font-size:1rem;">'
                        f'📌 Selecionado: <strong>{_sel_mat}</strong></div>',
                        unsafe_allow_html=True
                    )

                    _col_alt_p, _col_del_p = st.columns(2)

                    with _col_alt_p:
                        with st.expander("✏️ Alterar Produto"):
                            _apv = st.session_state.get("_alt_prod_v", 0)
                            cats_al = sorted(_get_column_safe(load("cat"), "Nome"))
                            _db_uns_al = sorted(_get_column_safe(load("unid"), "Nome"))
                            uns_al = _db_uns_al if _db_uns_al else ["un"]
                            alt_nome = st.text_input("Descrição do Material", value=_sv(row_sel["Material"]),
                                                     key=f"alt_pnome_{_sel_orig_idx}_{_apv}")
                            ac1, ac2 = st.columns(2)
                            _cat_opts = ["--- Selecione ---"] + cats_al
                            _cat_cur = _sv(row_sel["Categoria"])
                            _cat_idx = _cat_opts.index(_cat_cur) if _cat_cur in _cat_opts else 0
                            alt_cat = ac1.selectbox("Categoria", _cat_opts, index=_cat_idx,
                                                    key=f"alt_pcat_{_sel_orig_idx}_{_apv}")
                            _un_cur = _sv(row_sel["Unidade"])
                            _un_idx = uns_al.index(_un_cur) if _un_cur in uns_al else 0
                            alt_un = ac2.selectbox("Unidade", uns_al, index=_un_idx,
                                                   key=f"alt_pun_{_sel_orig_idx}_{_apv}")
                            if st.button("💾 Salvar Alteração", type="primary", use_container_width=True,
                                         key=f"save_alt_prod_{_apv}"):
                                if alt_nome and alt_cat != "--- Selecione ---":
                                    df_prod.loc[_sel_orig_idx, "Material"] = alt_nome.strip()
                                    df_prod.loc[_sel_orig_idx, "Categoria"] = alt_cat
                                    df_prod.loc[_sel_orig_idx, "Unidade"] = alt_un
                                    # Limpa FKs antigos para forçar re-resolução pelo nome em _resolve_fk
                                    if "category_id" in df_prod.columns:
                                        df_prod.loc[_sel_orig_idx, "category_id"] = None
                                    if "unit_id" in df_prod.columns:
                                        df_prod.loc[_sel_orig_idx, "unit_id"] = None
                                    try:
                                        save(df_prod, "prod")
                                        st.session_state["_alt_prod_v"] = _apv + 1
                                        st.toast(f"✅ '{alt_nome.strip()}' alterado com sucesso!", icon="✅")
                                    except Exception as _e_alt:
                                        st.error(f"❌ Erro ao salvar: {_e_alt}")
                                        st.stop()
                                    _limpar_prod_sel()
                                    st.rerun()
                                else:
                                    st.warning("Preencha todos os campos.")

                    with _col_del_p:
                        with st.expander("🗑️ Excluir Produto"):
                            st.warning(f"Excluir **{_sel_mat}**?")
                            if st.button("🗑️ Confirmar Exclusão", type="primary",
                                         use_container_width=True, key="del_prod_confirm"):
                                df_prod = df_prod.drop(_sel_orig_idx).reset_index(drop=True)
                                save(df_prod, "prod")
                                _limpar_prod_sel()
                                st.success("Produto excluído!")
                                st.rerun()

                elif not _prod_sel_rows and get_permissao(st.session_state.usuario_perfil, "excluir"):
                    if len(df_prod_s) > 0:
                        st.caption("💡 Clique em uma linha da tabela para selecionar e editar/excluir.")
                    else:
                        st.info("Nenhum produto encontrado para a pesquisa.")

        with tab_forn:
            _ESTADOS = ["","AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS",
                        "MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]
            _fk = st.session_state.get("forn_form_key", 0)
            with st.container(border=True):
                st.markdown("**Cadastro de Fornecedor**")

                # Linha 1: Razão Social + CNPJ + Inscrição Estadual
                fa1, fa2, fa3 = st.columns([3, 2, 2])
                forn_nome    = fa1.text_input("🏢 Nome / Razão Social *", key=f"forn_nome_{_fk}")
                forn_cnpj    = fa2.text_input("CNPJ", placeholder="00.000.000/0000-00", key=f"forn_cnpj_{_fk}")
                forn_ie      = fa3.text_input("Inscrição Estadual", key=f"forn_ie_{_fk}")

                # Linha 2: Contato + Telefone + Celular + E-mail
                fb1, fb2, fb3, fb4 = st.columns(4)
                forn_contato = fb1.text_input("👤 Contato", key=f"forn_contato_{_fk}")
                forn_tel     = fb2.text_input("📞 Telefone", key=f"forn_tel_{_fk}")
                forn_cel     = fb3.text_input("📱 Celular", key=f"forn_cel_{_fk}")
                forn_email   = fb4.text_input("✉️ E-mail", key=f"forn_email_{_fk}")

                # Linha 3: Endereço + Bairro
                fc1, fc2 = st.columns([3, 2])
                forn_end     = fc1.text_input("📍 Endereço", key=f"forn_end_{_fk}")
                forn_bairro  = fc2.text_input("Bairro", key=f"forn_bairro_{_fk}")

                # Linha 4: Cidade + Estado + CEP
                fd1, fd2, fd3 = st.columns([3, 1, 2])
                forn_cidade  = fd1.text_input("Cidade", key=f"forn_cidade_{_fk}")
                forn_estado  = fd2.selectbox("UF", _ESTADOS, key=f"forn_estado_{_fk}")
                forn_cep     = fd3.text_input("CEP", placeholder="00000-000", key=f"forn_cep_{_fk}")

                # Linha 5: Observações
                forn_obs     = st.text_area("📝 Observações", height=80, key=f"forn_obs_{_fk}")

                b_inc, b_can, b_sai = st.columns(3)
                if b_inc.button("✅ Incluir Fornecedor", type="primary", use_container_width=True):
                    if forn_nome:
                        df = load("forn")
                        novo = pd.DataFrame([{
                            "Nome_Fornecedor": forn_nome.strip().upper(),
                            "CNPJ":            forn_cnpj.strip(),
                            "Insc_Estadual":   forn_ie.strip(),
                            "Telefone":        forn_tel.strip(),
                            "Celular":         forn_cel.strip(),
                            "Email":           forn_email.strip(),
                            "Contato":         forn_contato.strip(),
                            "Endereco":        forn_end.strip(),
                            "Bairro":          forn_bairro.strip(),
                            "Cidade":          forn_cidade.strip().upper(),
                            "Estado":          forn_estado,
                            "CEP":             forn_cep.strip(),
                            "Observacao":      forn_obs.strip(),
                            "Data_Cadastro":   datetime.today().strftime("%Y-%m-%d"),
                        }])
                        save(_concat_safe([df, novo]), "forn")
                        st.success(f"✅ Fornecedor '{forn_nome.upper()}' cadastrado!")
                        st.session_state.forn_form_key = _fk + 1
                        st.rerun()
                    else:
                        st.warning("Preencha o nome do fornecedor.")
                if b_can.button("❌ Cancelar", use_container_width=True, key="can_forn"):
                    st.session_state.forn_form_key = _fk + 1
                    st.rerun()
                if b_sai.button("🏠 Voltar ao Painel", use_container_width=True, key="sai_forn"):
                    ir_para("Início")

            df_forn = load("forn")
            if len(df_forn) > 0:
                _sorted_forns = ["--- Mostrar Todos ---"] + sorted(
                    df_forn["Nome_Fornecedor"].dropna().unique().tolist())
                busca_forn = st.selectbox(
                    "🔍 Pesquisar / Localizar Fornecedor (digite para filtrar em tempo real):",
                    _sorted_forns, key="busca_forn",
                    help="Clique e comece a digitar — os itens são filtrados instantaneamente")
                if busca_forn != "--- Mostrar Todos ---":
                    df_forn_s = df_forn[df_forn["Nome_Fornecedor"] == busca_forn]
                    st.markdown(f"**1 resultado encontrado de {len(df_forn)} fornecedor(es)**")
                else:
                    df_forn_s = df_forn.sort_values("Nome_Fornecedor")
                    st.markdown(f"**{len(df_forn)} fornecedor(es) — ordenado(s) alfabeticamente**")

                # Exibe colunas principais na tabela (evita tabela muito larga)
                _cols_show_forn = [c for c in ["Nome_Fornecedor","CNPJ","Telefone","Celular","Email","Contato","Cidade","Estado","Data_Cadastro"] if c in df_forn_s.columns]
                _df_forn_show = fmt_datas(df_forn_s[_cols_show_forn], cols=["Data_Cadastro"])
                st.dataframe(_df_forn_show, width='stretch', hide_index=True)

                # ── Exportar relação de fornecedores ─────────────────────
                _df_exp_forn = _df_forn_show.reset_index(drop=True)
                _met_forn = {"Total de Fornecedores": str(len(_df_exp_forn))}
                if REPORTLAB_OK:
                    st.download_button(
                        "🖨️ Imprimir / Exportar PDF — Fornecedores",
                        gerar_pdf_relatorio("Relação de Fornecedores", _df_exp_forn, _met_forn),
                        file_name="relacao_fornecedores.pdf", mime="application/pdf",
                        use_container_width=True, key="dl_pdf_forn"
                    )
                else:
                    st.download_button(
                        "🖨️ Imprimir / Exportar HTML — Fornecedores",
                        gerar_html_relatorio("Relação de Fornecedores", _df_exp_forn, _met_forn),
                        file_name="relacao_fornecedores.html", mime="text/html",
                        use_container_width=True, key="dl_html_forn"
                    )

                if get_permissao(st.session_state.usuario_perfil, "excluir"):
                    if len(df_forn_s) > 0:
                        with st.expander("✏️ Alterar Fornecedor"):
                            idx_alt_f = st.selectbox("Selecione o fornecedor para alterar:", df_forn_s.index,
                                                     format_func=lambda i: df_forn.loc[i, "Nome_Fornecedor"], key="sel_alt_forn")
                            row_alt_f = df_forn.loc[idx_alt_f]

                            aa1, aa2, aa3 = st.columns([3, 2, 2])
                            alt_fnome   = aa1.text_input("🏢 Nome / Razão Social *", value=_sv(row_alt_f.get("Nome_Fornecedor","")), key=f"alt_fnome_{idx_alt_f}")
                            alt_fcnpj   = aa2.text_input("CNPJ", value=_sv(row_alt_f.get("CNPJ","")), key=f"alt_fcnpj_{idx_alt_f}")
                            alt_fie     = aa3.text_input("Inscrição Estadual", value=_sv(row_alt_f.get("Insc_Estadual","")), key=f"alt_fie_{idx_alt_f}")

                            ab1, ab2, ab3, ab4 = st.columns(4)
                            alt_fcontato = ab1.text_input("👤 Contato", value=_sv(row_alt_f.get("Contato","")), key=f"alt_fcontato_{idx_alt_f}")
                            alt_ftel     = ab2.text_input("📞 Telefone", value=_sv(row_alt_f.get("Telefone","")), key=f"alt_ftel_{idx_alt_f}")
                            alt_fcel     = ab3.text_input("📱 Celular", value=_sv(row_alt_f.get("Celular","")), key=f"alt_fcel_{idx_alt_f}")
                            alt_femail   = ab4.text_input("✉️ E-mail", value=_sv(row_alt_f.get("Email","")), key=f"alt_femail_{idx_alt_f}")

                            ac1, ac2 = st.columns([3, 2])
                            alt_fend    = ac1.text_input("📍 Endereço", value=_sv(row_alt_f.get("Endereco","")), key=f"alt_fend_{idx_alt_f}")
                            alt_fbairro = ac2.text_input("Bairro", value=_sv(row_alt_f.get("Bairro","")), key=f"alt_fbairro_{idx_alt_f}")

                            ad1, ad2, ad3 = st.columns([3, 1, 2])
                            alt_fcidade = ad1.text_input("Cidade", value=_sv(row_alt_f.get("Cidade","")), key=f"alt_fcidade_{idx_alt_f}")
                            _est_cur = _sv(row_alt_f.get("Estado",""))
                            _est_idx = _ESTADOS.index(_est_cur) if _est_cur in _ESTADOS else 0
                            alt_festado = ad2.selectbox("UF", _ESTADOS, index=_est_idx, key=f"alt_festado_{idx_alt_f}")
                            alt_fcep    = ad3.text_input("CEP", value=_sv(row_alt_f.get("CEP","")), key=f"alt_fcep_{idx_alt_f}")

                            alt_fobs = st.text_area("📝 Observações", value=_sv(row_alt_f.get("Observacao","")), height=80, key=f"alt_fobs_{idx_alt_f}")

                            if st.button("💾 Salvar Alteração", type="primary", use_container_width=True, key="save_alt_forn"):
                                if alt_fnome:
                                    df_forn.loc[idx_alt_f, "Nome_Fornecedor"] = alt_fnome.strip().upper()
                                    df_forn.loc[idx_alt_f, "CNPJ"]           = alt_fcnpj.strip()
                                    df_forn.loc[idx_alt_f, "Insc_Estadual"]  = alt_fie.strip()
                                    df_forn.loc[idx_alt_f, "Telefone"]       = alt_ftel.strip()
                                    df_forn.loc[idx_alt_f, "Celular"]        = alt_fcel.strip()
                                    df_forn.loc[idx_alt_f, "Email"]          = alt_femail.strip()
                                    df_forn.loc[idx_alt_f, "Contato"]        = alt_fcontato.strip()
                                    df_forn.loc[idx_alt_f, "Endereco"]       = alt_fend.strip()
                                    df_forn.loc[idx_alt_f, "Bairro"]         = alt_fbairro.strip()
                                    df_forn.loc[idx_alt_f, "Cidade"]         = alt_fcidade.strip().upper()
                                    df_forn.loc[idx_alt_f, "Estado"]         = alt_festado
                                    df_forn.loc[idx_alt_f, "CEP"]            = alt_fcep.strip()
                                    df_forn.loc[idx_alt_f, "Observacao"]     = alt_fobs.strip()
                                    save(df_forn, "forn")
                                    st.success("✅ Fornecedor alterado com sucesso!")
                                    st.rerun()
                                else:
                                    st.warning("Preencha o nome do fornecedor.")

                        with st.expander("🗑️ Excluir Fornecedor"):
                            idx_del = st.selectbox("Selecione:", df_forn_s.index,
                                                   format_func=lambda i: df_forn.loc[i, "Nome_Fornecedor"], key="del_sel_forn")
                            if st.button("Confirmar Exclusão", key="del_forn"):
                                df_forn = df_forn.drop(idx_del).reset_index(drop=True)
                                save(df_forn, "forn")
                                st.success("Excluído!")
                                st.rerun()
                    else:
                        st.info("Nenhum fornecedor encontrado para a pesquisa.")

        with tab_cat:
            _render_generic_cad("Categorias", "cat", "Nome",
                                ref_keys=[("prod", "Categoria")])

        with tab_obras_t:
            _render_generic_cad("Obras", "obras", "Nome_Obra")

        with tab_unid:
            _render_generic_cad("Unid/Medida", "unid", "Nome",
                                ref_keys=[("prod", "Unidade"), ("mov", "Unidade")])

        with tab_equip_t:
            _render_generic_cad("Equipamentos (Locação)", "equip", "Nome_Equipamento")


    # ══════════════════════════════════════════════════════
    #              PÁGINA: MOVIMENTAÇÃO
    # ══════════════════════════════════════════════════════
    elif st.session_state.pagina == "Movimentação":
        _tem_acesso_mov = get_permissao(st.session_state.usuario_perfil, "lancamentos")
        if not _tem_acesso_mov:
            st.error("⛔ Seu perfil não tem permissão para acessar Movimentação.")
            if st.button("🏠 Voltar ao Painel"): ir_para("Início")
        if _tem_acesso_mov:
            page_header("🔄 Lançamento de Movimentação")

        df_prod = load("prod")
        df_obras = load("obras")

        if len(df_prod) == 0:
            st.warning("⚠️ Nenhum produto cadastrado. Cadastre produtos antes de lançar movimentações.")
            if st.button("Ir para Cadastros"):
                ir_para("Cadastros")
        else:
            _mk = st.session_state.get("mov_form_key", 0)
            df_forn_list = load("forn")
            fornecedores_list = ["--- Selecione ---"] + sorted(df_forn_list["Nome_Fornecedor"].dropna().unique().tolist())
            locais = ["Almoxarifado Central"] + list(df_obras["Nome_Obra"].dropna().unique())
            locais_saida = locais + ["Consumo", "Perda/Extravio", "Devolução Fornecedor", "Outro"]

            with st.container(border=True):
                st.markdown("**Nova Movimentação**")

                c1, c2 = st.columns(2)
                data_mov = c1.date_input("📅 Data", value=datetime.today(), format="DD/MM/YYYY", key=f"mov_data_{_mk}")
                _tipos_mov = ["Compra", "Entrada", "Saída", "Transferência"]
                if st.session_state.get("usuario_perfil") == "admin":
                    _tipos_mov += ["Correção de Digitação", "Acerto de Estoque"]
                tipo_mov = c2.selectbox("📋 Tipo", _tipos_mov, key=f"mov_tipo_{_mk}",
                    help="Compra = entrada via fornecedor (NF) | Entrada = devolução/ajuste | Saída = consumo/obra | Transferência = entre locais | Correção/Acerto = somente admin")

                # Material com categoria e unidade automáticos
                material_sel = st.selectbox("📦 Material", ["--- Selecione ---"] + sorted(df_prod["Material"].dropna().unique().tolist()), key=f"mov_mat_{_mk}")

                cat_auto = ""
                un_auto = ""
                if material_sel != "--- Selecione ---":
                    row = df_prod[df_prod["Material"] == material_sel].iloc[0]
                    cat_auto = row["Categoria"]
                    un_auto = row["Unidade"]

                c3, c4 = st.columns(2)
                c3.text_input("Categoria", value=cat_auto, disabled=True, key=f"mov_cat_{_mk}")
                c4.text_input("Unidade", value=un_auto, disabled=True, key=f"mov_un_{_mk}")

                # Campos específicos de Compra (NF)
                forn_sel = ""
                data_nf_val = None
                num_nf_val = ""
                if tipo_mov == "Compra":
                    st.markdown("**🧾 Dados da Nota Fiscal**")
                    nf1, nf2, nf3 = st.columns(3)
                    forn_sel = nf1.selectbox("🏢 Fornecedor", fornecedores_list, key=f"mov_forn_{_mk}")
                    data_nf_val = nf2.date_input("📅 Data NF", value=datetime.today(), format="DD/MM/YYYY", key=f"mov_data_nf_{_mk}")
                    num_nf_val = nf3.text_input("🔢 Número NF", key=f"mov_num_nf_{_mk}")

                # Origem / Destino por tipo
                local_ajuste = ""
                ajuste_dir_sel = "Acréscimo (+)"
                c5, c6 = st.columns(2)
                if tipo_mov == "Compra":
                    c5.text_input("📍 Origem", value="Fornecedor", disabled=True, key=f"mov_orig_lbl_{_mk}")
                    destino_mov = c6.selectbox("📍 Destino", locais, key=f"mov_dest_{_mk}")
                    origem_mov = "Fornecedor"
                elif tipo_mov == "Entrada":
                    origem_mov = c5.selectbox("📍 Origem", locais + ["Devolução de Obra", "Outro"], key=f"mov_orig_{_mk}")
                    destino_mov = c6.selectbox("📍 Destino", locais, key=f"mov_dest_{_mk}")
                elif tipo_mov == "Saída":
                    origem_mov = c5.selectbox("📍 Origem", locais, key=f"mov_orig_{_mk}")
                    destino_mov = c6.selectbox("📍 Destino", locais_saida, key=f"mov_dest_{_mk}")
                elif tipo_mov == "Transferência":
                    origem_mov = c5.selectbox("📍 Origem", locais, key=f"mov_orig_{_mk}")
                    destino_mov = c6.selectbox("📍 Destino", locais, key=f"mov_dest_{_mk}")
                else:  # Correção de Digitação / Acerto de Estoque
                    if tipo_mov == "Correção de Digitação":
                        ajuste_dir_sel = c5.selectbox("📍 Direção", ["Acréscimo (+)", "Desconto (-)"], key=f"mov_dir_{_mk}")
                    else:
                        c5.markdown("&nbsp;")
                    local_ajuste = c6.selectbox("📍 Local", locais, key=f"mov_local_{_mk}")
                    origem_mov = ""
                    destino_mov = local_ajuste

                # Quantidade, Valor Unitário e Observação
                c7, c8, c9 = st.columns(3)
                qtd_mov = c7.number_input(f"📊 Quantidade ({un_auto})", min_value=0.0, step=1.0, format="%.2f", key=f"mov_qtd_{_mk}")
                valor_unit = c8.number_input("💰 Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f", key=f"mov_vunit_{_mk}")
                obs_mov = c9.text_input("📝 Observação (opcional)", key=f"mov_obs_{_mk}")

                valor_total = round(qtd_mov * valor_unit, 2)
                if valor_unit > 0 and qtd_mov > 0:
                    st.info(f"💵 **Valor Total: R$ {valor_total:,.2f}** ({qtd_mov:.2f} {un_auto} × R$ {valor_unit:.2f})")

                # Campos específicos de ajuste (Correção de Digitação / Acerto de Estoque)
                justificativa_mov = ""
                contagem_real_val = 0.0
                _saldo_calc_acerto = 0.0
                if tipo_mov in ("Correção de Digitação", "Acerto de Estoque"):
                    if tipo_mov == "Acerto de Estoque" and material_sel != "--- Selecione ---" and local_ajuste:
                        _df_ae = load("mov")
                        if len(_df_ae) > 0:
                            _dma = _df_ae[_df_ae["Material"] == material_sel]
                            _ae_ent  = _dma[(_dma["Tipo"].isin(["Compra", "Entrada", "Correção de Digitação", "Acerto de Estoque"])) & (_dma["Destino"] == local_ajuste)]["Qtd"].sum()
                            _ae_sai  = _dma[(_dma["Tipo"].isin(["Saída", "Correção de Digitação", "Acerto de Estoque"])) & (_dma["Origem"] == local_ajuste)]["Qtd"].sum()
                            _ae_t_in = _dma[(_dma["Tipo"] == "Transferência") & (_dma["Destino"] == local_ajuste)]["Qtd"].sum()
                            _ae_t_out= _dma[(_dma["Tipo"] == "Transferência") & (_dma["Origem"] == local_ajuste)]["Qtd"].sum()
                            _saldo_calc_acerto = _ae_ent - _ae_sai + _ae_t_in - _ae_t_out
                        st.info(f"📦 Estoque calculado em **{local_ajuste}**: **{_saldo_calc_acerto:.2f} {un_auto}**")
                        contagem_real_val = st.number_input(
                            f"🔢 Contagem Real ({un_auto})", min_value=0.0, step=1.0, format="%.2f", key=f"mov_cont_{_mk}")
                        _dif_acerto = contagem_real_val - _saldo_calc_acerto
                        if contagem_real_val > 0 or _saldo_calc_acerto > 0:
                            _dif_str_ac = f"+{_dif_acerto:.2f}" if _dif_acerto >= 0 else f"{_dif_acerto:.2f}"
                            _icone_ac = "🟢" if _dif_acerto > 0 else ("🔴" if _dif_acerto < 0 else "⚪")
                            st.info(f"{_icone_ac} Diferença apurada: **{_dif_str_ac} {un_auto}**")
                    justificativa_mov = st.text_area("📋 Justificativa (obrigatória)", key=f"mov_just_{_mk}", height=80,
                        placeholder="Ex.: Erro de digitação no lançamento do dia XX/XX | Contagem física realizada em DD/MM/YYYY")

                # Alerta de saldo insuficiente (Saída / Transferência)
                if tipo_mov in ("Saída", "Transferência") and material_sel != "--- Selecione ---" and qtd_mov > 0:
                    _df_chk = load("mov")
                    if len(_df_chk) > 0:
                        _dm = _df_chk[_df_chk["Material"] == material_sel]
                        _ent     = _dm[(_dm["Tipo"].isin(["Compra", "Entrada"])) & (_dm["Destino"] == origem_mov)]["Qtd"].sum()
                        _adj_in  = _dm[(_dm["Tipo"].isin(["Correção de Digitação", "Acerto de Estoque"])) & (_dm["Destino"] == origem_mov)]["Qtd"].sum()
                        _sai     = _dm[(_dm["Tipo"] == "Saída") & (_dm["Origem"] == origem_mov)]["Qtd"].sum()
                        _adj_out = _dm[(_dm["Tipo"].isin(["Correção de Digitação", "Acerto de Estoque"])) & (_dm["Origem"] == origem_mov)]["Qtd"].sum()
                        _t_out   = _dm[(_dm["Tipo"] == "Transferência") & (_dm["Origem"] == origem_mov)]["Qtd"].sum()
                        _t_in    = _dm[(_dm["Tipo"] == "Transferência") & (_dm["Destino"] == origem_mov)]["Qtd"].sum()
                        _saldo_disp = _ent + _adj_in - _sai - _adj_out - _t_out + _t_in
                    else:
                        _saldo_disp = 0.0
                    if qtd_mov > _saldo_disp:
                        st.warning(
                            f"⚠️ **Saldo insuficiente** — Saldo disponível em *{origem_mov}*: "
                            f"**{_saldo_disp:.2f} {un_auto}** — Confirme o Lançamento"
                        )

                st.markdown("")
                b1, b2, b3 = st.columns(3)

                if b1.button("✅ GRAVAR LANÇAMENTO", type="primary", use_container_width=True):
                    _is_ajuste = tipo_mov in ("Correção de Digitação", "Acerto de Estoque")
                    if material_sel == "--- Selecione ---":
                        st.error("Selecione um material.")
                    elif not _is_ajuste and qtd_mov <= 0:
                        st.error("Quantidade deve ser maior que zero.")
                    elif tipo_mov == "Correção de Digitação" and qtd_mov <= 0:
                        st.error("Quantidade deve ser maior que zero.")
                    elif tipo_mov == "Compra" and forn_sel == "--- Selecione ---":
                        st.error("Selecione o fornecedor para registrar uma Compra.")
                    elif _is_ajuste and not justificativa_mov.strip():
                        st.error("Justificativa é obrigatória para Correção de Digitação e Acerto de Estoque.")
                    elif _is_ajuste and not local_ajuste:
                        st.error("Selecione o local para o ajuste.")
                    else:
                        # Calcular valores finais para tipos de ajuste
                        _qtd_final  = qtd_mov
                        _orig_final = origem_mov
                        _dest_final = destino_mov
                        _obs_final  = obs_mov
                        _gravar_ok  = True

                        if tipo_mov == "Correção de Digitação":
                            if ajuste_dir_sel == "Acréscimo (+)":
                                _orig_final = "Ajuste de Estoque"
                                _dest_final = local_ajuste
                            else:
                                _orig_final = local_ajuste
                                _dest_final = "Ajuste de Estoque"
                            _obs_final = f"CORREÇÃO: {justificativa_mov}"

                        elif tipo_mov == "Acerto de Estoque":
                            _df_ae2 = load("mov")
                            if len(_df_ae2) > 0:
                                _dma2 = _df_ae2[_df_ae2["Material"] == material_sel]
                                _ae2_ent  = _dma2[(_dma2["Tipo"].isin(["Compra", "Entrada", "Correção de Digitação", "Acerto de Estoque"])) & (_dma2["Destino"] == local_ajuste)]["Qtd"].sum()
                                _ae2_sai  = _dma2[(_dma2["Tipo"].isin(["Saída", "Correção de Digitação", "Acerto de Estoque"])) & (_dma2["Origem"] == local_ajuste)]["Qtd"].sum()
                                _ae2_t_in = _dma2[(_dma2["Tipo"] == "Transferência") & (_dma2["Destino"] == local_ajuste)]["Qtd"].sum()
                                _ae2_t_out= _dma2[(_dma2["Tipo"] == "Transferência") & (_dma2["Origem"] == local_ajuste)]["Qtd"].sum()
                                _sc2 = _ae2_ent - _ae2_sai + _ae2_t_in - _ae2_t_out
                            else:
                                _sc2 = 0.0
                            _dif2 = contagem_real_val - _sc2
                            if abs(_dif2) < 0.001:
                                st.warning("Nenhuma diferença encontrada — estoque já está correto.")
                                _gravar_ok = False
                            else:
                                _qtd_final = abs(_dif2)
                                if _dif2 > 0:
                                    _orig_final = "Ajuste de Estoque"
                                    _dest_final = local_ajuste
                                else:
                                    _orig_final = local_ajuste
                                    _dest_final = "Ajuste de Estoque"
                                _obs_final = f"ACERTO: {justificativa_mov} | Saldo: {_sc2:.2f} | Contagem: {contagem_real_val:.2f}"

                        if _gravar_ok:
                            novo_dict = {
                                "Data": data_mov.strftime("%Y-%m-%d"),
                                "Tipo": tipo_mov,
                                "Material": material_sel,
                                "Categoria": cat_auto,
                                "Unidade": un_auto,
                                "Origem": _orig_final,
                                "Destino": _dest_final,
                                "Qtd": float(_qtd_final),
                                "Valor_Unit": float(valor_unit) if valor_unit > 0 else None,
                                "Valor_Total": float(round(_qtd_final * valor_unit, 2)) if valor_unit > 0 else None,
                                "Fornecedor": forn_sel if tipo_mov == "Compra" else None,
                                "Data_NF": data_nf_val.strftime("%Y-%m-%d") if tipo_mov == "Compra" and data_nf_val else None,
                                "Num_NF": num_nf_val if tipo_mov == "Compra" else None,
                                "Observacao": _obs_final,
                                "Usuario": st.session_state.usuario_nome
                            }
                            try:
                                _db_rec = _build_db_record(novo_dict, TABLE_CONFIG["mov"])
                                _insert_row("stock_movements", _db_rec)
                            except Exception as _e_grav:
                                st.error(f"❌ Erro ao gravar lançamento: {_e_grav}")
                                st.code(str(_db_rec) if '_db_rec' in dir() else str(novo_dict), language="python")
                                st.stop()
                            _local_ref = local_ajuste or destino_mov
                            st.success(f"✅ {tipo_mov} de {_qtd_final:.2f} {un_auto} de '{material_sel}' em '{_local_ref}' registrado!")
                            st.session_state.mov_form_key = _mk + 1
                            st.rerun()

                if b2.button("❌ Limpar", use_container_width=True):
                    st.session_state.mov_form_key = _mk + 1
                    st.rerun()
                if b3.button("🏠 Voltar ao Painel", use_container_width=True):
                    ir_para("Início")

            # Últimos lançamentos
            df_mov = load("mov")
            if len(df_mov) > 0:
                st.divider()
                st.markdown("**📋 Últimos 15 Lançamentos**")
                _cols_mov_user = [c for c in ["Data", "Tipo", "Material", "Categoria", "Unidade",
                                              "Origem", "Destino", "Qtd", "Valor_Unit", "Valor_Total",
                                              "Fornecedor", "Data_NF", "Num_NF", "Observacao", "Usuario"]
                                  if c in df_mov.columns]
                df_mov_show = fmt_datas(df_mov.tail(15).iloc[::-1][_cols_mov_user])
                st.dataframe(df_mov_show, width='stretch', hide_index=True)

                ent_r = df_mov[df_mov["Tipo"].isin(["Compra", "Entrada"])]["Qtd"].sum()
                sai_r = df_mov[df_mov["Tipo"] == "Saída"]["Qtd"].sum()
                vt_r  = df_mov["Valor_Total"].apply(pd.to_numeric, errors="coerce").sum() if "Valor_Total" in df_mov.columns else 0
                metricas_mov = {
                    "Total Entradas": f"{ent_r:.0f}",
                    "Total Saídas":   f"{sai_r:.0f}",
                    "Saldo Geral":    f"{ent_r - sai_r:.0f}",
                    "Valor Total":    f"R$ {vt_r:,.2f}",
                    "Registros":      str(len(df_mov)),
                }
                if REPORTLAB_OK:
                    pdf_bytes = gerar_pdf_relatorio(
                        "Lançamentos de Movimentação",
                        fmt_datas(cols_mov_user(df_mov.iloc[::-1])).reset_index(drop=True),
                        metricas_mov
                    )
                    st.download_button("🖨️ Exportar PDF — Todos os Lançamentos", pdf_bytes,
                                       file_name="movimentacoes.pdf", mime="application/pdf",
                                       use_container_width=True, key="dl_mov_pdf")
                else:
                    html_mov = gerar_html_relatorio(
                        "Lançamentos de Movimentação",
                        fmt_datas(cols_mov_user(df_mov.iloc[::-1])).reset_index(drop=True),
                        metricas_mov
                    )
                    st.download_button("🖨️ Exportar HTML — Todos os Lançamentos", html_mov,
                                       file_name="movimentacoes.html", mime="text/html",
                                       use_container_width=True, key="dl_mov_html")
                    st.warning("⚠️ Instale `reportlab` para exportar em PDF: `pip install reportlab`")

                # ── CONSULTA RÁPIDA COM FILTROS ──────────────────────────
                st.divider()
                st.markdown("#### 🔍 Consulta Rápida por Tipo / Local / Material")
                with st.container(border=True):
                    _cq1, _cq2, _cq3 = st.columns(3)
                    _locais_cq = sorted(set(
                        df_mov["Origem"].dropna().tolist() +
                        df_mov["Destino"].dropna().tolist()
                    ))
                    _mats_cq = sorted(df_mov["Material"].dropna().unique().tolist())
                    _tipos_fq = ["Todos", "Compra", "Entrada", "Saída", "Transferência", "Correção de Digitação", "Acerto de Estoque"]
                    _fq_tipo  = _cq1.selectbox("📋 Tipo", _tipos_fq, key="fq_tipo")
                    _fq_local = _cq2.selectbox("📍 Local (Origem ou Destino)", ["Todos"] + _locais_cq, key="fq_local")
                    _fq_mat   = _cq3.selectbox("📦 Material", ["Todos"] + _mats_cq, key="fq_mat")

                _df_fq = df_mov.copy()
                if _fq_tipo  != "Todos": _df_fq = _df_fq[_df_fq["Tipo"] == _fq_tipo]
                if _fq_local != "Todos": _df_fq = _df_fq[(_df_fq["Origem"] == _fq_local) | (_df_fq["Destino"] == _fq_local)]
                if _fq_mat   != "Todos": _df_fq = _df_fq[_df_fq["Material"] == _fq_mat]

                _ent_fq = _df_fq[_df_fq["Tipo"].isin(["Compra", "Entrada"])]["Qtd"].sum()
                _sai_fq = _df_fq[_df_fq["Tipo"] == "Saída"]["Qtd"].sum()
                _vt_fq  = _df_fq["Valor_Total"].apply(pd.to_numeric, errors="coerce").sum() if "Valor_Total" in _df_fq.columns else 0

                st.markdown(f"**{len(_df_fq)} registro(s) encontrado(s)**")
                _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                _mc1.metric("Entradas", f"{_ent_fq:.0f}")
                _mc2.metric("Saídas",   f"{_sai_fq:.0f}")
                _mc3.metric("Saldo",    f"{_ent_fq - _sai_fq:.0f}")
                _mc4.metric("Valor Total", f"R$ {_vt_fq:,.2f}")

                _df_fq_show = fmt_datas(cols_mov_user(_df_fq.iloc[::-1]))
                st.dataframe(_df_fq_show, width='stretch', hide_index=True)

                if len(_df_fq) > 0:
                    _titulo_fq = "Lançamentos"
                    if _fq_tipo  != "Todos": _titulo_fq += f" — {_fq_tipo}"
                    if _fq_local != "Todos": _titulo_fq += f" — {_fq_local}"
                    if _fq_mat   != "Todos": _titulo_fq += f" — {_fq_mat}"
                    _met_fq = {
                        "Entradas":    f"{_ent_fq:.0f}",
                        "Saídas":      f"{_sai_fq:.0f}",
                        "Saldo":       f"{_ent_fq - _sai_fq:.0f}",
                        "Valor Total": f"R$ {_vt_fq:,.2f}",
                        "Registros":   str(len(_df_fq)),
                    }
                    if REPORTLAB_OK:
                        st.download_button("🖨️ Exportar PDF — Seleção Filtrada",
                            gerar_pdf_relatorio(_titulo_fq, _df_fq_show.reset_index(drop=True), _met_fq),
                            file_name="lancamentos_filtrado.pdf", mime="application/pdf",
                            use_container_width=True, key="dl_fq_pdf")
                    else:
                        st.download_button("🖨️ Exportar HTML — Seleção Filtrada",
                            gerar_html_relatorio(_titulo_fq, _df_fq_show.reset_index(drop=True), _met_fq),
                            file_name="lancamentos_filtrado.html", mime="text/html",
                            use_container_width=True, key="dl_fq_html")


    # ══════════════════════════════════════════════════════
    #              PÁGINA: RELATÓRIOS
    # ══════════════════════════════════════════════════════
    elif st.session_state.pagina == "Relatórios":
        _tem_acesso_rel = get_permissao(st.session_state.usuario_perfil, "relatorios")
        if not _tem_acesso_rel:
            st.error("⛔ Seu perfil não tem permissão para acessar Relatórios.")
            if st.button("🏠 Voltar ao Painel"): ir_para("Início")
        if _tem_acesso_rel:
            page_header("📜 Relatórios e Consultas")

            df_mov = load("mov")
            df_obras = load("obras")

            if len(df_mov) == 0:
                st.info("Nenhuma movimentação registrada ainda.")
            else:
                OPCOES_PERIODO = ["Todo o período", "Este mês", "Este ano",
                                  "Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Personalizado"]

                tab_geral, tab_obra, tab_cat_r, tab_prod_r, tab_transf = st.tabs([
                    "📊 Geral", "🏗️ Por Obra", "🗂️ Por Categoria", "📦 Por Produto", "🔄 Transferências"
                ])

                # ── TAB: GERAL ─────────────────────────────────────────
                with tab_geral:
                    st.markdown("#### Entradas e Saídas — Visão Geral")
                    with st.container(border=True):
                        st.markdown("**🔍 Filtros**")
                        rg1, rg2, rg3 = st.columns(3)
                        fg_tipo = rg1.selectbox("Tipo", ["Todos", "Compra", "Entrada", "Saída"], key="fg_tipo")
                        fg_periodo = rg2.selectbox("Período", OPCOES_PERIODO, key="fg_periodo")
                        cats_g = ["Todos"] + sorted(df_mov["Categoria"].dropna().unique().tolist()) if "Categoria" in df_mov.columns else ["Todos"]
                        fg_cat = rg3.selectbox("Categoria", cats_g, key="fg_cat")
                        fg_ini = fg_fim = None
                        if fg_periodo == "Personalizado":
                            rgp1, rgp2 = st.columns(2)
                            fg_ini = rgp1.date_input("Data inicial", value=None, format="DD/MM/YYYY", key="fg_ini")
                            fg_fim = rgp2.date_input("Data final", value=None, format="DD/MM/YYYY", key="fg_fim")

                    df_g = df_mov[df_mov["Tipo"].isin(["Compra", "Entrada", "Saída"])].copy()
                    if fg_tipo != "Todos":
                        df_g = df_g[df_g["Tipo"] == fg_tipo]
                    if fg_cat != "Todos" and "Categoria" in df_g.columns:
                        df_g = df_g[df_g["Categoria"] == fg_cat]
                    df_g = aplicar_filtro_periodo(df_g, "Data", fg_periodo, fg_ini, fg_fim)

                    ent_g = df_g[df_g["Tipo"].isin(["Compra", "Entrada"])]["Qtd"].sum()
                    sai_g = df_g[df_g["Tipo"] == "Saída"]["Qtd"].sum()
                    vt_g = df_g["Valor_Total"].apply(pd.to_numeric, errors="coerce").sum() if "Valor_Total" in df_g.columns else 0

                    st.markdown(f"**{len(df_g)} registro(s) encontrado(s)**")
                    mg1, mg2, mg3, mg4 = st.columns(4)
                    mg1.metric("Entradas", f"{ent_g:.0f}")
                    mg2.metric("Saídas", f"{sai_g:.0f}")
                    mg3.metric("Saldo", f"{ent_g - sai_g:.0f}")
                    mg4.metric("💰 Valor Total", f"R$ {vt_g:,.2f}")

                    df_g_show = fmt_datas(cols_mov_user(df_g.iloc[::-1]))
                    st.dataframe(df_g_show, width='stretch', hide_index=True)

                    if len(df_g) > 0:
                        st.divider()
                        st.markdown("**📊 Resumo por Material**")
                        resumo_g = df_g.groupby(["Material", "Tipo"])["Qtd"].sum().unstack(fill_value=0)
                        for _c in ["Compra", "Entrada", "Saída"]:
                            if _c not in resumo_g.columns:
                                resumo_g[_c] = 0
                        resumo_g["Total Entradas"] = resumo_g["Compra"] + resumo_g["Entrada"]
                        resumo_g["Saldo"] = resumo_g["Total Entradas"] - resumo_g["Saída"]
                        st.dataframe(resumo_g, width='stretch')
                        _met_g = {"Entradas": f"{ent_g:.0f}", "Saídas": f"{sai_g:.0f}",
                                  "Saldo": f"{ent_g - sai_g:.0f}", "Valor Total": f"R$ {vt_g:,.2f}"}
                        if REPORTLAB_OK:
                            st.download_button("🖨️ Exportar PDF", gerar_pdf_relatorio(
                                "Relatório Geral — Entradas e Saídas", df_g_show, _met_g),
                                file_name="relatorio_geral.pdf", mime="application/pdf",
                                use_container_width=True, key="dl_geral")
                        else:
                            st.download_button("🖨️ Imprimir / Exportar HTML", gerar_html_relatorio(
                                "Relatório Geral — Entradas e Saídas", df_g_show, _met_g),
                                file_name="relatorio_geral.html", mime="text/html",
                                use_container_width=True, key="dl_geral")

                # ── TAB: POR OBRA ───────────────────────────────────────
                with tab_obra:
                    st.markdown("#### Movimentações por Obra")
                    obras_list_r = sorted(df_obras["Nome_Obra"].dropna().unique().tolist()) if len(df_obras) > 0 else []
                    with st.container(border=True):
                        st.markdown("**🔍 Filtros**")
                        ro1, ro2, ro3, ro4 = st.columns(4)
                        fo_obra = ro1.selectbox("Obra", ["Todas"] + obras_list_r, key="fo_obra")
                        fo_tipo = ro2.selectbox("Tipo", ["Todos", "Compra", "Entrada", "Saída", "Transferência"], key="fo_tipo")
                        fo_periodo = ro3.selectbox("Período", OPCOES_PERIODO, key="fo_periodo")
                        cats_o = ["Todos"] + sorted(df_mov["Categoria"].dropna().unique().tolist()) if "Categoria" in df_mov.columns else ["Todos"]
                        fo_cat = ro4.selectbox("Categoria", cats_o, key="fo_cat")
                        fo_ini = fo_fim = None
                        if fo_periodo == "Personalizado":
                            rop1, rop2 = st.columns(2)
                            fo_ini = rop1.date_input("Data inicial", value=None, format="DD/MM/YYYY", key="fo_ini")
                            fo_fim = rop2.date_input("Data final", value=None, format="DD/MM/YYYY", key="fo_fim")

                    df_o = df_mov.copy()
                    if fo_obra != "Todas":
                        df_o = df_o[(df_o["Origem"] == fo_obra) | (df_o["Destino"] == fo_obra)]
                    if fo_tipo != "Todos":
                        df_o = df_o[df_o["Tipo"] == fo_tipo]
                    if fo_cat != "Todos" and "Categoria" in df_o.columns:
                        df_o = df_o[df_o["Categoria"] == fo_cat]
                    df_o = aplicar_filtro_periodo(df_o, "Data", fo_periodo, fo_ini, fo_fim)

                    ent_o = df_o[df_o["Tipo"].isin(["Compra", "Entrada"])]["Qtd"].sum()
                    sai_o = df_o[df_o["Tipo"] == "Saída"]["Qtd"].sum()

                    st.markdown(f"**{len(df_o)} registro(s) encontrado(s)**")
                    mo1, mo2, mo3 = st.columns(3)
                    mo1.metric("Entradas", f"{ent_o:.0f}")
                    mo2.metric("Saídas", f"{sai_o:.0f}")
                    mo3.metric("Saldo", f"{ent_o - sai_o:.0f}")

                    df_o_show = fmt_datas(cols_mov_user(df_o.iloc[::-1]))
                    st.dataframe(df_o_show, width='stretch', hide_index=True)

                    if len(df_o) > 0:
                        st.divider()
                        st.markdown("**📊 Resumo por Obra**")
                        _obras_loop = obras_list_r if fo_obra == "Todas" else [fo_obra]
                        resumo_obras = []
                        for _ob in _obras_loop:
                            _ent = df_o[(df_o["Tipo"].isin(["Compra", "Entrada"])) & (df_o["Destino"] == _ob)]["Qtd"].sum()
                            _sai = df_o[(df_o["Tipo"] == "Saída") & (df_o["Origem"] == _ob)]["Qtd"].sum()
                            if _ent > 0 or _sai > 0:
                                resumo_obras.append({"Obra": _ob, "Entradas": _ent, "Saídas": _sai, "Saldo": _ent - _sai})
                        if resumo_obras:
                            st.dataframe(pd.DataFrame(resumo_obras), width='stretch', hide_index=True)
                        _met_o = {"Entradas": f"{ent_o:.0f}", "Saídas": f"{sai_o:.0f}", "Saldo": f"{ent_o - sai_o:.0f}"}
                        if REPORTLAB_OK:
                            st.download_button("🖨️ Exportar PDF", gerar_pdf_relatorio(
                                f"Relatório por Obra — {fo_obra}", df_o_show, _met_o),
                                file_name="relatorio_por_obra.pdf", mime="application/pdf",
                                use_container_width=True, key="dl_obra")
                        else:
                            st.download_button("🖨️ Imprimir / Exportar HTML", gerar_html_relatorio(
                                f"Relatório por Obra — {fo_obra}", df_o_show, _met_o),
                                file_name="relatorio_por_obra.html", mime="text/html",
                                use_container_width=True, key="dl_obra")

                # ── TAB: POR CATEGORIA ──────────────────────────────────
                with tab_cat_r:
                    st.markdown("#### Movimentações por Categoria")
                    with st.container(border=True):
                        st.markdown("**🔍 Filtros**")
                        rc1, rc2, rc3, rc4 = st.columns(4)
                        obras_c = ["Todas"] + sorted(df_obras["Nome_Obra"].dropna().unique().tolist()) if len(df_obras) > 0 else ["Todas"]
                        fc_obra = rc1.selectbox("Obra", obras_c, key="fc_obra")
                        cats_c = ["Todas"] + sorted(df_mov["Categoria"].dropna().unique().tolist()) if "Categoria" in df_mov.columns else ["Todas"]
                        fc_cat = rc2.selectbox("Categoria", cats_c, key="fc_cat")
                        fc_tipo = rc3.selectbox("Tipo", ["Todos", "Compra", "Entrada", "Saída"], key="fc_tipo")
                        fc_periodo = rc4.selectbox("Período", OPCOES_PERIODO, key="fc_periodo")
                        fc_ini = fc_fim = None
                        if fc_periodo == "Personalizado":
                            rcp1, rcp2 = st.columns(2)
                            fc_ini = rcp1.date_input("Data inicial", value=None, format="DD/MM/YYYY", key="fc_ini")
                            fc_fim = rcp2.date_input("Data final", value=None, format="DD/MM/YYYY", key="fc_fim")

                    df_c = df_mov.copy()
                    if fc_obra != "Todas":
                        df_c = df_c[(df_c["Origem"] == fc_obra) | (df_c["Destino"] == fc_obra)]
                    if fc_cat != "Todas" and "Categoria" in df_c.columns:
                        df_c = df_c[df_c["Categoria"] == fc_cat]
                    if fc_tipo != "Todos":
                        df_c = df_c[df_c["Tipo"] == fc_tipo]
                    df_c = aplicar_filtro_periodo(df_c, "Data", fc_periodo, fc_ini, fc_fim)

                    st.markdown(f"**{len(df_c)} registro(s) encontrado(s)**")
                    df_c_show = fmt_datas(cols_mov_user(df_c.iloc[::-1]))
                    st.dataframe(df_c_show, width='stretch', hide_index=True)

                    if len(df_c) > 0:
                        st.divider()
                        st.markdown("**📊 Resumo por Categoria**")
                        resumo_cat = df_c.groupby("Categoria").agg(
                            Lancamentos=("Qtd", "count"),
                            Qtd_Total=("Qtd", "sum")
                        ).sort_values("Qtd_Total", ascending=False)
                        if "Valor_Total" in df_c.columns:
                            resumo_cat["Valor_Total"] = df_c.groupby("Categoria")["Valor_Total"].apply(
                                lambda x: pd.to_numeric(x, errors="coerce").sum()
                            )
                        st.dataframe(resumo_cat, width='stretch')
                        if REPORTLAB_OK:
                            st.download_button("🖨️ Exportar PDF", gerar_pdf_relatorio(
                                f"Relatório por Categoria — {fc_cat}", df_c_show),
                                file_name="relatorio_por_categoria.pdf", mime="application/pdf",
                                use_container_width=True, key="dl_cat")
                        else:
                            st.download_button("🖨️ Imprimir / Exportar HTML", gerar_html_relatorio(
                                f"Relatório por Categoria — {fc_cat}", df_c_show),
                                file_name="relatorio_por_categoria.html", mime="text/html",
                                use_container_width=True, key="dl_cat")

                # ── TAB: POR PRODUTO ────────────────────────────────────
                with tab_prod_r:
                    st.markdown("#### Movimentações por Produto / Item")
                    with st.container(border=True):
                        st.markdown("**🔍 Filtros**")
                        rp1, rp2, rp3 = st.columns(3)
                        prods_p = ["Todos"] + sorted(df_mov["Material"].dropna().unique().tolist())
                        fp_prod = rp1.selectbox("Produto / Material", prods_p, key="fp_prod")
                        obras_p = ["Todas"] + sorted(df_obras["Nome_Obra"].dropna().unique().tolist()) if len(df_obras) > 0 else ["Todas"]
                        fp_obra = rp2.selectbox("Obra", obras_p, key="fp_obra")
                        fp_periodo = rp3.selectbox("Período", OPCOES_PERIODO, key="fp_periodo")
                        fp_ini = fp_fim = None
                        if fp_periodo == "Personalizado":
                            rpp1, rpp2 = st.columns(2)
                            fp_ini = rpp1.date_input("Data inicial", value=None, format="DD/MM/YYYY", key="fp_ini")
                            fp_fim = rpp2.date_input("Data final", value=None, format="DD/MM/YYYY", key="fp_fim")

                    df_p = df_mov.copy()
                    if fp_prod != "Todos":
                        df_p = df_p[df_p["Material"] == fp_prod]
                    if fp_obra != "Todas":
                        df_p = df_p[(df_p["Origem"] == fp_obra) | (df_p["Destino"] == fp_obra)]
                    df_p = aplicar_filtro_periodo(df_p, "Data", fp_periodo, fp_ini, fp_fim)

                    ent_p = df_p[df_p["Tipo"].isin(["Compra", "Entrada"])]["Qtd"].sum()
                    sai_p = df_p[df_p["Tipo"] == "Saída"]["Qtd"].sum()
                    vt_p = df_p["Valor_Total"].apply(pd.to_numeric, errors="coerce").sum() if "Valor_Total" in df_p.columns else 0

                    st.markdown(f"**{len(df_p)} registro(s) encontrado(s)**")
                    mp1, mp2, mp3, mp4 = st.columns(4)
                    mp1.metric("Entradas", f"{ent_p:.0f}")
                    mp2.metric("Saídas", f"{sai_p:.0f}")
                    mp3.metric("Saldo", f"{ent_p - sai_p:.0f}")
                    mp4.metric("💰 Valor Total", f"R$ {vt_p:,.2f}")

                    df_p_show = fmt_datas(cols_mov_user(df_p.iloc[::-1]))
                    st.dataframe(df_p_show, width='stretch', hide_index=True)

                    if len(df_p) > 0:
                        st.divider()
                        st.markdown("**📊 Resumo por Produto**")
                        resumo_p = df_p.groupby(["Material", "Tipo"])["Qtd"].sum().unstack(fill_value=0)
                        for _c in ["Compra", "Entrada", "Saída"]:
                            if _c not in resumo_p.columns:
                                resumo_p[_c] = 0
                        resumo_p["Total Entradas"] = resumo_p["Compra"] + resumo_p["Entrada"]
                        resumo_p["Saldo"] = resumo_p["Total Entradas"] - resumo_p["Saída"]
                        st.dataframe(resumo_p, width='stretch')
                        _met_p = {"Entradas": f"{ent_p:.0f}", "Saídas": f"{sai_p:.0f}",
                                  "Saldo": f"{ent_p - sai_p:.0f}", "Valor Total": f"R$ {vt_p:,.2f}"}
                        if REPORTLAB_OK:
                            st.download_button("🖨️ Exportar PDF", gerar_pdf_relatorio(
                                f"Relatório por Produto — {fp_prod}", df_p_show, _met_p),
                                file_name="relatorio_por_produto.pdf", mime="application/pdf",
                                use_container_width=True, key="dl_prod")
                        else:
                            st.download_button("🖨️ Imprimir / Exportar HTML", gerar_html_relatorio(
                                f"Relatório por Produto — {fp_prod}", df_p_show, _met_p),
                                file_name="relatorio_por_produto.html", mime="text/html",
                                use_container_width=True, key="dl_prod")

                # ── TAB: TRANSFERÊNCIAS ─────────────────────────────────
                with tab_transf:
                    st.markdown("#### Transferências entre Locais")
                    with st.container(border=True):
                        st.markdown("**🔍 Filtros**")
                        rt1, rt2, rt3, rt4 = st.columns(4)
                        _locs_t = sorted(set(
                            df_mov["Origem"].dropna().unique().tolist() +
                            df_mov["Destino"].dropna().unique().tolist()
                        ))
                        ft_origem = rt1.selectbox("Origem", ["Todos"] + _locs_t, key="ft_origem")
                        ft_destino = rt2.selectbox("Destino", ["Todos"] + _locs_t, key="ft_destino")
                        mats_t = ["Todos"] + sorted(df_mov["Material"].dropna().unique().tolist())
                        ft_mat = rt3.selectbox("Material", mats_t, key="ft_mat")
                        ft_periodo = rt4.selectbox("Período", OPCOES_PERIODO, key="ft_periodo")
                        ft_ini = ft_fim = None
                        if ft_periodo == "Personalizado":
                            rtp1, rtp2 = st.columns(2)
                            ft_ini = rtp1.date_input("Data inicial", value=None, format="DD/MM/YYYY", key="ft_ini")
                            ft_fim = rtp2.date_input("Data final", value=None, format="DD/MM/YYYY", key="ft_fim")

                    df_t = df_mov[df_mov["Tipo"] == "Transferência"].copy()
                    if ft_origem != "Todos":
                        df_t = df_t[df_t["Origem"] == ft_origem]
                    if ft_destino != "Todos":
                        df_t = df_t[df_t["Destino"] == ft_destino]
                    if ft_mat != "Todos":
                        df_t = df_t[df_t["Material"] == ft_mat]
                    df_t = aplicar_filtro_periodo(df_t, "Data", ft_periodo, ft_ini, ft_fim)

                    qtd_t = df_t["Qtd"].sum() if len(df_t) > 0 else 0
                    st.markdown(f"**{len(df_t)} transferência(s) encontrada(s)**")
                    mt1, mt2 = st.columns(2)
                    mt1.metric("Qtd Total Transferida", f"{qtd_t:.0f}")
                    mt2.metric("Registros", len(df_t))

                    df_t_show = fmt_datas(cols_mov_user(df_t.iloc[::-1]))
                    st.dataframe(df_t_show, width='stretch', hide_index=True)

                    if len(df_t) > 0:
                        st.divider()
                        st.markdown("**📊 Resumo por Origem → Destino**")
                        resumo_t = df_t.groupby(["Origem", "Destino"])["Qtd"].sum().reset_index()
                        resumo_t.columns = ["Origem", "Destino", "Qtd Total"]
                        st.dataframe(resumo_t, width='stretch', hide_index=True)
                        _met_t = {"Qtd Total": f"{qtd_t:.0f}", "Registros": str(len(df_t))}
                        if REPORTLAB_OK:
                            st.download_button("🖨️ Exportar PDF", gerar_pdf_relatorio(
                                "Relatório de Transferências", df_t_show, _met_t),
                                file_name="relatorio_transferencias.pdf", mime="application/pdf",
                                use_container_width=True, key="dl_transf")
                        else:
                            st.download_button("🖨️ Imprimir / Exportar HTML", gerar_html_relatorio(
                                "Relatório de Transferências", df_t_show, _met_t),
                                file_name="relatorio_transferencias.html", mime="text/html",
                                use_container_width=True, key="dl_transf")

            st.markdown("")
            if st.button("🏠 Voltar ao Painel", use_container_width=True):
                ir_para("Início")


    # ══════════════════════════════════════════════════════
    #              PÁGINA: ESTOQUE ATUAL
    # ══════════════════════════════════════════════════════
    elif st.session_state.pagina == "Estoque":
        page_header("📦 Posição de Estoque Atual")

        df_mov = load("mov")
        df_prod = load("prod")

        # CSS para labels dos filtros — injetado sempre que a página Estoque é carregada
        st.markdown("""<style>
div[data-testid="stHorizontalBlock"] div[data-testid="stSelectbox"] > label,
div[data-testid="stHorizontalBlock"] div[data-testid="stDateInput"] > label {
    background-color: #00527C !important;
    color: white !important;
    padding: 5px 10px !important;
    border-radius: 5px !important;
    display: block !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    margin-bottom: 2px !important;
    width: 100% !important;
    box-sizing: border-box !important;
}
</style>""", unsafe_allow_html=True)

        if len(df_mov) == 0:
            st.info("Nenhuma movimentação registrada. O estoque está vazio.")
        else:
            # --- Filtro de período (aplicado nas movimentações antes do cálculo) ---
            col_dp1, col_dp2, col_dp3 = st.columns([1.5, 1, 1])
            with col_dp1:
                opcao_data = st.selectbox("🗓️ Filtrar por Período",
                    ["Todo o período", "Hoje", "Entre datas"], key="est_opcao_data")
            data_ini_est = data_fim_est = None
            if opcao_data == "Entre datas":
                with col_dp2:
                    data_ini_est = st.date_input("📅 Data inicial", key="est_data_ini",
                                                 value=datetime.today().date(), format="DD/MM/YYYY")
                with col_dp3:
                    data_fim_est = st.date_input("📅 Data final", key="est_data_fim",
                                                 value=datetime.today().date(), format="DD/MM/YYYY")

            # Aplicar filtro de data nas movimentações
            df_mov_fil = df_mov.copy()
            df_mov_fil["Data"] = pd.to_datetime(df_mov_fil["Data"], errors="coerce")
            if opcao_data == "Hoje":
                hoje = datetime.today().date()
                df_mov_fil = df_mov_fil[df_mov_fil["Data"].dt.date == hoje]
            elif opcao_data == "Entre datas" and data_ini_est and data_fim_est:
                df_mov_fil = df_mov_fil[
                    (df_mov_fil["Data"].dt.date >= data_ini_est) &
                    (df_mov_fil["Data"].dt.date <= data_fim_est)
                ]

            if len(df_mov_fil) == 0:
                st.info("Nenhuma movimentação encontrada para o período selecionado.")
            else:
                st.divider()
                # Calcular saldo por material e destino/origem
                _tipos_ent_est = ["Entrada", "Correção de Digitação", "Acerto de Estoque"]
                entradas = df_mov_fil[df_mov_fil["Tipo"].isin(_tipos_ent_est)].groupby(["Material", "Destino"])["Qtd"].sum().reset_index()
                entradas.columns = ["Material", "Local", "Entrada"]

                _tipos_sai_est = ["Saída", "Correção de Digitação", "Acerto de Estoque"]
                saidas = df_mov_fil[df_mov_fil["Tipo"].isin(_tipos_sai_est)].groupby(["Material", "Origem"])["Qtd"].sum().reset_index()
                saidas.columns = ["Material", "Local", "Saída"]

                estoque = pd.merge(entradas, saidas, on=["Material", "Local"], how="outer").fillna(0)
                estoque["Saldo"] = estoque["Entrada"] - estoque["Saída"]
                # Remove local fictício usado internamente para registros de ajuste
                estoque = estoque[estoque["Local"] != "Ajuste de Estoque"]

                # Adicionar categoria e unidade
                if len(df_prod) > 0:
                    prod_info = df_prod[["Material", "Categoria", "Unidade"]].drop_duplicates()
                    estoque = pd.merge(estoque, prod_info, on="Material", how="left")

                # Filtros em linha
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    locais = ["Todos"] + sorted(estoque["Local"].dropna().unique().tolist())
                    filtro_local = st.selectbox("📍 Filtrar por Local", locais)
                with col_f2:
                    df_mat_opts = estoque.copy()
                    if filtro_local != "Todos":
                        df_mat_opts = df_mat_opts[df_mat_opts["Local"] == filtro_local]
                    mats = ["Todos"] + sorted(df_mat_opts["Material"].dropna().unique().tolist())
                    filtro_mat = st.selectbox("🔩 Filtrar por Material", mats)
                with col_f3:
                    df_cat_opts = estoque.copy()
                    if filtro_local != "Todos":
                        df_cat_opts = df_cat_opts[df_cat_opts["Local"] == filtro_local]
                    if filtro_mat != "Todos":
                        df_cat_opts = df_cat_opts[df_cat_opts["Material"] == filtro_mat]
                    cats = ["Todas"]
                    if "Categoria" in df_cat_opts.columns:
                        cats += sorted(df_cat_opts["Categoria"].dropna().unique().tolist())
                    filtro_cat = st.selectbox("🏷️ Filtrar por Categoria", cats)

                # Aplicar filtros
                estoque_filtrado = estoque.copy()
                if filtro_local != "Todos":
                    estoque_filtrado = estoque_filtrado[estoque_filtrado["Local"] == filtro_local]
                if filtro_cat != "Todas" and "Categoria" in estoque_filtrado.columns:
                    estoque_filtrado = estoque_filtrado[estoque_filtrado["Categoria"] == filtro_cat]
                if filtro_mat != "Todos":
                    estoque_filtrado = estoque_filtrado[estoque_filtrado["Material"] == filtro_mat]

                # Mostrar apenas itens com saldo > 0
                estoque_pos = estoque_filtrado[estoque_filtrado["Saldo"] > 0].sort_values(["Local", "Material"])

                if len(estoque_pos) > 0:
                    st.markdown(f"**{len(estoque_pos)} item(ns) em estoque**")
                    cols_show = ["Material", "Local", "Entrada", "Saída", "Saldo"]
                    if "Categoria" in estoque_pos.columns:
                        cols_show = ["Material", "Categoria", "Unidade", "Local", "Entrada", "Saída", "Saldo"]
                    st.dataframe(estoque_pos[cols_show], width='stretch', hide_index=True)

                    # Resumo geral por material (respeitando filtros)
                    st.divider()
                    st.markdown("**📊 Resumo Geral (todos os locais)**")
                    resumo_geral = estoque_filtrado.groupby("Material")[["Entrada", "Saída", "Saldo"]].sum().sort_values("Saldo", ascending=False)
                    st.dataframe(resumo_geral, width='stretch')

                    # Título do relatório com filtros aplicados
                    filtros_desc = []
                    if opcao_data == "Hoje":
                        filtros_desc.append(f"Data: {datetime.today().strftime('%d/%m/%Y')}")
                    elif opcao_data == "Entre datas" and data_ini_est and data_fim_est:
                        filtros_desc.append(f"Período: {data_ini_est.strftime('%d/%m/%Y')} a {data_fim_est.strftime('%d/%m/%Y')}")
                    if filtro_local != "Todos": filtros_desc.append(f"Local: {filtro_local}")
                    if filtro_cat != "Todas":   filtros_desc.append(f"Categoria: {filtro_cat}")
                    if filtro_mat != "Todos":   filtros_desc.append(f"Material: {filtro_mat}")
                    titulo_rel = "Posição de Estoque" + (f" — {', '.join(filtros_desc)}" if filtros_desc else " — Geral")
                    metricas_rel = {"Itens em estoque": str(len(estoque_pos))}

                    if REPORTLAB_OK:
                        pdf_bytes = gerar_pdf_relatorio(
                            titulo_rel,
                            estoque_pos[cols_show].reset_index(drop=True),
                            metricas_rel
                        )
                        st.download_button("🖨️ Exportar PDF", pdf_bytes,
                                           file_name="estoque_atual.pdf", mime="application/pdf",
                                           use_container_width=True, key="dl_estoque")
                    else:
                        html_est = gerar_html_relatorio(titulo_rel, estoque_pos[cols_show].reset_index(drop=True), metricas_rel)
                        st.download_button("🖨️ Exportar HTML", html_est,
                                           file_name="estoque_atual.html", mime="text/html",
                                           use_container_width=True, key="dl_estoque")
                        st.warning("⚠️ Instale `reportlab` para exportar em PDF: `pip install reportlab`")
                else:
                    st.info("Nenhum item com saldo positivo no período/filtros selecionados.")

        st.markdown("")
        if st.button("🏠 Voltar ao Painel", use_container_width=True):
            ir_para("Início")


    # ══════════════════════════════════════════════════════
    #              PÁGINA: GESTÃO DE USUÁRIOS (ADMIN)
    # ══════════════════════════════════════════════════════
    elif st.session_state.pagina == "Usuarios":
        if not get_permissao(st.session_state.usuario_perfil, "usuarios"):
            st.error("⛔ Acesso restrito a administradores.")
        else:
            page_header("👥 Gestão de Usuários")

            df_users = load_usuarios()

            # --- Cadastro de novo usuário ---
            with st.container(border=True):
                st.markdown("**➕ Novo Usuário**")
                cu1, cu2 = st.columns(2)
                novo_usuario = cu1.text_input("Login do usuário", placeholder="ex: joao.silva")
                novo_nome = cu2.text_input("Nome completo", placeholder="ex: João da Silva")

                cu3, cu4 = st.columns(2)
                perfis_disp = list(PERFIS.keys())
                perfil_labels = [f"{p} — {PERFIS[p]['descricao'].split('—')[1].strip()}" for p in perfis_disp]
                novo_perfil = cu3.selectbox("Perfil", perfis_disp, format_func=lambda p: f"{p} — {PERFIS[p]['descricao'].split('—')[1].strip()}")
                nova_senha = cu4.text_input("Senha", type="password", placeholder="Mínimo 4 caracteres")

                b1, b2, b3 = st.columns(3)
                if b1.button("✅ Criar Usuário", type="primary", use_container_width=True):
                    if not novo_usuario or not novo_nome or not nova_senha:
                        st.warning("Preencha todos os campos.")
                    elif len(nova_senha) < 4:
                        st.warning("A senha deve ter no mínimo 4 caracteres.")
                    elif novo_usuario.lower().strip() in df_users["usuario"].values:
                        st.error(f"❌ O usuário '{novo_usuario}' já existe.")
                    else:
                        novo_reg = pd.DataFrame([{
                            "usuario": novo_usuario.lower().strip(),
                            "senha_hash": hashlib.sha256(nova_senha.encode()).hexdigest(),
                            "nome": novo_nome.strip(),
                            "perfil": novo_perfil,
                            "ativo": True
                        }])
                        save_usuarios(pd.concat([df_users, novo_reg], ignore_index=True))
                        st.success(f"✅ Usuário '{novo_usuario}' criado com sucesso!")
                        st.rerun()
                if b2.button("❌ Cancelar", use_container_width=True):
                    st.rerun()
                if b3.button("🏠 Voltar ao Painel", use_container_width=True):
                    ir_para("Início")

            # --- Lista de usuários ---
            st.divider()
            st.markdown(f"**{len(df_users)} usuário(s) cadastrado(s)**")
            df_exibir = df_users[["usuario", "nome", "perfil", "ativo"]].copy()
            df_exibir["ativo"] = df_exibir["ativo"].apply(lambda x: "✅ Sim" if x else "❌ Não")
            st.dataframe(df_exibir, width='stretch', hide_index=True)

            # --- Ações: Resetar senha / Ativar-Desativar ---
            st.divider()
            col_act1, col_act2 = st.columns(2)

            with col_act1:
                with st.expander("🔑 Resetar Senha"):
                    usr_reset = st.selectbox("Selecione o usuário:", df_users["usuario"].values, key="reset_usr")
                    nova_senha_reset = st.text_input("Nova senha", type="password", key="reset_pwd", placeholder="Nova senha")
                    if st.button("Resetar Senha", type="primary", use_container_width=True):
                        if nova_senha_reset and len(nova_senha_reset) >= 4:
                            df_users.loc[df_users["usuario"] == usr_reset, "senha_hash"] = hashlib.sha256(nova_senha_reset.encode()).hexdigest()
                            save_usuarios(df_users)
                            st.success(f"✅ Senha de '{usr_reset}' alterada!")
                            st.rerun()
                        else:
                            st.warning("Senha deve ter no mínimo 4 caracteres.")

            with col_act2:
                with st.expander("🔄 Ativar / Desativar Usuário"):
                    usr_toggle = st.selectbox("Selecione o usuário:", df_users["usuario"].values, key="toggle_usr")
                    status_atual = df_users.loc[df_users["usuario"] == usr_toggle, "ativo"].values[0]
                    st.info(f"Status atual: {'✅ Ativo' if status_atual else '❌ Inativo'}")
                    novo_status = "Desativar" if status_atual else "Ativar"
                    if st.button(f"{novo_status} Usuário", type="primary", use_container_width=True):
                        if usr_toggle == st.session_state.usuario_login:
                            st.error("Você não pode desativar seu próprio usuário.")
                        else:
                            df_users.loc[df_users["usuario"] == usr_toggle, "ativo"] = not status_atual
                            save_usuarios(df_users)
                            st.success(f"✅ Usuário '{usr_toggle}' {'ativado' if not status_atual else 'desativado'}!")
                            st.rerun()


    # ══════════════════════════════════════════════════════
    #         PÁGINA: LOCAÇÃO DE EQUIPAMENTOS
    # ══════════════════════════════════════════════════════
    elif st.session_state.pagina == "Locacoes":
        _tem_acesso_loc = get_permissao(st.session_state.usuario_perfil, "locacoes")
        if not _tem_acesso_loc:
            st.error("⛔ Seu perfil não tem permissão para acessar Locações.")
            if st.button("🏠 Voltar ao Painel"): ir_para("Início")
        if _tem_acesso_loc:
            page_header("🏗️ Controle de Locação de Equipamentos")

            df_loc = load("loc")
            df_obras = load("obras")

            # --- Abas: Novo Lançamento / Consulta / Vencimentos ---
            aba_nova, aba_consulta, aba_venc = st.tabs(["➕ Nova Locação", "📋 Consultar Locações", "⏰ Controle de Vencimentos"])

            # ---- ABA 1: NOVA LOCAÇÃO ----
            with aba_nova:
                # Dialogs de cadastro rápido para Locações
                @st.dialog("➕ Novo Equipamento")
                def dialog_novo_equip():
                    novo_eq = st.text_input("Nome do Equipamento")
                    if st.button("✅ Salvar", type="primary", use_container_width=True, key="sv_eq"):
                        if novo_eq:
                            df = load("equip")
                            save(_concat_safe([df, pd.DataFrame([{"Nome_Equipamento": novo_eq.strip().upper()}])]), "equip")
                            st.success(f"✅ '{novo_eq.upper()}' cadastrado!")
                            st.rerun()

                @st.dialog("➕ Novo Fornecedor")
                def dialog_novo_forn_loc():
                    fn = st.text_input("Nome / Razão Social")
                    fc1, fc2 = st.columns(2)
                    cnpj = fc1.text_input("CNPJ")
                    tel = fc2.text_input("Telefone")
                    contato = st.text_input("Pessoa de Contato")
                    if st.button("✅ Salvar", type="primary", use_container_width=True, key="sv_fn"):
                        if fn:
                            df = load("forn")
                            save(_concat_safe([df, pd.DataFrame([{"Nome_Fornecedor": fn.strip().upper(), "CNPJ": cnpj, "Telefone": tel, "Contato": contato}])]), "forn")
                            st.success(f"✅ '{fn.upper()}' cadastrado!")
                            st.rerun()

                @st.dialog("➕ Nova Obra")
                def dialog_nova_obra_loc():
                    ob = st.text_input("Nome da Obra")
                    if st.button("✅ Salvar", type="primary", use_container_width=True, key="sv_ob"):
                        if ob:
                            df = load("obras")
                            save(_concat_safe([df, pd.DataFrame([{"Nome_Obra": ob.strip().upper()}])]), "obras")
                            st.success(f"✅ '{ob.upper()}' cadastrada!")
                            st.rerun()

                with st.container(border=True):
                    st.markdown("**Registrar Nova Locação**")

                    # Carregar cadastros
                    df_equip = load("equip")
                    df_forn = load("forn")
                    equip_list = sorted(df_equip["Nome_Equipamento"].dropna().unique()) if len(df_equip) > 0 else []
                    forn_list = sorted(df_forn["Nome_Fornecedor"].dropna().unique()) if len(df_forn) > 0 else []
                    obras_list = sorted(df_obras["Nome_Obra"].dropna().unique()) if len(df_obras) > 0 else []

                    lc1, lc2 = st.columns(2)
                    loc_descricao = lc1.selectbox("📦 Equipamento", ["--- Selecione ---"] + equip_list)
                    loc_qtd = lc2.number_input("Qtd", min_value=1, value=1, step=1)

                    lc3, lc4 = st.columns(2)
                    loc_valor = lc3.number_input("💰 Valor Mensal (R$)", min_value=0.0, step=10.0, format="%.2f")
                    loc_fornecedor = lc4.selectbox("🏢 Fornecedor", ["--- Selecione ---"] + forn_list)

                    lc5, lc6 = st.columns(2)
                    loc_contrato = lc5.text_input("📄 Nº Contrato")
                    loc_obra = lc6.selectbox("🏗️ Obra", ["--- Selecione ---"] + obras_list)

                    # Cadastro rápido
                    st.caption("Não encontrou? Cadastre rapidamente:")
                    qr1, qr2, qr3 = st.columns(3)
                    if qr1.button("➕ Equipamento", use_container_width=True, key="qr_eq"):
                        dialog_novo_equip()
                    if qr2.button("➕ Fornecedor", use_container_width=True, key="qr_fn"):
                        dialog_novo_forn_loc()
                    if qr3.button("➕ Obra", use_container_width=True, key="qr_ob"):
                        dialog_nova_obra_loc()

                    st.markdown("---")

                    st.markdown("**Período da Locação**")
                    lc7, lc8 = st.columns(2)
                    loc_dt_inicio = lc7.date_input("📅 Data Início Locação", value=datetime.today(), format="DD/MM/YYYY")
                    loc_dt_devolucao = lc8.date_input("📅 Previsão Devolução", value=None, format="DD/MM/YYYY")

                    st.markdown("**Período Atual de Pagamento**")
                    lc9, lc10, lc11 = st.columns(3)
                    loc_per_inicio = lc9.date_input("Início Período", value=datetime.today(), format="DD/MM/YYYY")
                    loc_per_final = lc10.date_input("Final Período", value=None, format="DD/MM/YYYY")
                    loc_venc_boleto = lc11.date_input("📅 Venc. Boleto", value=None, format="DD/MM/YYYY")

                    lc12, lc13 = st.columns(2)
                    loc_valor_periodo = lc12.number_input("💰 Valor do Período (R$)", min_value=0.0, step=10.0, format="%.2f")
                    loc_obs = lc13.text_input("📝 Observação")

                    st.markdown("")
                    bl1, bl2, bl3 = st.columns(3)
                    if bl1.button("✅ REGISTRAR LOCAÇÃO", type="primary", use_container_width=True):
                        if loc_descricao == "--- Selecione ---":
                            st.error("Selecione um equipamento.")
                        elif loc_fornecedor == "--- Selecione ---":
                            st.error("Selecione um fornecedor.")
                        elif loc_obra == "--- Selecione ---":
                            st.error("Selecione uma obra.")
                        else:
                            novo = pd.DataFrame([{
                                "Descricao": loc_descricao,
                                "Qtd": loc_qtd,
                                "Valor": loc_valor,
                                "Fornecedor": loc_fornecedor,
                                "Contrato": loc_contrato.strip(),
                                "Data_Inicio": loc_dt_inicio.strftime("%Y-%m-%d"),
                                "Data_Devolucao": loc_dt_devolucao.strftime("%Y-%m-%d") if loc_dt_devolucao else "",
                                "Obra": loc_obra,
                                "Periodo_Inicio": loc_per_inicio.strftime("%Y-%m-%d"),
                                "Periodo_Final": loc_per_final.strftime("%Y-%m-%d") if loc_per_final else "",
                                "Venc_Boleto": loc_venc_boleto.strftime("%Y-%m-%d") if loc_venc_boleto else "",
                                "Valor_Periodo": loc_valor_periodo,
                                "Observacao": loc_obs,
                                "Status": "Ativo",
                                "Usuario": st.session_state.usuario_nome
                            }])
                            save(_concat_safe([df_loc, novo]), "loc")
                            st.success(f"✅ Locação de '{loc_descricao}' registrada!")
                            st.rerun()
                    if bl2.button("❌ Limpar", use_container_width=True):
                        st.rerun()
                    if bl3.button("🏠 Voltar ao Painel", use_container_width=True):
                        ir_para("Início")

            # ---- ABA 2: CONSULTAR LOCAÇÕES ----
            with aba_consulta:
                if len(df_loc) == 0:
                    st.info("Nenhuma locação registrada ainda.")
                else:
                    with st.container(border=True):
                        st.markdown("**🔍 Filtros**")
                        fl1, fl2, fl3, fl4 = st.columns(4)

                        status_disp = ["Todos", "Ativo", "Devolvido"]
                        filtro_status = fl1.selectbox("Status", status_disp, key="loc_status")

                        fornecedores = ["Todos"] + sorted(df_loc["Fornecedor"].dropna().unique())
                        filtro_forn = fl2.selectbox("Fornecedor", fornecedores, key="loc_forn")

                        obras_disp = ["Todos"] + sorted(df_loc["Obra"].dropna().unique())
                        filtro_obra_loc = fl3.selectbox("Obra", obras_disp, key="loc_obra_f")

                        equips = ["Todos"] + sorted(df_loc["Descricao"].dropna().unique())
                        filtro_equip = fl4.selectbox("Equipamento", equips, key="loc_equip")

                    df_loc_f = df_loc.copy()
                    if filtro_status != "Todos":
                        df_loc_f = df_loc_f[df_loc_f["Status"] == filtro_status]
                    if filtro_forn != "Todos":
                        df_loc_f = df_loc_f[df_loc_f["Fornecedor"] == filtro_forn]
                    if filtro_obra_loc != "Todos":
                        df_loc_f = df_loc_f[df_loc_f["Obra"] == filtro_obra_loc]
                    if filtro_equip != "Todos":
                        df_loc_f = df_loc_f[df_loc_f["Descricao"] == filtro_equip]

                    # Métricas
                    rl1, rl2, rl3 = st.columns(3)
                    rl1.metric("📋 Registros", len(df_loc_f))
                    total_valor = df_loc_f["Valor_Periodo"].sum() if "Valor_Periodo" in df_loc_f.columns else 0
                    rl2.metric("💰 Total Período", f"R$ {total_valor:,.2f}")
                    ativos = len(df_loc_f[df_loc_f["Status"] == "Ativo"]) if "Status" in df_loc_f.columns else 0
                    rl3.metric("✅ Ativos", ativos)

                    cols_show = ["Descricao", "Qtd", "Valor", "Fornecedor", "Contrato", "Data_Inicio", "Obra", "Venc_Boleto", "Valor_Periodo", "Status"]
                    cols_show = [c for c in cols_show if c in df_loc_f.columns]
                    df_loc_show = fmt_datas(df_loc_f[cols_show])
                    st.dataframe(df_loc_show, width='stretch', hide_index=True)

                    html_loc = gerar_html_relatorio(
                        "Relatório de Locações de Equipamentos",
                        df_loc_show,
                        {"Registros": str(len(df_loc_f)),
                         "Total Período": f"R$ {total_valor:,.2f}",
                         "Ativos": str(ativos)}
                    )
                    st.download_button("🖨️ Imprimir / Exportar HTML", html_loc,
                                       file_name="relatorio_locacoes.html", mime="text/html",
                                       use_container_width=True, key="dl_locacoes")

                    # Marcar como devolvido
                    if get_permissao(st.session_state.usuario_perfil, "excluir"):
                        with st.expander("🔄 Alterar Status de Locação"):
                            ativos_df = df_loc[df_loc["Status"] == "Ativo"]
                            if len(ativos_df) > 0:
                                idx_dev = st.selectbox("Selecione equipamento:",
                                    ativos_df.index,
                                    format_func=lambda i: f"{df_loc.loc[i, 'Descricao']} - {df_loc.loc[i, 'Fornecedor']}",
                                    key="loc_devolver")
                                if st.button("📦 Marcar como Devolvido", type="primary", use_container_width=True):
                                    df_loc.loc[idx_dev, "Status"] = "Devolvido"
                                    df_loc.loc[idx_dev, "Data_Devolucao"] = datetime.today().strftime("%Y-%m-%d")
                                    save(df_loc, "loc")
                                    st.success("✅ Equipamento marcado como devolvido!")
                                    st.rerun()
                            else:
                                st.info("Nenhuma locação ativa para devolver.")

            # ---- ABA 3: CONTROLE DE VENCIMENTOS ----
            with aba_venc:
                if len(df_loc) == 0:
                    st.info("Nenhuma locação registrada ainda.")
                else:
                    df_venc = df_loc[df_loc["Status"] == "Ativo"].copy()
                    if len(df_venc) == 0:
                        st.info("Nenhuma locação ativa.")
                    else:
                        # Converter datas
                        df_venc["Venc_Boleto"] = pd.to_datetime(df_venc["Venc_Boleto"], errors="coerce")
                        hoje = pd.Timestamp(datetime.today().date())

                        # Classificar vencimentos
                        df_venc["Dias_Vencer"] = (df_venc["Venc_Boleto"] - hoje).dt.days
                        df_venc["Situacao"] = df_venc["Dias_Vencer"].apply(
                            lambda d: "🔴 VENCIDO" if pd.notna(d) and d < 0
                            else ("🟡 Vence em breve" if pd.notna(d) and d <= 7
                            else ("🟢 Em dia" if pd.notna(d) else "⚪ Sem data"))
                        )

                        # Métricas
                        vm1, vm2, vm3, vm4 = st.columns(4)
                        vencidos = len(df_venc[df_venc["Situacao"] == "🔴 VENCIDO"])
                        proximos = len(df_venc[df_venc["Situacao"] == "🟡 Vence em breve"])
                        em_dia = len(df_venc[df_venc["Situacao"] == "🟢 Em dia"])
                        sem_data = len(df_venc[df_venc["Situacao"] == "⚪ Sem data"])

                        vm1.metric("🔴 Vencidos", vencidos)
                        vm2.metric("🟡 Vence em breve", proximos)
                        vm3.metric("🟢 Em dia", em_dia)
                        vm4.metric("⚪ Sem data", sem_data)

                        # Alertas
                        if vencidos > 0:
                            st.error(f"⚠️ Existem {vencidos} boleto(s) VENCIDO(S)!")
                        if proximos > 0:
                            st.warning(f"⏰ {proximos} boleto(s) vencem nos próximos 7 dias.")

                        # Tabela ordenada por vencimento
                        df_venc_show = df_venc.sort_values("Dias_Vencer", na_position="last")
                        cols_venc = ["Situacao", "Descricao", "Fornecedor", "Obra", "Venc_Boleto", "Dias_Vencer", "Valor_Periodo", "Contrato"]
                        cols_venc = [c for c in cols_venc if c in df_venc_show.columns]
                        st.dataframe(fmt_datas(df_venc_show[cols_venc]), width='stretch', hide_index=True)

                        # Resumo por fornecedor
                        st.divider()
                        st.markdown("**📊 Resumo por Fornecedor**")
                        resumo_forn = df_venc.groupby("Fornecedor").agg(
                            Equipamentos=("Descricao", "count"),
                            Total_Periodo=("Valor_Periodo", "sum")
                        ).sort_values("Total_Periodo", ascending=False)
                        st.dataframe(resumo_forn, width='stretch')

            st.markdown("")
            if st.button("🏠 Voltar ao Painel", use_container_width=True, key="loc_voltar"):
                ir_para("Início")





