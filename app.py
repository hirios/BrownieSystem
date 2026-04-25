from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from datetime import datetime, date

app = Flask(__name__)
app.config['SECRET_KEY'] = 'brownie-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brownies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    preco_escola = db.Column(db.Float, default=0.0)
    preco_empresa = db.Column(db.Float, default=0.0)
    custo = db.Column(db.Float, default=0.0)
    comissao_escola = db.Column(db.Float, default=0.0)
    comissao_empresa = db.Column(db.Float, default=0.0)


class Vendedora(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    tem_comissao = db.Column(db.Boolean, default=True)
    comissao_escola = db.Column(db.Float, nullable=True)   # None = usa valor do produto
    comissao_empresa = db.Column(db.Float, nullable=True)  # None = usa valor do produto


class Lote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    data = db.Column(db.Date, default=date.today)
    observacao = db.Column(db.String(200))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    produto = db.relationship('Produto', backref='lotes')


class Transacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)
    vendedora_id = db.Column(db.Integer, db.ForeignKey('vendedora.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    local = db.Column(db.String(20))
    preco_unitario = db.Column(db.Float, default=0.0)
    data = db.Column(db.Date, default=date.today)
    observacao = db.Column(db.String(200))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    vendedora = db.relationship('Vendedora', backref='transacoes')
    produto = db.relationship('Produto', backref='transacoes')


def run_migrations():
    inspector = inspect(db.engine)
    produto_cols = [c['name'] for c in inspector.get_columns('produto')]
    with db.engine.connect() as conn:
        if 'preco_escola' not in produto_cols:
            conn.execute(text("ALTER TABLE produto ADD COLUMN preco_escola FLOAT DEFAULT 0.0"))
            if 'preco' in produto_cols:
                conn.execute(text("UPDATE produto SET preco_escola = preco"))
            conn.commit()
        if 'preco_empresa' not in produto_cols:
            conn.execute(text("ALTER TABLE produto ADD COLUMN preco_empresa FLOAT DEFAULT 0.0"))
            conn.commit()
        if 'comissao_escola' not in produto_cols:
            conn.execute(text("ALTER TABLE produto ADD COLUMN comissao_escola FLOAT DEFAULT 0.0"))
            conn.execute(text("UPDATE produto SET comissao_escola = 1.75 WHERE nome = 'Brownie Normal'"))
            conn.execute(text("UPDATE produto SET comissao_escola = 2.50 WHERE nome = 'Brownie Recheado'"))
            conn.commit()
        if 'comissao_empresa' not in produto_cols:
            conn.execute(text("ALTER TABLE produto ADD COLUMN comissao_empresa FLOAT DEFAULT 0.0"))
            conn.execute(text("UPDATE produto SET comissao_empresa = 2.00 WHERE nome = 'Brownie Normal'"))
            conn.execute(text("UPDATE produto SET comissao_empresa = 2.50 WHERE nome = 'Brownie Recheado'"))
            conn.commit()

    if 'vendedora' in inspector.get_table_names():
        vendedora_cols = [c['name'] for c in inspector.get_columns('vendedora')]
        with db.engine.connect() as conn:
            if 'tem_comissao' not in vendedora_cols:
                conn.execute(text("ALTER TABLE vendedora ADD COLUMN tem_comissao BOOLEAN DEFAULT 1"))
                conn.execute(text("UPDATE vendedora SET tem_comissao = 0 WHERE LOWER(nome) = 'rafa'"))
                conn.commit()
            if 'comissao_escola' not in vendedora_cols:
                conn.execute(text("ALTER TABLE vendedora ADD COLUMN comissao_escola FLOAT"))
                conn.commit()
            if 'comissao_empresa' not in vendedora_cols:
                conn.execute(text("ALTER TABLE vendedora ADD COLUMN comissao_empresa FLOAT"))
                conn.commit()

    if 'transacao' in inspector.get_table_names():
        transacao_cols = [c['name'] for c in inspector.get_columns('transacao')]
        with db.engine.connect() as conn:
            if 'local' not in transacao_cols:
                conn.execute(text("ALTER TABLE transacao ADD COLUMN local VARCHAR(20)"))
                conn.commit()
            if 'preco_unitario' not in transacao_cols:
                conn.execute(text("ALTER TABLE transacao ADD COLUMN preco_unitario FLOAT DEFAULT 0.0"))
                conn.execute(text("""
                    UPDATE transacao
                    SET preco_unitario = (
                        SELECT p.preco_escola FROM produto p WHERE p.id = transacao.produto_id
                    )
                    WHERE tipo = 'venda' AND (preco_unitario IS NULL OR preco_unitario = 0)
                """))
                conn.commit()


def _parse_datas(ini_str, fim_str):
    """Converte strings ISO para objetos date, retornando None em caso de erro."""
    try:
        ini = date.fromisoformat(ini_str) if ini_str else None
    except ValueError:
        ini = None
    try:
        fim = date.fromisoformat(fim_str) if fim_str else None
    except ValueError:
        fim = None
    return ini, fim


def calcular_stats(data_inicio=None, data_fim=None):
    """
    Calcula estatísticas respeitando o filtro de data.
    Usa queries pré-filtradas em vez dos relacionamentos ORM para garantir
    que apenas registros no período selecionado sejam computados.
    """
    produtos = Produto.query.all()
    vendedoras = Vendedora.query.filter_by(ativo=True).all()
    ids_sem_comissao = {v.id for v in Vendedora.query.filter_by(tem_comissao=False).all()}

    lotes_q = Lote.query
    trans_q = Transacao.query
    if data_inicio:
        lotes_q = lotes_q.filter(Lote.data >= data_inicio)
        trans_q = trans_q.filter(Transacao.data >= data_inicio)
    if data_fim:
        lotes_q = lotes_q.filter(Lote.data <= data_fim)
        trans_q = trans_q.filter(Transacao.data <= data_fim)

    lotes_list = lotes_q.all()
    trans_list = trans_q.all()

    # Índices para lookup rápido por ID
    lotes_por_prod = {}
    for l in lotes_list:
        lotes_por_prod.setdefault(l.produto_id, []).append(l)

    trans_por_prod = {}
    for t in trans_list:
        trans_por_prod.setdefault(t.produto_id, []).append(t)

    trans_por_vend = {}
    for t in trans_list:
        trans_por_vend.setdefault(t.vendedora_id, []).append(t)

    produto_by_id = {p.id: p for p in produtos}
    vendedora_by_id = {v.id: v for v in Vendedora.query.all()}

    stats_produtos = []
    total_custo = 0.0
    total_receita_real = 0.0
    total_lucro_esp_escola = 0.0
    total_lucro_esp_empresa = 0.0
    total_comissao_paga = 0.0
    total_lucro_esp_escola_liquido = 0.0
    total_lucro_esp_empresa_liquido = 0.0
    total_produzido = 0
    total_vendido = 0
    total_comido = 0

    for p in produtos:
        lotes = lotes_por_prod.get(p.id, [])
        trans = trans_por_prod.get(p.id, [])

        lotes_qtd = sum(l.quantidade for l in lotes)
        vendas = [t for t in trans if t.tipo == 'venda']
        comidos_t = [t for t in trans if t.tipo == 'comido']

        vendas_qtd = sum(t.quantidade for t in vendas)
        comido_qtd = sum(t.quantidade for t in comidos_t)
        estoque = lotes_qtd - vendas_qtd - comido_qtd

        custo = lotes_qtd * p.custo
        receita_real = sum(t.quantidade * (t.preco_unitario or 0) for t in vendas)
        lucro_real = receita_real - custo

        lucro_esp_escola = lotes_qtd * p.preco_escola - custo
        lucro_esp_empresa = lotes_qtd * p.preco_empresa - custo

        vendas_escola_qtd = sum(t.quantidade for t in vendas if t.local == 'escola')
        vendas_empresa_qtd = sum(t.quantidade for t in vendas if t.local == 'empresa')
        receita_escola = sum(t.quantidade * (t.preco_unitario or 0) for t in vendas if t.local == 'escola')
        receita_empresa = sum(t.quantidade * (t.preco_unitario or 0) for t in vendas if t.local == 'empresa')
        # Lucro bruto por canal: receita do canal − custo das unidades vendidas naquele canal
        lucro_real_escola = receita_escola - vendas_escola_qtd * p.custo
        lucro_real_empresa = receita_empresa - vendas_empresa_qtd * p.custo

        # Comissões pagas: exclui vendedoras sem comissão; usa taxa individual se definida
        comissao_paga_escola = 0.0
        comissao_paga_empresa = 0.0
        for t in vendas:
            if t.vendedora_id in ids_sem_comissao:
                continue
            v_t = vendedora_by_id.get(t.vendedora_id)
            if t.local == 'escola':
                rate = (v_t.comissao_escola if v_t and v_t.comissao_escola is not None else p.comissao_escola) or 0
                comissao_paga_escola += t.quantidade * rate
            elif t.local == 'empresa':
                rate = (v_t.comissao_empresa if v_t and v_t.comissao_empresa is not None else p.comissao_empresa) or 0
                comissao_paga_empresa += t.quantidade * rate
        comissao_paga_total = comissao_paga_escola + comissao_paga_empresa

        lucro_liquido = lucro_real - comissao_paga_total
        lucro_liquido_escola = lucro_real_escola - comissao_paga_escola
        lucro_liquido_empresa = lucro_real_empresa - comissao_paga_empresa

        lucro_esp_escola_liquido = lucro_esp_escola - lotes_qtd * (p.comissao_escola or 0)
        lucro_esp_empresa_liquido = lucro_esp_empresa - lotes_qtd * (p.comissao_empresa or 0)

        stats_produtos.append({
            'produto': p,
            'lotes_qtd': lotes_qtd,
            'vendas_qtd': vendas_qtd,
            'comido_qtd': comido_qtd,
            'estoque': estoque,
            'custo': custo,
            'receita_real': receita_real,
            'lucro_real': lucro_real,
            'lucro_liquido': lucro_liquido,
            'lucro_esp_escola': lucro_esp_escola,
            'lucro_esp_empresa': lucro_esp_empresa,
            'lucro_esp_escola_liquido': lucro_esp_escola_liquido,
            'lucro_esp_empresa_liquido': lucro_esp_empresa_liquido,
            'vendas_escola_qtd': vendas_escola_qtd,
            'vendas_empresa_qtd': vendas_empresa_qtd,
            'receita_escola': receita_escola,
            'receita_empresa': receita_empresa,
            'lucro_real_escola': lucro_real_escola,
            'lucro_real_empresa': lucro_real_empresa,
            'lucro_liquido_escola': lucro_liquido_escola,
            'lucro_liquido_empresa': lucro_liquido_empresa,
            'comissao_paga_escola': comissao_paga_escola,
            'comissao_paga_empresa': comissao_paga_empresa,
            'comissao_paga_total': comissao_paga_total,
        })

        total_custo += custo
        total_receita_real += receita_real
        total_lucro_esp_escola += lucro_esp_escola
        total_lucro_esp_empresa += lucro_esp_empresa
        total_comissao_paga += comissao_paga_total
        total_lucro_esp_escola_liquido += lucro_esp_escola_liquido
        total_lucro_esp_empresa_liquido += lucro_esp_empresa_liquido
        total_produzido += lotes_qtd
        total_vendido += vendas_qtd
        total_comido += comido_qtd

    stats_vendedoras = []
    for v in vendedoras:
        trans_v = trans_por_vend.get(v.id, [])
        vendas = [t for t in trans_v if t.tipo == 'venda']
        comidos = [t for t in trans_v if t.tipo == 'comido']
        receita = sum(t.quantidade * (t.preco_unitario or 0) for t in vendas)

        comissao_escola = 0.0
        comissao_empresa_total = 0.0
        if v.tem_comissao:
            for t in vendas:
                p_t = produto_by_id.get(t.produto_id)
                if p_t:
                    if t.local == 'escola':
                        rate = (v.comissao_escola if v.comissao_escola is not None else p_t.comissao_escola) or 0
                        comissao_escola += t.quantidade * rate
                    elif t.local == 'empresa':
                        rate = (v.comissao_empresa if v.comissao_empresa is not None else p_t.comissao_empresa) or 0
                        comissao_empresa_total += t.quantidade * rate
        comissao_empresa_individual = comissao_empresa_total / 3
        comissao_total_individual = comissao_escola + comissao_empresa_individual
        comissao_total_bruto = comissao_escola + comissao_empresa_total

        stats_vendedoras.append({
            'vendedora': v,
            'total_vendas_qtd': sum(t.quantidade for t in vendas),
            'total_comidos_qtd': sum(t.quantidade for t in comidos),
            'receita': receita,
            'comissao_escola': comissao_escola,
            'comissao_empresa_total': comissao_empresa_total,
            'comissao_empresa_individual': comissao_empresa_individual,
            'comissao_total_individual': comissao_total_individual,
            'comissao_total_bruto': comissao_total_bruto,
        })

    stats_vendedoras.sort(key=lambda x: x['receita'], reverse=True)

    total_lucro_bruto = total_receita_real - total_custo
    return {
        'stats_produtos': stats_produtos,
        'stats_vendedoras': stats_vendedoras,
        'max_receita': max((s['receita'] for s in stats_vendedoras), default=0),
        'total_custo': total_custo,
        'total_receita_real': total_receita_real,
        'total_lucro_real': total_lucro_bruto,
        'total_lucro_bruto': total_lucro_bruto,
        'total_lucro_liquido': total_lucro_bruto - total_comissao_paga,
        'total_comissao_paga': total_comissao_paga,
        'total_lucro_esp_escola': total_lucro_esp_escola,
        'total_lucro_esp_empresa': total_lucro_esp_empresa,
        'total_lucro_esp_escola_liquido': total_lucro_esp_escola_liquido,
        'total_lucro_esp_empresa_liquido': total_lucro_esp_empresa_liquido,
        'total_produzido': total_produzido,
        'total_vendido': total_vendido,
        'total_comido': total_comido,
        'total_estoque': total_produzido - total_vendido - total_comido,
    }


@app.route('/')
def dashboard():
    ini_str = request.args.get('data_inicio', '').strip()
    fim_str = request.args.get('data_fim', '').strip()
    data_inicio, data_fim = _parse_datas(ini_str, fim_str)
    # Normaliza strings para valores reais parseados (limpa entradas inválidas)
    ini_str = data_inicio.isoformat() if data_inicio else ''
    fim_str = data_fim.isoformat() if data_fim else ''

    stats = calcular_stats(data_inicio=data_inicio, data_fim=data_fim)

    recentes_q = Transacao.query.order_by(Transacao.criado_em.desc())
    if data_inicio:
        recentes_q = recentes_q.filter(Transacao.data >= data_inicio)
    if data_fim:
        recentes_q = recentes_q.filter(Transacao.data <= data_fim)
    recentes = recentes_q.limit(10).all()

    return render_template('dashboard.html',
                           stats=stats,
                           recentes=recentes,
                           data_inicio=ini_str,
                           data_fim=fim_str,
                           data_inicio_dt=data_inicio,
                           data_fim_dt=data_fim)


@app.route('/configuracoes', methods=['GET', 'POST'])
def configuracoes():
    if request.method == 'POST':
        for p in Produto.query.all():
            try:
                p.preco_escola = float(request.form.get(f'preco_escola_{p.id}') or 0)
                p.preco_empresa = float(request.form.get(f'preco_empresa_{p.id}') or 0)
                p.custo = float(request.form.get(f'custo_{p.id}') or 0)
                p.comissao_escola = float(request.form.get(f'comissao_escola_{p.id}') or 0)
                p.comissao_empresa = float(request.form.get(f'comissao_empresa_{p.id}') or 0)
            except ValueError:
                pass
        db.session.commit()
        flash('Configurações salvas com sucesso!', 'success')
        return redirect(url_for('configuracoes'))

    produtos = Produto.query.all()
    vendedoras = Vendedora.query.all()
    return render_template('configuracoes.html', produtos=produtos, vendedoras=vendedoras)


@app.route('/lancamentos')
def lancamentos():
    produtos = Produto.query.all()
    vendedoras = Vendedora.query.filter_by(ativo=True).all()
    stats = calcular_stats()
    today = date.today().isoformat()
    return render_template('lancamentos.html', produtos=produtos, vendedoras=vendedoras,
                           stats=stats, today=today)


@app.route('/lancamentos/lote', methods=['POST'])
def add_lote():
    produto_id = request.form.get('produto_id')
    quantidade = request.form.get('quantidade')
    data_str = request.form.get('data')
    observacao = request.form.get('observacao', '').strip()

    if not produto_id or not quantidade or int(quantidade) < 1:
        flash('Preencha todos os campos obrigatórios.', 'error')
        return redirect(url_for('lancamentos'))

    data = date.fromisoformat(data_str) if data_str else date.today()
    db.session.add(Lote(produto_id=int(produto_id), quantidade=int(quantidade),
                        data=data, observacao=observacao))
    db.session.commit()
    flash('Lote de produção registrado!', 'success')
    return redirect(url_for('lancamentos'))


@app.route('/lancamentos/transacao', methods=['POST'])
def add_transacao():
    tipo = request.form.get('tipo')
    vendedora_id = request.form.get('vendedora_id')
    produto_id = request.form.get('produto_id')
    quantidade = request.form.get('quantidade')
    local = request.form.get('local') or None
    data_str = request.form.get('data')
    observacao = request.form.get('observacao', '').strip()

    if not all([tipo, vendedora_id, produto_id, quantidade]) or int(quantidade) < 1:
        flash('Preencha todos os campos obrigatórios.', 'error')
        return redirect(url_for('lancamentos'))

    if tipo == 'venda' and not local:
        flash('Selecione o local de venda (Escola ou Empresa).', 'error')
        return redirect(url_for('lancamentos'))

    preco_unitario = 0.0
    if tipo == 'venda':
        produto = Produto.query.get(int(produto_id))
        preco_unitario = produto.preco_escola if local == 'escola' else produto.preco_empresa

    data = date.fromisoformat(data_str) if data_str else date.today()
    db.session.add(Transacao(tipo=tipo, vendedora_id=int(vendedora_id), produto_id=int(produto_id),
                             quantidade=int(quantidade), local=local, preco_unitario=preco_unitario,
                             data=data, observacao=observacao))
    db.session.commit()
    flash('Venda registrada!' if tipo == 'venda' else 'Consumo registrado!', 'success')
    return redirect(url_for('lancamentos'))


@app.route('/historico')
def historico():
    ini_str = request.args.get('data_inicio', '').strip()
    fim_str = request.args.get('data_fim', '').strip()
    data_inicio, data_fim = _parse_datas(ini_str, fim_str)
    ini_str = data_inicio.isoformat() if data_inicio else ''
    fim_str = data_fim.isoformat() if data_fim else ''

    lotes_q = Lote.query.order_by(Lote.criado_em.desc())
    transacoes_q = Transacao.query.order_by(Transacao.criado_em.desc())
    if data_inicio:
        lotes_q = lotes_q.filter(Lote.data >= data_inicio)
        transacoes_q = transacoes_q.filter(Transacao.data >= data_inicio)
    if data_fim:
        lotes_q = lotes_q.filter(Lote.data <= data_fim)
        transacoes_q = transacoes_q.filter(Transacao.data <= data_fim)

    return render_template('historico.html',
                           lotes=lotes_q.all(),
                           transacoes=transacoes_q.all(),
                           data_inicio=ini_str,
                           data_fim=fim_str,
                           data_inicio_dt=data_inicio,
                           data_fim_dt=data_fim)


@app.route('/configuracoes/vendedoras', methods=['POST'])
def salvar_comissoes_vendedoras():
    for v in Vendedora.query.all():
        val_escola = request.form.get(f'comissao_escola_{v.id}', '').strip()
        val_empresa = request.form.get(f'comissao_empresa_{v.id}', '').strip()
        try:
            v.comissao_escola = float(val_escola) if val_escola else None
        except ValueError:
            pass
        try:
            v.comissao_empresa = float(val_empresa) if val_empresa else None
        except ValueError:
            pass
    db.session.commit()
    flash('Comissões das vendedoras salvas!', 'success')
    return redirect(url_for('configuracoes'))


@app.route('/vendedora/<int:id>/toggle_comissao', methods=['POST'])
def toggle_comissao(id):
    v = Vendedora.query.get_or_404(id)
    v.tem_comissao = not v.tem_comissao
    db.session.commit()
    status = 'ativada' if v.tem_comissao else 'desativada'
    flash(f'Comissão {status} para {v.nome}.', 'success')
    return redirect(url_for('configuracoes'))


@app.route('/deletar/lote/<int:id>', methods=['POST'])
def deletar_lote(id):
    lote = Lote.query.get_or_404(id)
    db.session.delete(lote)
    db.session.commit()
    flash('Lote removido.', 'success')
    return redirect(url_for('historico'))


@app.route('/deletar/transacao/<int:id>', methods=['POST'])
def deletar_transacao(id):
    t = Transacao.query.get_or_404(id)
    db.session.delete(t)
    db.session.commit()
    flash('Registro removido.', 'success')
    return redirect(url_for('historico'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        run_migrations()
        if not Produto.query.first():
            db.session.add_all([
                Produto(nome='Brownie Normal', preco_escola=0.0, preco_empresa=0.0, custo=0.0,
                        comissao_escola=1.75, comissao_empresa=2.00),
                Produto(nome='Brownie Recheado', preco_escola=0.0, preco_empresa=0.0, custo=0.0,
                        comissao_escola=2.50, comissao_empresa=2.50),
            ])
        if not Vendedora.query.first():
            db.session.add_all([
                Vendedora(nome='Priscila'), Vendedora(nome='Ana'), Vendedora(nome='Rafa', tem_comissao=False),
                Vendedora(nome='Elisa'), Vendedora(nome='Isadora'),
            ])
        db.session.commit()
    app.run(host='0.0.0.0',port=5000, debug=True)
