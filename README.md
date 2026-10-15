# English Actors Register

A one-page register of everyone on Wikipedia's *List of English actors*: photo, dates, last appearance and top 5 films.

## What's in the folder

| File | What it is |
|---|---|
| `index.html` | The page. |
| `sync.py` | Builds and updates the saved copy below. Needs Python 3.8 or later, nothing to install. |
| `data/actors.json` | Created by `sync.py`: names, dates, gender, credits and photo details. |
| `photos/` | Created by `sync.py`: one small photo (120 px wide) per actor. |

## Hosting it for free on GitHub Pages (recommended)

GitHub hosts the site for free and also runs `sync.py` for you every week, so you never have to run it yourself. The included file `.github/workflows/sync-and-publish.yml` does this.

1. Create a free account at github.com, then a new **public** repository (for example `english-actors-register`).
2. Upload everything in this folder to it, including the hidden `.github` folder. The easiest way is **Add file → Upload files** and dragging the folder's contents in. If the `.github` folder won't drag, create the file by hand with **Add file → Create new file**, naming it `.github/workflows/sync-and-publish.yml` and pasting its contents.
3. In the repository, open **Settings → Pages** and set **Source** to **GitHub Actions**.
4. Open **Settings → Secrets and variables → Actions → Variables** and add a variable named `EAR_USER_AGENT` with a value like `EnglishActorsRegister/1.0 (https://yourname.github.io/english-actors-register; you@example.com)`.
5. The upload itself starts the first sync automatically (see the **Actions** tab). It takes 10 to 20 minutes. To start one by hand later, open **Actions → Sync from Wikipedia and publish** and press the green **Run workflow** button. Don't use **Re-run** on an old run, because that repeats the old code.

Your site is then live at `https://<your-username>.github.io/english-actors-register/`. It updates itself every Monday and after every upload, and you can press **Run workflow** any time to update it sooner.

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
