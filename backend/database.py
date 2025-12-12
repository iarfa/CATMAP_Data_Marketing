# Fichier: backend/database.py
import streamlit as st
import sqlalchemy
from sqlalchemy.engine import Engine


@st.cache_resource(show_spinner="Connexion BDD...")
def connect_to_db() -> Engine:
    """
    Crée et met en cache le moteur de connexion SQLAlchemy.
    Gère la connexion à la base PostGIS (Vectoriel & Raster).
    """
    try:
        # Configuration : Priorité aux secrets, sinon valeurs par défaut (Dev)
        # Basé sur le fichier database.py original
        if "DB_USER" in st.secrets:
            db_user = st.secrets["DB_USER"]
            db_pass = st.secrets["DB_PASS"]
            db_host = st.secrets["DB_HOST"]
            db_port = st.secrets["DB_PORT"]
            db_name = st.secrets["DB_NAME"]
        else:
            # Valeurs par défaut extraites de votre fichier original
            db_user = "sirene_user"
            db_pass = "application_catmap_datamarketing_geodata2025!"
            db_host = "localhost"
            db_port = "5433"  # Port spécifique conservé
            db_name = "sirene_france"

        db_uri = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

        # Création du moteur
        engine = sqlalchemy.create_engine(db_uri)

        # Test rapide de connexion (Ping)
        with engine.connect() as conn:
            # On vérifie juste que la connexion s'ouvre
            pass

        return engine

    except Exception as e:
        # On log l'erreur dans la console pour le dev backend
        print(f"❌ Erreur critique BDD : {e}")
        # On affiche une erreur utilisateur propre
        st.error(f"Impossible de se connecter à la base de données (Port {db_port}). Vérifiez le conteneur Docker.")
        return None