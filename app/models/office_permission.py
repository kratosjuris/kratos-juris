from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class OfficePermission(Base):
    __tablename__ = "office_permissions"
    __table_args__ = (
        UniqueConstraint("office_id", "permission_id", name="uq_office_permission"),
    )

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    permission_id = Column(
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    office = relationship("Office", back_populates="permission_links")
    permission = relationship("Permission")

    def __repr__(self) -> str:
        return (
            f"<OfficePermission office_id={self.office_id} "
            f"permission_id={self.permission_id}>"
        )