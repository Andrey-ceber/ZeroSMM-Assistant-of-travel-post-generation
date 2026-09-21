from functools import wraps

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    g,
)

from .models import (
    get_user_by_username,
    get_user_by_id,
    create_user,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped_view


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_user_by_id(user_id)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        error = None

        if not username:
            error = "Укажите логин."
        elif not email:
            error = "Укажите email."
        elif not password:
            error = "Укажите пароль."
        elif get_user_by_username(username) is not None:
            error = "Пользователь с таким логином уже существует."

        if error is None:
            create_user(username, email, password)
            flash("Регистрация прошла успешно, войдите в систему.")
            return redirect(url_for("auth.login"))

        flash(error)

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        error = None
        user = get_user_by_username(username)

        if user is None or not user.check_password(password):
            error = "Неверный логин или пароль."

        if error is None:
            session.clear()
            session.permanent = True  # долгая сессия (30 дней по умолчанию)
            session["user_id"] = user.id
            return redirect(url_for("smm.dashboard"))

        flash(error)

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


