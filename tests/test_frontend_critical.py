"""Critical frontend tests — Phase 1 blockers"""

import os

import pytest
from bs4 import BeautifulSoup
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
PASSWORD = "TestPass123!"


def _mk(app, role="student"):
    import uuid

    email = f"fe-{uuid.uuid4().hex[:8]}@test.com"
    return make_user(app, role=role, email=email), email


def _client(app, email):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _seed_subscription(app, student_id, price=500.0, status="pending"):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    plan_id = make_subscription_plan(app, sid, class_id=cid, price=price)
    return make_subscription(app, student_id, plan_id, cid, price=price, status=status)


class TestNestedMain:
    """Test that no template has nested <main> elements."""

    def test_admin_base_no_nested_main(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "admin", "base.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        mains = soup.find_all("main")
        # Should have NO <main> in admin/base.html (it extends base.html which has one)
        assert len(mains) == 0, f"admin/base.html has {len(mains)} <main> elements, should have 0"

    def test_ai_chat_no_nested_main(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "ai", "chat.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        mains = soup.find_all("main")
        assert len(mains) == 0, f"ai/chat.html has {len(mains)} <main> elements, should have 0"


class TestSearchInputLabel:
    """Test that search inputs have proper labels."""

    def test_search_macro_has_aria_label(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "macros", "forms.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert 'id="{{ name }}-search"' in content, "Search input must have id"
        assert "aria-label" in content or "label for=" in content, "Search input must have label or aria-label"


class TestAiChatNoInnerHTML:
    """Test that AI chat uses textContent not innerHTML for user content."""

    def test_render_messages_uses_textcontent(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "ai-chat.js")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        # Should NOT use innerHTML for user-generated content
        assert "innerHTML = " not in content or "innerHTML = html" not in content, (
            "renderMessages should not use innerHTML for message content"
        )

        # Should use textContent or createTextNode
        assert "textContent" in content or "createTextNode" in content or "document.createElement" in content, (
            "Should use safe DOM methods"
        )


class TestFetchErrorHandling:
    """Test that fetch calls have proper error handling."""

    def test_sendmessage_has_abortcontroller(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "ai-chat.js")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "AbortController" in content, "sendMessage must use AbortController"
        assert "signal: controller.signal" in content, "fetch must use abort signal"
        assert "setTimeout" in content and "controller.abort" in content, "Must have timeout that aborts controller"

    def test_fetch_has_try_catch(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "ai-chat.js")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "try {" in content and "} catch (error)" in content, "fetch must be wrapped in try/catch"
        assert "finally {" in content, "fetch must have finally block"


class TestHeadingHierarchy:
    """Test that heading hierarchy doesn't skip levels."""

    def test_invoice_has_no_skipped_headings(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "billing", "invoice.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        levels = [int(h.name[1]) for h in headings]

        # No skipped levels
        for i in range(1, len(levels)):
            assert levels[i] - levels[i - 1] <= 1, f"Heading level skip: {levels[i - 1]} -> {levels[i]}"

    def test_azad_card_macro_has_heading_level_param(self):
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "macros", "ui.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "heading_level" in content, "azad_card macro must accept heading_level param"
        assert "h{{ heading_level }}" in content, "Macro must use heading_level for h-tag"


class TestPaymentsUiNoMockAffordance:
    """AZ-P0-05: لا زر دفع بلا أثر مالي، والنيّة تُنشأ فعلاً."""

    def test_payment_templates_have_no_alert(self):
        """لا نص دفع ينتهي إلى alert() أو console.log بلا أثر مالي."""
        for name in ("index.html",):
            path = os.path.join(TEMPLATES_DIR, "payments_ui", name)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "alert(" not in content, name
            assert "console.log" not in content, name

    def test_billing_page_links_to_the_gateway_flow(self):
        """مسار البوابة الإلكترونية مُعلن من صفحة الاشتراك (لا ميزة مخفية)."""
        path = os.path.join(TEMPLATES_DIR, "billing", "class_billing.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "payments_ui.payment_methods_page" in content

    def test_no_subscription_context_offers_no_dead_action(self, app):
        """بلا اشتراك مملوك: لا زر، وتلميح يوضّح من أين يبدأ."""
        _uid, email = _mk(app)
        html = _client(app, email).get("/payments/").get_data(as_text=True)
        assert "payment-context-hint" in html
        assert "payment-method-select" not in html

    def test_owned_subscription_builds_button_on_its_amount(self, app):
        """اشتراك مملوك: الزر موجود ومبني على مبلغ الاشتراك وعملته."""
        uid, email = _mk(app)
        sub_id = _seed_subscription(app, uid, price=500.0)
        html = _client(app, email).get(f"/payments/?subscription_id={sub_id}").get_data(as_text=True)
        assert "payment-context" in html
        assert "payment-method-select" in html
        assert f'data-subscription-id="{sub_id}"' in html
        assert 'data-amount="500.00"' in html
        assert 'data-currency="ILS"' in html

    def test_foreign_subscription_is_not_payable(self, app):
        """اشتراك طالب آخر: لا يُبنى زر على ماله ولا يُكشف وجوده.

        طبقتان تمنعان ذلك: سياسة RLS تخفي صف اشتراك غير المالك (فتؤول
        القراءة إلى 404)، وفحص الملكية في المسار يردّ 403 إن وصل الصف
        لأي سبب (مثل تعطيل RLS في بيئة ما). كلا الرمزين يمنع الدفع،
        وكلاهما نمط مقبول في اختبارات الأمان بهذا المستودع.
        """
        owner, _ = _mk(app)
        sub_id = _seed_subscription(app, owner, price=500.0)
        _other, email = _mk(app)
        resp = _client(app, email).get(f"/payments/?subscription_id={sub_id}")
        assert resp.status_code in (403, 404)
        assert "payment-method-select" not in resp.get_data(as_text=True)

    def test_unknown_subscription_is_404(self, app):
        _uid, email = _mk(app)
        assert _client(app, email).get("/payments/?subscription_id=99999999").status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
