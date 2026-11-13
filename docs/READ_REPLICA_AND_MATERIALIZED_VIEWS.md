# Phase D — Read/Write Splitting, Materialized Views & Zero-Downtime Migrations

## Read/Write Splitting
- Set `READ_DATABASE_URL` to enable a `replica` bind in `SQLALCHEMY_BINDS`.
- Heavy reporting/analytics queries should use `db.get_engine(bind="replica")` or a `@readonly` helper.
- Writes always go to the primary (`db.session`).
- RLS policies must be replicated to the replica (they are part of schema).

## Materialized Views
- Create MVs for executive dashboards (e.g. `mv_school_revenue_daily`, `mv_class_grade_summary`).
- Refresh via scheduled ETL job (`flask refresh-materialized-views`) using `REFRESH MATERIALIZED VIEW CONCURRENTLY` (requires unique index).
- Application reads from MVs for dashboards; writes invalidate via event hooks.

## Zero-Downtime Migrations
- Backward-compatible patterns:
  1. Add column nullable → backfill → add NOT NULL constraint (separate migrations).
  2. Add index `CONCURRENTLY` (use `op.create_index(..., postgresql_concurrently=True)`).
  3. Rename column: add new → copy → drop old (never rename in one step).
  4. Never drop a column in the same release that stops reading it.
- Each migration must be reversible (`downgrade()`).
- Deploy: migrate first (backward compatible), then deploy code, then cleanup migration.
EOF