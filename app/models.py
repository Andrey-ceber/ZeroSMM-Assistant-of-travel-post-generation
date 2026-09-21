from __future__ import annotations

from . import db, bcrypt


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    vk_api_id = db.Column(db.String(128))
    vk_group_id = db.Column(db.String(128))

    def set_password(self, password: str):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)


def get_user_by_id(user_id: int) -> User | None:
    return User.query.get(user_id)


def get_user_by_username(username: str) -> User | None:
    return User.query.filter_by(username=username).first()


def create_user(username: str, email: str, password: str) -> User:
    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def update_vk_settings(user_id: int, vk_api_id: str, vk_group_id: str):
    user = get_user_by_id(user_id)
    if not user:
        return
    user.vk_api_id = vk_api_id
    user.vk_group_id = vk_group_id
    db.session.commit()


