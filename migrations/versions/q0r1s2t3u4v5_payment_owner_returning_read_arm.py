"""Payment owner reads own manual payments — USING arm for INSERT..RETURNING

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-10-14 00:00:00.000000

Why this migration exists
-------------------------
The subscription-owner arm on ``manual_payments``/``payment_receipts`` was
granted to ``WITH CHECK`` only. That is not enough: the ORM issues
``INSERT ... RETURNING``, and PostgreSQL checks the RETURNING rows against
``USING`` as well. The individual student (owner of a pending subscription,
tenant 0, no active membership) passes ``WITH CHECK`` through the owner arm,
then fails ``USING`` on the very same statement — so recording their own
manual payment raised 503 and closed the payment loop (AZ-P0-01).

The runtime builder in ``app.core.rls`` now adds the owner arm to both arms.
This migration replays the same builder so deployed databases carry the
identical policy text — the pattern set by ``p9q0r1s2t3u4`` after four
failures were caused by a migration and the runtime helper disagreeing.

The arm is scoped to the subscription's owner, so it reveals no other user's
row; tenant-scoped reads stay exactly as narrow as they were.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "q0r1s2t3u4v5"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on = None


def _rebuild() -> list[str]:
    from app.core.rls import build_all_policy_ddl

    statements, skipped = build_all_policy_ddl(op.get_bind())
    if skipped:
        print(f"[rls] tables without a policy in this database: {sorted(skipped)}")
    return statements


def upgrade() -> None:
    for statement in _rebuild():
        op.execute(statement)


def downgrade() -> None:
    # يعيد النص السابق؟ لا — البناء الحي بعد هذه المراجعة يظل حاملاً الذراع.
    # الرجوع الفعلي هو حالة ما قبل q0r1s2t3u4v5، وتعبيره هو نفسه الزرع من
    # البناء الحي فقط عندما يُستدعى على مصدر ما قبل التعديل؛ أثر الترقية
    # يبقى إبناء السياسات مطابقة للمنشئ الحي دائماً.
    for statement in _rebuild():
        op.execute(statement)
