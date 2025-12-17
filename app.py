import os
import logging
import datetime
import uuid
import time
from flask import Flask, render_template, request, jsonify, Response
from gtts import gTTS
from xhtml2pdf import pisa
from io import BytesIO
from pptx import Presentation
import speech_recognition as sr
from dotenv import load_dotenv
import psutil
import base64
import PIL.Image
from youtube_transcript_api import YouTubeTranscriptApi
from moviepy.editor import VideoFileClip

# --- IMPORT FOR GROQ ---
from groq import Groq

# --- LOAD ENV ---
basedir = os.path.abspath(os.path.dirname(__file__))
env_path = os.path.join(basedir, '.env')
load_dotenv(env_path)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION ---
API_KEY = os.environ.get("GROQ_API_KEY") 
STATIC_FOLDER = os.path.join(basedir, 'static')
if not os.path.exists(STATIC_FOLDER): os.makedirs(STATIC_FOLDER)

# --- STATS ---
global_stats = {
    "text_gen": 5, "audio_gen": 2, "transcribe": 3, "pdf_gen": 4, 
    "chat_msgs": 0, "image_analysis": 0, "code_review": 0, "quiz_gen": 0,
    "video_sum": 0, "file_conv": 0, "compression": 0, "vid_audio": 0
}

def increment_stat(field_name):
    try:
        if field_name in global_stats: global_stats[field_name] += 1
    except: pass

# --- AI WRAPPER (GROQ) ---
def get_safe_ai_response(prompt, image_file=None):
    if not API_KEY:
        print("❌ Error: GROQ_API_KEY not found in .env")
        return None

    try:
        client = Groq(api_key=API_KEY)
        
        # 1. HANDLE IMAGE ANALYSIS (Vision)
        if image_file:
            # Convert image to base64
            image_bytes = image_file.read()
            encoded_image = base64.b64encode(image_bytes).decode('utf-8')
            
            completion = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview", # Vision Model
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{encoded_image}"
                                },
                            },
                        ],
                    }
                ],
                temperature=0.5,
                max_tokens=1024,
            )
            return completion.choices[0].message.content

        # 2. HANDLE TEXT/CHAT (UPDATED MODEL)
        else:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile", # <--- UPDATED TO NEW MODEL
                messages=[
                    {"role": "system", "content": "You are a helpful AI assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=2048,
            )
            return completion.choices[0].message.content

    except Exception as e:
        print(f"❌ Groq API Error: {e}")
        return None

# --- ROUTES ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    try: c, r = psutil.cpu_percent(0.1), psutil.virtual_memory().percent
    except: c, r = 0, 0
    return jsonify({"cpu": c, "ram": r, "usage": global_stats})

@app.route('/download-report')
def download_report():
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try: 
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
        except: 
            cpu, ram = 0, 0

        report = f"""
========================================
       AI WORKSPACE SYSTEM REPORT       
========================================
Generated On: {now}
Backend Provider: Groq (Llama 3.3)

[SYSTEM HEALTH]
----------------------------------------
CPU Load  : {cpu}%
RAM Usage : {ram}%

[TOOL USAGE STATISTICS]
----------------------------------------
• Text Generators      : {global_stats.get('text_gen', 0)}
• Audio Generators     : {global_stats.get('audio_gen', 0)}
• Audio Transcriptions : {global_stats.get('transcribe', 0)}
• PDF Documents        : {global_stats.get('pdf_gen', 0)}
• Image Analysis       : {global_stats.get('image_analysis', 0)}
========================================
"""
        return Response(report, mimetype="text/plain", headers={"Content-disposition": "attachment; filename=System_Report.txt"})
    except Exception as e: return str(e), 500

@app.route('/chat', methods=['POST'])
def chat():
    increment_stat('chat_msgs')
    try:
        msg = request.form.get('message', '')
        if not msg: return jsonify({"success": False, "error": "Empty"}), 400
        res = get_safe_ai_response(msg)
        return jsonify({"success": True, "response": res if res else "Busy."})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/generate-minutes', methods=['POST'])
def generate_minutes():
    increment_stat('text_gen')
    try:
        notes = request.form.get('notes', '')
        res = get_safe_ai_response(f"Create structured Meeting Minutes based on these notes:\n{notes}")
        return jsonify({"success": True, "minutes": res if res else "Error"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/make-ppt', methods=['POST'])
def make_ppt():
    increment_stat('text_gen')
    try:
        topic = request.form.get('topic', '')
        src_text = request.form.get('source_text', '')
        template_file = request.files.get('template_file')
        
        # PPT Generation Logic
        if template_file and template_file.filename != '':
            temp_path = os.path.join(STATIC_FOLDER, f"temp_{uuid.uuid4().hex}.pptx")
            template_file.save(temp_path)
            prs = Presentation(temp_path)
        else:
            prs = Presentation()
            
        prompt = (f"Create a presentation about {topic}. {src_text}. "
                  "Format exactly like this:\nSLIDE_TITLE: [Title]\nBULLET: [Point 1]\nBULLET: [Point 2]")
        
        content = get_safe_ai_response(prompt)
        
        if not content: content = f"SLIDE_TITLE: {topic}\nBULLET: Content generation failed."
        
        lines = content.split('\n')
        curr = None
        for line in lines:
            clean = line.strip().replace('*', '').replace('#', '')
            if "SLIDE_TITLE:" in clean:
                try:
                    layout_index = 1 if len(prs.slide_layouts) > 1 else 0
                    curr = prs.slides.add_slide(prs.slide_layouts[layout_index])
                    curr.shapes.title.text = clean.split("SLIDE_TITLE:", 1)[1].strip()
                    curr.placeholders[1].text_frame.word_wrap = True
                except: pass
            elif "BULLET:" in clean and curr:
                try:
                    p = curr.placeholders[1].text_frame.add_paragraph()
                    p.text = clean.split("BULLET:", 1)[1].strip()
                    p.level = 0
                except: pass
                
        fname = f"ppt_{uuid.uuid4().hex[:10]}.pptx"
        prs.save(os.path.join(STATIC_FOLDER, fname))
        if 'temp_path' in locals() and os.path.exists(temp_path): os.remove(temp_path)
        return jsonify({"success": True, "file_url": f"/static/{fname}"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/text-to-audio', methods=['POST'])
def text_to_audio():
    increment_stat('audio_gen')
    try:
        text = request.form.get('text', '')
        lang = request.form.get('language', 'en') 
        if lang != 'en':
            res = get_safe_ai_response(f"Translate this to {lang} ONLY. No extra text:\n{text}")
            if res: text = res.strip()
        fname = f"audio_{uuid.uuid4().hex[:10]}.mp3"
        tts = gTTS(text=text, lang='en' if lang=='auto' else lang, slow=False)
        tts.save(os.path.join(STATIC_FOLDER, fname))
        return jsonify({"success": True, "file_url": f"/static/{fname}", "translated_text": text})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/audio-to-text', methods=['POST'])
def audio_to_text():
    increment_stat('transcribe')
    try:
        f = request.files['file']
        lang = request.form.get('language', 'en-US') 
        fname = f"up_{uuid.uuid4().hex[:10]}.wav"
        fpath = os.path.join(STATIC_FOLDER, fname)
        f.save(fpath)
        r = sr.Recognizer()
        with sr.AudioFile(fpath) as src:
            audio_data = r.record(src)
            txt = r.recognize_google(audio_data, language=lang)
        return jsonify({"success": True, "text": txt})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/translate', methods=['POST'])
def translate():
    increment_stat('text_gen')
    try:
        text = request.form.get('text', '').strip()
        target_lang = request.form.get('target_language', 'en').strip()

        if not text or not target_lang:
            return jsonify({"success": False, "error": "Missing text"}), 400

        # Updated Prompt for Groq
        prompt = (
            f"You are a professional translator. \n"
            f"Target Language: {target_lang}\n"
            f"Text: {text}\n"
            f"Output Requirement: Return the translation in native script, followed by '|||', followed by the English transliteration (pronunciation).\n"
            f"Example: [Native Script] ||| [Pronunciation]\n"
            f"Do not include any intro or outro text."
        )

        full_response = get_safe_ai_response(prompt)
        
        if not full_response:
            return jsonify({"success": False, "translation": "Error: AI Service Busy"}), 503

        # Split logic
        translated_text = full_response
        transliteration = ""
        if "|||" in full_response:
            parts = full_response.split("|||")
            translated_text = parts[0].strip()
            transliteration = parts[1].strip()

        # Generate Audio
        audio_url = None
        try:
            lang_map = {'french': 'fr', 'spanish': 'es', 'hindi': 'hi', 'german': 'de', 'kannada': 'kn', 'tamil': 'ta'}
            lang_code = target_lang if len(target_lang) == 2 else lang_map.get(target_lang.lower(), 'en')
            audio_name = f"trans_{uuid.uuid4().hex[:8]}.mp3"
            gTTS(text=translated_text, lang=lang_code, slow=False).save(os.path.join(STATIC_FOLDER, audio_name))
            audio_url = f"/static/{audio_name}"
        except: pass

        return jsonify({
            "success": True, 
            "translation": translated_text,
            "transliteration": transliteration,
            "audio_url": audio_url
        })
        
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/generate-email', methods=['POST'])
def generate_email():
    increment_stat('text_gen')
    try:
        to, topic = request.form.get('recipient', ''), request.form.get('topic', '')
        res = get_safe_ai_response(f"Write a professional email to {to} about {topic}.")
        return jsonify({"success": True, "email_content": res if res else "Busy"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/text-to-pdf', methods=['POST'])
def text_to_pdf():
    increment_stat('pdf_gen')
    try:
        h = request.form.get('html_content', '')
        if request.form.get('translation_needed') == 'true':
            t = request.form.get('target_language', 'English')
            res = get_safe_ai_response(f"Translate this HTML content to {t}, keeping all HTML tags intact: {h}")
            if res: h = res.replace('```html','').replace('```','')
        
        styled_html = f"""<html><body>{h}</body></html>"""
        fname = f"doc_{uuid.uuid4().hex[:10]}.pdf"
        with open(os.path.join(STATIC_FOLDER, fname), "w+b") as f: 
            pisa.CreatePDF(BytesIO(styled_html.encode('utf-8')), dest=f)
        return jsonify({"success": True, "file_url": f"/static/{fname}"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/analyze-image', methods=['POST'])
def analyze_image():
    increment_stat('image_analysis')
    try:
        if 'image' not in request.files: return jsonify({"success": False, "error": "No image"}), 400
        img_file = request.files['image']
        prompt = request.form.get('prompt', 'Describe this image detailedly.')
        
        # We pass the file object directly to our new Groq wrapper
        res = get_safe_ai_response(prompt, image_file=img_file)
        return jsonify({"success": True, "analysis": res if res else "Failed."})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/generate-quiz', methods=['POST'])
def generate_quiz():
    increment_stat('quiz_gen')
    try:
        topic = request.form.get('topic', '')
        count = request.form.get('count', '5')
        prompt = f"Create a {count}-question Multiple Choice Quiz about: {topic}. Include Answer Key at bottom."
        res = get_safe_ai_response(prompt)
        
        # Simple PDF generation for quiz
        html_content = f"<h2>Quiz: {topic}</h2><pre>{res}</pre>"
        fname = f"quiz_{uuid.uuid4().hex[:10]}.pdf"
        with open(os.path.join(STATIC_FOLDER, fname), "w+b") as f:
            pisa.CreatePDF(BytesIO(html_content.encode('utf-8')), dest=f)
            
        return jsonify({"success": True, "quiz": res, "file_url": f"/static/{fname}"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/review-code', methods=['POST'])
def review_code():
    increment_stat('code_review')
    try:
        code = request.form.get('code', '')
        res = get_safe_ai_response(f"Review this code and suggest improvements:\n{code}")
        return jsonify({"success": True, "review": res if res else "Error"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/summarize-video', methods=['POST'])
def summarize_video():
    increment_stat('video_sum')
    try:
        url = request.form.get('url', '')
        vid = None
        if "youtube.com" in url: vid = url.split("v=")[1].split("&")[0]
        elif "youtu.be" in url: vid = url.split("/")[-1]
        
        if not vid: return jsonify({"success": False, "error": "Invalid URL"}), 400
        
        transcript = YouTubeTranscriptApi.get_transcript(vid)
        full = " ".join([i['text'] for i in transcript])
        
        # Summarize chunks if too long
        prompt = f"Summarize this YouTube video transcript in detail:\n{full[:20000]}"
        res = get_safe_ai_response(prompt)
        return jsonify({"success": True, "summary": res if res else "Busy"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

# --- RESTORED FILE CONVERSION TOOLS ---

@app.route('/convert-file', methods=['POST'])
def convert_file():
    increment_stat('file_conv')
    try:
        if 'file' not in request.files: return jsonify({"success": False, "error": "No file uploaded"}), 400
        file = request.files['file']
        target_format = request.form.get('format', 'PNG').upper()
        if file.filename == '': return jsonify({"success": False, "error": "No file selected"}), 400
        
        img = PIL.Image.open(file)
        if target_format in ['JPEG', 'JPG', 'PDF']:
            img = img.convert('RGB')
            
        new_filename = f"converted_{uuid.uuid4().hex[:10]}.{target_format.lower()}"
        save_path = os.path.join(STATIC_FOLDER, new_filename)
        img.save(save_path, target_format if target_format != 'JPG' else 'JPEG')
        
        return jsonify({"success": True, "file_url": f"/static/{new_filename}"})
    except Exception as e: return jsonify({"success": False, "error": f"Error: {str(e)}"}), 500

@app.route('/compress-image', methods=['POST'])
def compress_image():
    increment_stat('compression')
    try:
        if 'file' not in request.files: return jsonify({"success": False, "error": "No file"}), 400
        file = request.files['file']
        quality = int(request.form.get('quality', '60'))
        
        img = PIL.Image.open(file)
        img = img.convert('RGB')
        
        new_filename = f"compressed_{uuid.uuid4().hex[:10]}.jpg"
        save_path = os.path.join(STATIC_FOLDER, new_filename)
        
        img.save(save_path, "JPEG", quality=quality, optimize=True)
        return jsonify({"success": True, "file_url": f"/static/{new_filename}"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/video-to-audio', methods=['POST'])
def video_to_audio():
    increment_stat('vid_audio')
    try:
        if 'file' not in request.files: return jsonify({"success": False, "error": "No video file"}), 400
        file = request.files['file']
        
        # Save temp video
        temp_vid_name = f"temp_vid_{uuid.uuid4().hex[:10]}.mp4"
        temp_vid_path = os.path.join(STATIC_FOLDER, temp_vid_name)
        file.save(temp_vid_path)
        
        # Output Audio Path
        audio_name = f"extracted_{uuid.uuid4().hex[:10]}.mp3"
        audio_path = os.path.join(STATIC_FOLDER, audio_name)
        
        # Convert
        clip = VideoFileClip(temp_vid_path)
        clip.audio.write_audiofile(audio_path, logger=None)
        clip.close()
        
        # Cleanup video
        if os.path.exists(temp_vid_path): os.remove(temp_vid_path)
        
        return jsonify({"success": True, "file_url": f"/static/{audio_name}"})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)