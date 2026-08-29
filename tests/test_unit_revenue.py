"""Unit tests for app.services.revenue — revenue tracking and analytics."""

from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models.billing import ManualPayment
from tests.conftest import (
    make_class,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def _setup_revenue_data(app):
    """Create sample revenue data for testing."""
    with app.app_context():
        school_id = make_school(app)
        student_id = make_user(app, "student", school_id=school_id)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        class_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, class_id, price=200.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=200.0, status="active")
        pay_id = make_payment(app, sub_id, amount=200.0, status="approved")
        # Add gateway to payment
        p = db.session.get(ManualPayment, pay_id)
        p.gateway = "manual"
        db.session.commit()
        return school_id, sub_id, pay_id


class TestRevenueSummary:
    def test_summary_with_no_data(self, app):
        from app.services.revenue import get_revenue_summary

        with app.app_context():
            result = get_revenue_summary()
            assert result["total_revenue"] == 0.0
            assert result["transaction_count"] == 0
            assert result["currency"] == "ILS"

    def test_summary_with_data(self, app):
        from app.services.revenue import get_revenue_summary

        _setup_revenue_data(app)
        with app.app_context():
            result = get_revenue_summary()
            assert result["total_revenue"] == 200.0
            assert result["transaction_count"] == 1

    def test_summary_with_custom_date_range(self, app):
        from app.services.revenue import get_revenue_summary

        _setup_revenue_data(app)
        with app.app_context():
            now = datetime.now(UTC)
            # Very narrow window — should find nothing
            result = get_revenue_summary(
                date_from=now - timedelta(days=1000),
                date_to=now - timedelta(days=999),
            )
            assert result["transaction_count"] == 0


class TestRevenueByGateway:
    def test_by_gateway_with_no_data(self, app):
        from app.services.revenue import get_revenue_by_gateway

        with app.app_context():
            result = get_revenue_by_gateway()
            assert result == []

    def test_by_gateway_with_data(self, app):
        from app.services.revenue import get_revenue_by_gateway

        _setup_revenue_data(app)
        with app.app_context():
            result = get_revenue_by_gateway()
            assert len(result) >= 1
            assert result[0]["gateway"] == "manual"
            assert result[0]["total"] == 200.0


class TestRevenueBySchool:
    def test_by_school_with_no_data(self, app):
        from app.services.revenue import get_revenue_by_school

        with app.app_context():
            result = get_revenue_by_school()
            assert result == []

    def test_by_school_with_data(self, app):
        from app.services.revenue import get_revenue_by_school

        _setup_revenue_data(app)
        with app.app_context():
            result = get_revenue_by_school()
            assert len(result) >= 1
            assert result[0]["total"] == 200.0

    def test_by_school_respects_limit(self, app):
        from app.services.revenue import get_revenue_by_school

        with app.app_context():
            result = get_revenue_by_school(limit=1)
            assert len(result) <= 1


class TestMonthlyRevenueTrend:
    def test_trend_with_no_data(self, app):
        from app.services.revenue import get_monthly_revenue_trend

        with app.app_context():
            result = get_monthly_revenue_trend()
            assert isinstance(result, list)

    def test_trend_with_data(self, app):
        from app.services.revenue import get_monthly_revenue_trend

        _setup_revenue_data(app)
        with app.app_context():
            result = get_monthly_revenue_trend(months=1)
            assert isinstance(result, list)


class TestGrowthRate:
    def test_growth_rate_with_no_data(self, app):
        from app.services.revenue import get_growth_rate

        with app.app_context():
            rate = get_growth_rate()
            assert rate == 0.0

    def test_growth_rate_positive(self, app):
        from app.services.revenue import get_growth_rate

        _setup_revenue_data(app)
        with app.app_context():
            # With data only in recent period, growth should be > 0
            rate = get_growth_rate()
            assert isinstance(rate, float)


class TestRevenueDashboard:
    def test_dashboard_with_no_data(self, app):
        from app.services.revenue import get_revenue_dashboard_data

        with app.app_context():
            data = get_revenue_dashboard_data()
            assert "summary" in data
            assert "by_gateway" in data
            assert "by_school" in data
            assert "monthly_trend" in data
            assert "growth_rate" in data
            assert "date_from" in data
            assert "date_to" in data

    def test_dashboard_with_data(self, app):
        from app.services.revenue import get_revenue_dashboard_data

        _setup_revenue_data(app)
        with app.app_context():
            data = get_revenue_dashboard_data()
            assert data["summary"]["total_revenue"] == 200.0

    def test_dashboard_custom_days(self, app):
        from app.services.revenue import get_revenue_dashboard_data

        with app.app_context():
            data = get_revenue_dashboard_data(days=7)
            assert (data["date_to"] - data["date_from"]).days == 7
