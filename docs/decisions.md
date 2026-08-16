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

---

## v1.0-core / Tenant sloj — 2026-08-16

### Kontekst

`provision_tenant()` i `public.tenants` su već postojali (v0.1-skeleton, ispred plana). Ono što je
ovom bloku stvarno ostalo: session zavisnost koja radi `SET LOCAL search_path` iz proverenog
tokena, i ORM model set koji se kroz nju razrešava — bez ijednog `schema=` argumenta. Do sada u
repo-u nije postojao nijedan SQLAlchemy ORM model; sledećih pet blokova (Datasource+S3,
Direktorijumi, Sync, Ingest, Chat) grade direktno na ovom sloju.

### Odluke

1. **`app/tenancy/registry.py`, ne `core/db.py`, drži tenant-session mehaniku.** `core/security.py`
   već uvozi `get_db` iz `core/db.py`; kad bi zavisnost za tenant-scoped sesiju živela u `db.py` i
   trebao joj `CurrentUser`/`get_current_user` kao `Depends()` parametar, nastao bi kružni uvoz.
   `tenancy/registry.py` drži jednosmeran sloj: `core` (opšta DB/identitet infrastruktura) ←
   `tenancy` (mapiranje identitet → šema) ← rute. Ovo je i tačno ime fajla koje BUILDPLAN.md već
   predviđa u §8 (`tenancy/{provision,registry}.py`).
2. **`tenant_session(user_id)` kontekst-menadžer ispod FastAPI zavisnosti**, ne direktno
   generator vezan za `Depends`. §3 eksplicitno kaže da worker (blok "Sync state + worker") mora
   da radi identičnu stvar sa golim `user_id` iz `sync_jobs` reda, bez ijednog HTTP zahteva na koji
   bi okačio `Depends`. Deljenje mehanizma sad znači da worker kasnije samo pozove
   `tenant_session()`, bez duplirane logike. Commit se dešava unutar `tenant_session` samog (ne u
   svakoj ruti pojedinačno) — ovo će koristiti svaka buduća ruta koja piše, pa centralizovan
   commit/rollback znači da nijedan budući blok ne može da ga zaboravi.
3. **`SET LOCAL search_path` ide kroz `psycopg.sql.Identifier`, izvršeno na Session-ovoj
   sopstvenoj konekciji** (`Session.connection().connection.dbapi_connection` za citiranje,
   `Connection.exec_driver_sql()` za izvršavanje) — ostaje na istoj transakciji koju Session
   koristi za sve naredne upite u tom zahtevu, uz jedini auditovan put za citiranje imena šeme,
   isti kao u `provision.py`. `schema_name` se čita iz `public.tenants` (`.scalar_one()`), nikad iz
   korisničkog unosa.
4. **Svih 7 tenant modela deklarisano odmah, u jednom fajlu**, iako će ih većina rutа koristiti tek
   u kasnijim blokovima — `domain/models.py` se prvi put pravi u ovom bloku, pa je jedan prolaz
   protiv `provision_tenant()`-ove DDL jeftiniji nego pet parcijalnih provera kroz blokove. Ovo je i
   doslovno značenje CLAUDE.md invarijante "jedan set modela opslužuje sve tenante". `chunks.embedding`
   koristi `pgvector.sqlalchemy.Vector(384)` — dodat `pgvector` u `requirements.txt` (nije bio
   zavisnost do sada), iako se kolona ne čita/piše do bloka "Ingest + dedup".
5. **Alembic i dalje ne dira tenant šeme** (`migrations/env.py` ima `target_metadata = None`) —
   `provision_tenant()`-ova ručno pisana DDL ostaje jedini izvor istine za oblik tenant tabela;
   `domain/models.py` je drugi, ručno održavan opis istog oblika, korišćen samo za ORM upite u
   runtime-u. Postojeća asimetrija iz §8 ("Alembic za `public`, versioned DDL za tenante") — ovaj
   blok je ne menja, samo dodaje ORM stranu.

### Verifikacija

`docker compose up --build` (rebuild `api`/`worker` slike zbog novog `pgvector` paketa), pa
`docker compose exec -T api pytest -q` → **14 passed** (11 postojećih + 3 nova u
`test_isolation.py`: `SHOW search_path` sadrži tačnu šemu po korisniku, ORM upis kroz Alice-inu
sesiju nije vidljiv kroz Bob-ovu i obrnuto — isti model, ista neti kvalifikovana tabela, fizički
druga tabela — i SPEC.md §3-ov v1.0 meta-test: bez postavljenog `search_path`, nekvalifikovan upit
na `datasources` puca sa `UndefinedTable`).

---

## v1.0-core / Datasource + S3 — 2026-08-16

### Kontekst

Prvi blok koji stvarno koristi tenant-scoped ORM sloj (`get_tenant_db`, `Datasource` model) kroz
pravu HTTP rutu, ne samo direktan test — potvrda da mehanizam iz prethodnog bloka radi pod pravim
zahtevom. Registracija direktorijuma (pretvaranje pregledanog prefiksa u praćen `directories` red)
je sledeći, poseban blok — ovaj staje na: poveži datasource, sačuvaj konfiguraciju bezbedno,
omogući pregled prefiksa.

### Odluke

1. **Fernet ključ je fiksni dev-default u `config.py`, ne obavezna env promenljiva** — isti obrazac
   kao `jwt_secret_key` (Auth blok). Mora biti fiksan, ne regenerisan pri svakom pokretanju:
   Postgres podaci prežive `docker compose up` restart (samo `-v` briše), pa bi promenljiv ključ
   nasukao svaki već enkriptovan `config_encrypted` red. Drži obećanje iz §12 da je
   `OPENROUTER_API_KEY` jedini obavezan ključ.
2. **`Connector` Protocol dobija sva tri metoda odmah** (`list_prefixes`, `list_objects`,
   `get_object_bytes`), `S3Connector` implementira sva tri, ali ova ruta zove samo
   `list_prefixes`. §7 (v1.4 pasus) već imenuje tačno ovu trojku kao oblik koji
   `GoogleDriveConnector` mora da deli sa `S3Connector` — pisanje svih sada znači da Sync i Ingest
   (kojima trebaju `list_objects`/`get_object_bytes`) ne diraju ugovor ovog Protocol-a kasnije.
   Ista logika kao "svih 7 tenant modela odmah" iz prethodnog bloka.
3. **Nema provere konekcije na `POST /datasources`.** Loš bucket/kredencijali pucaju glasno na
   sledećem pozivu (`browse`), što je i sledeći korak u demo skripti (§9: poveži → pregledaj →
   registruj). Provera na oba mesta bi bila dupliranje za 35-minutni blok.
4. **`browse` ne hvata `botocore` greške u posebnu taksonomiju** — sirov `ClientError` kao 500 je
   prihvatljivo za ovaj blok; lepše mapiranje provajder-grešaka nije ono što brief demonstrira.
5. **Pydantic šeme (`S3ConnectionConfig`, `DatasourceCreate`, `DatasourceOut`) žive u
   `datasources.py`, ne u `domain/schemas.py`** — isti obrazac kao `auth.py` (`LoginRequest`,
   `UserOut` su takođe lokalne). Ništa drugo ih još ne koristi, pa bi deljeni schemas fajl razbio
   tipove jedne rute na dva mesta bez ikakve koristi od deljenja.
6. **`GET /datasources/{id}/browse` na tuđ ID vraća 404, ne 403** — besplatno iz tenant-šema
   izolacije: strani ID prosto nije red u ovoj tenant tabeli, pa "ne postoji" i "postoji ali nije
   tvoje" izgledaju identično. Ista osobina koju §3 traži za dokumente/sync.
7. **Novi test fajl `test_datasources.py`, ne prošireni `test_isolation.py`** — isti presedan kao
   `test_seed.py`/`test_auth.py`: jedan fajl po funkcionalnosti (uključujući njene sopstvene
   izolacione provere), `test_isolation.py` ostaje niži DB/session-mehanizam sloj.

### Verifikacija

`docker compose up --build` (novi `cryptography` paket), pa `docker compose exec -T api pytest -q`
→ **18 passed** (14 postojećih + 4 nova u `test_datasources.py`: kreiranje + listanje vraća
`DatasourceOut` bez config polja, `browse` nad pravim LocalStack-om vraća stvarne prefikse
(`alice/contracts/`, `alice/duplicates/`) što dokazuje ceo put enkripcija→upis→dekripcija→boto3
poziv, Alice-in datasource se ne pojavljuje u Bob-ovoj listi, Bob-ov `browse` na Alice-in ID → 404).

---

## v1.0-core / Direktorijumi — 2026-08-16

### Kontekst

`directories` tabela i `Directory` ORM model su već postojali (v0.1-skeleton, Tenant sloj blok) —
ovom bloku je ostalo čisto API površina iznad postojeće šeme: registruj, listaj, obriši. Nijedan
red u `documents` još ne može da pokazuje na direktorijum, jer Sync i Ingest još ne postoje — pa je
brisanje direktorijuma u ovom bloku prost `DELETE`, bez ikakve kaskadne logike.

### Odluke

1. **Register/list ugnježdeni pod `/datasources/{id}/directories`, delete pljosnat
   `/directories/{id}`.** Isti obrazac koji SPEC.md sam koristi kad referiše ovaj endpoint u §3/§4
   (`DELETE /directories/{id}`), i simetrično sa postojećim `GET /datasources/{id}/browse` iz
   prethodnog bloka — register/list logično traže roditelja (koji datasource), delete ne mora.
2. **404 na nepostojeći/tuđ `datasource_id`, ista logika kao `browse`.** `_get_datasource_or_404`
   radi identičnu proveru koju je prethodni blok već uveo za `browse_datasource` — tenant izolacija
   je besplatna posledica `search_path`, "ne postoji" i "postoji ali nije tvoje" izgledaju identično
   i za register i za list.
3. **Duplo registrovan `(datasource_id, prefix)` → `409`, ne `500`.** Tabela već ima
   `UNIQUE(datasource_id, prefix)` (Tenant sloj blok); ruta hvata `IntegrityError` i prevodi ga u
   čitljiv HTTP status — isti obrazac kao SPEC-ov opis partial unique index-a za `sync_jobs` u §5
   (baza je izvor istine za ograničenje, aplikacija ga samo čitljivo prevodi).
4. **`_get_datasource_or_404` helper ostaje lokalan u `directories.py`, ne premešten u
   `datasources.py`.** Koristi se dva puta unutar istog fajla (register + list); deljenje sa već
   završenim `datasources.py` bi značilo diranje gotovog bloka radi tri linije koje se ne ponavljaju
   van ovog fajla.
5. **Nema cascade/refcount logike u `DELETE /directories/{id}` u ovom bloku, namerno.** Puna verzija
   (soft-delete svih dokumenata direktorijuma → refcount na `chunks`/`contents` → tek onda hard-delete
   `directories` reda, §4) je eksplicitno budžetirana kao deo kasnijeg **Uklanjanje** bloka, kad Sync
   i Ingest već mogu da popune `documents`. Dodavanje te logike sada bi bila mrtva grana koda —
   ništa još ne postoji da bi je pokrenulo.
6. **Novi test fajl `test_directories.py`, isti presedan kao `test_datasources.py`** — jedan fajl po
   funkcionalnosti, uključujući njene sopstvene izolacione provere (register/list/delete na tuđem
   resursu → `404`, ne `403`).

### Greške pronađene i ispravljene tokom izrade

- **`api`/`worker` nemaju bind mount — kod se peče u image na build-u.** Prvi `pytest` posle pisanja
  koda je tiho pokazao "18 passed" (stari broj, stari image), nova ruta i novi test fajl uopšte
  nisu bili unutar kontejnera. Ispravka: svaka izmena koda tokom ovog bloka tražila je
  `docker compose up --build api` pre `pytest`-a, ne samo `exec`. Vredna lekcija za sve naredne
  blokove — "test prošao" bez rebuild-a ovde ne dokazuje ništa.
- **Test cleanup pucao na FK, ne na `search_path`.** `_delete_datasource` je brisao `Datasource` red
  bez da prvo obriše njegove `Directory` redove; `directories_datasource_id_fkey` (namerno bez
  `ON DELETE CASCADE`, v0.1-skeleton odluka #6) je to ispravno odbio. Ispravka: `_delete_datasource`
  prvo pronađe i obriše sve `Directory` redove za taj `datasource_id`, eksplicitan `db.flush()`, tek
  onda briše `Datasource` — bez `flush()`-a SQLAlchemy nema garantovan redosled DELETE naredbi kad
  ne postoji `relationship()` između modela, samo `ForeignKey` kolona.

### Verifikacija

`docker compose up --build api` pa `docker compose exec -T api pytest -q` → **24 passed** (18
postojećih + 6 novih u `test_directories.py`: registracija + listanje, duplo registrovan prefiks →
`409`, registracija pod nepostojećim `datasource_id` → `404`, brisanje uklanja iz liste, Bob-ov
register/list na Alice-in `datasource_id` → `404` za oba, Bob-ovo brisanje Alice-inog
`directory_id` → `404` i red ostaje netaknut).

---

## v1.0-core / Sync state + worker — 2026-08-16

### Kontekst

`sync_jobs` i njegov partial unique index su već postojali (v0.1-skeleton) bez ijednog reda koda
koji ih koristi. Ovom bloku je ostalo da to postane pravi mehanizam: enqueue/poll API i pravi
worker loop, umesto `worker.py`-a koji je do sada samo spavao. `documents`/`contents`/`chunks` se u
ovom bloku ne diraju uopšte — §8 tu granicu povlači eksplicitno (vidi odluku #1).

### Odluke

1. **Worker u ovom bloku samo LIST-uje i broji, ne dira `documents`.** §8 razdvaja ovaj blok
   (`sync_jobs`, partial unique index, SKIP LOCKED petlja, polling endpoint) od "Ingest + dedup"
   (streaming sha256, ekstrakcija, chunking, embedding, **sva tri sloja dedupa** — uključujući sloj
   1, `(source_key, etag, size)`). Pošto sloj 1 eksplicitno pripada sledećem bloku, posao ovde staje
   na `connector.list_objects(prefix)` i `stats = {"scanned": N}`. Namerno nema
   `unchanged`/`indexed`/`deduped` ključeva sa lažnim nulama — to bi izgledalo kao "0 indeksirano"
   umesto "još nije implementirano". Pretpostavka je zapisana i u BUILDPLAN.md.
2. **`sync_jobs` ostaje sirov SQL, bez ORM modela** — isti obrazac kao `public.users`/`public.tenants`
   u `security.py`/`registry.py`, `text()` sa eksplicitnim `public.sync_jobs` prefiksom. Tabela na
   koju se pristupa isključivo po `id`/`directory_id`/`user_id` ne dobija ORM model samo da bi
   postojao.
3. **Claim korak radi na golom `SessionLocal()`, ne na `tenant_session`.** Worker ne zna kom
   tenantu posao pripada dok ne pročita `user_id` iz preuzetog reda — `SELECT ... FOR UPDATE SKIP
   LOCKED LIMIT 1` pa odmah `UPDATE ... state='running'`, ista transakcija, commit. Tek posle toga
   `run_sync` otvara `tenant_session(user_id)` za `Directory`/`Datasource` i S3 poziv — tačno
   podela koju `registry.py`-jev docstring (Tenant sloj blok) već najavljuje.
4. **409 telo traži upit posle neuspelog INSERT-a, što traži eksplicitan rollback.** Povreda unique
   indexa abortuje trenutnu Postgres transakciju; svaki naredni upit na istoj konekciji puca dok se
   transakcija ne rollback-uje. Pošto taj rollback briše i `SET LOCAL search_path`, naredni upit za
   postojeći posao mora biti eksplicitno `public.`-kvalifikovan (nije tenant tabela, pa to i nije
   problem). Isti obrazac 409-a kao Direktorijumi blok (`IntegrityError` → čitljiv status), ovde uz
   dodatni rollback jer treba i telo odgovora, ne samo status kod.
5. **Greška na nivou posla ide u `stats.error`, ne u novu kolonu.** `sync_jobs` ima `error_count`
   (int, rezervisan za v1.2-ov brojač po fajlu), ali nema tekstualnu `error` kolonu. Otkaz celog
   posla (direktorijum nestao pre nego što ga je worker stigao, loš connector config) je druga vrsta
   otkaza od po-fajl otkaza; JSONB polje koje već postoji je jeftinije od migracije za kolonu koju bi
   v1.2 verovatno svejedno hteo drugačije oblikovanu.
6. **`GET` pre ijednog sync-a → `404`.** SPEC/§5 opisuje četiri stanja (nothing new / in progress /
   running / finished), ne i peto za "nikad pokrenuto". Tretirano isto kao svaki drugi nepostojeći
   resurs u ovom kodu (404, ne prazan objekat) — ista 404-ne-403 linija kao svuda drugde.
7. **Jedan namerno pokrenut `failed` put, preko direktno ubačenog reda.** Realan `failed` scenario
   (direktorijum obrisan između enqueue-a i preuzimanja) bi tražio trkanje sa pravim workerom da bi
   test bio determinstičan. Test umesto toga ubacuje `sync_jobs` red direktno (`db_conn`) sa
   `directory_id`-jem koji ne postoji ni u jednoj tenant šemi, i poluje `public.sync_jobs.state`
   direktno — jedini način da se `run_sync`-ova except grana pouzdano pokrije bez flakiness-a.

### Greške pronađene i ispravljene tokom izrade

- **`:stats::jsonb` u `text()` SQL-u je tiho progutao bind parametar.** SQLAlchemy-jev parser za
  `text()` bind parametre se zbunio na `::` odmah posle imena parametra — `:stats` nikad nije
  prepoznat kao bind, ostao je bukvalno u SQL-u, i psycopg je pukao na "syntax error at or near
  ':'" tek unutar workera (ne u samom API zahtevu). Worker je pao na prvom poslu i ostao mrtav do
  sledećeg `docker compose up`, ostavljajući poslove zaglavljene u `queued`/`running` zauvek — tačno
  scenario koji je BUILDPLAN.md već imenovao kao poznato v1.0 ograničenje (nema reaper-a), samo iz
  pogrešnog razloga (bug, ne stvarna smrt workera). Ispravka: `CAST(:stats AS jsonb)` umesto `::`
  na oba mesta gde se `stats` upisuje.

### Verifikacija

`docker compose up -d --build` (rebuild `api` i `worker`, oba bez bind mounta), pa
`docker compose exec -T api pytest -q` → **30 passed** (24 postojećih + 6 novih u
`test_sync_state.py`: enqueue → worker stvarno završi posao sa `stats.scanned == 3` nad pravim
`alice/contracts/` fixture-ima, drugi klik zaredom → `409` sa postojećim poslom u telu, Bob-ov
POST/GET na Alice-in `directory_id` → `404` oba, POST na nepostojeći `directory_id` → `404`, GET
pre ijednog sync-a → `404`, worker označava posao `failed` kad direktorijum ne postoji).

---

## v1.0-core / Ingest + dedup — 2026-08-16

### Kontekst

`sync_jobs`/`SKIP LOCKED` petlja i polling endpoint su već postojali (Sync state + worker blok),
ali worker je do sada samo brojao objekte — `documents`/`contents`/`chunks` nijednom nisu bili
dotaknuti. Ovom bloku je ostalo jezgro celog sistema: `run_sync` mora stvarno da skine bajtove,
ekstrahuje tekst, iseče ga na chunk-ove, embeduje ih i upiše, poštujući sva tri sloja dedupa iz
§4 SPEC.md i živ predikat iz CLAUDE.md invarijante. Bez ovog bloka Chat + RAG (dva bloka dalje)
nema nad čim da radi.

### Odluke

1. **Tri sloja dedupa kao tri uzastopne, kratko-spajajuće provere u `ingest_object()`**, ne tri
   odvojena prolaza kroz listing. Sloj 1 (postojeći `documents` red za `(directory_id,
   source_key)` čiji se `remote_etag`/`remote_size` poklapaju) prekida funkciju pre bilo kakvog
   mrežnog poziva. Ako taj red postoji ali nije živ, funkcija ga svejedno ne dira — to je
   dovoljno da "uklanjanje preživi re-sync" (§4) već sada radi ispravno, iako `removed_at` još
   niko ne postavlja (taj deo dolazi tek u bloku "Uklanjanje"). Sloj 2 (`contents[content_hash]`
   već postoji) preskače ekstrakciju/chunking/embedding, samo upiše `documents` red. Redosled je
   bitan: sloj 1 mora biti prvi jer je jedini koji izbegava mrežni poziv uopšte.
2. **Živ predikat centralizovan u `app/domain/refcount.py`** (`is_live_clause()` +
   `release_content_if_orphaned()`), ne inline uslov u `ingest/index.py`. Ovaj blok je prvo mesto
   gde se predikat koristi (sloj-3 dedup provera i refcount pri promeni sadržaja na istoj
   putanji) — "Uklanjanje" blok i v1.2-ov `known_keys` diff ga ponovo uvoze umesto da naprave
   drugu kopiju, tačno kako CLAUDE.md traži.
3. **Izmenjen fajl na istoj putanji odmah pušta stari `content_hash` kroz refcount, u ovom
   bloku, ne odloženo za "Uklanjanje".** SPEC.md §4 ("ista putanja + drugi bajtovi → nov sadržaj,
   stari chunk-ovi se povlače") je deo definicije dedupa, ne uklanjanja — ostavljanje starih
   `chunks`/`contents` redova siročadi ovde bi bio tih gubitak podataka istog tipa koji CLAUDE.md
   izričito zabranjuje.
4. **`run_sync` napušta `tenant_session()` helper i ručno upravlja sesijom** (isti stil kao
   `claim_next_queued_job`), jer SPEC §5 traži commit po dokumentu (worker umre na pola → restart
   nastavlja, ne kreće ispočetka), a `tenant_session()` commit-uje samo jednom na kraju. Pošto je
   `SET LOCAL search_path` transakcijski, mora se ponovo pozvati posle svakog `db.commit()` u
   petlji — inače sledeći nekvalifikovani upit ne vidi tenant tabele.
5. **Chunking: `RecursiveCharacterTextSplitter`, `chunk_size=1500`, `chunk_overlap=200`
   karaktera** — SPEC ne propisuje brojeve. 1500 karaktera je ~375 tokena po `len(text)//4`
   proceni (ista formula koju BUILDPLAN već najavljuje za v1.6 kompakciju), bezbedno ispod
   512-token limita `bge-small-en-v1.5` modela. `chunks.token_count` popunjen istom formulom.
   Pretpostavka je zapisana i u BUILDPLAN.md.
6. **"Streaming sha256" pročitano kao hashlib streaming API, ne novi S3-streaming protokol.**
   `app/ingest/hash.py` hešira kroz `.update()` u 1MB blokovima, ali `Connector.get_object_bytes`
   i dalje vraća pune bajtove — fixtures su mali fajlovi, pravo mrežno streaming skidanje bi
   tražilo izmenu `Connector` Protocol-a preko `S3Connector`-a, van budžeta ovog bloka.
7. **Embedder iza sopstvenog `Protocol`-a** (`app/ingest/embed.py`), model učitan lenjo i
   keš-ovan na nivou procesa — isti obrazac kao `Connector`. `Dockerfile` dobija build-time korak
   koji unapred skida `bge-small-en-v1.5` ONNX model, jer `api`/`worker` nemaju bind mount niti
   mrežni pristup posle build-a.
8. **Ekstrakcija po ekstenziji fajla, ne po sadržaju** (`.pdf` → pypdf, `.txt`/`.md` → UTF-8
   decode), nepoznata ekstenzija diže grešku bez per-file catch-a — per-file greška → `partial`
   stanje je eksplicitno v1.2 opseg (Sync state + worker bloka napomena), ne ovog bloka.

### Greške pronađene i ispravljene tokom izrade

- **`fastembed<0.5` ne podržava Python 3.13.** `pip install` u image-u je pukao na "no matching
  distribution" — SPEC/BUILDPLAN nisu fiksirali verziju, pretpostavljena `>=0.4,<0.5` je zastarela
  za bazni image (`python:3.13-slim`). Ispravka: `fastembed>=0.8,<0.9`, zapisano u BUILDPLAN.md.
- **SQLAlchemy ne uređuje INSERT redosled preko `Content`/`Chunk` samo na osnovu kolonskog
  `ForeignKey()`-a.** Bez `relationship()` između modela, unit-of-work ne zna da `chunks` mora
  posle `contents` — prvi pravi sync je pukao na `chunks_content_hash_fkey` jer je `chunks` insert
  otišao pre `contents` insert-a u istom flush-u. Ista klasa greške kao FK-redosled bug iz
  Direktorijumi bloka, samo u suprotnom smeru (tamo DELETE, ovde INSERT). Ispravka: eksplicitan
  `db.flush()` odmah posle `db.add(Content(...))`, pre nego što se ijedan `Chunk` doda.
- **Postojeći `test_sync_state.py`-jev cleanup je pukao na FK čim je worker počeo stvarno da piše
  u `documents`.** Ranije (Sync state + worker blok) worker nikad nije dirao `documents`, pa
  `_cleanup` nije morao da ga briše pre `directories`; sad kad ingest stvarno upisuje redove,
  `documents.directory_id` (bez `ON DELETE CASCADE`, v0.1-skeleton odluka #6) odbija brisanje
  direktorijuma dok referenca postoji. Ispravka: `_cleanup` prvo briše `Document` redove za
  direktorijum, tek onda sam direktorijum — ista popravka i u novom `test_dedup.py`-jevom
  cleanup-u. `contents`/`chunks` namerno ostaju netaknuti posle cleanup-a — sadržajno adresirani,
  bezbedno deljeni između testova, ne test-scoped scratch.

### Verifikacija

`docker compose up --build api worker` (novi `pypdf`/`langchain-text-splitters`/`fastembed`
paketi i fastembed model bake-ovan u image), pa `docker compose exec -T api pytest -q` →
**33 passed** (30 postojećih + 3 nova u `test_dedup.py`: svež sync `alice/contracts/` stvarno
ekstrahuje PDF (`mime=application/pdf`, `text_len>0`), drugi sync iste nepromenjene direktorijuma
vraća tačno `{scanned:3, unchanged:3, downloaded:0, indexed:0, deduped:0}`, `alice/duplicates/`
(bajt-identičan `msa_copy.md`) posle sync-a `alice/contracts/` vraća `deduped:1, indexed:0` i deli
isti `content_hash` sa `msa.md` bez duplog upisa u `chunks`). Ručno potvrđeno i preko `psql`-a:
`contents` posle oba sync-a ima tačno 3 distinct `content_hash` (ne 4), `policy.pdf` ima
`mime=application/pdf, text_len=41, chunk_count=1`.

---

## v1.0-core / Uklanjanje — 2026-08-16

### Kontekst

`documents` redovi sada postoje i popunjavaju se (Ingest + dedup blok), što znači da kaskadne
operacije — brisanje dokumenta, brisanje celog direktorijuma — postaju životnopravni. Ovom bloku je
ostalo: `DELETE /documents/{id}` sa refcount oslobađanjem, `DELETE /directories/{id}` kao kaskada
(soft-delete svih dokumenata → refcount → hard-delete direktorijuma), i race-guard u worker-u
protiv sinhronizacije koja je u toku kad se direktorijum obriše mid-sync.

### Odluke

1. **`DELETE /documents/{id}` radi na `is_live_clause()` iz `refcount.py`, bez Python re-provere
   posle učitavanja.** Isti helper koji je "Ingest + dedup" već uvozio za sloj-3 dedup proveru —
   dokument koji je nepostojeći, cross-tenant (nevidljiv kroz `search_path`) ili već uklonjen svi
   daju isti 404, bez ponavljanja predikata u drugoj kodu. Soft delete (`removed_at = now()`), pa
   `release_content_if_orphaned()` ako je imao `content_hash`. 204 No Content na uspeh.

2. **`DELETE /directories/{id}` hard-briše sve `documents` redove za taj direktorijum, ne samo
   markiranja `removed_at`.** `documents.directory_id` je NOT NULL bez `ON DELETE CASCADE` — "nijedan
   documents red više ne pokazuje na taj direktorijum" (§4) doslovno znači da tih redova više nema.
   Algoritam: (1) pročitaj `content_hash` skup iz trenutno živih `documents` redova (samo oni mogu
   biti orfani ovde), (2) hard-briši sve `documents` redove za direktorijum, (3) pokreni refcount
   oslobađanje samo za taj skup, (4) tek onda briši `directories` red. Nema dupliranja
   predikata — isti `is_live_clause()` helper kao `DELETE /documents` i Ingest blok.

3. **Race-guard: worker reCheck-uje `EXISTS(Directory)` na početku svake iteracije petlje.** Petlja
   po fajlovima (`for obj in objects: ... ingest_object ... db.commit() ... set_search_path ...`)
   sada proverava `directory_id` (sirov UUID argument, ne `directory` ORM objekat — onaj se ekspajruje
   posle `db.commit()` sa `expire_on_commit=True`) pre svakog `ingest_object` poziva. `break` umesto
   `continue` — kad direktorijum nestane, ostaće nestao za ostatak run-a, nema smisla dalje
   downloadovati/ekstrahuvati/embedovati. Proverava se u istoj (pre-commit) transakciji kao file
   upisi i post-commit `set_search_path` re-setup, pa je logika korektna kroz sve `db.commit()`
   granice.

4. **"Uklanjanje preživljava re-sync" je već ispravno bez izmene `ingest/index.py`.** Sloj-1 check
   (existing `(directory_id, source_key)` sa poklapajućim `etag`/`size`) se vraća pre nego što
   dotakne `removed_at`, što znači da je soft-obrisani dokument zaključan na mjestu — novi sync-i
   ga ne vraćaju. Bilo je greške u zavisnosti, a ne koda. Dodan regresioni test
   (`test_removed_document_does_not_reappear_on_unchanged_resync`) da se tvrdnja učini oborivom.

5. **`GET` lista dokumenata po direktorijumu ostaje van ovog bloka.** BUILDPLAN (§7 tabela) je
   eksplicitno stavlja u "React UI" blok — testovi čitaju `documents` redove direktno preko
   `tenant_session`, isti obrazac kao `test_dedup.py`/`test_sync_state.py`, što dokazuje da API
   nikada nije bio potreban za funckionalnost, samo za front-end.

6. **Novi test fajl `test_removal.py`, isti presedan kao `test_dedup.py`** — šest testova:
   refcount oslobađanja samo kad nema više živih referenci, nepostojeći dokument → 404,
   cross-tenant pristup → 404 ne 403, uklonjen dokument ostaje uklonjen posle re-sync-a,
   kaskadno brisanje direktorijuma sa refcount (sadržaj deli se između dva direktorijuma, briše se
   tek posle što oba nestanu), i deterministički race-guard test (monkeypatch `ingest_object` da
   commit-uje posle prvog fajla, pa pravi `DELETE /directories` poziv iz testnog HTTP klijenta,
   potom `run_sync` u istom proces kao worker, proveravam da je samo 1 fajl obrađen od 3 skenirana).

### Greške pronađene i ispravljene tokom izrade

- **`job_id` može biti neiniitijalizovan u `test_directory_deleted_mid_sync_worker_skips_remaining_files`
  cleanup-u** — test direktno ubacuje `sync_jobs` red kroz `db_conn`, trebam `job_id` inicijalizovan
  na početku try bloka sa `= None` da se cleanup ne presiječe ako je INSERT pukao. Nema stvarne
  greške u kodu, samo test-robusnost.

### Verifikacija

`docker compose up --build api worker` (bez novih spoljnih zavisnosti, čist refactoring), pa
`docker compose exec -T api pytest -q` → **39 passed** (33 postojećih + 6 novih u `test_removal.py`:
delete dokumena oslobađa sadržaj samo kad nema drugih živih referenci, nepostojeći/tuđ dokument
vraća 404, uklonjeni dokument se ne pojavljuje u resync-u, kaskadno brisanje direktorijuma,
race-guard worker ostaje između oba direktorijuma).
