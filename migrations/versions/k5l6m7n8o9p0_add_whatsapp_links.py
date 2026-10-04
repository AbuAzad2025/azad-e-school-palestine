"""whatsapp_links — ربط أرقام واتساب بالحسابات المؤكَّدة

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-10-03

الجدول يربط رقماً بصيغة E.164 بحساب ومدرسة. فريد على الرقم وحده لأن
الويب هوك لا يعرف المدرسة مسبقاً — فالبحث O(1) بفهرس فريد بدل مسح.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("whatsapp_links"):
        return

    op.create_table(
        "whatsapp_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("school_id", sa.BigInteger(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("phone", name="uq_whatsapp_link_phone"),
    )
    op.create_index("ix_whatsapp_links_user_id", "whatsapp_links", ["user_id"])
    op.create_index("ix_whatsapp_links_school_id", "whatsapp_links", ["school_id"])
    op.create_index("ix_whatsapp_links_user_active", "whatsapp_links", ["user_id", "is_active"])

    op.execute(sa.text("ALTER TABLE whatsapp_links ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE whatsapp_links FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_whatsapp_links ON whatsapp_links"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_whatsapp_links ON whatsapp_links
                FOR ALL
                USING (
                    current_setting('app.is_super_admin', true) = '1'
                    OR school_id = current_setting('app.current_school_id', true)::bigint
                )
                WITH CHECK (
                    current_setting('app.is_super_admin', true) = '1'
                    OR school_id = current_setting('app.current_school_id', true)::bigint
                )
            """
        )
    )


def downgrade() -> None:
    if not _table_exists("whatsapp_links"):
        return
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_whatsapp_links ON whatsapp_links"))
    op.drop_table("whatsapp_links")
