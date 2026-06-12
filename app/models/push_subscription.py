from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PushSubscription(Base):
    """
    Guarda uma inscrição de Web Push (um navegador/dispositivo por linha).

    Cada usuário pode ter várias inscrições (celular, desktop, etc.).
    O 'endpoint' é único e identifica o destino do push.

    OBS.: confirme que os nomes das tabelas referenciadas abaixo
    ("users.id" e "offices.id") batem com o __tablename__ dos seus
    models User e Office. "offices" já está confirmado no projeto;
    se o de usuário for diferente de "users", ajuste o ForeignKey.
    """

    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    # A quem pertence a inscrição
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Dados da inscrição vindos do navegador
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)

    # Metadados úteis
    user_agent = Column(String(400), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    # Relacionamentos (opcionais; só funcionam se os models tiverem
    # back_populates configurado — deixei sem back_populates para
    # não exigir alteração nos seus models existentes)
    user = relationship("User", lazy="joined", viewonly=True)
    office = relationship("Office", lazy="joined", viewonly=True)

    def as_subscription_info(self) -> dict:
        """Formato que o pywebpush espera."""
        return {
            "endpoint": self.endpoint,
            "keys": {
                "p256dh": self.p256dh,
                "auth": self.auth,
            },
        }