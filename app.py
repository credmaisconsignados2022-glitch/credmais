# app.py — CredMais (versão completa, pronta para substituir)
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
# CONFIGURAÇÃO
# ===========================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "credmais_secret_2025"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///credmais.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

db = SQLAlchemy(app)

# ===========================
# MODELOS
# ===========================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)  # pode ser placeholder até o primeiro acesso
    telefone = db.Column(db.String(40))
    password = db.Column(db.String(255), nullable=False)
    bloqueado = db.Column(db.Boolean, default=False)
    primeiro_acesso = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.email or self.nome}>"

class Vendedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
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

    def __repr__(self):
        return f"<Cliente {self.nome} - {self.cpf}>"

class Evidencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Evidencia {self.arquivo}>"

class Anotacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Anotacao {self.titulo}>"

# ===========================
# UTILITÁRIOS
# ===========================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def fmt_currency(value):
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

app.jinja_env.filters["fmt"] = fmt_currency

# ===========================
# HELPERS — filtragem por usuário/admin
# ===========================
def soma_por_produto(usuario_id, text_match, is_admin=False):
    q = db.session.query(db.func.sum(Cliente.valor)).filter(Cliente.produto.ilike(f"%{text_match}%"))
    if not is_admin:
        q = q.filter(Cliente.usuario_id == usuario_id)
    return q.scalar() or 0.0

def soma_status(usuario_id, status, is_admin=False):
    q = db.session.query(db.func.sum(Cliente.valor)).filter(Cliente.status_contrato == status)
    if not is_admin:
        q = q.filter(Cliente.usuario_id == usuario_id)
    return q.scalar() or 0.0

# ===========================
# GARANTE USUÁRIO ADMIN PADRÃO
# ===========================
def ensure_admin():
    admin_email = "credmaisconsignados2022@gmail.com"
    admin_pass = "Latoya2019!"
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        u = User(
            nome="Latoya Filemes",
            email=admin_email,
            password=generate_password_hash(admin_pass),
            bloqueado=False,
            primeiro_acesso=False
        )
        db.session.add(u)
        db.session.commit()
        print("Admin criado:", admin_email)

# ===========================
# ROTAS - AUTENTICAÇÃO
# ===========================
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        if not email or not senha:
            flash("Preencha e-mail e senha!", "warning")
            return render_template("login.html", hora=datetime.now())

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, senha):
            if user.bloqueado:
                flash("Usuário bloqueado. Contate o administrador.", "danger")
                return render_template("login.html", hora=datetime.now())
            # se ainda não finalizou primeiro acesso (email pode ser placeholder), força fluxo
            if user.primeiro_acesso:
                # coloca id de primeiro acesso na sessão e redireciona para validação/finalização
                session["primeiro_acesso_user_id"] = user.id
                flash("Finalize seu cadastro antes de usar o painel.", "warning")
                return redirect(url_for("primeiro_acesso"))
            session["usuario_id"] = user.id
            session["nome"] = user.nome
            session["email"] = user.email
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html", hora=datetime.now())

    return render_template("login.html", hora=datetime.now())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===========================
# PRIMEIRO ACESSO (ADM cria nome + senha provisória, usuário finaliza com email+senha)
# ===========================
@app.route("/primeiro_acesso", methods=["GET", "POST"])
def primeiro_acesso():
    # Página para validar nome + senha provisória e encaminhar para finalizar
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha_prov = request.form.get("senha_provisoria", "")

        candidato = User.query.filter_by(nome=nome, primeiro_acesso=True).first()
        if not candidato:
            flash("Usuário não encontrado ou já finalizou o cadastro.", "warning")
            return render_template("primeiro_acesso.html", hora=datetime.now())

        if not check_password_hash(candidato.password, senha_prov):
            flash("Senha provisória inválida.", "danger")
            return render_template("primeiro_acesso.html", hora=datetime.now())

        # autenticado pelo par nome+senha provisória -> grava na sessão e vai para finalizar
        session["primeiro_acesso_user_id"] = candidato.id
        return redirect(url_for("primeiro_acesso_finalizar"))

    return render_template("primeiro_acesso.html", hora=datetime.now())

@app.route("/primeiro_acesso/finalizar", methods=["GET", "POST"])
def primeiro_acesso_finalizar():
    uid = session.get("primeiro_acesso_user_id")
    if not uid:
        flash("Valide seu nome e senha provisória antes.", "warning")
        return redirect(url_for("primeiro_acesso"))

    candidato = User.query.get(uid)
    if not candidato:
        flash("Usuário inválido. Contate o administrador.", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nova_senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar", "")

        if not email or not nova_senha or not confirmar:
            flash("Preencha todos os campos.", "warning")
            return render_template("primeiro_acesso_finalizar.html", usuario=candidato, hora=datetime.now())

        if nova_senha != confirmar:
            flash("Senhas não coincidem.", "warning")
            return render_template("primeiro_acesso_finalizar.html", usuario=candidato, hora=datetime.now())

        # garante que email não está em uso por outro usuário
        outro = User.query.filter(User.email == email, User.id != candidato.id).first()
        if outro:
            flash("E-mail já utilizado por outro usuário.", "danger")
            return render_template("primeiro_acesso_finalizar.html", usuario=candidato, hora=datetime.now())

        candidato.email = email
        candidato.password = generate_password_hash(nova_senha)
        candidato.primeiro_acesso = False
        db.session.commit()

        flash("Cadastro finalizado! Faça login.", "success")
        session.pop("primeiro_acesso_user_id", None)
        return redirect(url_for("login"))

    return render_template("primeiro_acesso_finalizar.html", usuario=candidato, hora=datetime.now())

# ===========================
# DASHBOARD
# ===========================
@app.route("/dashboard")
def dashboard():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # identifica admin
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    uid = None if is_admin else session.get("usuario_id")

    # função auxiliar para filtrar produtos por usuário
    def soma_produto(busca):
        q = db.session.query(db.func.sum(Cliente.valor)).filter(Cliente.produto.ilike(f"%{busca}%"))
        if not is_admin:
            q = q.filter(Cliente.usuario_id == uid)
        return q.scalar() or 0.0

    # produtos — COMPLETO, ATUALIZADO, E COM ACUMULATIVO DO AUMENTO 2026
    produtos = {
        "Cartão": soma_produto("Cartão"),
        "Margem Novo": soma_produto("Margem Novo"),
        "Saque Complementar": soma_produto("Saque Complementar"),
        "Margem de Aumento 2026 (Acumulativo)": (
            soma_produto("Margem de Aumento 2026") +
            soma_produto("Aumento 2026")
        ),
        "Portabilidade": soma_produto("Portabilidade"),
        "FGTS/CLT": soma_produto("FGTS"),
        "Refin": soma_produto("Refin"),
        "Governo/Prefeitura": soma_produto("Governo") + soma_produto("Prefeitura"),
        "Bolsa": soma_produto("Bolsa"),
        "Empréstimo Pessoal": soma_produto("Empréstimo Pessoal"),
    }

    # totais por status
    def soma_status(status):
        q = db.session.query(db.func.sum(Cliente.valor)).filter(Cliente.status_contrato == status)
        if not is_admin:
            q = q.filter(Cliente.usuario_id == uid)
        return q.scalar() or 0.0

    pagos = soma_status("Pago")
    em_aberto = soma_status("Em Aberto")
    cancelados = soma_status("Cancelado")

    return render_template(
        "dashboard.html",
        nome=session.get("nome"),
        produtos=produtos,
        pagos=pagos,
        em_aberto=em_aberto,
        cancelados=cancelados,
        hora=datetime.now()
    )


# ===========================
# CLIENTES (FILTRADO POR USUÁRIO)
# ===========================
@app.route("/clientes", methods=["GET", "POST"], endpoint="clientes_view")
def clientes_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    uid = None if is_admin else session.get("usuario_id")

    if is_admin:
        clientes = Cliente.query.order_by(Cliente.criado_em.desc()).all()
    else:
        clientes = Cliente.query.filter_by(usuario_id=uid).order_by(Cliente.criado_em.desc()).all()

    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template("clientes.html", clientes=clientes, vendedores=vendedores, nome=session.get("nome"), hora=datetime.now())

@app.route("/salvar_cliente", methods=["POST"])
def salvar_cliente():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    uid = session.get("usuario_id")
    cid = request.form.get("id")
    nome = request.form.get("nome")
    cpf = request.form.get("cpf")
    telefone = request.form.get("telefone")
    produto = request.form.get("produto")
    try:
        valor = float(request.form.get("valor") or 0)
    except:
        valor = 0.0
    vendedor_id = request.form.get("vendedor")
    status_contrato = request.form.get("status_contrato") or "Em Aberto"
    status_comissao = request.form.get("status_comissao") or "A Pagar"
    status_formalizacao = request.form.get("status_formalizacao") or "Não Formalizado"

    if cid:
        c = Cliente.query.get(int(cid))
        if not c:
            flash("Cliente não encontrado", "danger")
            return redirect(url_for("clientes_view"))
        c.nome = nome
        c.cpf = cpf
        c.telefone = telefone
        c.produto = produto
        c.valor = valor
        c.vendedor_id = int(vendedor_id) if vendedor_id else None
        c.status_contrato = status_contrato
        c.status_comissao = status_comissao
        c.status_formalizacao = status_formalizacao
        db.session.commit()
        flash("Cliente atualizado!", "success")
    else:
        novo = Cliente(
            usuario_id=uid,
            nome=nome,
            cpf=cpf,
            telefone=telefone,
            produto=produto,
            valor=valor,
            vendedor_id=int(vendedor_id) if vendedor_id else None,
            status_contrato=status_contrato,
            status_comissao=status_comissao,
            status_formalizacao=status_formalizacao
        )
        db.session.add(novo)
        db.session.commit()
        flash("Cliente cadastrado!", "success")

    return redirect(url_for("clientes_view"))

@app.route("/excluir_cliente/<int:id>")
def excluir_cliente(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    c = Cliente.query.get(id)
    if not c:
        flash("Cliente não encontrado!", "warning")
        return redirect(url_for("clientes_view"))
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    if not is_admin and c.usuario_id != session.get("usuario_id"):
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
# EVIDÊNCIAS (UPLOAD, DOWNLOAD, EXCLUIR)
# ===========================
@app.route("/upload_evidencia/<int:id>", methods=["POST"])
def upload_evidencia(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    cliente = Cliente.query.get(id)
    if not cliente:
        flash("Cliente não encontrado!", "warning")
        return redirect(url_for("clientes_view"))
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    if not is_admin and cliente.usuario_id != session.get("usuario_id"):
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))
    arquivos = request.files.getlist("arquivo")
    if not arquivos:
        flash("Nenhum arquivo enviado!", "warning")
        return redirect(url_for("clientes_view"))
    enviados = 0
    for arquivo in arquivos:
        if arquivo and allowed_file(arquivo.filename):
            filename = secure_filename(f"{cliente.cpf}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{arquivo.filename}")
            destino = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            arquivo.save(destino)
            novo = Evidencia(cliente_id=cliente.id, arquivo=filename)
            db.session.add(novo)
            enviados += 1
    if enviados > 0:
        db.session.commit()
        flash(f"{enviados} evidência(s) enviada(s)!", "success")
    else:
        flash("Nenhum arquivo válido enviado!", "danger")
    return redirect(url_for("clientes_view"))

@app.route("/baixar_evidencia/<path:filename>")
def baixar_evidencia(filename):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    ev = Evidencia.query.filter_by(arquivo=filename).first()
    if ev:
        cliente = Cliente.query.get(ev.cliente_id)
        is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
        if not is_admin and cliente.usuario_id != session.get("usuario_id"):
            flash("Ação não permitida!", "danger")
            return redirect(url_for("clientes_view"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

@app.route("/excluir_evidencia/<int:id>")
def excluir_evidencia(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    ev = Evidencia.query.get(id)
    if not ev:
        flash("Evidência não encontrada!", "warning")
        return redirect(url_for("clientes_view"))
    cliente = Cliente.query.get(ev.cliente_id)
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    if not is_admin and cliente.usuario_id != session.get("usuario_id"):
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
# BUSCAR CLIENTE (POR CPF)
# ===========================
@app.route("/buscar_cliente", methods=["GET"])
def buscar_cliente():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    cpf = request.args.get("cpf", "").strip()
    if not cpf:
        return redirect(url_for("clientes_view"))
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    uid = None if is_admin else session.get("usuario_id")
    query = Cliente.query.filter(Cliente.cpf.like(f"%{cpf}%"))
    if not is_admin:
        query = query.filter(Cliente.usuario_id == uid)
    clientes = query.order_by(Cliente.criado_em.desc()).all()
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template("clientes.html", clientes=clientes, vendedores=vendedores, nome=session.get("nome"), hora=datetime.now())

# ===========================
# USUÁRIOS (ADMIN) - restaura rota usuarios_view
# ===========================
@app.route("/usuarios", endpoint="usuarios_view")
def usuarios_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    usuarios = User.query.order_by(User.nome).all()
    return render_template("usuarios.html", usuarios=usuarios, nome=session.get("nome"), hora=datetime.now())

@app.route("/salvar_usuario", methods=["POST"])
def salvar_usuario():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    nome = request.form.get("nome")
    senha_prov = request.form.get("senha_provisoria")
    if not nome or not senha_prov:
        flash("Preencha nome e gere a senha provisória.", "warning")
        return redirect(url_for("usuarios_view"))
    placeholder = f"pendente_{uuid.uuid4().hex}@local"
    novo = User(nome=nome, email=placeholder, password=generate_password_hash(senha_prov), primeiro_acesso=True, bloqueado=False)
    db.session.add(novo)
    db.session.commit()
    flash("Usuário criado! Envie nome + senha provisória para o usuário finalizar.", "success")
    return redirect(url_for("usuarios_view"))

@app.route("/editar_usuario/<int:id>", methods=["GET", "POST"])
def editar_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    u = User.query.get(id)
    if not u:
        flash("Usuário não encontrado", "warning")
        return redirect(url_for("usuarios_view"))
    if request.method == "POST":
        u.nome = request.form.get("nome") or u.nome
        email = request.form.get("email")
        if email:
            u.email = email.strip().lower()
        nova_senha = request.form.get("senha")
        if nova_senha:
            u.password = generate_password_hash(nova_senha)
            u.primeiro_acesso = False
        db.session.commit()
        flash("Usuário atualizado", "success")
        return redirect(url_for("usuarios_view"))
    return render_template("editar_usuario.html", usuario=u, nome=session.get("nome"), hora=datetime.now())

@app.route("/bloquear_usuario/<int:id>")
def bloquear_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    u = User.query.get(id)
    if u:
        u.bloqueado = True
        db.session.commit()
        flash("Usuário bloqueado", "success")
    return redirect(url_for("usuarios_view"))

@app.route("/desbloquear_usuario/<int:id>")
def desbloquear_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    u = User.query.get(id)
    if u:
        u.bloqueado = False
        db.session.commit()
        flash("Usuário desbloqueado", "success")
    return redirect(url_for("usuarios_view"))

@app.route("/excluir_usuario/<int:id>")
def excluir_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    u = User.query.get(id)
    if u:
        db.session.delete(u)
        db.session.commit()
        flash("Usuário excluído", "success")
    return redirect(url_for("usuarios_view"))

# ===========================
# VENDEDORES (RESTORED)
# ===========================
@app.route("/vendedores", methods=["GET", "POST"], endpoint="vendedores_view")
def vendedores_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if request.method == "POST":
        vid = request.form.get("id")
        nome = request.form.get("nome")
        telefone = request.form.get("telefone")
        if not nome:
            flash("Preencha nome!", "warning")
            return redirect(url_for("vendedores_view"))
        if vid:
            v = Vendedor.query.get(int(vid))
            if v:
                v.nome = nome
                v.telefone = telefone
                db.session.commit()
                flash("Vendedor atualizado!", "success")
        else:
            novo = Vendedor(nome=nome, telefone=telefone)
            db.session.add(novo)
            db.session.commit()
            flash("Vendedor cadastrado!", "success")
        return redirect(url_for("vendedores_view"))
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template("vendedores.html", vendedores=vendedores, nome=session.get("nome"), hora=datetime.now())

@app.route("/excluir_vendedor/<int:id>")
def excluir_vendedor(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    v = Vendedor.query.get(id)
    if not v:
        flash("Vendedor não encontrado!", "warning")
    else:
        db.session.delete(v)
        db.session.commit()
        flash("Vendedor excluído!", "success")
    return redirect(url_for("vendedores_view"))

@app.route("/vendedor_pdf/<int:id>")
def vendedor_pdf(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    vend = Vendedor.query.get(id)
    if not vend:
        flash("Vendedor não encontrado", "warning")
        return redirect(url_for("vendedores_view"))
    vendas = Cliente.query.filter(Cliente.vendedor_id == id).order_by(Cliente.criado_em.desc()).all()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    y = altura - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(largura / 2, y, f"Relatório Vendedor - {vend.nome}")
    y -= 30
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Cliente")
    c.drawString(250, y, "Produto")
    c.drawString(400, y, "Valor")
    y -= 16
    c.setFont("Helvetica", 10)
    total = 0.0
    for v in vendas:
        if y < 80:
            c.showPage()
            y = altura - 40
        c.drawString(50, y, v.nome[:30])
        c.drawString(250, y, (v.produto or "")[:25])
        c.drawString(400, y, fmt_currency(v.valor))
        total += v.valor or 0
        y -= 14
    if y < 120:
        c.showPage()
        y = altura - 40
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(largura - 50, y - 10, f"TOTAL VENDAS: {fmt_currency(total)}")
    c.showPage()
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"vendas_{vend.nome}.pdf", mimetype="application/pdf")

# ===========================
# RELATÓRIOS
# ===========================
@app.route("/relatorios", methods=["GET", "POST"], endpoint="relatorios_view")
def relatorios_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
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
        except Exception:
            flash("Datas inválidas", "warning")
            return render_template("relatorios.html", vendedores=vendedores, resultados=[], total=0.0, nome=session.get("nome"), hora=datetime.now())
        query = Cliente.query.filter(Cliente.criado_em.between(dt_inicio, dt_fim))
        vendedor_filter = vendedor_id
        if vendedor_filter:
            try:
                query = query.filter(Cliente.vendedor_id == int(vendedor_filter))
            except:
                pass
        if produto:
            query = query.filter(Cliente.produto == produto)
        resultados = query.order_by(Cliente.criado_em.desc()).all()
        total = sum(c.valor for c in resultados)
        if acao == "gerar_pdf":
            return gerar_relatorio_pdf(resultados, total)
    return render_template("relatorios.html", vendedores=vendedores, resultados=resultados, total=total, nome=session.get("nome"), hora=datetime.now())

def gerar_relatorio_pdf(resultados, total):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    y = altura - 50
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0.108, 0.494, 0.188)
    c.drawCentredString(largura / 2, y, "Relatório CredMais")
    c.setFillColorRGB(0, 0, 0)
    y -= 30
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Cliente")
    c.drawString(200, y, "CPF")
    c.drawString(320, y, "Produto")
    c.drawString(430, y, "Valor")
    c.drawString(500, y, "Vendedor")
    y -= 16
    c.setFont("Helvetica", 10)
    for r in resultados:
        if y < 80:
            c.showPage()
            y = altura - 40
            c.setFont("Helvetica", 10)
        vendedor_nome = ""
        if r.vendedor_id:
            vend = Vendedor.query.get(r.vendedor_id)
            vendedor_nome = vend.nome if vend else ""
        c.drawString(50, y, (r.nome or "")[:24])
        c.drawString(200, y, (r.cpf or "")[:20])
        c.drawString(320, y, (r.produto or "")[:20])
        c.drawString(430, y, fmt_currency(r.valor))
        c.drawString(500, y, (vendedor_nome or "")[:18])
        y -= 14
    if y < 120:
        c.showPage()
        y = altura - 40
    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(largura - 50, y, f"TOTAL: {fmt_currency(total)}")
    c.showPage()
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="relatorio_credmais.pdf", mimetype="application/pdf")

# ===========================
# ANOTAÇÕES (CRUD básico)
# ===========================
@app.route("/anotacoes", endpoint="anotacoes_view")
def anotacoes_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    uid = session.get("usuario_id")
    anotacoes = Anotacao.query.filter_by(usuario_id=uid).order_by(Anotacao.criado_em.desc()).all()
    return render_template("anotacoes.html", anotacoes=anotacoes, nome=session.get("nome"), hora=datetime.now())

@app.route("/anotacoes/nova")
def anotacoes_nova():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    return render_template("anotacoes_nova.html", nome=session.get("nome"), hora=datetime.now())

@app.route("/anotacoes/abrir/<int:id>")
def anotacoes_abrir(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    uid = session.get("usuario_id")
    anot = Anotacao.query.get(id)
    if not anot or anot.usuario_id != uid:
        flash("Anotação não encontrada!", "warning")
        return redirect(url_for("anotacoes_view"))
    return render_template("anotacoes_abrir.html", anotacao=anot, nome=session.get("nome"), hora=datetime.now())

@app.route("/anotacoes/editar/<int:id>")
def anotacoes_editar(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    uid = session.get("usuario_id")
    anot = Anotacao.query.get(id)
    if not anot or anot.usuario_id != uid:
        flash("Anotação não encontrada!", "warning")
        return redirect(url_for("anotacoes_view"))
    return render_template("anotacoes_editar.html", anotacao=anot, nome=session.get("nome"), hora=datetime.now())

@app.route("/salvar_anotacao", methods=["POST"])
def salvar_anotacao():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    uid = session.get("usuario_id")
    aid = request.form.get("id")
    titulo = request.form.get("titulo")
    texto = request.form.get("texto")
    if aid:
        a = Anotacao.query.get(int(aid))
        if a and a.usuario_id == uid:
            a.titulo = titulo
            a.texto = texto
            db.session.commit()
            flash("Anotação atualizada!", "success")
    else:
        nova = Anotacao(usuario_id=uid, titulo=titulo, texto=texto)
        db.session.add(nova)
        db.session.commit()
        flash("Anotação criada!", "success")
    return redirect(url_for("anotacoes_view"))

@app.route("/excluir_anotacao/<int:id>")
def excluir_anotacao(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    uid = session.get("usuario_id")
    a = Anotacao.query.get(id)
    if a and a.usuario_id == uid:
        db.session.delete(a)
        db.session.commit()
        flash("Anotação excluída!", "success")
    return redirect(url_for("anotacoes_view"))

# ===========================
# CALCULADORA / SIMULAÇÃO PDF
# ===========================
@app.route("/calculadora", endpoint="calculadora_view")
def calculadora_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    return render_template("calculadora.html", nome=session.get("nome"), hora=datetime.now())

@app.route("/gerar_pdf_simulacao", methods=["POST"])
def gerar_pdf_simulacao():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    tipo = request.form.get("tipo")
    cliente_nome = request.form.get("nome") or "Cliente"
    cliente_cpf = request.form.get("cpf") or ""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0.108, 0.494, 0.188)
    c.drawCentredString(largura / 2, altura - 50, "Relatório de Simulação - CredMais")
    c.setFillColorRGB(0, 0, 0)
    y = altura - 80
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Cliente: {cliente_nome}")
    y -= 18
    c.drawString(50, y, f"CPF: {cliente_cpf}")
    y -= 28
    if tipo in ["cartao", "ambos"]:
        valor_pag = float(request.form.get("valor_pagamento") or 0)
        multiplicador_cartao = float(request.form.get("multiplicador_cartao") or 0)
        margem_cartao = valor_pag * 0.05
        total_cartao = margem_cartao * (multiplicador_cartao if multiplicador_cartao > 0 else 1)
        valor_70 = total_cartao * 0.7
        valor_30 = total_cartao * 0.3
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Cartão Consignado")
        y -= 16
        c.setFont("Helvetica", 11)
        c.drawString(60, y, f"Margem: {fmt_currency(margem_cartao)}")
        y -= 14
        c.drawString(60, y, f"Valor total (limite): {fmt_currency(total_cartao)}")
        y -= 14
        c.drawString(60, y, f"70% (Dinheiro): {fmt_currency(valor_70)}")
        y -= 14
        c.drawString(60, y, f"30% (Cartão): {fmt_currency(valor_30)}")
        y -= 22
    if tipo in ["margem", "ambos"]:
        salario_atual = float(request.form.get("salario_atual") or 0)
        aumento_percent = float(request.form.get("aumento_percent") or 0)
        multiplicador_margem = float(request.form.get("multiplicador_margem") or 0)
        prazo = request.form.get("prazo") or ""
        novo_salario = salario_atual + (salario_atual * aumento_percent / 100)
        aumento_valor = novo_salario - salario_atual
        margem = aumento_valor * 0.35
        valor_liberado = margem * (multiplicador_margem if multiplicador_margem > 0 else 1)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Aumento de Margem")
        y -= 16
        c.setFont("Helvetica", 11)
        c.drawString(60, y, f"Novo Salário: {fmt_currency(novo_salario)}")
        y -= 14
        c.drawString(60, y, f"Aumento: {fmt_currency(aumento_valor)}")
        y -= 14
        c.drawString(60, y, f"Margem Consignável (35% do aumento): {fmt_currency(margem)}")
        y -= 14
        c.drawString(60, y, f"Valor liberado: {fmt_currency(valor_liberado)}")
        y -= 14
        if prazo:
            c.drawString(60, y, f"Prazo: {prazo} meses")
            y -= 14
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.drawCentredString(largura / 2, 40, "Sistema CredMais — Desenvolvido por Latoya Filemes")
    c.showPage()
    c.save()
    buffer.seek(0)
    filename = f"Simulacao_{cliente_nome.replace(' ', '_')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

# ===========================
# ERRO DE ARQUIVO GRANDE
# ===========================
@app.errorhandler(413)
def request_entity_too_large(error):
    flash("Arquivo muito grande. Limite 10MB.", "danger")
    return redirect(request.referrer or url_for("clientes_view"))

# ===========================
# EXECUÇÃO
# ===========================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_admin()
    print("🚀 Servidor CredMais iniciado em http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
