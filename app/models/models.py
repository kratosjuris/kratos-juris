from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Receber(db.Model):
    __tablename__ = "receber"

    id = db.Column(db.Integer, primary_key=True)

    # dados principais
    cliente = db.Column(db.String(160), nullable=False)
    cpfcnpj = db.Column(db.String(20), nullable=True)
    processo = db.Column(db.String(60), nullable=True)
    categoria = db.Column(db.String(40), nullable=False, default="Honorários")

    valor = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # datas
    vencimento = db.Column(db.Date, nullable=False)
    recebido_em = db.Column(db.Date, nullable=True)

    # status e forma
    status = db.Column(db.String(20), nullable=False, default="Pendente")  # Pendente/Recebido/Parcial/Cancelado
    forma = db.Column(db.String(30), nullable=True)  # PIX/Transferência/etc.

    obs = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
