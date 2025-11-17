# Fichier: scripts/import_data.py
# (Version ROBUSTE FINALE - N'utilise pas Pandas pour la lecture)
# A FAIRE qu'une seule fois

import csv
import psycopg2  # On utilise le pilote de base
import sqlalchemy
import time
import sys
import re

# ====================================================================
# 1. CONFIGURATION UTILISATEUR
# ====================================================================

DB_URI = "postgresql://sirene_user:application_catmap_datamarketing_geodata2025!@localhost:5433/sirene_france"

# ⬇️ CHEMIN VERS VOTRE FICHIER PROPRE (celui de sortie du script précédent) ⬇️
PATH_VOTRE_CSV_PROPRE = r"C:\Users\ilyes.arfa_square-ma\OneDrive - Circle Strategy\Bureau\CATMAP_Data_Marketing\fichier_final_CLEAN.csv"


# ====================================================================
# 2. FONCTIONS D'IMPORTATION
# ====================================================================

def import_csv_data_robuste(engine):
    """
    Importe votre CSV pré-nettoyé LIGNE PAR LIGNE.
    C'est plus lent, mais ça ne plantera pas sur les erreurs de type.
    """
    print("--- Étape 1/3 : Démarrage de l'importation (Mode Robuste) ---")
    print(f"Fichier source : {PATH_VOTRE_CSV_PROPRE}")
    print("Cela peut prendre 1 à 2 heures.")

    # On se connecte avec psycopg2
    conn = engine.raw_connection()
    cursor = conn.cursor()

    start_time = time.time()
    total_rows = 0

    try:
        with open(PATH_VOTRE_CSV_PROPRE, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=',')

            # --- 1. Traitement de l'en-tête ---
            header = next(reader)
            # On s'assure que les noms sont "safe" pour SQL (sans "")
            header_sql = [f'"{h}"' for h in header]

            # Crée la table
            # On définit TOUTES les colonnes en TEXT, sauf lat/lon/nombre
            # C'est la clé pour éviter l'erreur "00nan"
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS etablissements (
                siren TEXT, siret TEXT, datecreationetablissement TEXT, datederniertraitementetablissement TEXT, 
                etablissementsiege BOOLEAN, numerovoieetablissement TEXT, typevoieetablissement TEXT, 
                libellevoieetablissement TEXT, codepostaletablissement TEXT, libellecommuneetablissement TEXT, 
                activiteprincipaleetablissement TEXT, caractereemployeuretablissement TEXT, 
                denominationunitelegale TEXT, precision_geocodage TEXT, 
                longitude DOUBLE PRECISION, latitude DOUBLE PRECISION, 
                intitules_naf_vf TEXT, intitules_naf_65_caracteres TEXT, 
                categorie TEXT, nombre_d_etablissements DOUBLE PRECISION, 
                numero_dep TEXT, adresse TEXT, nom_dep TEXT
            );
            """
            cursor.execute(create_table_sql)
            conn.commit()

            # On trouve les index des colonnes à convertir
            idx_lon = header.index('longitude')
            idx_lat = header.index('latitude')
            idx_siege = header.index('etablissementsiege')
            idx_nombre = header.index('nombre_d_etablissements')

            # --- 2. Préparation de la requête d'insertion ---
            insert_query = f"INSERT INTO etablissements ({', '.join(header_sql)}) VALUES ({'%s, ' * (len(header) - 1)}%s)"

            # --- 3. Lecture des lignes ---
            buffer = []
            for line in reader:
                total_rows += 1

                # --- Nettoyage des types ---
                # On convertit les types numériques, et on met None si ça échoue
                try:
                    line[idx_lon] = float(line[idx_lon]) if line[idx_lon] else None
                except (ValueError, TypeError):
                    line[idx_lon] = None

                try:
                    line[idx_lat] = float(line[idx_lat]) if line[idx_lat] else None
                except (ValueError, TypeError):
                    line[idx_lat] = None

                try:
                    line[idx_nombre] = float(line[idx_nombre]) if line[idx_nombre] else None
                except (ValueError, TypeError):
                    line[idx_nombre] = None

                # Conversion du booléen
                line[idx_siege] = (str(line[idx_siege]).lower() == 'true')

                # Remplacer les chaînes vides par None (NULL en SQL)
                line_with_nulls = [None if v == '' else v for v in line]

                buffer.append(tuple(line_with_nulls))

                # On insère par paquets de 20 000 (rapide et sûr)
                if len(buffer) >= 20000:
                    cursor.executemany(insert_query, buffer)
                    buffer = []
                    print(f"  -> Traitement... ({total_rows:,} lignes importées)")

            # On insère le reste du buffer
            if buffer:
                cursor.executemany(insert_query, buffer)
                print(f"  -> Traitement... ({total_rows:,} lignes importées)")

    except Exception as e:
        print(f"\n[ERREUR PENDANT L'IMPORTATION] : {e}")
        print(f"Erreur survenue autour de la ligne {total_rows}")
        conn.rollback()
        cursor.close()
        conn.close()
        sys.exit(1)

    # Si tout va bien, on valide
    conn.commit()
    cursor.close()
    conn.close()

    end_time = time.time()
    print(f"✅ Étape 1/3 Terminée : {total_rows:,} lignes importées en {end_time - start_time:.2f} secondes.")


# ... (Le reste du script, Étape 2 et 3, est identique) ...

def create_indexes_and_geom(engine):
    print("\n--- Étape 2/3 : Création de la géométrie et des index ---")
    print("Cela peut prendre 30-60 minutes.")

    start_time = time.time()

    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("COMMIT"))

        print("  -> Activation de l'extension 'postgis'...")
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS postgis;"))

        print("  -> Création de la colonne 'geom'...")
        conn.execute(sqlalchemy.text("ALTER TABLE etablissements ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);"))

        print("  -> Remplissage de 'geom' à partir de longitude/latitude...")
        conn.execute(sqlalchemy.text("""
            UPDATE etablissements
            SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
            WHERE longitude IS NOT NULL AND latitude IS NOT NULL;
        """))
        conn.execute(sqlalchemy.text("COMMIT"))

        print("  -> Indexation de la table (siret)...")
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS idx_etab_siret ON etablissements (siret);"))

        print("  -> Indexation de la table (siren)...")
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS idx_etab_siren ON etablissements (siren);"))

        print("  -> Indexation de la table (geom - SPATIAL)...")
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS idx_etab_geom ON etablissements USING GIST (geom);"))

    end_time = time.time()
    print(f"✅ Étape 2/3 Terminée : Indexation en {end_time - start_time:.2f} secondes.")


def analyze_database(engine):
    print("\n--- Étape 3/3 : Finalisation (ANALYZE) ---")
    start_time = time.time()

    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("COMMIT"))
        conn.execute(sqlalchemy.text("ANALYZE etablissements;"))

    end_time = time.time()
    print(f"✅ Étape 3/3 Terminée : Finalisation en {end_time - start_time:.2f} secondes.")
    print("\n🎉🎉🎉 L'importation est terminée ! Votre base de données est prête. 🎉🎉🎉")


# ====================================================================
# 4. EXÉCUTION DU SCRIPT
# ====================================================================

if __name__ == "__main__":
    try:
        # On utilise SQLAlchemy juste pour créer le moteur de connexion
        engine = sqlalchemy.create_engine(DB_URI)
        with engine.connect() as conn:
            print(f"Connexion à la base de données '{conn.engine.url.database}' réussie.")
    except Exception as e:
        print(f"[ERREUR] Impossible de se connecter à la base de données : {e}")
        print("Vérifiez que :")
        print("1. Votre conteneur Docker 'bdd_sirene_postgis' est bien lancé (docker ps).")
        print("2. L'URI de connexion (mot de passe, port 5433) est correcte.")
        sys.exit(1)

    try:
        total_start = time.time()

        import_csv_data_robuste(engine)  # On appelle la nouvelle fonction
        create_indexes_and_geom(engine)
        analyze_database(engine)

        total_end = time.time()
        print(f"Temps total de l'opération : {(total_end - total_start) / 60:.2f} minutes.")

    except FileNotFoundError as e:
        print(f"\n[ERREUR CRITIQUE] Fichier non trouvé.")
        print(f"{e}")
        print("Vérifiez que la variable 'PATH_VOTRE_CSV_PROPRE' est correcte en haut du script.")
    except Exception as e:
        print(f"\n[ERREUR INCONNUE] L'opération a été interrompue : {e}")
        print("Il est possible que la table 'etablissements' soit dans un état incomplet.")
        print("Vous devrez peut-être la supprimer (DROP TABLE etablissements;) avant de relancer.")