"""Locust load test scenario for Azad E-School.

Target: 1,000 concurrent simulated users (configurable via --users).

Usage (with a running server on http://127.0.0.1:5000):
    .venv\\Scripts\\locust -f tests/load/locustfile.py --host http://127.0.0.1:5000 -u 1000 -r 100 -t 5m

Environment variables:
    AZAD_TEST_EMAIL    - email for authenticated user flow
    AZAD_TEST_PASSWORD - password for authenticated user flow
"""

import os

from locust import HttpUser, between, task


class PublicUser(HttpUser):
    """Simulates anonymous visitors browsing public pages and static assets."""

    wait_time = between(1, 5)
    weight = 3

    @task(5)
    def landing(self):
        self.client.get("/", name="GET /")

    @task(2)
    def pricing(self):
        self.client.get("/pricing", name="GET /pricing")

    @task(2)
    def login_page(self):
        self.client.get("/auth/login", name="GET /auth/login")

    @task(1)
    def static_css(self):
        self.client.get("/static/css/app.css", name="GET /static/css/app.css")

    @task(1)
    def static_js(self):
        self.client.get("/static/js/index.js", name="GET /static/js/index.js")


class AuthenticatedUser(HttpUser):
    """Simulates a logged-in user interacting with protected dashboards."""

    wait_time = between(2, 8)
    weight = 1

    def on_start(self):
        self.email = os.getenv("AZAD_TEST_EMAIL", "")
        self.password = os.getenv("AZAD_TEST_PASSWORD", "")
        self.logged_in = False
        if self.email and self.password:
            response = self.client.post(
                "/auth/login",
                data={"email": self.email, "password": self.password, "remember": "y"},
                name="POST /auth/login",
                allow_redirects=False,
            )
            self.logged_in = response.status_code in (200, 302)

    @task(3)
    def dashboard(self):
        if not self.logged_in:
            return
        self.client.get("/dashboard", name="GET /dashboard")

    @task(2)
    def admin_dashboard(self):
        if not self.logged_in:
            return
        self.client.get("/admin/", name="GET /admin/")

    @task(2)
    def my_classes(self):
        if not self.logged_in:
            return
        self.client.get("/schools/my-classes", name="GET /schools/my-classes")

    @task(1)
    def individual_courses(self):
        if not self.logged_in:
            return
        self.client.get("/individual/my-courses", name="GET /individual/my-courses")

    @task(1)
    def ai_chat(self):
        if not self.logged_in:
            return
        self.client.get("/ai/chat", name="GET /ai/chat")


class SpikeUser(HttpUser):
    """Short, bursty requests to test autoscaling / rate limiting."""

    wait_time = between(0.1, 0.5)
    weight = 1

    @task(1)
    def spike_landing(self):
        self.client.get("/", name="GET / (spike)")

    @task(1)
    def spike_login(self):
        self.client.get("/auth/login", name="GET /auth/login (spike)")
