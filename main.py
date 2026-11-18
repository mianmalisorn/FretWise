from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import hashlib
import os

app = FastAPI(title="FretWise")

app.add_middleware(SessionMiddleware, secret_key="fretwise-secret-key")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

DATABASE_URL = "sqlite:///./fretwise.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)

    tabs = relationship("Tab", back_populates="user")
    favorites = relationship("Favorite", back_populates="user")


class Tab(Base):
    __tablename__ = "tabs"

    id = Column(Integer, primary_key=True)
    title = Column(String)
    artist = Column(String)

    cover_url = Column(String, default="")
    spotify_url = Column(String, default="")

    capo = Column(String, default="Без капо")
    strumming = Column(Text, default="")
    picking = Column(Text, default="")
    chords = Column(Text, default="")

    original_text = Column(Text)
    simplified_text = Column(Text)

    is_public = Column(Boolean, default=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User", back_populates="tabs")

    favorites = relationship("Favorite", back_populates="tab")


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    tab_id = Column(Integer, ForeignKey("tabs.id"))

    user = relationship("User", back_populates="favorites")
    tab = relationship("Tab", back_populates="favorites")


Base.metadata.create_all(bind=engine)


def get_current_user(request: Request, db):
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    return db.query(User).filter(User.id == user_id).first()


def is_admin(user):
    return user and user.username == "admin"


def split_chords(chords_text: str):
    if not chords_text:
        return []

    return [
        chord.strip()
        for chord in chords_text.split(",")
        if chord.strip()
    ]


def chord_image_exists(chord: str):
    file_path = f"static/chords/{chord}.png"
    return os.path.exists(file_path)


def simplify_tab(text: str) -> str:
    replacements = {
        "F#m": "Em",
        "F#": "G",
        "Bm": "Am",
        "B": "A",
        "C#m": "Am",
        "C#": "C",
        "G#m": "Em",
        "G#": "G",
        "D#m": "Dm",
        "D#": "D",
        "A#m": "Am",
        "A#": "A",
        "Bb": "A",
        "Eb": "D",
        "Ab": "G",
        "Db": "C",
        "F": "C"
    }

    simplified = text

    sorted_chords = sorted(replacements.keys(), key=len, reverse=True)

    for hard in sorted_chords:
        simplified = simplified.replace(hard, replacements[hard])

    return simplified


@app.get("/")
def index(request: Request):
    db = SessionLocal()

    user = get_current_user(request, db)
    public_tabs = db.query(Tab).filter(Tab.is_public == True).all()

    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "public_tabs": public_tabs
        }
    )

    db.close()
    return response


@app.get("/register")
def register_page(request: Request):
    db = SessionLocal()
    user = get_current_user(request, db)
    db.close()

    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "error": None,
            "user": user
        }
    )


@app.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()

    existing_user = db.query(User).filter(User.username == username).first()

    if existing_user:
        db.close()

        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "Пользователь уже существует",
                "user": None
            }
        )

    user = User(username=username, password_hash=hash_password(password))

    db.add(user)
    db.commit()
    db.close()

    return RedirectResponse("/login", status_code=303)


@app.get("/login")
def login_page(request: Request):
    db = SessionLocal()
    user = get_current_user(request, db)
    db.close()

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "user": user
        }
    )


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()

    user = db.query(User).filter(User.username == username).first()

    if not user or not verify_password(password, user.password_hash):
        db.close()

        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Неверный логин или пароль",
                "user": None
            }
        )

    request.session["user_id"] = user.id

    db.close()

    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard")
def dashboard(request: Request):
    db = SessionLocal()

    user = get_current_user(request, db)

    if not user:
        db.close()
        return RedirectResponse("/login", status_code=303)

    tabs = db.query(Tab).filter(Tab.user_id == user.id, Tab.is_public == False).all()

    favorite_tabs = (
        db.query(Tab)
        .join(Favorite, Favorite.tab_id == Tab.id)
        .filter(Favorite.user_id == user.id)
        .all()
    )

    response = templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "tabs": tabs,
            "favorite_tabs": favorite_tabs,
            "is_admin": is_admin(user)
        }
    )

    db.close()
    return response


@app.post("/songs/create")
def create_song(
    request: Request,
    title: str = Form(...),
    artist: str = Form(""),
    cover: UploadFile = File(None),
    spotify_url: str = Form(""),
    capo: str = Form("Без капо"),
    strumming: str = Form(""),
    picking: str = Form(""),
    chords: str = Form(""),
    original_text: str = Form(""),
    is_public: str = Form(None)
):
    db = SessionLocal()

    user = get_current_user(request, db)

    if not user:
        db.close()
        return RedirectResponse("/login", status_code=303)

    can_publish = is_admin(user) and is_public == "on"

    cover_path = ""

    if cover and cover.filename:
        file_location = f"static/covers/{cover.filename}"

        with open(file_location, "wb") as file_object:
            file_object.write(cover.file.read())

        cover_path = f"/static/covers/{cover.filename}"

    tab = Tab(
        title=title,
        artist=artist,
        cover_url=cover_path,
        spotify_url=spotify_url,
        capo=capo,
        strumming=strumming,
        picking=picking,
        chords=chords,
        original_text=original_text,
        simplified_text=simplify_tab(original_text),
        is_public=can_publish,
        user_id=user.id
    )

    db.add(tab)
    db.commit()
    db.close()

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/tabs/{tab_id}")
def tab_detail(request: Request, tab_id: int):
    db = SessionLocal()

    user = get_current_user(request, db)
    tab = db.query(Tab).filter(Tab.id == tab_id).first()

    if not tab:
        db.close()
        return RedirectResponse("/", status_code=303)

    if not user:
        db.close()
        return RedirectResponse("/register", status_code=303)

    if not tab.is_public and tab.user_id != user.id:
        db.close()
        return RedirectResponse("/dashboard", status_code=303)

    favorite = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.tab_id == tab.id)
        .first()
    )

    chord_list = split_chords(tab.chords)

    chord_cards = []

    for chord in chord_list:
        chord_cards.append(
            {
                "name": chord,
                "image_url": f"/static/chords/{chord}.png",
                "has_image": chord_image_exists(chord)
            }
        )

    response = templates.TemplateResponse(
        request,
        "tab_detail.html",
        {
            "user": user,
            "tab": tab,
            "is_favorite": True if favorite else False,
            "chord_cards": chord_cards
        }
    )

    db.close()
    return response

@app.get("/tabs/{tab_id}/edit")
def edit_song_page(request: Request, tab_id: int):
    db = SessionLocal()

    user = get_current_user(request, db)
    tab = db.query(Tab).filter(Tab.id == tab_id).first()

    if not user:
        db.close()
        return RedirectResponse("/login", status_code=303)

    if not tab:
        db.close()
        return RedirectResponse("/", status_code=303)

    if tab.user_id != user.id and not is_admin(user):
        db.close()
        return RedirectResponse("/dashboard", status_code=303)

    response = templates.TemplateResponse(
        request,
        "edit_song.html",
        {
            "user": user,
            "tab": tab,
            "is_admin": is_admin(user)
        }
    )

    db.close()
    return response


@app.post("/tabs/{tab_id}/edit")
def edit_song(
    request: Request,
    tab_id: int,
    title: str = Form(...),
    artist: str = Form(""),
    cover_url: str = Form(""),
    spotify_url: str = Form(""),
    capo: str = Form("Без капо"),
    strumming: str = Form(""),
    picking: str = Form(""),
    chords: str = Form(""),
    original_text: str = Form(""),
    is_public: str = Form(None)
):
    db = SessionLocal()

    user = get_current_user(request, db)
    tab = db.query(Tab).filter(Tab.id == tab_id).first()

    if not user:
        db.close()
        return RedirectResponse("/login", status_code=303)

    if not tab:
        db.close()
        return RedirectResponse("/", status_code=303)

    if tab.user_id != user.id and not is_admin(user):
        db.close()
        return RedirectResponse("/dashboard", status_code=303)

    tab.title = title
    tab.artist = artist
    tab.cover_url = cover_url
    tab.spotify_url = spotify_url
    tab.capo = capo
    tab.strumming = strumming
    tab.picking = picking
    tab.chords = chords
    tab.original_text = original_text
    tab.simplified_text = simplify_tab(original_text)

    if is_admin(user):
        tab.is_public = True if is_public == "on" else False

    db.commit()
    db.close()

    return RedirectResponse(f"/tabs/{tab_id}", status_code=303)


@app.post("/favorite/{tab_id}")
def toggle_favorite(request: Request, tab_id: int):
    db = SessionLocal()

    user = get_current_user(request, db)

    if not user:
        db.close()
        return RedirectResponse("/login", status_code=303)

    tab = db.query(Tab).filter(Tab.id == tab_id).first()

    if not tab:
        db.close()
        return RedirectResponse("/", status_code=303)

    favorite = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.tab_id == tab.id)
        .first()
    )

    if favorite:
        db.delete(favorite)
    else:
        db.add(Favorite(user_id=user.id, tab_id=tab.id))

    db.commit()
    db.close()

    return RedirectResponse(f"/tabs/{tab_id}", status_code=303)

@app.post("/tabs/{tab_id}/delete")
def delete_song(request: Request, tab_id: int):
    db = SessionLocal()

    user = get_current_user(request, db)
    tab = db.query(Tab).filter(Tab.id == tab_id).first()

    if not user:
        db.close()
        return RedirectResponse("/login", status_code=303)

    if not tab:
        db.close()
        return RedirectResponse("/", status_code=303)

    if tab.user_id != user.id and not is_admin(user):
        db.close()
        return RedirectResponse("/dashboard", status_code=303)

    favorites = db.query(Favorite).filter(Favorite.tab_id == tab.id).all()

    for favorite in favorites:
        db.delete(favorite)

    db.delete(tab)
    db.commit()
    db.close()

    return RedirectResponse("/dashboard", status_code=303)