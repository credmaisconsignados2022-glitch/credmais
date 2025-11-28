
# app.py — CredMais atualizado e isolado
from datetime import datetime
import os
import io
import uuid
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# ===========================
# CONFIG
# ===========================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "credmais_secret_2025"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///credmais.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

db = SQLAlchemy(app)

# ===========================
# MODELOS
# ===========================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    telefone = db.Column(db.String(40))
    password = db.Column(db.String(255), nullable=False)
    bloqueado = db.Column(db.Boolean, default=False)
    primeiro_acesso = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.email or self.nome}>"

class Vendedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer)  # <---- AQUI A ALTERAÇÃO
    nome = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(40))

    def __repr__(self):
        return f"<Vendedor {self.nome}>"

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer)
    nome = db.Column(db.String(150), nullable=False)
    cpf = db.Column(db.String(30), nullable=False)
    telefone = db.Column(db.String(40))
    produto = db.Column(db.String(120))
    valor = db.Column(db.Float, default=0.0)
    vendedor_id = db.Column(db.Integer)
    status_contrato = db.Column(db.String(50), default="Em Aberto")
    status_comissao = db.Column(db.String(50), default="A Pagar")
    status_formalizacao = db.Column(db.String(50), default="Não Formalizado")
    evidencia = db.Column(db.String(255))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    evidencias = db.relationship("Evidencia", backref="cliente", cascade="all,delete")

class Evidencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

class Anotacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

# ===========================
# FUNÇÕES / FILTRO
# ===========================
def fmt_currency(value):
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

app.jinja_env.filters["fmt"] = fmt_currency

# ===========================
# LOGIN
# ===========================
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        senha = request.form.get("senha","")

        if not email or not senha:
            flash("Preencha e-mail e senha!", "warning")
            return render_template("login.html")

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, senha):
            if user.bloqueado:
                flash("Usuário bloqueado.", "danger")
                return render_template("login.html")

            if user.primeiro_acesso:
                session["primeiro_acesso_user_id"] = user.id
                return redirect(url_for("primeiro_acesso"))

            session["usuario_id"] = user.id
            session["nome"] = user.nome
            session["email"] = user.email
            flash("Login realizado!", "success")
            return redirect(url_for("dashboard"))

        flash("E-mail ou senha incorretos!", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===========================
# DASHBOARD 100% ISOLADO
# ===========================
@app.route("/dashboard")
def dashboard():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")

    def soma_produto(busca):
        q = db.session.query(db.func.sum(Cliente.valor)) \
            .filter(Cliente.usuario_id == uid) \
            .filter(Cliente.produto.ilike(f"%{busca}%"))
        return q.scalar() or 0.0

    def soma_status(status):
        q = db.session.query(db.func.sum(Cliente.valor)) \
            .filter(Cliente.usuario_id == uid) \
            .filter(Cliente.status_contrato == status)
        return q.scalar() or 0.0

    produtos = {
        "Cartão": soma_produto("Cartão"),
        "Margem Novo": soma_produto("Margem Novo"),
        "Saque Complementar": soma_produto("Saque Complementar"),
        "Margem de Aumento 2026 (Acumulativo)":
            soma_produto("Margem de Aumento 2026") + soma_produto("Aumento 2026"),
        "Portabilidade": soma_produto("Portabilidade"),
        "FGTS/CLT": soma_produto("FGTS"),
        "Refin": soma_produto("Refin"),
        "Governo/Prefeitura": soma_produto("Governo") + soma_produto("Prefeitura"),
        "Bolsa": soma_produto("Bolsa"),
        "Empréstimo Pessoal": soma_produto("Empréstimo Pessoal"),
    }

    pagos = soma_status("Pago")
    em_aberto = soma_status("Em Aberto")
    cancelados = soma_status("Cancelado")

    return render_template(
        "dashboard.html",
        nome=session.get("nome"),
        produtos=produtos,
        pagos=pagos,
        em_aberto=em_aberto,
        cancelados=cancelados
    )
# ===========================
# CLIENTES (ISOLADO POR USUÁRIO)
# ===========================
@app.route("/clientes", methods=["GET", "POST"], endpoint="clientes_view")
def clientes_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")

    clientes = Cliente.query \
        .filter(Cliente.usuario_id == uid) \
        .order_by(Cliente.criado_em.desc()).all()

    vendedores = Vendedor.query \
        .filter(Vendedor.usuario_id == uid) \
        .order_by(Vendedor.nome).all()

    return render_template(
        "clientes.html",
        clientes=clientes,
        vendedores=vendedores,
        nome=session.get("nome"),
        hora=datetime.now()
    )


@app.route("/salvar_cliente", methods=["POST"])
def salvar_cliente():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    cid = request.form.get("id")
    vendedor_id = request.form.get("vendedor")

    if vendedor_id:
        # O vendedor só pode ser do usuário logado
        v = Vendedor.query.get(int(vendedor_id))
        if not v or v.usuario_id != uid:
            flash("Vendedor não permitido.", "danger")
            return redirect(url_for("clientes_view"))

    if cid:
        c = Cliente.query.get(int(cid))
        if not c or c.usuario_id != uid:
            flash("Cliente não encontrado.", "danger")
            return redirect(url_for("clientes_view"))
        # atualizar
        c.nome = request.form.get("nome")
        c.cpf = request.form.get("cpf")
        c.telefone = request.form.get("telefone")
        c.produto = request.form.get("produto")
        c.valor = float(request.form.get("valor") or 0)
        c.vendedor_id = int(vendedor_id) if vendedor_id else None
    else:
        novo = Cliente(
            usuario_id=uid,
            nome=request.form.get("nome"),
            cpf=request.form.get("cpf"),
            telefone=request.form.get("telefone"),
            produto=request.form.get("produto"),
            valor=float(request.form.get("valor") or 0),
            vendedor_id=int(vendedor_id) if vendedor_id else None
        )
        db.session.add(novo)

    db.session.commit()
    flash("Cliente salvo!", "success")
    return redirect(url_for("clientes_view"))


# ===========================
# VENDEDORES ISOLADOS
# ===========================
@app.route("/vendedores", methods=["GET", "POST"], endpoint="vendedores_view")
def vendedores_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")

    if request.method == "POST":
        vid = request.form.get("id")
        nome = request.form.get("nome")
        telefone = request.form.get("telefone")

        if vid:
            v = Vendedor.query.get(int(vid))
            if v and v.usuario_id == uid:
                v.nome = nome
                v.telefone = telefone
        else:
            novo = Vendedor(usuario_id=uid, nome=nome, telefone=telefone)
            db.session.add(novo)

        db.session.commit()
        return redirect(url_for("vendedores_view"))

    vendedores = Vendedor.query \
        .filter(Vendedor.usuario_id == uid) \
        .order_by(Vendedor.nome).all()

    return render_template(
        "vendedores.html",
        vendedores=vendedores,
        nome=session.get("nome"),
        hora=datetime.now()
    )
# ===========================
# BUSCAR CLIENTE (ISOLADO)
# ===========================
@app.route("/buscar_cliente", methods=["GET"])
def buscar_cliente():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    cpf = request.args.get("cpf", "").strip()

    if not cpf:
        return redirect(url_for("clientes_view"))

    clientes = Cliente.query \
        .filter(Cliente.usuario_id == uid) \
        .filter(Cliente.cpf.like(f"%{cpf}%")) \
        .order_by(Cliente.criado_em.desc()).all()

    vendedores = Vendedor.query \
        .filter(Vendedor.usuario_id == uid) \
        .order_by(Vendedor.nome).all()

    return render_template(
        "clientes.html",
        clientes=clientes,
        vendedores=vendedores,
        nome=session.get("nome"),
        hora=datetime.now()
    )

# ===========================
# EXCLUIR CLIENTE (ISOLADO)
# ===========================
@app.route("/excluir_cliente/<int:id>")
def excluir_cliente(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    c = Cliente.query.get(id)

    if not c or c.usuario_id != uid:
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))

    for ev in c.evidencias:
        caminho = os.path.join(app.config["UPLOAD_FOLDER"], ev.arquivo)
        if os.path.exists(caminho):
            os.remove(caminho)

    db.session.delete(c)
    db.session.commit()
    flash("Cliente excluído!", "success")
    return redirect(url_for("clientes_view"))

# ===========================
# EXCLUIR VENDEDOR (ISOLADO)
# ===========================
@app.route("/excluir_vendedor/<int:id>")
def excluir_vendedor(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    v = Vendedor.query.get(id)

    if not v or v.usuario_id != uid:
        flash("Ação não permitida!", "danger")
        return redirect(url_for("vendedores_view"))

    db.session.delete(v)
    db.session.commit()
    flash("Vendedor excluído!", "success")
    return redirect(url_for("vendedores_view"))

# ===========================
# RELATÓRIOS ISOLADOS
# ===========================
@app.route("/relatorios", methods=["GET", "POST"], endpoint="relatorios_view")
def relatorios_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")

    vendedores = Vendedor.query \
        .filter(Vendedor.usuario_id == uid) \
        .order_by(Vendedor.nome).all()

    resultados = []
    total = 0.0

    if request.method == "POST":
        data_inicio = request.form.get("data_inicio")
        data_fim = request.form.get("data_fim")
        vendedor_id = request.form.get("vendedor")
        produto = request.form.get("produto")
        acao = request.form.get("acao")

        try:
            dt_inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
            dt_fim = datetime.strptime(data_fim, "%Y-%m-%d")
            dt_fim = datetime(dt_fim.year, dt_fim.month, dt_fim.day, 23, 59, 59)
        except:
            flash("Datas inválidas", "warning")
            return render_template("relatorios.html", vendedores=vendedores)

        query = Cliente.query.filter(
            Cliente.usuario_id == uid,
            Cliente.criado_em.between(dt_inicio, dt_fim)
        )

        if vendedor_id:
            query = query.filter(Cliente.vendedor_id == int(vendedor_id))

        if produto:
            query = query.filter(Cliente.produto == produto)

        resultados = query.order_by(Cliente.criado_em.desc()).all()
        total = sum(c.valor for c in resultados)

        if acao == "gerar_pdf":
            return gerar_relatorio_pdf(resultados, total)

    return render_template(
        "relatorios.html",
        vendedores=vendedores,
        resultados=resultados,
        total=total,
        nome=session.get("nome"),# ===========================
# EVIDÊNCIAS (UPLOAD / DOWNLOAD / DELETE)
# ===========================
@app.route("/upload_evidencia/<int:id>", methods=["POST"])
def upload_evidencia(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    cliente = Cliente.query.get(id)

    if not cliente or cliente.usuario_id != uid:
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))

    arquivos = request.files.getlist("arquivo")
    enviados = 0

    for arquivo in arquivos:
        if not arquivo:
            continue
        filename = secure_filename(
            f"{cliente.cpf}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{arquivo.filename}"
        )
        destino = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        arquivo.save(destino)

        db.session.add(Evidencia(cliente_id=cliente.id, arquivo=filename))
        enviados += 1

    if enviados:
        db.session.commit()
        flash(f"{enviados} evidência(s) enviada(s)!", "success")
    else:
        flash("Nenhum arquivo enviado!", "warning")

    return redirect(url_for("clientes_view"))


@app.route("/baixar_evidencia/<path:filename>")
def baixar_evidencia(filename):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    ev = Evidencia.query.filter_by(arquivo=filename).first()

    if not ev:
        flash("Evidência não encontrada!", "danger")
        return redirect(url_for("clientes_view"))

    cliente = Cliente.query.get(ev.cliente_id)

    if cliente.usuario_id != uid:
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))

    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@app.route("/excluir_evidencia/<int:id>")
def excluir_evidencia(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    ev = Evidencia.query.get(id)

    if not ev:
        flash("Evidência não encontrada!", "warning")
        return redirect(url_for("clientes_view"))

    cliente = Cliente.query.get(ev.cliente_id)

    if cliente.usuario_id != uid:
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))

    caminho = os.path.join(app.config["UPLOAD_FOLDER"], ev.arquivo)
    if os.path.exists(caminho):
        os.remove(caminho)

    db.session.delete(ev)
    db.session.commit()
    flash("Evidência excluída!", "success")
    return redirect(url_for("clientes_view"))


# ===========================
# ANOTAÇÕES ISOLADAS
# ===========================
@app.route("/anotacoes")
def anotacoes_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    anotacoes = Anotacao.query \
        .filter(Anotacao.usuario_id == uid) \
        .order_by(Anotacao.criado_em.desc()).all()

    return render_template(
        "anotacoes.html",
        anotacoes=anotacoes,
        nome=session.get("nome"),
        hora=datetime.now()
    )


@app.route("/salvar_anotacao", methods=["POST"])
def salvar_anotacao():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    aid = request.form.get("id")

    if aid:
        a = Anotacao.query.get(int(aid))
        if a and a.usuario_id == uid:
            a.titulo = request.form.get("titulo")
            a.texto = request.form.get("texto")
    else:
        db.session.add(
            Anotacao(
                usuario_id=uid,
                titulo=request.form.get("titulo"),
                texto=request.form.get("texto")
            )
        )

    db.session.commit()
    return redirect(url_for("anotacoes_view"))


# ===========================
DASHBOARD PDF / SIMULAÇÃO / CALCULADORA
# ===========================
@app.route("/calculadora")
def calculadora_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    return render_template("calculadora.html", nome=session.get("nome"))


@app.route("/gerar_pdf_simulacao", methods=["POST"])
def gerar_pdf_simulacao():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # NADA AQUI mistura usuário
    # PDF é independente, não precisa mudar nada

    # (o teu código desse PDF pode ficar igual)
    ...

        hora=datetime.now()
    )
