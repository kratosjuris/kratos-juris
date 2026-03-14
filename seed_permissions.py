from app.core.database import SessionLocal
from app.core.permission_seed import seed_permissions

def main():
    db = SessionLocal()
    try:
        created, existing = seed_permissions(db)
        print("=" * 60)
        print("SEED DE PERMISSÕES DO KRATOS")
        print(f"Criadas:    {created}")
        print(f"Existentes: {existing}")
        print("=" * 60)
    finally:
        db.close()

if __name__ == "__main__":
    main()