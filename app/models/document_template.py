from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.core.database import Base


class OfficeDocumentTemplate(Base):
    __tablename__ = "office_document_templates"

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    doc_key = Column(String(60), nullable=False, index=True)
    display_name = Column(String(150), nullable=False)

    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)

    file_size = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)

    is_active = Column(Boolean, nullable=False, default=True, index=True)

    detected_placeholders = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


Index(
    "ix_office_document_templates_office_doc_active",
    OfficeDocumentTemplate.office_id,
    OfficeDocumentTemplate.doc_key,
    OfficeDocumentTemplate.is_active,
)