"""اختبارات نموذج التواصل"""

import pytest

from app.models.communication import ContactMessage


def test_contact_route_returns_200(client):
    """صفحة التواصل تعمل"""
    response = client.get("/contact/")
    assert response.status_code == 200


def test_contact_submit_success(client, app):
    """إرسال نموذج التواصل بنجاح"""
    from app.extensions import db
    response = client.post("/contact/", data={
        "name": "Ahmed Mohammed",
        "email": "ahmed@test.com",
        "phone": "0599123456",
        "subject": "Inquiry",
        "message": "Hello, I have a question about the platform"
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Thank" in response.data or b"\xd8\xb4\xd9\x83\xd8\xb1\xd8\xa7" in response.data

    # Check message saved in DB
    with app.app_context():
        msg = ContactMessage.query.filter_by(email="ahmed@test.com").first()
        assert msg is not None
        assert msg.name == "Ahmed Mohammed"
        assert msg.subject == "Inquiry"
        assert msg.status == "new"


def test_contact_submit_validation_error(client):
    """فشل التحقق من صحة البيانات"""
    response = client.post("/contact/", data={
        "name": "",
        "email": "invalid-email",
        "subject": "",
        "message": ""
    })
    assert response.status_code == 200
    # Should show validation errors
    assert b"required" in response.data.lower() or b"error" in response.data.lower()


def test_admin_contact_inbox(client, app, admin_user):
    """صندوق وارد رسائل التواصل للأدمن"""
    from app.extensions import db
    from app.models.user import User, UserRole
    from app.models.communication import ContactMessage

    with app.app_context():
        # Create a contact message
        msg = ContactMessage(name="User", email="user@test.com",
                             subject="Test", message="Test message")
        db.session.add(msg)
        db.session.commit()

    # Login as admin
    client.post("/auth/login", data={
        "email": admin_user.email,
        "password": "TestPass123!"
    }, follow_redirects=True)

    response = client.get("/admin/contact")
    assert response.status_code == 200
    assert b"User" in response.data
    assert b"user@test.com" in response.data