# Fichier: database.py
import streamlit as st
import sqlalchemy

@st.cache_resource(show_spinner="Connexion BDD...")
def connect_to_db():
    """
    Crée et met en cache le moteur de connexion SQLAlchemy.
    """
    try:
        db_user = "sirene_user"
        db_pass = "application_catmap_datamarketing_geodata2025!"
        db_host = "localhost"
        db_port = "5433"
        db_name = "sirene_france"

        # Pour la prod (si secrets):
        # db_user = st.secrets["DB_USER"]
        # ...

        db_uri = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = sqlalchemy.create_engine(db_uri)

        # Test rapide
        with engine.connect() as conn:
            pass

        return engine

    except Exception as e:
        print(f"Erreur connexion BDD: {e}")
        return None