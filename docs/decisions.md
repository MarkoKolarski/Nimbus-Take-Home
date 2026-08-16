# Decisions Log

Format: ADR-lite. Svaki unos odgovara jednom git tagu; poruka tog taga je
tačno ovaj unos.

---

## v0.1-skeleton — 2026-08-16

### Kontekst

Prvi blok: `docker compose up --build` mora da digne prazan ali ispravan
sistem — bazu, S3 emulator, backend, frontend — sa 2 test korisnika i
fixture fajlovima već ubačenim, da bi svaki sledeći blok imao na čemu da
radi umesto da gradi infrastrukturu usput.

### Odluke

1. **Ceo `public` control-plane šema (users, tenants, sync_jobs) u jednoj
   Alembic migraciji**, iako `sync_jobs` ne koristi nijedan red koda do
   bloka "Sync state + worker". §3 ih tretira kao jednu celinu; druga
   migracija samo za `sync_jobs` kasnije ne bi ništa dobila.
2. **`provision_tenant()` piše kompletnu DDL od 7 tabela odmah**
   (datasources, directories, documents, contents, chunks, chats,
   chat_messages), iako ih većina stoji neiskorišćena do kasnijih blokova.
   §3 eksplicitno kaže da je provisioning "jedna verzionisana funkcija" —
   ne inkrementalna gradnja po bloku.
3. **`users.password_hash` dodat mimo §3-ovog skraćenog popisa kolona** —
   Auth blok već obećava pravi email+lozinka ekran za ova dva korisnika, a
   ovaj blok je taj koji pravi te redove; jeftinije je dodati kolonu sada
   nego raditi ALTER TABLE kasnije.
4. **Ime tenant šeme = `tenant_` + slug email lokalnog dela**
   (`tenant_alice`, `tenant_bob`) — čitljivo za demo, namerno nije
   collision-safe za buduće JIT-provizionisane korisnike (v1.5 problem).
5. **`tests/test_seed.py` kao četvrti test fajl**, mimo §8-ovog popisa od
   tri (test_isolation/test_dedup/test_sync_state) — CLAUDE.md zahteva da
   `pytest -q` stvarno prođe kao dokaz da je blok gotov; bez ijednog testa
   pytest vraća exit 5, ne čist prolaz. Ovo je odvojena, trajna briga
   (da li je bootstrap ispravan), ne duplikat ta tri.
6. **Nijedan FK u tenant šemi nema `ON DELETE CASCADE`** — §4-ov dizajn
   uklanjanja eksplicitno upravlja redosledom brisanja na nivou aplikacije
   (soft-delete → refcount → tek onda hard-delete roditelja); default
   `RESTRICT` to primorava i na nivou baze.
7. **Van obima namerno**: rute mimo `/health`, ORM domain modeli,
   `SET LOCAL search_path`, fastembed/pypdf/langchain zavisnosti, README.
   Sve već zakazano u kasnijim blokovima.

### Greške pronađene i ispravljene tokom izrade

- **Pogrešan DB drajver.** `database_url` podrazumevano `postgresql://...`
  bi SQLAlchemy razrešio na `psycopg2`, koji nije ni instaliran
  (instaliran je `psycopg` v3). Ispravka: `sqlalchemy_database_url`
  property koja dodaje `+psycopg` samo za SQLAlchemy potrošače; sirovi
  `psycopg.connect()` pozivi (seed, provisioning) i dalje koriste prostu
  DSN formu.
- **npm workspaces diže lockfile u koren.** Root `package.json` (iz Koraka
  1) već ima `workspaces: ["apps/*"]`, pa `npm install` unutar `apps/web`
  stavlja `node_modules`/`package-lock.json` u koren repo-a, ne lokalno.
  Ispravka: Docker build kontekst za `web` je koren repo-a, ne
  `apps/web`.
- **Healthcheck lažno "unhealthy" iako sajt radi.** Unutar
  `nginx:alpine` kontejnera, `localhost` se razrešava i na `127.0.0.1` i
  na `::1`; `wget` prvo probode IPv6, nginx sluša samo IPv4 →
  "connection refused" iako je sajt potpuno živ spolja. Ispravka:
  healthcheck gađa `127.0.0.1` direktno.

### Verifikacija

Ceo sistem (6 servisa) proveren iz čistog stanja (`docker compose down -v`
pa `up --build`): svi servisi healthy/exited-0, `pytest -q` → 3 passed,
`\dn` pokazuje `public` + `tenant_alice` + `tenant_bob`, svih 6 fixture
fajlova u S3 bucket-u, ponovno pokretanje `seed` na toploj bazi ne dupli
ništa.

---

## v1.0-core / Auth — 2026-08-16

### Kontekst

Prvi funkcionalni blok posle skeleta: login, logout, `get_current_user` kao
jedini izvor identiteta. Sve dalje rute (Tenant sloj pa nadalje) zavise od
ove zavisnosti da postoji.

### Odluke

1. **Backend-only ovaj blok, login ekran čeka "React UI" blok.** SPEC/§8
   opisuje "pravi email+lozinka ekran, ne goli birač identiteta" — to je
   API ugovor (email+password telo, ne birač korisnika), ne zahtev da
   `apps/web` ima formu već sada. React UI je već budžetiran kao poseban
   60-minutni blok koji gradi jedini ekran; diranje `apps/web` dvaput bi
   bilo rasipanje. Pretpostavka je zapisana i u BUILDPLAN.md.
2. **JWT u httpOnly cookie-ju** (`access_token`), `samesite=lax`,
   `secure=False` — lokalni http demo, isti origin kroz nginx `/api/`
   proxy, nema CORS-a.
3. **Login je enumeration-safe**: pogrešan email i pogrešna lozinka vraćaju
   identičan `401 {"detail": "invalid credentials"}` — ista logika kao
   404-ne-403 pravilo za dokumente (§3), ne otkriva koji nalog postoji.
4. **`get_current_user` čita `public.users` direktno preko SQLAlchemy
   `text()`**, bez ORM modela — nijedan model za `users` još ne postoji, a
   pravljenje jednog radi tačno jednog upita bi bilo prerana apstrakcija.
   ORM domain modeli dolaze u Tenant sloj bloku.
5. **`get_db()` dodat u `core/db.py` sada, plain.** Tenant sloj blok će ga
   proširiti sa `SET LOCAL search_path` u istoj transakciji — prirodan
   sledeći korak, ne otpisana apstrakcija.
6. **Route-introspection test (`test_no_route_accepts_user_id_...`) ulazi u
   ovaj blok, ne kasnije** — to je mehanizam koji čuva CLAUDE.md invarijantu
   ("nijedna ruta ne prima `user_id`"), pa svaka ruta dodata posle ovog
   bloka mora već biti pokrivena.
7. **Dev JWT secret je hardkodovan default u `config.py`, ne u
   `.env.example`** — SPEC-ov zahtev je da je `OPENROUTER_API_KEY` jedini
   obavezan ključ; JWT secret je override-abilan preko env-a za bilo šta
   ozbiljnije od lokalnog demoa.

### Verifikacija

`docker compose up --build` iz toplog stanja, pa
`docker compose exec -T api pytest -q` → **11 passed** (3 iz `test_seed.py`
+ 8 iz novog `test_auth.py`: login uspeh sa httponly cookie-jem, pogrešna
lozinka, nepoznat email vraća isti 401, `/auth/me` bez cookie-ja → 401,
alice/bob vraćaju različit i tačan identitet bez mešanja, falsifikovan JWT
(pravi `sub`, pogrešan potpis) → 401, logout briše cookie i naredni
`/auth/me` → 401, route-introspection test). Ručno potvrđeno i kroz pravi
HTTP stek (`curl` login/me za oba korisnika kroz `localhost:8000`) — cookie
jars za alice i bob vraćaju tačno njihove identitete, bez cookie-ja `401`,
pogrešna lozinka `401`.
