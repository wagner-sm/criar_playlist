import os
import json
from flask import Flask, redirect, url_for, session, request, render_template_string, flash
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'segredo-mude-para-um-valor-forte')

# Cria o credentials.json a partir da variável de ambiente, se não existir
if not os.path.exists("credentials.json"):
    creds = os.environ.get("GOOGLE_CREDENTIALS")
    if creds:
        with open("credentials.json", "w") as f:
            f.write(creds)

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:5000/oauth2callback")

def get_flow():
    return Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

def get_youtube():
    from google.oauth2.credentials import Credentials
    credentials = Credentials(**session['credentials'])
    return build("youtube", "v3", credentials=credentials)

@app.route('/')
def index():
    if 'credentials' not in session:
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Criador de Playlist YouTube</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light">
        <div class="container py-5">
            <div class="card shadow-sm mx-auto" style="max-width: 500px;">
                <div class="card-body text-center">
                    <h1 class="mb-4">Criador de Playlist YouTube</h1>
                    <a href="{{ url_for('authorize') }}" class="btn btn-danger btn-lg">Autenticar com Google</a>
                </div>
            </div>
        </div>
        </body>
        </html>
        ''')
    return redirect(url_for('playlist'))

@app.route('/authorize')
def authorize():
    flow = get_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    flow = get_flow()
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    flash('Autenticado com sucesso!', 'success')
    return redirect(url_for('playlist'))

@app.route('/playlist', methods=['GET', 'POST'])
def playlist():
    if 'credentials' not in session:
        return redirect(url_for('index'))

    log = []
    if request.method == 'POST':
        playlist_name = request.form.get('playlist_name')
        playlist_desc = request.form.get('playlist_desc')
        artist = request.form.get('artist')
        public = request.form.get('public') == 'on'
        delay = request.form.get('delay') == 'on'
        songs_text = request.form.get('songs_text')

        if not playlist_name or not artist or not songs_text:
            flash('Preencha todos os campos!', 'warning')
        else:
            try:
                youtube = get_youtube()
                privacy = "public" if public else "private"
                playlist_id = youtube.playlists().insert(
                    part="snippet,status",
                    body={
                        "snippet": {"title": playlist_name, "description": playlist_desc},
                        "status": {"privacyStatus": privacy}
                    }
                ).execute()["id"]
                log.append(f"Playlist criada com ID: {playlist_id}")

                songs = [song.strip() for song in songs_text.split("\n") if song.strip()]
                added_count = 0
                failed_count = 0

                for i, song in enumerate(songs, 1):
                    query = f"{artist} {song}"
                    log.append(f"Processando música {i}/{len(songs)}: {song}")
                    try:
                        search = youtube.search().list(
                            part="snippet",
                            maxResults=1,
                            q=query,
                            type="video"
                        ).execute()
                        items = search.get("items", [])
                        if items:
                            video_id = items[0]["id"]["videoId"]
                            youtube.playlistItems().insert(
                                part="snippet",
                                body={
                                    "snippet": {
                                        "playlistId": playlist_id,
                                        "resourceId": {"kind": "youtube#video", "videoId": video_id}
                                    }
                                }
                            ).execute()
                            log.append(f"✓ Adicionado: {song}")
                            added_count += 1
                        else:
                            log.append(f"✗ Não encontrado: {song}")
                            failed_count += 1
                        if delay and i < len(songs):
                            time.sleep(1)
                    except HttpError as e:
                        error_code = e.resp.status
                        error_content = str(e)
                        if error_code == 409:
                            log.append(f"⚠ Erro 409 (conflito) para: {song} - Tentando continuar...")
                        elif error_code == 403:
                            if 'quotaExceeded' in error_content:
                                log.append("⚠ Quota da API do YouTube excedida. Parando o processamento.")
                                flash("Quota da API do YouTube excedida. Tente novamente amanhã ou reduza o número de músicas.", "danger")
                                break  # Para o loop imediatamente
                            else:
                                log.append(f"⚠ Erro 403 para: {song} (motivo desconhecido)")
                                failed_count += 1
                        else:
                            log.append(f"⚠ Erro HTTP {error_code} para: {song}")
                            failed_count += 1
                    except Exception as e:
                        log.append(f"⚠ Erro inesperado para {song}: {str(e)}")
                        failed_count += 1

                flash(f"Concluído! {added_count} adicionadas, {failed_count} falharam", "success")
            except Exception as e:
                flash(f"Erro ao criar playlist: {str(e)}", "danger")

    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Criar Playlist YouTube</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
    <div class="container py-5">
        <div class="card shadow-sm mx-auto" style="max-width: 700px;">
            <div class="card-body">
                <h1 class="mb-4 text-center">Criar Playlist</h1>
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    <div>
                    {% for category, message in messages %}
                      <div class="alert alert-{{ 'danger' if category == 'danger' else 'success' if category == 'success' else 'warning' }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                      </div>
                    {% endfor %}
                    </div>
                  {% endif %}
                {% endwith %}
                <form method="post">
                    <div class="mb-3">
                        <label class="form-label">Nome da Playlist:</label>
                        <input type="text" name="playlist_name" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Descrição:</label>
                        <input type="text" name="playlist_desc" class="form-control">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Artista:</label>
                        <input type="text" name="artist" class="form-control" required>
                    </div>
                    <div class="form-check mb-2">
                        <input class="form-check-input" type="checkbox" name="public" id="public">
                        <label class="form-check-label" for="public">Playlist pública</label>
                    </div>
                    <div class="form-check mb-3">
                        <input class="form-check-input" type="checkbox" name="delay" id="delay" checked>
                        <label class="form-check-label" for="delay">Delay entre requisições (evita limite de API)</label>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Músicas (uma por linha):</label>
                        <textarea name="songs_text" rows="8" class="form-control" required></textarea>
                    </div>
                    <button type="submit" class="btn btn-primary">Criar Playlist</button>
                    <a href="{{ url_for('logout') }}" class="btn btn-secondary ms-2">Sair</a>
                </form>
                {% if log %}
                <hr>
                <h4 class="mt-4">Log:</h4>
                <pre class="bg-light p-3 border rounded" style="max-height: 300px; overflow-y: auto;">{% for line in log %}{{ line }}
{% endfor %}</pre>
                {% endif %}
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    ''', log=log)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
