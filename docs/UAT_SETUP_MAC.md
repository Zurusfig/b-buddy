# Budget Buddy UAT setup on a Mac

This guide runs the NgernTong finance app and Budget Buddy coach on one MacBook, using the **existing online Supabase UAT database**. The web app and API are in `finance-tracker`; the coach, persona ground truth, logs and UAT report are in `b-buddy`. Keep the two repositories side by side.

## 1. Get access and install prerequisites

Ask the project owner for access to the Supabase project and the database, gateway and login values below through a private channel. Generate the app-to-coach secret locally in step 4.

| Value | Where it goes | Purpose |
| --- | --- | --- |
| Supabase app `DATABASE_URL` | `finance-tracker/backend/.env` | Finance app and login database |
| Coach reader `COACH_DATABASE_URL` | `b-buddy/Harness/.env` | Read-only access to the same Supabase database |
| One `COACH_SHARED_SECRET` | **Both** env files | API-to-coach authentication; generate locally |
| `GATEWAY_KEY` | `b-buddy/Harness/.env` | Advice questions through Gemma; requires CUNET VPN |
| Demo account passwords | Private handoff only | Henry, Diana and Grace logins |

Use Node 22, Python 3.11, Git, make and Ollama. On the Mac, check `node -v`, `python3.11 --version` and `ollama --version`. Install missing prerequisites before continuing. **Do not commit or send `.env` files, database URLs, keys or passwords in chat.**

## 2. Get the UAT branches

Clone the two repositories into the same parent directory. If they are already cloned, fetch and switch to the named branches instead.

```sh
mkdir -p ~/budget-buddy-uat && cd ~/budget-buddy-uat
git clone --branch feat/routed-coach-personas https://github.com/Zurusfig/b-buddy.git
git clone --branch feat/coach-chat https://github.com/SuK014/finance-tracker.git
```

Check that `b-buddy` contains `Harness/scripts/uat_report.py` and `finance-tracker` contains the **Practice / Recorded UAT** selector in Ask Buddy. If the finance branch is unavailable, ask for its pushed branch or PR before setup.

## 3. Install without replacing existing settings

```sh
cd ~/budget-buddy-uat/finance-tracker
make setup
cd ../b-buddy
python3.11 dev.py setup
python3.11 dev.py check
```

`make setup` installs the web and API packages and creates their env files only when absent. `dev.py setup` creates the Python environment and `Harness/.env` without overwriting existing values. Start the Ollama app. If `dev.py check` says the small model is missing, run `python3.11 dev.py pull` from `b-buddy`. The required model is `qwen3:4b-q4_K_M`.

## 4. Connect both apps to the existing Supabase UAT database

From `b-buddy`, run `python3.11 dev.py coach-secret`. It creates `COACH_SHARED_SECRET` in `Harness/.env` if one is not already set. Copy that line into `finance-tracker/backend/.env`. Then edit `finance-tracker/backend/.env`:

```dotenv
DATABASE_URL=<existing Supabase app connection>
JWT_SECRET=<new long random value for this Mac>
COACH_SHARED_SECRET=<same value as the coach>
CORS_ORIGIN=http://localhost:3000
```

Generate a new local JWT secret with `node -e "console.log(require('crypto').randomBytes(48).toString('hex'))"` and paste it into the env file. Edit `finance-tracker/frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:3001
NEXT_PUBLIC_COACH_ENABLED=true
```

Edit `b-buddy/Harness/.env`:

```dotenv
COACH_SHARED_SECRET=<same value as finance-tracker/backend/.env>
COACH_DATABASE_URL=<read-only coach reader connection to the same Supabase database>
COACH_REFERENCE_MONTH=2026-10
GATEWAY_KEY=<course gateway key for advice>
```

**Keep `COACH_REFERENCE_MONTH=2026-10` even though UAT is in November.** In these scenarios “this month” means October 2026 and “last month” means September 2026. The coach account must be the read-only `coach_reader` role, not the database owner. From `b-buddy`, run `python3.11 dev.py demo-check-reader` to verify its access. Run `python3.11 dev.py check --gateway` while on CUNET VPN if you need to verify advice routing.

The shared Supabase database already has the UAT personas. **Do not run `make migrate` or `demo-seed --yes` against it again.** If you are setting up a new, empty Supabase project instead, follow `b-buddy/README.md` under “Finance app link” for migrations, reader-role SQL and seeding. That is a separate one-time database setup.

## 5. Start the integrated app

Start Ollama first. From the parent directory, run:

```sh
cd ~/budget-buddy-uat
make -C b-buddy PY=python3.11 app-up
```

Keep this terminal open. It starts the web app on `:3000`, finance API on `:3001`, and coach on `127.0.0.1:8765`. Stop all three with Ctrl-C. In another terminal, check:

```sh
curl http://localhost:3001/health
curl http://127.0.0.1:8765/health
```

The API should return `{"status":"ok"}` and the coach should report `"ready": true`. After signing in, the finance app's authenticated `/api/chat/health` is checked by Ask Buddy. A `401` from that endpoint without a login is expected.

## 6. Check personas and practice safely

Open `http://localhost:3000/?uat=1`. Sign in with a demo account supplied privately by the owner:

| Persona | Username | UAT role |
| --- | --- | --- |
| Henry | `henry@demo.budgetbuddy.test` | Main student; most tasks |
| Diana | `diana@demo.budgetbuddy.test` | Thai food and transport tasks |
| Grace | `grace@demo.budgetbuddy.test` | No-budget task |

Open **Ask Buddy** and select **Practice** to try a prompt against the signed-in persona's real Supabase data. The normal reply and **How I got this** tool receipt appear in chat. Practice sends no UAT task ID, so its log entry appears as **Free question** in the report's **UAT runs → Run explorer**. It does not count in Grades, the round matrix, acceptance measures or recorded UAT timing stats. Switching modes clears the chat and task selection.

For the official session, select **Recorded UAT**, set Round (1 or 2), Tester (1–4) and the task. Start **New chat** for every task; then choose its task ID again. The account must match the task's persona. The app does not let the browser choose another user's `user_id` for the coach.

## 7. Watch the local report

In a separate terminal, from `b-buddy`, run:

```sh
cd ~/budget-buddy-uat/b-buddy
./.venv/bin/python Harness/scripts/uat_report.py --date 2026-11-04 --watch
```

Open `Harness/reports/uat_report.html` in Chrome. The script regenerates it every 10 seconds; the page reloads every 15 seconds. The **UAT runs** tab shows all questions and tool results, including Practice questions. The **Grades** tab measures only questions with a task ID. The report is a local HTML file and is gitignored because it embeds questions and tool results. `Harness/logs/coach_calls.jsonl` is the underlying local log; keep it private and do not delete it during UAT.

To explore the report UI without contacting the coach or changing the real log, run `./.venv/bin/python Harness/scripts/uat_report.py --demo` and open `Harness/reports/uat_report_demo.html`.

## 8. Let testers use their own devices (same Wi-Fi)

Find the MacBook's Wi-Fi address with `ipconfig getifaddr en0`. Use that address instead of `localhost` in `finance-tracker/frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://<Mac-Wi-Fi-IP>:3001
```

Add both origins in `finance-tracker/backend/.env`:

```dotenv
CORS_ORIGIN=http://localhost:3000,http://<Mac-Wi-Fi-IP>:3000
```

Restart `app-up` after changing env files. Testers open `http://<Mac-Wi-Fi-IP>:3000/?uat=1` on the same Wi-Fi. Permit local incoming connections for Node if macOS asks. The coach still listens only on `127.0.0.1:8765` on the MacBook; testers never connect to it directly. Keep the MacBook awake during both rounds.

## Quick troubleshooting

| Symptom | Check |
| --- | --- |
| Ask Buddy says offline | Ollama is running; `python3.11 dev.py check`; coach `/health` |
| Coach cannot read transactions | `COACH_DATABASE_URL` points to the same Supabase DB; `python3.11 dev.py demo-check-reader` |
| App has no chat button | `NEXT_PUBLIC_COACH_ENABLED=true`, then restart the web app |
| Task is unavailable | Sign in as the persona assigned to that UAT task |
| Practice does not appear in report | Report watcher is running; correct `--date`; click **UAT runs** and clear filters |
| Advice fails | Connect to CUNET VPN and run `python3.11 dev.py check --gateway` |
| Phone cannot connect | Same Wi-Fi, correct Mac IP, both `:3000` and `:3001` accessible, CORS origin set |

The owner must hand off the database connections, gateway key and passwords privately. Generate the shared secret on the UAT Mac and keep it in the two local env files. Git provides the code and setup steps, never credentials.
