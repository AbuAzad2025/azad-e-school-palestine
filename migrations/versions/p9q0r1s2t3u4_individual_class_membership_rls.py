"""Let an individual subscriber reach the class they actually paid for

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-10-05 00:00:00.000000

Why this migration exists
-------------------------
The hybrid-tenancy feature and the RLS policies disagree about what a tenant
is, and the disagreement is not a test artifact.

An individual student is linked to the platform's system school, and to no
other school at all. The class they subscribe to belongs to a real school they
hold no role link to. Every policy written so far answers "is this row mine?"
with exactly one value — ``app.current_school_id`` — so the system school hides
every page of the feature: the catalogue comes back empty,
``db.session.get(ClassRoom, …)`` returns ``None``, and ``subscribe_to_class``
reports "this course is not available" about a class sitting right there.
Registering as an individual failed too, with a 500, because seeding the system
school's twelve grades inserts into a tenant table from a request whose tenant
is school 0.

The fix is a second value, not a weaker first one. ``app.current_class_ids``
carries the classes the actor is an *active member* of, and the content graph
grows a read arm for them. ``class_members`` and ``subscriptions`` also grow a
``user_id`` arm, which is what makes the derivation non-circular: the actor's
own enrollment rows stay visible whatever the tenant is, so the list can be
read before the tenant narrows the session.

Two deliberate limits, both security decisions rather than shortcuts:

* The class arm is added to ``USING`` only. Read access to a class is not
  authority to author inside it — otherwise a student could insert lessons and
  assignments into any class they are enrolled in. Only ``class_members`` and
  ``subscriptions``, both keyed by the actor, widen ``WITH CHECK``, and even
  there the arm implies nothing about anybody else's row.
* ``classes`` additionally becomes cross-school *readable* when it is public —
  but only for actors carrying ``app.is_individual = '1'``. Browsing the
  catalogue is the point of the feature; handing the same reach to ordinary
  school tenants would be a new leak, not a restored function.

Nothing here refers to another policy-protected table from inside a policy, so
no new recursion is introduced.

Why the DDL is built by ``app.core.rls``
----------------------------------------
This migration does not restate the policy bodies. It calls
``build_all_policy_ddl``, the same pure function the runtime
``enable_all_rls_policies`` uses. Four of the failures that led here were
caused by a migration and a runtime helper disagreeing about what a policy
says; restating the bodies in a second place is how that happened once already
and is how it would happen again.

``downgrade()`` therefore rebuilds from the same registries rather than
restoring the previous revision's SQL, which the shared builder no longer knows
how to express. The pre-revision state is reachable with ``alembic downgrade
n7o8p9q0r1s2`` followed by ``upgrade`` of the two revisions this one replaces.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "p9q0r1s2t3u4"
down_revision = "o8p9q0r1s2t3"
branch_labels = None
depends_on = None


def _rebuild() -> list[str]:
    from app.core.rls import build_all_policy_ddl

    statements, skipped = build_all_policy_ddl(op.get_bind())
    if skipped:
        # Not fatal — a fresh database reaches the same state without the
        # tables that have not been migrated yet — but it is worth saying.
        print(f"[rls] tables without a policy in this database: {sorted(skipped)}")
    return statements


def upgrade() -> None:
    for statement in _rebuild():
        op.execute(statement)


def downgrade() -> None:
    for statement in _rebuild():
        op.execute(statement)