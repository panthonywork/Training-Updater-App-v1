# TD Collateral Modernizer

An internal tool that uses AI to draft content updates for outdated product documents — preserving your existing formatting, branding, and structure while you review and approve every proposed change.

---

## What It Does

1. You upload an outdated document (Word, PowerPoint, or PDF) alongside updated reference material (a new product spec, updated brief, etc.)
2. The AI reads both files, identifies what's outdated or missing, and drafts replacement text for each affected section
3. You review every proposed change side by side with the original — accepting, editing, or rejecting each one
4. When you're done reviewing, you download an updated file with only your approved changes applied

**The AI drafts. You decide. Nothing changes without your approval.**

---

## What You Need

- A Mac or Windows computer with Python installed
- A terminal (Terminal on Mac, Command Prompt or PowerShell on Windows)
- An API key from one of the supported AI providers (see below)

### Supported AI Providers

| Provider | Where to get a key |
|---|---|
| Google Gemini | [aistudio.google.com](https://aistudio.google.com) — free tier available |
| OpenAI | [platform.openai.com](https://platform.openai.com) |
| Anthropic Claude | [console.anthropic.com](https://console.anthropic.com) |
| Azure OpenAI (Copilot) | Your organization's Azure portal |

You only need one provider configured to use the tool.

---

## Setup (First Time Only)

### Step 1 — Check Python is installed

Open a terminal and run:

```
python3 --version
```

You should see something like `Python 3.11.x`. If you get an error, download Python from [python.org](https://python.org) and install it first.

### Step 2 — Download the project

If you received this as a folder, skip this step. Otherwise, place the project folder somewhere you can find it (for example, your Desktop or Documents folder).

### Step 3 — Install dependencies

In your terminal, navigate to the project folder:

```
cd /path/to/Training Updater App v1
```

Then run:

```
python3 -m pip install uv
python3 -m uv pip install -r requirements.txt
```

This downloads the required libraries. It takes 1–2 minutes and only needs to be done once.

### Step 4 — Add your API key

In the project folder, find the file named `.env.example`. Make a copy of it and name the copy `.env` (no `.example` at the end).

Open `.env` in any text editor and add your API key. For example, if you're using Google Gemini:

```
GEMINI_API_KEY=your_key_here
```

Replace `your_key_here` with your actual key. Save and close the file.

> **Note:** The `.env` file contains your private API key. Do not share it or upload it anywhere.

---

## Running the App

### Option A — Double-click launcher (Mac)

Double-click the file **Launch App.command** in the project folder.

A terminal window opens briefly, then your browser opens automatically at `http://localhost:8501`.

### Option B — Terminal

In your terminal, navigate to the project folder and run:

```
streamlit run app.py
```

Your browser opens automatically. If it doesn't, go to `http://localhost:8501` manually.

To stop the app, press **Ctrl + C** in the terminal.

---

## How to Use

### Dashboard

When you open the app you land on the **Dashboard**. From here you can:

- **New Project** — group documents that share the same reference material (upload reference files once, process many documents)
- **Quick Process** — process a single document without creating a project

### Quick Process

1. Click **Quick Process** on the dashboard
2. Upload the document you want to update (`.docx`, `.pptx`, or `.pdf`)
3. Upload one or more reference files containing the updated information (`.docx` or `.pdf`)
4. Optionally add a note describing what has changed (e.g. "Product name changed from Acme Pro to Acme Suite")
5. Click **Process Documents**

### Projects

1. Click **New Project** and give it a name
2. Upload your reference files — these are shared across all documents in the project
3. Add the documents you want to update to the queue
4. Click **Process Now** on any document to run the AI

### Reviewing Changes

After processing, you land on the **Review** screen:

- **Sections needing review** are shown expanded with the original text on the left and the AI's proposed text on the right
- **Accept** — use the AI's version
- **Edit then Accept** — modify the proposed text in the box, then click Accept
- **Reject** — keep the original unchanged
- Sections already up to date are collapsed automatically
- A progress bar shows how many sections you've resolved

Once all sections are resolved, the **Generate & Download** button becomes active.

### Downloading

Click **Generate & Download** to produce the updated file. The file is named:

```
[original_filename]_updated_YYYY-MM-DD.docx
```

Open it in Word (or PowerPoint) to verify the changes before sending it for management sign-off.

---

## Troubleshooting

### "Invalid or missing API key"
Check that your `.env` file exists in the project folder and that the key is correct. Restart the app after making changes to `.env`.

### "Access denied (403)" or "Model not available"
The model you selected is not available on your API plan. For the Gemini free tier, change the **Classify model** and **Rewrite model** in the sidebar to `gemini-1.5-flash`.

### "Rate limit reached"
You've sent too many requests in a short time. Wait a moment and click **Try Again**.

### "This PDF appears to be a scanned image"
The PDF is an image scan with no readable text. Convert it to a text-based PDF first, or re-type the content into a Word document.

### The app won't start
Make sure you ran the `pip install` step. If the error mentions a missing package, run:
```
python3 -m uv pip install -r requirements.txt
```

### Port already in use
If the browser shows nothing and the terminal says "port 8501 is already in use", stop any other running instance of the app and try again, or run:
```
streamlit run app.py --server.port 8502
```

---

## File Support

| File type | As document to update | As reference material |
|---|---|---|
| Word (`.docx`) | ✅ Full support | ✅ Full support |
| PowerPoint (`.pptx`) | ✅ Full support | ❌ Not supported |
| PDF (text-based) | ⚠️ Review doc only — no patched PDF output | ✅ Full support |
| PDF (scanned image) | ❌ Not supported | ❌ Not supported |

---

## Data & Privacy

- Your documents and generated content stay on your computer at all times
- The only data sent externally is the **text content** of your documents, which is sent to your chosen AI provider's API for processing
- Nothing is stored in the cloud — sessions and project history are saved locally in `data/app.db`
- Your API key is stored only in your local `.env` file

---

*For questions or issues, contact the tool owner.*
