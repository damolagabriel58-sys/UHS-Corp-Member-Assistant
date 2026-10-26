
from datetime import datetime, timezone


from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utc_now():
    return datetime.now(timezone.utc)


class CorpsMember(Base):
    __tablename__ = "corps_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    state_code: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        index=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="corps_member"
    )


class Document(Base):
    __tablename__ = "documents"

    __table_args__ = (
        UniqueConstraint(
            "gmail_message_id",
            "attachment_id",
            name="uq_gmail_attachment",
        ),
        UniqueConstraint(
            "corps_member_id",
            "month",
            "document_type",
            name="uq_member_month_document_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    corps_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("corps_members.id"),
        nullable=True,
        index=True,
    )

    document_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    month: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    gmail_message_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    attachment_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    sender_email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending_review",
        index=True,
        nullable=False,
    )

    original_file_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    signed_file_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    corps_member: Mapped[CorpsMember | None] = relationship(
        back_populates="documents"
    )

    audit_logs: Mapped[list["DocumentAuditLog"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentAuditLog(Base):
    __tablename__ = "document_audit_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"),
        nullable=False,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    actor: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    document: Mapped["Document"] = relationship(
        back_populates="audit_logs"
    )
class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True, index=True)

    token_hash = Column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )

    email = Column(
        String(320),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    revoked_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class GmailCredential(Base):
    __tablename__ = "gmail_credentials"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
        nullable=False,
    )

    encrypted_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
