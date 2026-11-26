# Certificate Generator

Writes each recipient's name on a certificate template, saves one PDF per
person, and emails it to them. Made for HR staff and executives: everything
happens in a simple web page that runs on your own computer.

## What you need

- Windows, macOS or Linux with **Python 3.10 or newer**
- A **Gmail account** with 2-Step Verification turned on (only for sending emails)

## Install (once)

```powershell
git clone https://github.com/leash06/automation_certificates.git
cd automation_certificates
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### Gmail setup (once)

1. Open <https://myaccount.google.com/apppasswords> and create an App Password
   named "Certificates". Google shows 16 letters.
2. In the project folder, run this to create `.env` and open it:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
   (Creating it by hand in Notepad often saves it as `.env.txt`, which the
   app cannot find.)
3. In `.env`, replace the example values with your Gmail address and the
   App Password, then save.

`.env` is never sent to GitHub. Never put the password anywhere else.

## Run

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

The app opens in your browser at <http://localhost:8501>. Only your own
computer can open it.

## How to use it

1. **Template:** upload a PNG, JPG or PDF. Click on the template where the
   centre of the name should be, or drag the name to move it, like in Canva.
   Drag a corner handle of the purple box to make the name bigger or
   smaller. Pink lines appear, and the name snaps, when it reaches the
   centre of the page. The **Centre horizontally / vertically / both**
   buttons also put it exactly in the middle. Choose the font, size, colour and maximum width; the preview and
   the three samples (short, long, accented name) update immediately.
   To match a colour already on the template, switch clicking to
   **eyedropper** and click that colour. Click **Save placement** to reuse it
   next time.
2. **Recipient list:** upload Excel (.xlsx), CSV, or the CSV of a Google
   Form's sheet. The name and email columns are found automatically; if not,
   choose them. An optional column can mark people as *winner*. Rows with an
   empty name, a bad email or a duplicate are listed and skipped.
3. **Preview and generate:** check the first certificate, then generate all.
   The PDFs go to a new dated folder inside `output/`.
4. **Send by email:** edit the subject and messages (`{name}` becomes each
   person's name). Start with a **dry run**: it prepares everything and sends
   nothing. **Untick "Dry run" to really send**; while it is ticked, no email
   leaves your computer. If some people already received this
   certificate, you are warned first.
5. **Report:** counts of generated, sent, failed and skipped. Download
   `failed.csv`, resend to failed emails in one click, or fix the file and
   upload it again as the recipient list.

Everything that happens is written to `certificates.log`.

## Fonts

About 25 free certificate fonts from Google Fonts come with the tool (script,
serif and modern styles). To add another, open **Add a font** under the font
list and either:

- type the name of any font from <https://fonts.google.com> (for example
  `Playfair Display`) and click **Download from Google Fonts**, or
- upload a `.ttf` or `.otf` file.

New fonts are saved in `fonts/`, so they keep working offline. Their licence
files go in `fonts/licenses/`. Choose fonts that support accents (é, ç, ñ).

## For developers

```powershell
python -m pytest          # run all tests
python generator.py       # make 3 sample PDFs in output/ from the sample template
```

| File | Responsibility |
|---|---|
| `app.py` | Streamlit screens only: collects choices, shows results |
| `template_loader.py` | PNG/JPG/PDF template → one RGB image (PDF at 300 DPI) |
| `people_loader.py` | Excel/CSV list → valid recipients + skipped rows with reasons |
| `generator.py` | Draws the name centred on the anchor, shrinks long names, saves PDFs |
| `mailer.py` | Gmail sending with delay, one retry, dry run and sending history |
| `settings_store.py` | Saves placement and messages per template in `settings.json` |
| `font_library.py` | Lists fonts, adds uploaded fonts, downloads Google Fonts |
| `placement_canvas.py` | Template preview where the name is dragged smoothly in the browser |
| `tests/` | Automated tests (Gmail is replaced by a fake, nothing is sent) |

Not stored in Git: `.env`, `output/`, `settings.json`, logs, and any `.csv` or
`.xlsx` recipient list.
