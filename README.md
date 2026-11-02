# ai-ATS-checker
# 📄 ATS Resume Checker

A Streamlit app that scores a resume for ATS (Applicant Tracking System) friendliness and suggests concrete improvements, powered by Google Gemini Flash.

## Features
- Upload a resume as **PDF, DOCX or TXT**
- Optional **job description** for a tailored score and keyword gap
- ATS score (0-100) with a breakdown: formatting, keywords, content, impact, skills, readability
- Strengths, weaknesses, missing keywords and prioritised improvements
- Rewritten bullet points, quick rule-based checks, downloadable report

## Project structure
```
app.py            # Streamlit app
requirements.txt  # Python dependencies
README.md         # This file
```

## Run locally
1. Install Python 3.10+.
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   # Windows: venv\Scripts\activate    |   Mac/Linux: source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Get a free API key from https://aistudio.google.com/apikey
4. Provide the key (pick one):
   - Paste it in the app sidebar, **or**
   - Set an environment variable: `GEMINI_API_KEY=your_key`, **or**
   - Create `.streamlit/secrets.toml` containing:
     ```toml
     GEMINI_API_KEY = "your_key"
     ```
5. Start the app:
   ```bash
   streamlit run app.py
   ```

## Push to GitHub
```bash
git init
git add app.py requirements.txt README.md
git commit -m "Initial commit: ATS resume checker"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```
Create the empty repository on github.com first. Add a `.gitignore` with `.streamlit/secrets.toml` and `venv/` so your key is never uploaded.

## Deploy on Streamlit Community Cloud
1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app** -> choose your repository, branch `main`, main file `app.py`.
3. Open **Advanced settings -> Secrets** and add:
   ```toml
   GEMINI_API_KEY = "your_key"
   ```
4. Click **Deploy**. Your app gets a public URL in a few minutes.

## Notes
- Scanned/image-only PDFs have no extractable text; use a text-based PDF or DOCX.
- If a model name stops working, change the model in the sidebar or in `MODEL_OPTIONS` inside `app.py`.
- Resume text is sent to Google's Gemini API; do not upload resumes you are not allowed to share.
