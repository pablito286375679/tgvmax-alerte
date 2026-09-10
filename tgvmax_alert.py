import os
import json
import argparse
from datetime import datetime, date, timedelta
import urllib.parse
import urllib.request
import urllib.error

# Point de terminaison officiel de l'API Open Data SNCF
SNCF_API_URL = "https://data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax/records"
CACHE_FILE = "tgvmax_seen_trains.json"

# Trajets surveillés par défaut au départ et à destination d'Angers
DEFAULT_ROUTES = [
    {
        "origine": "ANGERS SAINT LAUD",
        "destination": "PARIS (intramuros)",
        "heure_min": "06:00",
        "heure_max": "23:00"
    },
    {
        "origine": "PARIS (intramuros)",
        "destination": "ANGERS SAINT LAUD",
        "heure_min": "06:00",
        "heure_max": "23:00"
    },
    {
        "origine": "ANGERS SAINT LAUD",
        "destination": "LILLE (intramuros)",
        "heure_min": "06:00",
        "heure_max": "23:00"
    },
    {
        "origine": "ANGERS SAINT LAUD",
        "destination": "TOURS",
        "heure_min": "06:00",
        "heure_max": "23:00"
    }
]

def load_cache():
    """Charge l'historique des identifiants de trains déjà notifiés pour bloquer les doublons."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as err:
            print(f"[Cache] Erreur lors du chargement : {err}")
            return set()
    return set()

def save_cache(seen_set):
    """Sauvegarde les 600 derniers identifiants de trains notifiés dans le cache JSON."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_set)[-600:], f, indent=2, ensure_ascii=False)
        print(f"[Cache] Enregistré ({len(seen_set)} trains mémorisés).")
    except Exception as err:
        print(f"[Cache] Erreur lors de l'écriture : {err}")

def query_sncf_tgvmax(origine, destination, date_min, date_max):
    """Interroge directement l'API Open Data SNCF (dataset tgvmax)."""
    orig_clean = origine.replace('-', ' ').strip().upper()
    dest_clean = destination.replace('-', ' ').strip().upper()

    clauses = [
        'od_happy_card="OUI"',
        f'date >= "{date_min}"',
        f'date <= "{date_max}"'
    ]

    # Normalisation pour la gare d'origine
    if "ANGERS" in orig_clean:
        clauses.append('(origine="ANGERS SAINT LAUD" or startswith(origine, "ANGERS"))')
    else:
        clauses.append(f'(origine="{orig_clean}" or startswith(origine, "{orig_clean}"))')

    # Normalisation pour la gare de destination
    if "PARIS" in dest_clean:
        clauses.append('(destination="PARIS (intramuros)" or startswith(destination, "PARIS"))')
    elif "LILLE" in dest_clean:
        clauses.append('(startswith(destination, "LILLE") or destination="LILLE (intramuros)")')
    elif "TOURS" in dest_clean or "PIERRE" in dest_clean:
        clauses.append('(destination="TOURS" or startswith(destination, "ST PIERRE DES CORPS") or destination="ST PIERRE DES CORPS")')
    else:
        clauses.append(f'(destination="{dest_clean}" or startswith(destination, "{dest_clean}"))')

    params = {
        "where": " AND ".join(clauses),
        "order_by": "date desc, heure_depart asc",  # Priorité aux dates les plus lointaines (J+30)
        "limit": 100
    }

    url = f"{SNCF_API_URL}?{urllib.parse.urlencode(params)}"
    print(f"[API SNCF] Recherche : {origine} ➔ {destination}...")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "TGVMaxBot/3.0 (GitHubActions-5Min)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status == 200:
                payload = json.loads(response.read().decode("utf-8"))
                records = payload.get("results", [])
                print(f"[API SNCF] {len(records)} train(s) à 0 € trouvé(s).")
                return records
    except Exception as err:
        print(f"[API SNCF] Erreur d'interrogation : {err}")
        return []

def build_email_html(trains_found, target_d30_str):
    """Crée un email HTML responsive et lisible sur mobile avec mise en valeur de J+30."""
    rows = ""
    has_d30 = False

    for t in trains_found:
        date_str = t.get("date", "N/A")
        is_d30 = (date_str == target_d30_str)
        if is_d30:
            has_d30 = True

        h_dep = t.get("heure_depart", "N/A")
        h_arr = t.get("heure_arrivee", "N/A")
        num = t.get("train_no", "N/A")
        orig = t.get("origine", "")
        dest = t.get("destination", "")

        tag_d30 = '<span style="background:#ff2a85;color:#ffffff;font-size:10px;font-weight:900;padding:2px 6px;border-radius:6px;margin-left:6px;">NOUVEAU J+30</span>' if is_d30 else ''

        rows += f"""
        <tr style="border-bottom: 1px solid #25386b; background: {'rgba(255,42,133,0.12)' if is_d30 else 'transparent'};">
            <td style="padding: 12px; font-weight: bold; color: #ff2a85;">
                {date_str} {tag_d30}
            </td>
            <td style="padding: 12px; font-weight: bold; color: #ffffff;">{h_dep} &rarr; {h_arr}</td>
            <td style="padding: 12px; color: #94a3b8; font-size: 13px;">TGV n°{num}</td>
            <td style="padding: 12px; color: #cbd5e1;">{orig} &rarr; {dest}</td>
            <td style="padding: 12px; text-align: right;">
                <span style="background: #10b981; color: #042f2e; font-weight: 900; font-size: 12px; padding: 4px 10px; border-radius: 20px;">0 €</span>
            </td>
        </tr>
        """

    header_title = "⚡ NOUVELLES PLACES J+30 OUVERTES !" if has_d30 else "⚡ Place TGV Max disponible à 0 € !"

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #060c1e; color: #f8fafc; padding: 20px; margin: 0;">
        <div style="max-width: 620px; margin: auto; background: #0e1834; border-radius: 20px; padding: 24px; border: 1px solid #25386b;">
            <div style="text-align: center; margin-bottom: 20px;">
                <span style="display: inline-block; width: 46px; height: 46px; line-height: 46px; background: #ff2a85; border-radius: 14px; font-size: 24px;">⚡</span>
                <h1 style="color: #ffffff; font-size: 20px; font-weight: 900; margin: 12px 0 4px 0;">{header_title}</h1>
                <p style="color: #94a3b8; font-size: 13px; margin: 0;">Réservation immédiate conseillée avant épuisement des quotas.</p>
            </div>

            <table style="width: 100%; border-collapse: collapse; text-align: left; margin: 18px 0; font-size: 14px;">
                <thead>
                    <tr style="border-bottom: 2px solid #25386b; color: #94a3b8; font-size: 11px; text-transform: uppercase;">
                        <th style="padding: 8px 12px;">Date</th>
                        <th style="padding: 8px 12px;">Horaires</th>
                        <th style="padding: 8px 12px;">Train</th>
                        <th style="padding: 8px 12px;">Trajet</th>
                        <th style="padding: 8px 12px; text-align: right;">Tarif</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>

            <div style="text-align: center; margin: 28px 0 10px 0;">
                <a href="https://www.sncf-connect.com/app/home/shop" 
                   style="background: linear-gradient(135deg, #10b981, #059669); color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 14px; font-weight: 900; font-size: 15px; display: inline-block; box-shadow: 0 4px 15px rgba(16,185,129,0.4);">
                    Réserver sur SNCF Connect &rarr;
                </a>
            </div>
            <p style="text-align: center; font-size: 11px; color: #64748b; margin-top: 20px;">Vigie automatique TGV Max Jeune • Scan toutes les 5 minutes</p>
        </div>
    </body>
    </html>
    """

def send_alert_resend(api_key, recipient, new_trains, target_d30_str):
    """Expédie l'alerte instantanée via l'API officielle Resend."""
    first = new_trains[0]
    has_d30 = any(t.get("date") == target_d30_str for t in new_trains)
    prefix = "🚨 [J+30 OUVERT]" if has_d30 else "⚡ [0 € DISPO]"
    subject = f"{prefix} {first.get('origine')} ➔ {first.get('destination')} ({len(new_trains)} train(s))"

    html_content = build_email_html(new_trains, target_d30_str)

    payload = {
        "from": "Alerte TGV Max <onboarding@resend.dev>",
        "to": [recipient],
        "subject": subject,
        "html": html_content
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TGVMaxBot/3.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status in (200, 201):
                print(f"✅ [Resend] Alerte expédiée avec succès à {recipient} !")
                return True
    except Exception as err:
        print(f"❌ [Resend] Échec de l'envoi : {err}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Robot de surveillance TGV Max")
    parser.add_argument("--once", action="store_true", help="Exécute un seul cycle de vérification")
    args = parser.parse_args()

    resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
    recipient_email = os.getenv("RECIPIENT_EMAIL", "").strip()

    if not resend_api_key or not recipient_email:
        print("⚠️ Variables d'environnement RESEND_API_KEY ou RECIPIENT_EMAIL manquantes.")
        return

    today = date.today()
    max_date = today + timedelta(days=30)
    target_d30_str = max_date.isoformat()
    date_min = today.isoformat()
    date_max = target_d30_str

    routes = DEFAULT_ROUTES
    env_routes = os.getenv("ROUTES_JSON", "").strip()
    if env_routes:
        try:
            routes = json.loads(env_routes)
        except Exception as e:
            print(f"[Config] Erreur lecture ROUTES_JSON : {e}")

    print(f"=== Surveillance TGV Max 5 Min ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    print(f"🎯 Jour cible J+30 : {target_d30_str}")

    seen_trains = load_cache()
    newly_opened = []

    for r in routes:
        orig = r.get("origine", "ANGERS SAINT LAUD")
        dest = r.get("destination", "PARIS (intramuros)")
        h_min = r.get("heure_min", "00:00")
        h_max = r.get("heure_max", "23:59")

        results = query_sncf_tgvmax(orig, dest, date_min, date_max)
        for t in results:
            train_date = t.get("date")
            train_num = t.get("train_no")
            train_dep = t.get("heure_depart", "00:00")

            if not (h_min <= train_dep <= h_max):
                continue

            unique_key = f"{train_date}_{orig}_{dest}_{train_num}_{train_dep}"
            if unique_key not in seen_trains:
                is_d30_label = " [🔥 J+30]" if train_date == target_d30_str else ""
                print(f"  🎯 NOUVEAU TRAIN{is_d30_label} : {train_date} à {train_dep} ({train_num})")
                seen_trains.add(unique_key)
                newly_opened.append(t)

    if newly_opened:
        print(f"\n⚡ {len(newly_opened)} nouvelle(s) place(s) détectée(s). Envoi du mail...")
        send_alert_resend(resend_api_key, recipient_email, newly_opened, target_d30_str)
        save_cache(seen_trains)
    else:
        print("\nAucune nouvelle place détectée lors de ce passage.")

if __name__ == "__main__":
    main()
