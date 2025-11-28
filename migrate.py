from app import db, Cliente, Vendedor

def migrar_vendedores():
    vendedores = Vendedor.query.all()
    count = 0

    for v in vendedores:
        if v.usuario_id:
            continue

        cliente = Cliente.query.filter_by(vendedor_id=v.id).first()

        if cliente:
            v.usuario_id = cliente.usuario_id
            count += 1

    db.session.commit()
    print(f"Migração concluída. Vendedores atualizados: {count}")

if __name__ == "__main__":
    migrar_vendedores()
