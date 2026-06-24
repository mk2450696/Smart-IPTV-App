import subprocess
import os
import json
import requests
import re
from flask import Flask, request, Response, stream_with_context, redirect, jsonify

app = Flask(__name__)

# --- CONFIG ---
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

# CREDENTIALS
OS_API_KEY = "oKhrXoAVjqjJuYgd2zbH62WTag88mZDq" # <--- PASTE KEY
# -------------------

NET_FLAGS = ['-user_agent', 'VLC/3.0.18 LibVLC/3.0.18', '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '10']

# --- CORS ---
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.after_request
def after_request(response):
    return add_cors_headers(response)

# --- DOLBY CHECK (FIXED) ---
def check_is_dolby(url):
    print(f"🕵️ PROBING FOR DOLBY: {url}")
    try:
        # INCREASED PROBE SIZE: 5MB / 5 Seconds
        # This ensures we read the 'side_data' even if headers are large
        cmd = [
            FFPROBE_PATH, 
            '-v', 'quiet', 
            '-print_format', 'json', 
            '-show_streams', 
            '-select_streams', 'v:0', 
            *NET_FLAGS, 
            '-probesize', '5000000',      # Was 500,000 -> Now 5,000,000
            '-analyzeduration', '5000000', # Was 0.5s -> Now 5s (Max wait)
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        data = json.loads(result.stdout)
        
        for stream in data.get('streams', []):
            # 1. Check Codec Tag (e.g. dvhe, dvh1)
            codec_tag = stream.get('codec_tag_string', '')
            if 'dvh' in codec_tag or 'dvhe' in codec_tag:
                print(f"✅ DOLBY FOUND (Codec Tag: {codec_tag})")
                return True
                
            # 2. Check Side Data (The most reliable method for MKV)
            side_data_list = stream.get('side_data_list', [])
            for side in side_data_list:
                side_type = side.get('side_data_type', '')
                if 'DOVI' in side_type or 'Dolby' in side_type:
                    print(f"✅ DOLBY FOUND (Side Data: {side_type})")
                    return True

        print("❌ NO DOLBY DETECTED (Standard HDR/SDR)")
        return False
    except Exception as e: 
        print(f"⚠️ PROBE ERROR: {e}")
        return False

# --- SUBTITLE SEARCH ---
def parse_raw_title(raw):
    clean = raw.strip()
    season, episode = None, None
    se_match = re.search(r'[Ss](\d+)\s*[EeXx](\d+)', clean)
    if se_match:
        season = int(se_match.group(1))
        episode = int(se_match.group(2))
    
    title = clean
    year_match = re.search(r'(.*?)[\(\[](\d{4})[\)\]]', clean)
    if year_match:
        title = year_match.group(1).strip()
    elif se_match:
        title = clean[:se_match.start()].strip()

    title = re.sub(r'^.*?- ', '', title).strip(' -')
    return title, season, episode

@app.route('/search_subs')
def search_subs():
    raw_name = request.args.get('raw_name', '')
    lang = request.args.get('lang', 'en')
    result_index = int(request.args.get('index', '0'))
    
    headers = {"Api-Key": OS_API_KEY, "User-Agent": "MyHomeIPTV v1.0"}
    title, season, episode = parse_raw_title(raw_name)
    print(f"🔎 SEARCHING: {title} S{season}E{episode} [{lang}] Index: {result_index}")

    params = {"query": title, "languages": lang, "order_by": "votes", "order_direction": "desc"}
    if season and episode:
        params["season_number"] = season
        params["episode_number"] = episode

    try:
        r = requests.get("https://api.opensubtitles.com/api/v1/subtitles", params=params, headers=headers)
        data = r.json()
        
        if data.get('total_count', 0) > result_index:
            target = data['data'][result_index]
            fid = target['attributes']['files'][0]['file_id']
            fname = target['attributes']['files'][0]['file_name']
            
            print(f"✅ DOWNLOAD: {fname}")
            
            dl_r = requests.post("https://api.opensubtitles.com/api/v1/download", json={"file_id": fid}, headers=headers)
            if dl_r.status_code == 200:
                raw_srt = requests.get(dl_r.json().get('link')).text
                vtt = "WEBVTT\n\n" + raw_srt.replace(',', '.')
                return Response(vtt, mimetype='text/vtt')
    except Exception as e: print(e)

    return Response("WEBVTT\n\nNOTE No subtitles found", mimetype='text/vtt')

# --- METADATA ---
@app.route('/get_meta')
def get_meta():
    url = request.args.get('url')
    if not url: return jsonify({'error': 'No URL'}), 400
    try:
        cmd = [FFPROBE_PATH, '-v', 'quiet', '-print_format', 'json', '-show_format', *NET_FLAGS, url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        data = json.loads(result.stdout)
        return jsonify({'duration': float(data['format']['duration'])})
    except: return jsonify({'duration': 0})

# --- VIDEO PROXY ---
@app.route('/stream_ts')
def stream_ts():
    return "Video proxy disabled for Cloud Hosting", 403
    url = request.args.get('url')
    start_time = request.args.get('start', '0')
    if not url: return "Missing URL", 400

    # DOLBY CHECK (Only on initial load)
    if start_time == '0':
        if check_is_dolby(url):
            print(f"↪️ REDIRECTING (Dolby): {url}")
            return redirect(url, code=302)

    is_live = '/live/' in url
    mode_log = "LIVE (Fast)" if is_live else "VOD (Buffered)"
    print(f"⚙️ PROXYING [{mode_log}] @ {start_time}s")

    cmd = [
        FFMPEG_PATH, *NET_FLAGS, '-ss', start_time, '-i', url,
        '-map', '0:v', '-map', '0:a', '-sn',
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ac', '2',
        '-map_metadata', '0',
        '-f', 'mpegts'
    ]

    if is_live:
        cmd.extend([
            '-tune', 'zerolatency',
            '-probesize', '2000000',
            '-analyzeduration', '2000000',
            '-flush_packets', '1',
            '-fflags', '+genpts+igndts+nobuffer'
        ])
    else:
        cmd.extend([
            '-probesize', '5000000',
            '-analyzeduration', '5000000',
            '-flush_packets', '1',
            '-fflags', '+genpts+igndts'
        ])

    cmd.append('-')

    def generate():
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                data = proc.stdout.read(4096*10)
                if not data: break
                yield data
        except: proc.terminate()
        finally: proc.terminate()

    return Response(stream_with_context(generate()), mimetype='video/MP2T')

if __name__ == '__main__':
    print("🚀 SERVER V14 (DEEP PROBE) RUNNING on Port 5000")
    app.run(host='0.0.0.0', port=5000, threaded=True)

# --- CLOUD STATIC FILE SERVER ---
from flask import send_from_directory

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

@app.route('/')
def serve_index():
    # Change 'index.html' to whatever your main TV webpage file is, if it's different
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    # Binds to the port Render gives us
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
