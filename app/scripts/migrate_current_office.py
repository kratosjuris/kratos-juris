from __future__ import annotations

from app.core.database import SessionLocal, create_tables
from app.models.office import Office
from app.models.user import User


OFFICE_NAME = "Kratos Juris"


def main():
    print("=" * 70)
    print("MIGRAÇÃO DO ESCRITÓRIO ATUAL")
    print("=" * 70)

    create_tables()

    db = SessionLocal()
    try:
        office = (
            db.query(Office)
            .filter(Office.nome == OFFICE_NAME)
            .first()
        )

        if office:
            print(f"[OK] Escritório já existe: id={office.id} nome={office.nome}")
        else:
            office = Office(nome=OFFICE_NAME)
            db.add(office)
            db.commit()
            db.refresh(office)
            print(f"[OK] Escritório criado: id={office.id} nome={office.nome}")

        users_without_office = (
            db.query(User)
            .filter(User.office_id.is_(None))
            .all()
        )

        updated = 0
        for user in users_without_office:
            user.office_id = office.id
            updated += 1

        if updated:
            db.commit()

        print(f"[OK] Usuários vinculados ao escritório atual: {updated}")

        total_users_in_office = (
            db.query(User)
            .filter(User.office_id == office.id)
            .count()
        )

        users_still_without_office = (
            db.query(User)
            .filter(User.office_id.is_(None))
            .count()
        )

        print("-" * 70)
        print(f"Escritório principal: id={office.id} | nome={office.nome}")
        print(f"Total de usuários neste escritório: {total_users_in_office}")
        print(f"Usuários ainda sem escritório: {users_still_without_office}")
        print("=" * 70)

    except Exception as e:
        db.rollback()
        print(f"[ERRO] Falha na migração: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()