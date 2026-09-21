from datetime import timedelta

from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from config import Config

# расширения создаём один раз здесь
db = SQLAlchemy()
bcrypt = Bcrypt()


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # загружаем настройки через Config
    app.config.from_object(Config)

    # добавляем дефолтные значения, не ломая существующий config
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///app.db")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=30))

    # инициализация расширений
    db.init_app(app)
    bcrypt.init_app(app)

    # регистрация blueprints
    from .auth import auth_bp
    from .smm import smm_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(smm_bp)

    # редирект с корня на дашборд
    @app.route("/")
    def index():
        return redirect(url_for("smm.dashboard"))

    # создание таблиц
    with app.app_context():
        from .models import User  # noqa: F401

        db.create_all()

    return app


