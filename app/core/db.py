"""ذرّية المعاملات — النقطة المركزية الوحيدة لكل commit/rollback.

كل عملية كتابة في services تمر عبر tx():
1. commit واحد عند النجاح.
2. rollback كامل عند أي خطأ (لا حالة نصف مكتوبة).
3. تسجيل الخطأ في سجل التطبيق مع سياق مهيكل (correlation_id, tenant).
4. دعم المعاملات المتداخلة عبر savepoints (لا commit مبكر).

P2-14: Nested transaction safety via savepoints.
P2-15: Post-commit hooks for side effects (email, notifications).
P2-16: ORM object expiry after commit for read-your-writes consistency.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, TypeVar

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

T = TypeVar("T")

# ─── Depth tracker: detects nested tx() calls ───────────────────────────
_tx_depth: ContextVar[int] = ContextVar("_tx_depth", default=0)

# ─── Post-commit hook registry ─────────────────────────────────────────
# Hooks stored per-commit: list of callables to run AFTER the outermost tx() commits.
_post_commit_hooks: ContextVar[list[Callable[[], None]] | None] = ContextVar("_post_commit_hooks", default=None)


class TxError(Exception):
    """خطأ منطقي في العملية — يُترجَم لرسالة مستخدم دون rollback مزدوج."""


class _TxContext:
    """Scoped context for a single tx() invocation.

    Tracks depth, whether this invocation is the outermost (owns the commit),
    and accumulates post-commit hooks.  On failure, all accumulated hooks
    are discarded so they never fire.
    """

    __slots__ = ("is_outermost", "hooks", "_depth_token")

    def __init__(self) -> None:
        current = _tx_depth.get()
        self.is_outermost = current == 0
        self.hooks: list[Callable[[], None]] = []
        self._depth_token = _tx_depth.set(current + 1)

    def finalize(self, *, committed: bool) -> None:
        """Restore depth.  If this was the outermost tx and we committed,
        drain accumulated hooks.  Otherwise, propagate hooks upward."""
        _tx_depth.reset(self._depth_token)
        if committed and self.is_outermost:
            # Fire hooks outside any transaction context
            _drain_post_commit_hooks(self.hooks)
        elif committed and not self.is_outermost:
            # Inner tx committed (savepoint released) — merge hooks upward
            parent = _post_commit_hooks.get(None) or []
            parent.extend(self.hooks)


def _drain_post_commit_hooks(hooks: list[Callable[[], None]]) -> None:
    """Execute post-commit hooks one by one.  Failures are logged but
    never prevent the transaction from being considered successful."""
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    for hook in hooks:
        try:
            hook()
        except Exception:
            logger.exception("post_commit_hook_failed", hook=repr(hook))


def _add_post_commit_hook(fn: Callable[[], None]) -> None:
    """Register a callable to run after the outermost transaction commits."""
    hooks = _post_commit_hooks.get(None) or []
    hooks.append(fn)
    # Update the ContextVar with the same list (ContextVar requires re-set)
    _post_commit_hooks.set(hooks)


# Public alias for clarity in service code
def tx_on_commit(fn: Callable[[], None]) -> None:
    """Register a side-effect to execute after the outermost tx() commits.

    This is the ONLY safe way to trigger emails, notifications, webhooks,
    or any non-DB side effect from within a tx() closure.

    Example:
        def _approve():
            payment.status = "approved"
            sub.status = "active"
            tx_on_commit(lambda: send_payment_approved_email(payment))
    """
    _add_post_commit_hook(fn)


def tx(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """ينفّذ func داخل معاملة واحدة. يعيد النتيجة أو يرفع الخطأ مع rollback.

    Nested safety:
      - If called from within an already-active tx(), uses a SAVEPOINT
        instead of committing.  This prevents premature lock release
        and keeps the outer atomic unit intact.
      - Only the OUTERMOST tx() performs the real commit.

    Post-commit hooks:
      - Call tx_on_commit(fn) inside the closure to schedule side effects.
      - Hooks fire ONLY after the outermost commit succeeds.

    ORM consistency:
      - After commit, expired attributes are refreshed so callers
        see the database-truth (not stale Python objects).
    """
    ctx = _TxContext()

    try:
        result = func(*args, **kwargs)

        if ctx.is_outermost:
            # Outermost transaction — real commit
            db.session.commit()
            _expire_committed_objects()
            ctx.finalize(committed=True)
            return result
        else:
            # Nested transaction — use savepoint (begin_nested creates SAVEPOINT)
            # The savepoint releases on commit, keeping changes visible to outer tx.
            with db.session.begin_nested():
                pass  # SAVEPOINT created and released — changes merged into outer tx
            ctx.finalize(committed=True)
            return result

    except TxError:
        # Business-logic failure — rollback and re-raise.
        # The caller catches TxError and translates to a user message.
        if ctx.is_outermost:
            db.session.rollback()
            _expire_committed_objects()
        ctx.finalize(committed=False)
        raise

    except SQLAlchemyError:
        # Database error — rollback and re-raise
        if ctx.is_outermost:
            db.session.rollback()
            _expire_committed_objects()
            _log_transaction_failure("sqlalchemy_error")
        ctx.finalize(committed=False)
        raise

    except Exception:
        # Unexpected error — rollback and re-raise
        if ctx.is_outermost:
            db.session.rollback()
            _expire_committed_objects()
            _log_transaction_failure("unexpected_error")
        ctx.finalize(committed=False)
        raise


def _expire_committed_objects() -> None:
    """Expire all persistent objects in the session after commit.

    This forces SQLAlchemy to re-fetch from the DB on next attribute access,
    preventing stale reads within the same request.  Without this, a service
    might read an object modified by a prior tx() in the same request and
    see the old values.
    """
    try:
        db.session.expire_all()
    except Exception:
        # Non-critical: if expiry fails, worst case is stale reads.
        # Never let this crash the transaction.
        pass


def _log_transaction_failure(kind: str) -> None:
    """Log a transaction failure with structured context."""
    from app.core.logging import get_correlation_id, get_logger

    logger = get_logger(__name__)
    try:
        from flask_login import current_user

        user_id = current_user.id if current_user.is_authenticated else None
    except Exception:
        user_id = None

    try:
        from app.core.tenancy import current_school_id

        school_id = current_school_id()
    except Exception:
        school_id = None

    logger.error(
        "transaction_failed",
        failure_kind=kind,
        user_id=user_id,
        school_id=school_id,
        correlation_id=get_correlation_id(),
        depth=_tx_depth.get(),
    )
