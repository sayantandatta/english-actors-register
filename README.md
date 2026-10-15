# English Actors Register

A one-page register of everyone on Wikipedia's *List of English actors*: photo, dates, last appearance and top 5 films.

## What's in the folder

| File | What it is |
|---|---|
| `index.html` | The page. |
| `sync.py` | Builds and updates the saved copy below. Needs Python 3.8 or later, nothing to install. |
| `data/actors.json` | Created by `sync.py`: names, dates, gender, credits and photo details. |
| `photos/` | Created by `sync.py`: one small photo (120 px wide) per actor. |
| `admin.html` | The dashboard for reviewing visitors' suggestions and photos (sign-in required). |
| `setup.sql`, `setup-submissions.sql` | Database setup for votes and for visitor submissions (see below). |

## Hosting it for free on GitHub Pages (recommended)

GitHub hosts the site for free and also runs `sync.py` for you every week, so you never have to run it yourself. The included file `.github/workflows/sync-and-publish.yml` does this.

1. Create a free account at github.com, then a new **public** repository (for example `english-actors-register`).
2. Upload everything in this folder to it, including the hidden `.github` folder. The easiest way is **Add file → Upload files** and dragging the folder's contents in. If the `.github` folder won't drag, create the file by hand with **Add file → Create new file**, naming it `.github/workflows/sync-and-publish.yml` and pasting its contents.
3. In the repository, open **Settings → Pages** and set **Source** to **GitHub Actions**.
4. Open **Settings → Secrets and variables → Actions → Variables** and add a variable named `EAR_USER_AGENT` with a value like `EnglishActorsRegister/1.0 (https://yourname.github.io/english-actors-register; you@example.com)`.
5. The upload itself starts the first sync automatically (see the **Actions** tab). It takes 10 to 20 minutes. To start one by hand later, open **Actions → Sync from Wikipedia and publish** and press the green **Run workflow** button. Don't use **Re-run** on an old run, because that repeats the old code.

Your site is then live at `https://<your-username>.github.io/english-actors-register/`. It updates itself every Monday and Thursday and after every upload, and you can press **Run workflow** any time to update it sooner.

## Getting found by search engines

Each sync also writes the pieces search engines look for: a plain-HTML index of every actor at the bottom of the page (readable without JavaScript), a page description and canonical address, structured data, and `sitemap.xml`. When something changes, the workflow tells Bing and other IndexNow engines straight away, using the key file in the top folder (a long name ending in `.txt`; leave it in place).

To register the site (once):

1. **Google:** open Google Search Console, add a **URL prefix** property for your site address, and verify it. The simplest way is to choose **HTML file**, download the small `google….html` file and upload it to the top folder of this repository. Then open **Sitemaps** and submit `sitemap.xml`. Use **URL Inspection → Request indexing** to ask for a first crawl.
2. **Bing:** open Bing Webmaster Tools and choose **Import from Google Search Console**. This verifies the site and copies the sitemap, and it also covers Yahoo and DuckDuckGo, which use Bing's index.

If you use your own domain, set an Actions variable named `EAR_SITE_URL` to the full address (ending in `/`).

## Visitor counter and votes (optional)

The page can show how many people have visited, and let visitors like, dislike or mark as neutral each actor, with running totals. These need a small free database, so they stay hidden until you set one up:

1. Sign up at supabase.com (you can sign in with GitHub) and create a new project on the **Free** plan. Pick any name and database password, and a region near your visitors.
2. In the project, open **SQL Editor → New query**, paste everything from `setup.sql` in this folder, and press **Run**.
3. Open **Project Settings → API** (or **Connect**) and copy the **Project URL** and the **publishable** (or **anon public**) key.
4. In `index.html`, find `const VOTES_API = { url: "", key: "" };` and put those two values between the quotes.

The publishable key is meant to be public: with `setup.sql` in place it can only count visits, record one vote per browser per actor, and read the totals. No names, emails or IP addresses are stored. Free projects pause after a week without use; the twice-weekly update reads the totals each time, which keeps the database awake.

## Visitor suggestions, photos and the admin dashboard (optional)

When the database above is set up, visitors can:

- search for a film or show that isn't on the page and see its year, director and cast, with buttons for any cast members who are in the register;
- suggest an actor who's missing (their email, the actor's first and last name and one film are required; a photo is optional);
- send a photo for an actor shown as "No photo found".

Everything they send waits in a private queue. Nothing appears on the site until you approve it in the dashboard at `https://<your-username>.github.io/english-actors-register/admin.html`, where you can correct the details, approve, reject, take an approved item back off the site, or delete it. Submitters' emails are only visible in the dashboard.

To switch it on (once):

1. In Supabase, open **SQL Editor → New query**, paste everything from `setup-submissions.sql`, and press **Run**.
2. Open **Authentication → Users → Add user → Create new user**, enter your email and a strong password, and tick **Auto Confirm User**.
3. Back in the **SQL Editor**, run this one line with your own email: `insert into public.ear_admins (email) values ('you@example.com');`
4. Open **Authentication → Sign In / Providers** and turn off **Allow new users to sign up**, so nobody else can create an account.
5. Open `admin.html` on your site and sign in.

To add another reviewer, repeat steps 2 and 3 with their email. Visitors can't read the queue, see other people's emails or change anything: they can only add a submission (up to 20 a day per email) and upload a photo into the private queue.

## Hosting it anywhere else

1. Run the sync once, on your computer or on the server:

   ```
   EAR_USER_AGENT="EnglishActorsRegister/1.0 (https://your.site; you@your.site)" python3 sync.py
   ```

   Wikimedia asks scripts to identify themselves, so put your own site and contact address in `EAR_USER_AGENT`. The first run looks up all ~600 names and downloads about 600 photos. Expect 10 to 20 minutes and a few MB.

2. Upload the whole folder (`index.html`, `data/`, `photos/`) to any static web host, such as GitHub Pages, Netlify, an S3 bucket or your own web server.

3. To keep it current, run `python3 sync.py` again whenever you like, for example weekly with cron:

   ```
   0 3 * * 1  cd /path/to/english-actors-register && EAR_USER_AGENT="..." python3 sync.py
   ```

   Later runs only look up names that are new on the list, or entries that were incomplete last time. Photos already in `photos/` are never downloaded again unless the source photo changed.

### Sync options

| Command | Does |
|---|---|
| `python3 sync.py` | Only what's new or missing (the usual run) |
| `python3 sync.py --full` | Re-check dates and credits for everyone (photos still download only if changed) |
| `python3 sync.py --letters AB` | Limit to surnames starting with A and B |
| `python3 sync.py --prune` | Also delete photos no longer used by anyone |

## How the page loads when hosted

- It reads `data/actors.json` and shows photos from `photos/`, so it makes no lookups for names already saved.
- It makes one request to Wikipedia to check for names added to the list since the last sync. It looks up only those names live, and the visitor's browser remembers that check for a day.
- If Wikipedia can't be reached, it shows the saved copy on its own.

Opened directly from your computer (double-clicking `index.html`), browsers block it from reading the `data` folder. It then falls back to looking everything up live and keeping photos in the browser.
