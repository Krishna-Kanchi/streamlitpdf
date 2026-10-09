# Put PDF ToolHub online

## Option A - Streamlit Community Cloud (free, easiest)
1. Create a GitHub account and a new repository; upload every file in this folder (app.py, engine.py,
   requirements.txt, packages.txt, fonts/, .streamlit/).
2. Go to share.streamlit.io, sign in with GitHub, click "Create app".
3. Pick your repository, branch `main`, main file `app.py`. In Advanced settings choose Python 3.12.
4. Click Deploy. You get a public URL like https://your-name-pdf-toolhub.streamlit.app
`packages.txt` installs OCR (English, Telugu, Hindi) and Noto fonts on the server automatically.

## Option B - Render / Railway / Fly.io / any Docker host
Push the folder to GitHub, create a "Web Service" from the repo with Runtime = Docker. The Dockerfile reads $PORT.

## Option C - Hugging Face Spaces (free)
Create a Space with SDK = Docker. Add this block at the very top of README.md:
---
title: PDF ToolHub
sdk: docker
app_port: 7860
---
and set the environment variable PORT=7860 in the Space settings.

## Option D - Your own server
docker build -t pdf-toolhub .
docker run -p 80:8501 pdf-toolhub

## Before you go public
- Free tiers have about 1 GB RAM: very large PDFs, OCR and "Maximum" compression may fail. Lower maxUploadSize in
  .streamlit/config.toml if needed.
- Files are processed in memory and not saved, but users upload to YOUR server - say so in a privacy note.
- To restrict access, use Streamlit Cloud's "Viewers" setting or put the app behind a login (Cloudflare Access, etc.).
- Custom domain: Render/Railway support it directly; Streamlit Cloud needs a redirect or reverse proxy.
