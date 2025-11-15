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
    email = db.Column(db.String(150), unique=True, nullable=False)
    telefone = db.Column(db.String(40))
    password = db.Column(db.String(255), nullable=False)
    bloqueado = db.Column(db.Boolean, default=False)
    primeiro_acesso = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<User {self.email}>"


class Vendedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(40))

    def __repr__(self):
        return f"<Vendedor {self.nome}>"


class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # coluna que identifica o dono do cadastro (usuário logado)
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
    evidencia = db.Column(db.String(255))  # campo mantido por compatibilidade
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    # relacionamento com múltiplas evidências
    evidencias = db.relationship("Evidencia", backref="cliente", cascade="all,delete")

    def __repr__(self):
        return f"<Cliente {self.nome} - {self.cpf}>"


class Evidencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Evidencia {self.arquivo} (cliente {self.cliente_id})>"


# ===========================
# UTILITÁRIOS
# ===========================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def fmt_currency(value):
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"


app.jinja_env.filters["fmt"] = fmt_currency


# ===========================
# HELPERS — filtragem por usuário/admin
# ===========================
def soma_por_produto(usuario_id, text_match, is_admin=False):
    q = db.session.query(db.func.sum(Cliente.valor)).filter(
        Cliente.produto.ilike(f"%{text_match}%")
    )
    if not is_admin:
        q = q.filter(Cliente.usuario_id == usuario_id)
    return q.scalar() or 0.0


def soma_status(usuario_id, status, is_admin=False):
    q = db.session.query(db.func.sum(Cliente.valor)).filter(
        Cliente.status_contrato == status
    )
    if not is_admin:
        q = q.filter(Cliente.usuario_id == usuario_id)
    return q.scalar() or 0.0


# ===========================
# GARANTE USUÁRIO ADMIN PADRÃO
# ===========================
def ensure_admin():
    admin_email = "credmaisconsignados2022@gmail.com"
    admin_pass = "Latoya2019!"
    # função chamada dentro de app.app_context() para evitar erro de contexto
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
                flash("Usuário bloqueado!", "danger")
                return render_template("login.html", hora=datetime.now())

            if user.primeiro_acesso:
                session["primeiro_acesso_user_id"] = user.id
                return redirect(url_for("primeiro_acesso_finalizar"))

            session["usuario_id"] = user.id
            session["nome"] = user.nome
            session["email"] = user.email
            return redirect(url_for("dashboard"))

        flash("E-mail ou senha incorretos!", "danger")
        return render_template("login.html", hora=datetime.now())

    return render_template("login.html", hora=datetime.now())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ===========================
# PRIMEIRO ACESSO
# ===========================
@app.route("/primeiro_acesso", methods=["GET", "POST"])
def primeiro_acesso():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha_prov = request.form.get("senha_provisoria", "")

        user = User.query.filter(
            User.nome == nome,
            User.primeiro_acesso == True
        ).first()

        if not user:
            flash("Usuário não encontrado ou já finalizou o cadastro.", "warning")
            return render_template("primeiro_acesso.html", hora=datetime.now())

        if not check_password_hash(user.password, senha_prov):
            flash("Senha provisória incorreta!", "danger")
            return render_template("primeiro_acesso.html", hora=datetime.now())

        session["primeiro_acesso_user_id"] = user.id
        return redirect(url_for("primeiro_acesso_finalizar"))

    return render_template("primeiro_acesso.html", hora=datetime.now())


@app.route("/primeiro_acesso/finalizar", methods=["GET", "POST"])
def primeiro_acesso_finalizar():
    uid = session.get("primeiro_acesso_user_id")

    if not uid:
        flash("Valide seu nome e senha provisória antes.", "warning")
        return redirect(url_for("primeiro_acesso"))

    user = User.query.get(uid)

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        confirm = request.form.get("senha_confirm", "")

        if senha != confirm:
            flash("Senhas não coincidem!", "warning")
            return render_template("primeiro_acesso_finalizar.html", usuario=user, hora=datetime.now())

        if User.query.filter(User.email == email).first():
            flash("Email já está em uso!", "danger")
            return render_template("primeiro_acesso_finalizar.html", usuario=user, hora=datetime.now())

        user.email = email
        user.password = generate_password_hash(senha)
        user.primeiro_acesso = False
        db.session.commit()

        session.pop("primeiro_acesso_user_id", None)
        session["usuario_id"] = user.id
        session["nome"] = user.nome
        session["email"] = user.email

        flash("Cadastro finalizado! Você foi logado.", "success")
        return redirect(url_for("dashboard"))

    return render_template("primeiro_acesso_finalizar.html", usuario=user, hora=datetime.now())


# ===========================
# DASHBOARD — Filtrado por usuário (admin vê tudo)
# ===========================
@app.route("/dashboard")
def dashboard():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    uid = None if is_admin else session.get("usuario_id")

    produtos = {
        "Cartão": soma_por_produto(uid, "Cartão", is_admin),
        "Margem Novo": soma_por_produto(uid, "Margem Novo", is_admin),
        "Saque Complementar": soma_por_produto(uid, "Saque Complementar", is_admin),
        "Margem de Aumento 2026 (Acumulativo)": (
            soma_por_produto(uid, "Margem de Aumento 2026", is_admin) or
            soma_por_produto(uid, "Aumento 2026", is_admin)
        ),
        "Portabilidade": soma_por_produto(uid, "Portabilidade", is_admin),
        "FGTS/CLT": soma_por_produto(uid, "FGTS", is_admin),
        "Refin": soma_por_produto(uid, "Refin", is_admin),
        "Governo/Prefeitura": (soma_por_produto(uid, "Governo", is_admin) + soma_por_produto(uid, "Prefeitura", is_admin)),
        "Bolsa": soma_por_produto(uid, "Bolsa", is_admin),
        "Empréstimo Pessoal": soma_por_produto(uid, "Empréstimo Pessoal", is_admin),
    }

    pagos = soma_status(uid, "Pago", is_admin)
    em_aberto = soma_status(uid, "Em Aberto", is_admin)
    cancelados = soma_status(uid, "Cancelado", is_admin)

    return render_template(
        "dashboard.html",
        produtos=produtos,
        pagos=pagos,
        em_aberto=em_aberto,
        cancelados=cancelados,
        nome=session.get("nome"),
        hora=datetime.now()
    )


# ===========================
# CLIENTES (FILTRADO POR USUÁRIO)
# ===========================
@app.route("/clientes")
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

    # impede usuário de excluir cliente de outro usuário
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    if not is_admin and c.usuario_id != session.get("usuario_id"):
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))

    # remove arquivos relacionados na pasta
    for ev in c.evidencias:
        caminho = os.path.join(app.config["UPLOAD_FOLDER"], ev.arquivo)
        if os.path.exists(caminho):
            os.remove(caminho)

    db.session.delete(c)
    db.session.commit()

    flash("Cliente excluído!", "success")
    return redirect(url_for("clientes_view"))


# ===========================
# UPLOAD DE EVIDÊNCIA (MÚLTIPLOS)
# ===========================
@app.route("/upload_evidencia/<int:id>", methods=["POST"])
def upload_evidencia(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    cliente = Cliente.query.get(id)
    if not cliente:
        flash("Cliente não encontrado!", "warning")
        return redirect(url_for("clientes_view"))

    # bloqueia upload de cliente que não é do usuário
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    if not is_admin and cliente.usuario_id != session.get("usuario_id"):
        flash("Ação não permitida!", "danger")
        return redirect(url_for("clientes_view"))

    # aceita múltiplos arquivos com o campo 'arquivo'
    arquivos = request.files.getlist("arquivo")
    if not arquivos or len(arquivos) == 0:
        flash("Nenhum arquivo enviado!", "warning")
        return redirect(url_for("clientes_view"))

    enviados = 0
    for arquivo in arquivos:
        if arquivo and allowed_file(arquivo.filename):
            filename = secure_filename(
                f"{cliente.cpf}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{arquivo.filename}"
            )
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


# ===========================
# DOWNLOAD INDIVIDUAL DE EVIDÊNCIA
# ===========================
@app.route("/baixar_evidencia/<path:filename>")
def baixar_evidencia(filename):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # opção de segurança extra: checar se o arquivo pertence a um cliente do usuário
    ev = Evidencia.query.filter_by(arquivo=filename).first()
    if ev:
        cliente = Cliente.query.get(ev.cliente_id)
        is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
        if not is_admin and cliente.usuario_id != session.get("usuario_id"):
            flash("Ação não permitida!", "danger")
            return redirect(url_for("clientes_view"))

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True
    )


# compatibilidade com rota antiga (se você usar download_evidencia)
@app.route("/download_evidencia/<path:filename>")
def download_evidencia(filename):
    return baixar_evidencia(filename)


# ===========================
# EXCLUIR EVIDÊNCIA (POR ID)
# ===========================
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

    return render_template(
        "clientes.html",
        clientes=clientes,
        vendedores=vendedores,
        nome=session.get("nome"),
        hora=datetime.now()
    )


# ===========================
# USUÁRIOS (ADMIN)
# ===========================
@app.route("/usuarios")
def usuarios_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # Somente ADMIN pode acessar
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))

    usuarios = User.query.order_by(User.nome).all()

    return render_template(
        "usuarios.html",
        usuarios=usuarios,
        nome=session.get("nome"),
        hora=datetime.now()
    )


@app.route("/salvar_usuario", methods=["POST"])
def salvar_usuario():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # Somente ADMIN cria usuários
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))

    nome = request.form.get("nome")
    senha_prov = request.form.get("senha_provisoria")

    if not nome or not senha_prov:
        flash("Preencha nome e gere a senha provisória.", "warning")
        return redirect(url_for("usuarios_view"))

    placeholder = f"pendente_{uuid.uuid4().hex}@local"

    novo = User(
        nome=nome,
        email=placeholder,
        password=generate_password_hash(senha_prov),
        primeiro_acesso=True,
        bloqueado=False
    )
    db.session.add(novo)
    db.session.commit()

    flash("Usuário criado!", "success")
    return redirect(url_for("usuarios_view"))


@app.route("/bloquear_usuario/<int:id>")
def bloquear_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # Somente ADMIN pode bloquear
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))

    u = User.query.get(id)
    if u:
        u.bloqueado = True
        db.session.commit()
        flash("Usuário bloqueado!", "success")

    return redirect(url_for("usuarios_view"))


@app.route("/desbloquear_usuario/<int:id>")
def desbloquear_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # Somente ADMIN pode desbloquear
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))

    u = User.query.get(id)
    if u:
        u.bloqueado = False
        db.session.commit()
        flash("Usuário desbloqueado!", "success")

    return redirect(url_for("usuarios_view"))


@app.route("/excluir_usuario/<int:id>")
def excluir_usuario(id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # Somente ADMIN pode excluir
    if session.get("email") != "credmaisconsignados2022@gmail.com":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))

    u = User.query.get(id)
    if not u:
        flash("Usuário não encontrado!", "warning")
    else:
        db.session.delete(u)
        db.session.commit()
        flash("Usuário excluído!", "success")

    return redirect(url_for("usuarios_view"))


# ===========================
# VENDEDORES
# ===========================
@app.route("/vendedores", methods=["GET", "POST"])
def vendedores_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    if request.method == "POST":
        vid = request.form.get("id")
        nome = request.form.get("nome")
        telefone = request.form.get("telefone")

        if not nome or not telefone:
            flash("Preencha nome e telefone!", "warning")
            return redirect(url_for("vendedores_view"))

        if vid:
            v = Vendedor.query.get(int(vid))
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
    return render_template(
        "vendedores.html",
        vendedores=vendedores,
        nome=session.get("nome"),
        hora=datetime.now()
    )


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


# ===========================
# FUNÇÃO PDF RELATÓRIO
# ===========================
def gerar_relatorio_pdf(resultados, total):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    y = altura - 60
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(largura / 2, y, "Relatório de Vendas CredMais")
    y -= 30

    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Cliente")
    c.drawString(180, y, "CPF")
    c.drawString(300, y, "Produto")
    c.drawString(450, y, "Valor")
    y -= 15

    c.setFont("Helvetica", 10)

    for r in resultados:
        if y < 70:
            c.showPage()
            y = altura - 60
            c.setFont("Helvetica", 10)

        c.drawString(40, y, r.nome)
        c.drawString(180, y, r.cpf)
        c.drawString(300, y, r.produto)
        c.drawString(450, y, fmt_currency(r.valor))
        y -= 14

    c.setFont("Helvetica-Bold", 12)
    if y < 100:
        c.showPage()
        y = altura - 60

    c.drawRightString(largura - 40, y, f"TOTAL: {fmt_currency(total)}")

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="relatorio.pdf")


# ===========================
# RELATÓRIOS — CONSULTA + PDF (FILTRADO POR USUÁRIO)
# ===========================
@app.route("/relatorios", methods=["GET", "POST"])
def relatorios_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    # pega vendedores
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()

    # verifica se é admin
    is_admin = session.get("email") == "credmaisconsignados2022@gmail.com"
    uid = None if is_admin else session.get("usuario_id")

    resultados = []
    total = 0.0

    # ======================
    # CONSULTAR
    # ======================
    if request.method == "POST" and request.form.get("acao") == "consultar":

        data_inicio = request.form.get("data_inicio") or ""
        data_fim = request.form.get("data_fim") or ""
        vendedor_id = request.form.get("vendedor") or ""
        produto = request.form.get("produto") or ""
        cliente_nome = request.form.get("cliente_nome") or ""

        # salva filtros para o PDF
        session["filtro_data_inicio"] = data_inicio
        session["filtro_data_fim"] = data_fim
        session["filtro_vendedor"] = vendedor_id
        session["filtro_produto"] = produto
        session["filtro_cliente"] = cliente_nome

        # valida datas
        try:
            dt_i = datetime.strptime(data_inicio, "%Y-%m-%d") if data_inicio else datetime(2000, 1, 1)
            dt_f = datetime.strptime(data_fim, "%Y-%m-%d") if data_fim else datetime(2100, 1, 1)
            dt_f = datetime(dt_f.year, dt_f.month, dt_f.day, 23, 59, 59)
        except:
            flash("Datas inválidas!", "warning")
            return render_template(
                "relatorios.html",
                vendedores=vendedores,
                resultados=[],
                total=0.0,
                nome=session.get("nome"),
                hora=datetime.now()
            )

        # inicia consulta
        query = Cliente.query.filter(Cliente.criado_em.between(dt_i, dt_f))

        # filtra por dono dos dados (somente admin vê tudo)
        if not is_admin:
            query = query.filter(Cliente.usuario_id == uid)

        # filtra vendedor
        if vendedor_id != "":
            query = query.filter(Cliente.vendedor_id == int(vendedor_id))

        # filtra produto
        if produto != "":
            query = query.filter(Cliente.produto == produto)

        # filtra cliente pelo nome digitado
        if cliente_nome:
            query = query.filter(Cliente.nome.ilike(f"%{cliente_nome}%"))

        # executa
        resultados = query.order_by(Cliente.criado_em.desc()).all()
        total = sum(c.valor for c in resultados)

        return render_template(
            "relatorios.html",
            vendedores=vendedores,
            resultados=resultados,
            total=total,
            nome=session.get("nome"),
            hora=datetime.now()
        )

    # ======================
    # GERAR PDF
    # ======================
    if request.method == "POST" and request.form.get("acao") == "gerar_pdf":

        data_inicio = session.get("filtro_data_inicio")
        data_fim = session.get("filtro_data_fim")
        vendedor_id = session.get("filtro_vendedor")
        produto = session.get("filtro_produto")
        cliente_nome = session.get("filtro_cliente")

        # impede PDF sem consulta
        if data_inicio is None or data_fim is None:
            flash("Faça uma consulta primeiro!", "warning")
            return redirect(url_for("relatorios_view"))

        # datas
        dt_i = datetime.strptime(data_inicio, "%Y-%m-%d") if data_inicio else datetime(2000, 1, 1)
        dt_f = datetime.strptime(data_fim, "%Y-%m-%d") if data_fim else datetime(2100, 1, 1)
        dt_f = datetime(dt_f.year, dt_f.month, dt_f.day, 23, 59, 59)

        # refaz consulta
        query = Cliente.query.filter(Cliente.criado_em.between(dt_i, dt_f))

        # filtra por usuário
        if not is_admin:
            query = query.filter(Cliente.usuario_id == uid)

        # vendedor
        if vendedor_id:
            query = query.filter(Cliente.vendedor_id == int(vendedor_id))

        # produto
        if produto:
            query = query.filter(Cliente.produto == produto)

        # nome do cliente digitado
        if cliente_nome:
            query = query.filter(Cliente.nome.ilike(f"%{cliente_nome}%"))

        resultados = query.order_by(Cliente.criado_em.desc()).all()
        total = sum(c.valor for c in resultados)

        return gerar_relatorio_pdf(resultados, total)

    # ============= GET NORMAL =============
    return render_template(
        "relatorios.html",
        vendedores=vendedores,
        resultados=[],
        total=0.0,
        nome=session.get("nome"),
        hora=datetime.now()
    )


# ===========================
# CALCULADORA
# ===========================
@app.route("/calculadora")
def calculadora_view():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    return render_template(
        "calculadora.html",
        nome=session.get("nome"),
        hora=datetime.now()
    )


# ===========================
# GERAR PDF DA SIMULAÇÃO
# ===========================
@app.route("/gerar_pdf_simulacao", methods=["POST"])
def gerar_pdf_simulacao():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    nome = request.form.get("nome")
    cpf = request.form.get("cpf")
    tipo = request.form.get("tipo")

    # CARTÃO
    margem_cartao = request.form.get("margem_cartao")
    limite_cartao = request.form.get("limite_cartao")
    saque_cartao = request.form.get("saque_cartao")
    cartao_cartao = request.form.get("cartao_cartao")

    # AUMENTO 2026
    novo_salario = request.form.get("novo_salario")
    aumento_margem = request.form.get("aumento_margem")
    margem_nova = request.form.get("margem_nova")
    valor_liberado = request.form.get("valor_liberado")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    y = altura - 60

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(largura / 2, y, "Simulação CredMais")
    y -= 40

    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Cliente: {nome or ''}")
    y -= 15
    c.drawString(50, y, f"CPF: {cpf or ''}")
    y -= 30

    # -------------------
    # SIMULAÇÃO CARTÃO
    # -------------------
    if tipo in ["cartao", "ambos"] and margem_cartao:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "🪙 Simulação - Cartão Consignado")
        y -= 20

        c.setFont("Helvetica", 11)
        c.drawString(50, y, f"Margem: R$ {float(margem_cartao):,.2f}")
        y -= 15
        c.drawString(50, y, f"Limite: R$ {float(limite_cartao):,.2f}")
        y -= 15
        c.drawString(50, y, f"Saque: R$ {float(saque_cartao):,.2f}")
        y -= 15
        c.drawString(50, y, f"Cartão: R$ {float(cartao_cartao):,.2f}")
        y -= 30

    # -------------------
    # SIMULAÇÃO AUMENTO 2026
    # -------------------
    if tipo in ["margem", "ambos"] and novo_salario:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "📈 Simulação - Aumento Margem 2026")
        y -= 20

        c.setFont("Helvetica", 11)
        c.drawString(50, y, f"Novo Salário: R$ {float(novo_salario):,.2f}")
        y -= 15
        c.drawString(50, y, f"Aumento: R$ {float(aumento_margem):,.2f}")
        y -= 15
        c.drawString(50, y, f"Nova Margem: R$ {float(margem_nova):,.2f}")
        y -= 15
        c.drawString(50, y, f"Valor Liberado: R$ {float(valor_liberado):,.2f}")
        y -= 30

    c.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="simulacao.pdf"
    )


# ===========================
# ERRO DE ARQUIVO GRANDE
# ===========================
@app.errorhandler(413)
def request_entity_too_large(error):
    flash("Arquivo muito grande. Limite 10MB.", "danger")
    return redirect(request.referrer or url_for("clientes_view"))


# ===========================
# EXECUÇÃO FINAL
# ===========================
if __name__ == "__main__":
    # cria tabelas e garante admin dentro do contexto da app (evita erro de app context)
    with app.app_context():
        db.create_all()
        ensure_admin()

    app.run(host="0.0.0.0", port=5000, debug=True)

