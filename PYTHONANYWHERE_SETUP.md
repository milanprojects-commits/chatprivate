# PythonAnywhere Setup Guide 🚀

## Quick Start (5-10 minuten)

### Stap 1: Account Aanmaken
1. Ga naar **www.pythonanywhere.com**
2. Klik "Sign up for free"
3. Kies username (dit wordt je domain: `username.pythonanywhere.com`)
4. Bevestig email

### Stap 2: Code Uploaden
1. Open **Files** in PythonAnywhere
2. Upload deze bestanden:
   - `app.py`
   - `templates/first.html`
   - `requirements.txt`

Zorg dat de mapstructuur is:
```
/home/username/mysite/
    ├── app.py
    ├── requirements.txt
    ├── templates/
    │   └── first.html
```

### Stap 3: Web App Aanmaken
1. Ga naar **Web** tab
2. Klik "Add a new web app"
3. Kies **Python 3.10** + **Flask**
4. Click "Next" (standaard instellingen)

### Stap 4: WSGI File Configureren
1. Klik op **Web** → je app
2. Onder "Code" → "WSGI configuration file"
3. Pas het aan naar:

```python
import sys
path = '/home/your_username/mysite'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app
application = app
```

Zorg dat je `/home/your_username/mysite` vervanger door je echte pad!

### Stap 5: Virtual Environment & Dependencies
1. Ga naar **Consoles**
2. Klik "Bash"
3. Voer uit:

```bash
cd ~/mysite
mkvirtualenv --python=/usr/bin/python3.10 mysite_venv
pip install -r requirements.txt
```

4. Terug in **Web** tab
5. Under "Virtualenv", voer in: `/home/your_username/.virtualenvs/mysite_venv`

### Stap 6: Herstarten
1. Klik de rode "Reload" knop bovenaan op Web tab
2. Wacht 10 seconden
3. Je app is live op: `https://your_username.pythonanywhere.com`

---

## Database & Persistent Storage ✅

De SQLite database (`chat.db`) wordt automatisch:
- **Aangemaakt** bij eerste start
- **Opgeslagen** in je project folder
- **Behouden** tussen restarts
- **Gedeeld** tussen alle web workers

### Database Toegang (Bash Console)

```bash
sqlite3 ~/mysite/chat.db
# Zie alle tables
.tables

# Zie alle chat rooms
SELECT * FROM chat_rooms;

# Verwijder een room
DELETE FROM chat_rooms WHERE room_id = 'abc123';
```

---

## Troubleshooting 🔧

**"App crashes" / "Internal Server Error"**
- Controleer error log in **Web** tab onder "Error log"
- Zorg dat `/home/your_username/mysite` correct is in WSGI file
- Klik "Reload" button

**"ModuleNotFoundError: No module named 'flask'"**
- Controleer Virtual Environment pad is juist
- Zorg dat je `pip install -r requirements.txt` hebt gedaan

**"Permission denied" op database**
- Database moet writable zijn
- Zorg dat `chat.db` in je project folder staat (niet in templates/)

---

## Limiteringen van Free Plan

| Feature | Free | Paid |
|---------|------|------|
| RAM | 512MB | Meer |
| Console | Ja | Ja |
| Always-on | Nee | Ja |
| CPU Time | Beperkt | Onbeperkt |
| Opslag | 512MB | Meer |

⚠️ **Gratis account wordt gepauzeerd na 3 maanden inactiviteit**

---

## Bonus: Custom Domain 🌍

1. Koop een domein (bijv. bij Namecheap)
2. In PythonAnywhere → Web → "Web address" → klik je domein
3. Volg instructies voor DNS-instellingen

---

## Logs & Debugging 📝

**Error Log checken:**
```bash
# In Bash Console
tail -f ~/mysite/error_log.txt
```

**SQL Queries debuggen:**
```python
# Voeg dit toe in app.py voor debug output
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Performance Tips ⚡

1. **Caching:** Voeg memcache toe voor snellere chatroom checks
2. **Compression:** Gzip responses in Flask
3. **Database Index:** Voeg index toe op `room_id` in messages table

```sql
CREATE INDEX idx_room_messages ON messages(room_id);
```

---

## Volgende Stap: Production-Ready 🎯

Voor een echte productie app:
1. **PostgreSQL** in plaats van SQLite (PythonAnywhere kan dit installeren)
2. **Gunicorn** web server
3. **Redis** voor real-time messaging
4. **SSL/TLS** (PythonAnywhere doet dit automatisch)

Veel succes! 🚀
