import os
import json
import argparse
from datetime import datetime, date, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    PARIS_TZ = timezone(timedelta(hours=2))
import urllib.parse
import urllib.request
import urllib.error

SNCF_API_URL = "https://data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax/records"
CACHE_FILE = "tgvmax_seen_trains.json"

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
    """Charge la liste des identifiants de trains actifs lors de la dernière exécution."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception as err:
            print(f"[Cache] Erreur de lecture : {err}")
            return set()
    return set()

def save_cache(current_active_keys):
    """Enregistre l'état exact des trains disponibles actuellement pour détecter tout changement ou nouvelle libération."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(current_active_keys), f, indent=2, ensure_ascii=False)
        print(f"[Cache] Enregistré ({len(current_active_keys)} train(s) actuellement actifs).")
    except Exception as err:
        print(f"[Cache] Erreur d'écriture : {err}")

def query_sncf_tgvmax(origine, destination, date_min, date_max):
    """Interroge l'API SNCF avec pagination automatique pour ne manquer AUCUN train (dépassement du cap de 100)."""
    orig_clean = origine.replace('-', ' ').strip().upper()
    dest_clean = destination.replace('-', ' ').strip().upper()

    clauses = [
        'od_happy_card="OUI"',
        f'date >= "{date_min}"',
        f'date <= "{date_max}"'
    ]

    # Filtrage strict sans opérateur search() pour ne jamais confondre Angers et Angoulême
    if "ANGERS" in orig_clean:
        clauses.append('(origine = "ANGERS SAINT LAUD" or origine like "ANGERS %")')
    elif "PARIS" in orig_clean:
        clauses.append('(origine = "PARIS (intramuros)" or origine like "PARIS %")')
    elif "LILLE" in orig_clean:
        clauses.append('(origine = "LILLE (intramuros)" or origine like "LILLE %")')
    elif any(k in orig_clean for k in ("TOURS", "CORPS", "PIERRE")):
        clauses.append('(origine = "TOURS" or origine = "ST PIERRE DES CORPS" or origine like "ST PIERRE DES CORPS %" or origine like "TOURS %")')
    else:
        clauses.append(f'origine = "{orig_clean}"')

    if "PARIS" in dest_clean:
        clauses.append('(destination = "PARIS (intramuros)" or destination like "PARIS %")')
    elif "LILLE" in dest_clean:
        clauses.append('(destination = "LILLE (intramuros)" or destination like "LILLE %")')
    elif any(k in dest_clean for k in ("TOURS", "CORPS", "PIERRE")):
        clauses.append('(destination = "TOURS" or destination = "ST PIERRE DES CORPS" or destination like "ST PIERRE DES CORPS %" or destination like "TOURS %")')
    elif "ANGERS" in dest_clean:
        clauses.append('(destination = "ANGERS SAINT LAUD" or destination like "ANGERS %")')
    else:
        clauses.append(f'destination = "{dest_clean}"')

    where_str = " AND ".join(clauses)
    all_records = []
    offset = 0
    limit = 100

    while offset < 1000:
        params = {
            "where": where_str,
            "order_by": "date asc, heure_depart asc",
            "limit": limit,
            "offset": offset
        }

        url = f"{SNCF_API_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "TGVMaxBot/3.1 (GitHubActions-Reliability)"}
        )

        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    batch = payload.get("results", [])
                    all_records.extend(batch)
                    if len(batch) < limit:
                        break
                    offset += limit
                else:
                    break
        except Exception as err:
            print(f"[API SNCF] Erreur pagination à offset {offset} : {err}")
            break

    print(f"[API SNCF] {origine} ➔ {destination} : {len(all_records)} train(s) à 0 € récupérés au total.")
    return all_records

def build_email_html(trains_found, target_d30_str):
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
        <tr style="border-bottom: 1px solid #25386b; background: {'rgba(255,42,133,0.15)' if is_d30 else 'transparent'};">
            <td style="padding: 12px; font-weight: bold; color: #ff2a85;">
                {date_str} {tag_d30}
            </td>
            <td style="padding: 12px; font-weight: bold; color: #ffffff;">{h_dep} &rarr; {h_arr}</td>
            <td style="padding: 12px; color: #94a3b8; font-size: 13px;">TGV n°{num}</td>
            <td style="padding: 12px; color: #cbd5e1;">{orig} &rarr; {dest}</td>
            <td style="padding: 12px; text-align: right;">
                <span style="background: #10b981; color: #042f2e; font-weight: 900; font-size: 12px; padding: 4px 10px; border-radius: 20px;">0 € DISPO</span>
            </td>
        </tr>
        """

    header_title = "⚡ NOUVELLES PLACES J+30 OUVERTES !" if has_d30 else "⚡ Place TGV Max libérée (0 €) !"

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #060c1e; color: #f8fafc; padding: 20px; margin: 0;">
        <div style="max-width: 620px; margin: auto; background: #0e1834; border-radius: 20px; padding: 24px; border: 1px solid #25386b;">
            <div style="text-align: center; margin-bottom: 20px;">
                <span style="display: inline-block; width: 46px; height: 46px; line-height: 46px; background: #ff2a85; border-radius: 14px; font-size: 24px;">⚡</span>
                <h1 style="color: #ffffff; font-size: 20px; font-weight: 900; margin: 12px 0 4px 0;">{header_title}</h1>
                <p style="color: #94a3b8; font-size: 13px; margin: 0;">Une place vient d'apparaître ou d'être libérée sur votre trajet.</p>
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
            <p style="text-align: center; font-size: 11px; color: #64748b; margin-top: 20px;">Vigie automatique TGV Max • Scan continu toutes les 5 minutes</p>
        </div>
    </body>
    </html>
    """

def send_alert_resend(api_key, recipient, new_trains, target_d30_str):
    first = new_trains[0]
    has_d30 = any(t.get("date") == target_d30_str for t in new_trains)
    prefix = "🚨 [J+30 OUVERT]" if has_d30 else "⚡ [0 € LIBÉRÉ]"
    subject = f"{prefix} {first.get('origine')} ➔ {first.get('destination')} ({len(new_trains)} place(s))"

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
            "User-Agent": "TGVMaxBot/3.1"
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

    now_paris = datetime.now(PARIS_TZ)
    today = now_paris.date()
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

    print(f"=== Surveillance TGV Max ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    print(f"🎯 Jour cible J+30 : {target_d30_str}")

    # Charge l'ensemble des trains qui étaient disponibles au passage précédent
    previously_seen = load_cache()
    current_active_keys = set()
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
            current_active_keys.add(unique_key)

            # Si ce train n'était PAS disponible lors de la dernière vérification, on alerte !
            if unique_key not in previously_seen:
                is_d30_label = " [🔥 J+30]" if train_date == target_d30_str else ""
                print(f"  🎯 NOUVEAU TRAIN DISPONIBLE{is_d30_label} : {train_date} à {train_dep} ({train_num})")
                newly_opened.append(t)

    if newly_opened:
        print(f"\n⚡ {len(newly_opened)} nouvelle(s) place(s) détectée(s). Envoi de l'email d'alerte...")
        send_alert_resend(resend_api_key, recipient_email, newly_opened, target_d30_str)
        # Met à jour l'état actuel des trains disponibles
        save_cache(current_active_keys)
    else:
        print("\nAucune nouvelle place détectée lors de ce passage.")
        # Sauvegarde tout de même pour désinscrire les trains qui sont devenus complets
        save_cache(current_active_keys)

if __name__ == "__main__":
    main()
