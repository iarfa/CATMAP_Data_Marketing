# Fichier: scripts/import_data.py

import csv
import sqlalchemy
import time
import sys

# ====================================================================
# 1. CONFIGURATION
# ====================================================================

# Connexion à la base de données Docker (Port 5433)
DB_URI = "postgresql://sirene_user:application_catmap_datamarketing_geodata2025!@localhost:5433/sirene_france"

# Chemin fichier CSV (sortie des scripts 1 et 2)
PATH_VOTRE_CSV = r"C:\Users\ilyes.arfa_square-ma\OneDrive - Circle Strategy\Bureau\CATMAP_Data_Marketing\Fichier_final_CATMAP_Novembre25.csv"


# ====================================================================
# 2. LOGIQUE D'IMPORTATION
# ====================================================================

def import_csv_data_robuste(engine):
    print("--- Étape 1/3 : Importation des données ---")
    print(f"Source : {PATH_VOTRE_CSV}")

    conn = engine.raw_connection()
    cursor = conn.cursor()
    start_time = time.time()
    total_rows = 0

    try:
        with open(PATH_VOTRE_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=',')  # On utilise la virgule comme séparateur

            # --- A. Lecture et Nettoyage des En-têtes ---
            header = next(reader)
            # On nettoie les noms pour SQL (enlever espaces, majuscules, guillemets)
            header_sql = [h.strip().lower().replace(" ", "_").replace("'", "") for h in header]

            print(f"Colonnes détectées ({len(header)}) : {header_sql}")

            # --- B. Reset de la Table (DROP & CREATE) ---
            print("Suppression de l'ancienne table...")
            cursor.execute("DROP TABLE IF EXISTS etablissements;")

            print("Création de la nouvelle table (15 colonnes)...")
            create_table_sql = """
            CREATE TABLE etablissements (
                siren TEXT, 
                siret TEXT, 
                datecreationetablissement TEXT, 
                etablissementsiege BOOLEAN, 
                adresse TEXT, 
                activiteprincipaleetablissement TEXT, 
                denominationunitelegale TEXT, 
                numero_dep TEXT, 
                nom_dep TEXT, 
                longitude DOUBLE PRECISION, 
                latitude DOUBLE PRECISION, 
                precision_geocodage TEXT, 
                categorie TEXT, 
                intitules_naf_vf TEXT, 
                nombre_d_etablissements DOUBLE PRECISION
            );
            """
            cursor.execute(create_table_sql)
            conn.commit()

            # --- C. Repérage des colonnes critiques ---
            # On cherche les index pour convertir les types au vol
            try:
                # On cherche "longitude", "latitude", "etablissementsiege", "nombre..." dans les en-têtes nettoyés
                idx_lon = header_sql.index('longitude')
                idx_lat = header_sql.index('latitude')
                idx_siege = header_sql.index('etablissementsiege')

                # Pour le nombre d'établissements, on cherche le mot clé si le nom exact varie
                idx_nombre = -1
                for i, col in enumerate(header_sql):
                    if "nombre" in col and "etablissement" in col:
                        idx_nombre = i
                        break
            except ValueError as e:
                print(f"ERREUR FATALE : Colonne manquante dans le CSV ({e})")
                sys.exit(1)

            # --- D. Insertion des données ---
            # On prépare la requête SQL avec le bon nombre de placeholders (%s)
            placeholders = ", ".join(["%s"] * len(header))
            insert_query = f"INSERT INTO etablissements VALUES ({placeholders})"

            buffer = []

            for line in reader:
                total_rows += 1

                # Sécurité : Si la ligne n'a pas le bon nombre de colonnes, on la saute
                if len(line) != len(header):
                    continue

                # 1. Nettoyage Latitude / Longitude (Conversion en float)
                try:
                    line[idx_lon] = float(str(line[idx_lon]).replace(',', '.')) if line[idx_lon] else None
                except:
                    line[idx_lon] = None

                try:
                    line[idx_lat] = float(str(line[idx_lat]).replace(',', '.')) if line[idx_lat] else None
                except:
                    line[idx_lat] = None

                # 2. Nettoyage Nombre d'établissements
                if idx_nombre != -1:
                    try:
                        line[idx_nombre] = float(str(line[idx_nombre]).replace(',', '.')) if line[idx_nombre] else None
                    except:
                        line[idx_nombre] = None

                # 3. Nettoyage Booléen Siège
                val_siege = str(line[idx_siege]).lower().strip()
                line[idx_siege] = (val_siege in ['true', '1', 'vrai', 'oui'])

                # 4. Gestion des vides (String vide -> NULL SQL)
                cleaned_line = [None if str(v).strip() == '' else v for v in line]

                buffer.append(tuple(cleaned_line))

                # Insertion par lots de 20 000
                if len(buffer) >= 20000:
                    cursor.executemany(insert_query, buffer)
                    conn.commit()
                    buffer = []
                    print(f"  -> {total_rows:,} lignes traitées...")

            # Insertion du reste
            if buffer:
                cursor.executemany(insert_query, buffer)
                conn.commit()
                print(f"  -> {total_rows:,} lignes traitées (FIN).")

    except Exception as e:
        print(f"\n[ERREUR CRITIQUE] : {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

    end_time = time.time()
    print(f"✅ Import terminé en {end_time - start_time:.2f} secondes.")


def create_indexes_and_geom(engine):
    print("\n--- Étape 2/3 : Géométrie et Index ---")
    start_time = time.time()

    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("COMMIT"))  # Obligatoire pour CREATE INDEX / VACUUM etc

        print("  -> Activation PostGIS...")
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS postgis;"))

        print("  -> Ajout colonne géométrie...")
        conn.execute(sqlalchemy.text("ALTER TABLE etablissements ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);"))

        print("  -> Calcul des points GPS (Cela peut prendre quelques minutes)...")
        conn.execute(sqlalchemy.text("""
            UPDATE etablissements
            SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
            WHERE longitude IS NOT NULL AND latitude IS NOT NULL;
        """))
        conn.execute(sqlalchemy.text("COMMIT"))

        print("  -> Création des index (SIRET, SIREN, NAF, GEOM)...")
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS idx_etab_siret ON etablissements (siret);"))
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS idx_etab_siren ON etablissements (siren);"))
        conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS idx_etab_naf ON etablissements (activiteprincipaleetablissement);"))
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS idx_etab_geom ON etablissements USING GIST (geom);"))
        conn.execute(sqlalchemy.text("COMMIT"))

    end_time = time.time()
    print(f"✅ Géométrie et Index terminés en {end_time - start_time:.2f} secondes.")


def analyze_database(engine):
    print("\n--- Étape 3/3 : Optimisation ---")
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("COMMIT"))
        conn.execute(sqlalchemy.text("ANALYZE etablissements;"))
    print("✅ Base optimisée.")


# ====================================================================
# EXÉCUTION
# ====================================================================
if __name__ == "__main__":
    try:
        engine = sqlalchemy.create_engine(DB_URI)
        # Test de connexion
        with engine.connect() as conn:
            pass

        import_csv_data_robuste(engine)
        create_indexes_and_geom(engine)
        analyze_database(engine)

        print("\n🎉🎉🎉 TOUT EST PRÊT ! Vous pouvez relancer Streamlit. 🎉🎉🎉")

    except Exception as e:
        print(f"Impossible de se connecter à la base : {e}")
        print("Vérifiez que Docker tourne (docker ps) et que le port 5433 est ouvert.")