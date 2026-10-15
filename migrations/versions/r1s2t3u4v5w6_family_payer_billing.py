"""Family payer billing — payer identity on subscriptions and manual payments

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-10-15 00:00:00.000000

Why this migration exists
-------------------------
AZ-P0-03: every billing route was gated to the student role — the parent, a
full role that already exists on the platform, could not pay for their linked
child, and no family statement screen listed the child's fees. Paying *for*
somebody needs an identity for the somebody who paid; ``user_id`` must keep
meaning "the subscriber" (access, invoices, membership activation all hang off
it), so the payer travels in its own column.

Two columns, both deliberately ``nullable`` — absence is meaningful, not
unknown: ``NULL`` says the payer is the subscriber themselves (the student),
the only shape that exists before this feature. No backfill: every historical
row was paid by its owner.

* ``subscriptions.payer_id`` — who initiated the subscription (set when a
  parent subscribes on behalf of their linked child).
* ``manual_payments.payer_id`` — who actually sent each payment; the admin
  review screen shows it next to the reference.

Why the guards
--------------
The test suite creates its schema with ``create_all`` (models, not migrations)
and toggles this revision directly on the same database, so the columns may
already exist when ``upgrade()`` runs and must survive a repeatable
upgrade/downgrade/upgrade cycle. Hence ``ADD COLUMN IF NOT EXISTS`` and
``DROP COLUMN IF EXISTS`` — plain expressions here would 500 on the second
run. Alembic autogenerate emits plain DDL; the guards are the whole reason
this file is handwritten.

Indexes mirror the model: both columns are filterable (future "paid by a
parent" admin reports), and both are sparse in the common case.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "r1s2t3u4v5w6"
down_revision = "q0r1s2t3u4v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS payer_id INTEGER REFERENCES users(id) ON DELETE SET NULL"  # nosec B608 — يستهدف جدولين ثابتين لا مدخلات
    )
    op.execute(
        "ALTER TABLE manual_payments ADD COLUMN IF NOT EXISTS payer_id INTEGER REFERENCES users(id) ON DELETE SET NULL"  # nosec B608 — استهداف ثابت
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_payer_id ON subscriptions (payer_id)")  # nosec B608
    op.execute("CREATE INDEX IF NOT EXISTS ix_manual_payments_payer_id ON manual_payments (payer_id)")  # nosec B608


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_manual_payments_payer_id")  # nosec B608 — أسماء ثابتة
    op.execute("DROP INDEX IF EXISTS ix_subscriptions_payer_id")  # nosec B608 — أسماء ثابتة
    op.execute("ALTER TABLE manual_payments DROP COLUMN IF EXISTS payer_id")  # nosec B608
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS payer_id")  # nosec B608
