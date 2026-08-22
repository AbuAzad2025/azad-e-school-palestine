"""add missing model tables

Revision ID: f0e1d2c3b4a5
Revises: a3b2c1d0e4f5
Create Date: 2026-08-21 20:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f0e1d2c3b4a5'
down_revision = 'a3b2c1d0e4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'badge_criteria_type') THEN
        CREATE TYPE badge_criteria_type AS ENUM (
            'first_quiz', 'perfect_score', 'streak_7_days', 'course_complete', 'early_bird'
        );
    END IF;
END $$
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS badges (
	name VARCHAR(100) NOT NULL,
	description TEXT,
	icon_name VARCHAR(50) NOT NULL,
	criteria_type badge_criteria_type NOT NULL,
	criteria_value SMALLINT,
	is_active BOOLEAN NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS contact_messages (
	name TEXT NOT NULL,
	email TEXT NOT NULL,
	phone TEXT,
	subject TEXT NOT NULL,
	message TEXT NOT NULL,
	status TEXT NOT NULL,
	replied_at TIMESTAMP WITH TIME ZONE,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS health_checks (
	component VARCHAR(50) NOT NULL,
	status VARCHAR(10) NOT NULL,
	message TEXT,
	latency_ms BIGINT,
	checked_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS academic_events (
	school_id BIGINT NOT NULL,
	title TEXT NOT NULL,
	event_type VARCHAR(20) NOT NULL,
	start_date DATE NOT NULL,
	end_date DATE,
	is_active BOOLEAN NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_academic_events_school_id ON academic_events (school_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS ai_usage_logs (
	user_id BIGINT,
	model TEXT NOT NULL,
	prompt_tokens INTEGER NOT NULL,
	completion_tokens INTEGER NOT NULL,
	total_tokens INTEGER NOT NULL,
	estimated_cost_usd FLOAT NOT NULL,
	action TEXT NOT NULL,
	meta JSONB,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS certificate_templates (
	school_id BIGINT,
	name TEXT NOT NULL,
	template_html TEXT NOT NULL,
	is_active BOOLEAN NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS family_link_codes (
	student_id BIGINT NOT NULL,
	code CITEXT NOT NULL,
	used BOOLEAN NOT NULL,
	used_by BIGINT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	id BIGSERIAL NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_student_link_code UNIQUE (student_id, code),
	FOREIGN KEY(student_id) REFERENCES users (id),
	UNIQUE (code),
	FOREIGN KEY(used_by) REFERENCES users (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_family_link_codes_student_id ON family_link_codes (student_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS family_links (
	parent_id BIGINT NOT NULL,
	student_id BIGINT NOT NULL,
	status VARCHAR(10) NOT NULL,
	linked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_family_link UNIQUE (parent_id, student_id),
	FOREIGN KEY(parent_id) REFERENCES users (id),
	FOREIGN KEY(student_id) REFERENCES users (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_family_links_student_id ON family_links (student_id)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_family_links_parent_id ON family_links (parent_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS notification_preferences (
	user_id BIGINT NOT NULL,
	notif_type TEXT NOT NULL,
	email_enabled BOOLEAN NOT NULL,
	in_app_enabled BOOLEAN NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_notif_pref UNIQUE (user_id, notif_type),
	FOREIGN KEY(user_id) REFERENCES users (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_notification_preferences_user_id ON notification_preferences (user_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS onboarding_progress (
	school_id BIGINT NOT NULL,
	current_step SMALLINT NOT NULL,
	total_steps SMALLINT NOT NULL,
	completed_steps JSONB,
	is_complete BOOLEAN NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (school_id),
	FOREIGN KEY(school_id) REFERENCES schools (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS rubric_templates (
	teacher_id BIGINT NOT NULL,
	school_id BIGINT NOT NULL,
	title TEXT NOT NULL,
	description TEXT,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(teacher_id) REFERENCES users (id),
	FOREIGN KEY(school_id) REFERENCES schools (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS student_badges (
	student_id BIGINT NOT NULL,
	badge_id BIGINT NOT NULL,
	earned_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_student_badge UNIQUE (student_id, badge_id),
	FOREIGN KEY(student_id) REFERENCES users (id),
	FOREIGN KEY(badge_id) REFERENCES badges (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_student_badges_student_id ON student_badges (student_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS tenant_quotas (
	school_id BIGINT NOT NULL,
	tier VARCHAR(20) NOT NULL,
	max_students INTEGER NOT NULL,
	max_teachers INTEGER NOT NULL,
	max_classes INTEGER NOT NULL,
	max_storage_mb INTEGER NOT NULL,
	ai_enabled BOOLEAN NOT NULL,
	max_ai_tokens_monthly INTEGER NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id)
)
""")

    op.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS ix_tenant_quotas_school_id ON tenant_quotas (school_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS tutor_payouts (
	tutor_id BIGINT NOT NULL,
	amount NUMERIC(10, 2) NOT NULL,
	status VARCHAR(10) NOT NULL,
	reviewed_by BIGINT,
	reviewed_at TIMESTAMP WITH TIME ZONE,
	note TEXT,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tutor_id) REFERENCES users (id),
	FOREIGN KEY(reviewed_by) REFERENCES users (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_tutor_payouts_tutor_id ON tutor_payouts (tutor_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS rubric_criteria (
	template_id BIGINT NOT NULL,
	title TEXT NOT NULL,
	description TEXT,
	max_score NUMERIC(5, 2) NOT NULL,
	sort_order SMALLINT,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(template_id) REFERENCES rubric_templates (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS tutor_commissions (
	session_id BIGINT NOT NULL,
	tutor_id BIGINT NOT NULL,
	session_amount NUMERIC(10, 2) NOT NULL,
	commission_rate NUMERIC(5, 2) NOT NULL,
	commission_amount NUMERIC(10, 2) NOT NULL,
	tutor_net NUMERIC(10, 2) NOT NULL,
	status VARCHAR(10) NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (session_id),
	FOREIGN KEY(session_id) REFERENCES tutoring_sessions (id),
	FOREIGN KEY(tutor_id) REFERENCES users (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_tutor_commissions_tutor_id ON tutor_commissions (tutor_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS tutor_reviews (
	session_id BIGINT NOT NULL,
	student_id BIGINT NOT NULL,
	rating SMALLINT NOT NULL,
	comment TEXT,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_tutor_review_per_session UNIQUE (session_id, student_id),
	FOREIGN KEY(session_id) REFERENCES tutoring_sessions (id),
	FOREIGN KEY(student_id) REFERENCES users (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS grade_appeals (
	submission_id BIGINT NOT NULL,
	student_id BIGINT NOT NULL,
	reason TEXT NOT NULL,
	status VARCHAR(15) NOT NULL,
	teacher_response TEXT,
	reviewed_by BIGINT,
	reviewed_at TIMESTAMP WITH TIME ZONE,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_grade_appeal UNIQUE (submission_id, student_id),
	FOREIGN KEY(submission_id) REFERENCES submissions (id),
	FOREIGN KEY(student_id) REFERENCES users (id),
	FOREIGN KEY(reviewed_by) REFERENCES users (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS reminder_logs (
	subscription_id BIGINT NOT NULL,
	reminder_type VARCHAR(10) NOT NULL,
	sent_at TIMESTAMP WITH TIME ZONE,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_reminder_log_unique UNIQUE (subscription_id, reminder_type),
	FOREIGN KEY(subscription_id) REFERENCES subscriptions (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_reminder_logs_subscription_id ON reminder_logs (subscription_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS rubric_grades (
	submission_id BIGINT NOT NULL,
	criterion_id BIGINT NOT NULL,
	score NUMERIC(5, 2) NOT NULL,
	comment TEXT,
	graded_by BIGINT,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_rubric_grade UNIQUE (submission_id, criterion_id),
	FOREIGN KEY(submission_id) REFERENCES submissions (id),
	FOREIGN KEY(criterion_id) REFERENCES rubric_criteria (id),
	FOREIGN KEY(graded_by) REFERENCES users (id)
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS student_progress (
	student_id BIGINT NOT NULL,
	lesson_id BIGINT NOT NULL,
	class_id BIGINT NOT NULL,
	status VARCHAR(10) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	seconds_spent INTEGER NOT NULL,
	progress_pct SMALLINT NOT NULL,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_student_lesson_progress UNIQUE (student_id, lesson_id),
	FOREIGN KEY(student_id) REFERENCES users (id),
	FOREIGN KEY(lesson_id) REFERENCES lessons (id),
	FOREIGN KEY(class_id) REFERENCES classes (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_student_progress_student_id ON student_progress (student_id)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_student_progress_class_id ON student_progress (class_id)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_student_progress_lesson_id ON student_progress (lesson_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS offline_downloads (
	student_id BIGINT NOT NULL,
	attachment_id BIGINT NOT NULL,
	lesson_id BIGINT NOT NULL,
	status VARCHAR(15) NOT NULL,
	downloaded_at TIMESTAMP WITH TIME ZONE,
	expires_at TIMESTAMP WITH TIME ZONE,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(student_id) REFERENCES users (id),
	FOREIGN KEY(attachment_id) REFERENCES lesson_attachments (id),
	FOREIGN KEY(lesson_id) REFERENCES lessons (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_offline_downloads_student_id ON offline_downloads (student_id)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS video_progress (
	student_id BIGINT NOT NULL,
	attachment_id BIGINT NOT NULL,
	lesson_id BIGINT NOT NULL,
	class_id BIGINT NOT NULL,
	seconds_watched INTEGER NOT NULL,
	total_seconds INTEGER NOT NULL,
	completed BOOLEAN NOT NULL,
	last_watched_at TIMESTAMP WITH TIME ZONE,
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_student_video_progress UNIQUE (student_id, attachment_id),
	FOREIGN KEY(student_id) REFERENCES users (id),
	FOREIGN KEY(attachment_id) REFERENCES lesson_attachments (id),
	FOREIGN KEY(lesson_id) REFERENCES lessons (id),
	FOREIGN KEY(class_id) REFERENCES classes (id)
)
""")

    op.execute("""
CREATE INDEX IF NOT EXISTS ix_video_progress_student_id ON video_progress (student_id)
""")


def downgrade():
    op.execute("DROP TYPE IF EXISTS badge_criteria_type CASCADE")
    op.execute("DROP TABLE IF EXISTS video_progress CASCADE")
    op.execute("DROP TABLE IF EXISTS offline_downloads CASCADE")
    op.execute("DROP TABLE IF EXISTS student_progress CASCADE")
    op.execute("DROP TABLE IF EXISTS rubric_grades CASCADE")
    op.execute("DROP TABLE IF EXISTS reminder_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS grade_appeals CASCADE")
    op.execute("DROP TABLE IF EXISTS tutor_reviews CASCADE")
    op.execute("DROP TABLE IF EXISTS tutor_commissions CASCADE")
    op.execute("DROP TABLE IF EXISTS rubric_criteria CASCADE")
    op.execute("DROP TABLE IF EXISTS tutor_payouts CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant_quotas CASCADE")
    op.execute("DROP TABLE IF EXISTS student_badges CASCADE")
    op.execute("DROP TABLE IF EXISTS rubric_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS onboarding_progress CASCADE")
    op.execute("DROP TABLE IF EXISTS notification_preferences CASCADE")
    op.execute("DROP TABLE IF EXISTS family_links CASCADE")
    op.execute("DROP TABLE IF EXISTS family_link_codes CASCADE")
    op.execute("DROP TABLE IF EXISTS certificate_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_usage_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS academic_events CASCADE")
    op.execute("DROP TABLE IF EXISTS health_checks CASCADE")
    op.execute("DROP TABLE IF EXISTS contact_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS badges CASCADE")
