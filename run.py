"""نقطة الدخول — تشغيل التطبيق محلياً"""

import sys

from app import create_app

app = create_app()

if __name__ == "__main__":
    # يقبل: python run.py [--host H] [--port P]
    args = dict(zip(sys.argv[1::2], sys.argv[2::2], strict=False))
    host = args.get("--host", "127.0.0.1")
    port = int(args.get("--port", "8000"))
    app.run(host=host, port=port, debug=app.config.get("DEBUG", False))
