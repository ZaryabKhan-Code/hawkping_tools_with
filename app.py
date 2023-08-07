import os
import io
import img2pdf
import requests
from docx2pdf import convert
from flask import Flask, request, jsonify,send_file
from werkzeug.utils import secure_filename
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from flask_cors import CORS
from flask_httpauth import HTTPBasicAuth
import datetime
import subprocess

app = Flask(__name__)
app.config['CLIENT_MAX_SIZE'] = 100 * 1024 * 1024
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

CORS(app, origins='*')
auth = HTTPBasicAuth()

USERS = {
    'owner': 'owner',
    'Testing@printhash.com': 'TestingHawkPingApis',
}
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


@auth.verify_password
def verify_password(username, password):
    if username in USERS and password == USERS[username]:
        return True
    return False

user_request_count = {}

MAX_REQUESTS_PER_DAY = 10
ALLOWED_EXTENSIONS_IMG = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_EXTENSIONS_DOCX = {'docx','doc'}
ALLOWED_EXTENSIONS_MP3 = {'mp3'}

@app.before_request
def rate_limit():
    user = auth.current_user()
    if user:
        current_date = datetime.date.today()
        if user not in user_request_count or user_request_count[user][0] != current_date:
            user_request_count[user] = [current_date, 0]

        if user_request_count[user][1] >= MAX_REQUESTS_PER_DAY:
            return jsonify({'message': 'Request limit exceeded. Please try again tomorrow.'}), 429

        user_request_count[user][1] += 1

SWAGGER_URL = '/api/docs'
API_URL = '/api/spec'
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={
        'app_name': 'Hawkping Tools',
        'layout': 'BaseLayout',
        'deepLinking': True,
        'display_request_duration': True,
        'doc_expansion': 'list',
        'default_models_expand_depth': 2,
        'theme': 'tango',
        'title': 'Hawkping Tools',

    }
)

app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)


@app.route('/images-to-pdf', methods=['POST'])
def images_to_pdf():
    """
    Convert images to a single PDF.
    ---
    tags:
      - Pdf Tool Api
    parameters:
      - in: formData
        name: files
        type: file
        required: true
        description: List of image files. You can also upload a single file by choosing the "Choose File" button multiple times.
    responses:
      200:
        description: A single PDF file containing all images.
        content:
          application/pdf:
            schema:
              type: string
              format: binary
              description: The PDF file.
    """

    files = request.files.getlist('files')

    if not files:
        return jsonify({'message': 'No files uploaded'}), 400

    images = []
    for file in files:
        if file.filename == '':
            return jsonify({'message': 'Invalid file'}), 400

        if allowed_file_img(file.filename):
            images.append(file.read())
        else:
            return jsonify({'message': 'Invalid file format. Allowed extensions: png, jpg, jpeg, webp'}), 400

    try:
        pdf_bytes = convert_images_to_pdf(images)
        return pdf_bytes, 200, {'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename=output.pdf'}
    except Exception as e:
        return jsonify({'message': 'Failed to convert images to PDF: ' + str(e)}), 500

@app.route('/audio-to-text', methods=['POST'])
def audio_to_text():
    """
    Convert audio file to text.
    ---
    tags:
      - Audio Tool Api
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: The audio file Mp3 Only.
    responses:
      200:
        description: Text transcription of the audio file.
        schema:
          type: object
          properties:
            text:
              type: string
              description: The transcribed text from the audio file.
    """
    if 'file' not in request.files:
        return jsonify({'message': 'No file uploaded'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'message': 'Invalid file'}), 400

    if file and allowed_file_mp3(file.filename):
        audio_file = secure_filename(file.filename)
        file.save(audio_file)

        try:
            text = convert_audio_to_text(audio_file)
            return jsonify({'text': text}), 200
        finally:
            os.remove(audio_file)

    return jsonify({'message': 'Invalid file format. Allowed extensions: mp3'}), 400



@app.route('/word-to-pdf', methods=['POST'])
def docx_to_pdf():
    """
    Convert Word to PDF.
    ---
    tags:
      - Pdf Tool Api
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: The Word file to convert to PDF.
    responses:
      200:
        description: The converted PDF file.
        content:
          application/pdf:
            schema:
              type: string
              format: binary
              description: The PDF file.
    """
    file = request.files.get('file')

    if not file:
        return jsonify({'message': 'No file uploaded'}), 400

    if file.filename == '':
        return jsonify({'message': 'Invalid file'}), 400
    if allowed_file_docx(file.filename):
        try:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            pdf_bytes = convert_using_unoconv(file_path)

            if pdf_bytes is None:
                return jsonify({'message': 'Failed to convert Docx to PDF'}), 500

            os.remove(file_path)

            pdf_filename = 'output.pdf'
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=pdf_filename
            )
        except Exception as e:
            return jsonify({'message': 'Failed to convert Docx to PDF: ' + str(e)}), 500
    else:
        return jsonify({'message': 'Invalid file format. Allowed extensions: docx'}), 400

def convert_using_unoconv(docx_file_path):
    try:
        process = subprocess.Popen(
            ['unoconv', '-f', 'pdf', docx_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        _, error_output = process.communicate()

        if process.returncode == 0:
            pdf_file_path = os.path.splitext(docx_file_path)[0] + ".pdf"
            with open(pdf_file_path, 'rb') as pdf_file:
                pdf_bytes = pdf_file.read()

            os.remove(pdf_file_path)
            return pdf_bytes
        else:
            print(f"unoconv error: {error_output.decode()}")
            return None
    except Exception as e:
        print(f"Error during conversion: {str(e)}")
        return None



def allowed_file_img(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS_IMG

def allowed_file_mp3(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS_MP3


def allowed_file_docx(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS_DOCX


def convert_audio_to_text(audio_file):
    api_url = 'https://api.deepgram.com/v1/listen?model=nova&punctuate=true'
    token = '79cf957591c25570bc451d140588ec61fadef981'

    headers = {'Authorization': 'Token ' + token}

    with open(audio_file, 'rb') as file:
        response = requests.post(api_url, headers=headers, data=file)

    if response.ok:
        data = response.json()
        if 'results' in data and 'channels' in data['results'] and len(data['results']['channels']) > 0:
            channel = data['results']['channels'][0]
            if 'alternatives' in channel and len(channel['alternatives']) > 0:
                transcript = channel['alternatives'][0]['transcript']
                return transcript
            else:
                return 'No transcript found in the API response'
        else:
            return 'No channels or alternatives found in the API response'
    else:
        return 'API request failed with status code: ' + str(response.status_code)

def convert_images_to_pdf(images):
    pdf_bytes = io.BytesIO()
    pdf_bytes.write(img2pdf.convert(images))
    pdf_bytes.seek(0)
    return pdf_bytes.getvalue()

@app.route('/api/spec', methods=['GET'])
def swagger_spec():
    swag = swagger(app)
    swag['info'] = {
        'version': '1.0',
        'title': 'Hawkping Tools',
        'description': '''
🚀 Welcome to our amazing API! 🎉 
This API is your gateway to a plethora of powerful tools that can transform your digital world like never before! 🌌

🎤 Audio to Text 📝
With our cutting-edge technology, you can effortlessly convert your audio files into beautifully formatted text documents. Just send us your audio, and we'll do the heavy lifting, providing you with accurate and reliable transcriptions in no time! 🎵🔠

🌄 Image to PDF 🖼️➡️📄
Tired of managing multiple image files? No worries! We've got you covered with our lightning-fast Image to PDF conversion tool. Transform those scattered images into a single, convenient, and easily shareable PDF document with just a few clicks! 📁💻📤

📑 Document to PDF 📄➡️📄
Say goodbye to the hassle of handling separate document files. Our Document to PDF feature allows you to combine multiple document formats, such as text files, spreadsheets, and presentations, into a single PDF document. Streamline your digital documents and make sharing and archiving a breeze! 📝📊📎➡️📑

🚧 And many more to come! 🛠️
We are continuously working to expand our collection of tools, bringing you even more functionality and convenience. Stay tuned for exciting updates as we roll out new features and enhancements to help you conquer your digital tasks with ease! 🚀🌟

So, what are you waiting for? Dive into our API and experience the magic of transforming audio, images, and much more into a world of possibilities! 🌈🔮''',
        'contact': {
            'name': 'Team Hash',
            'email': ''
        },
        'license': {
            'name': 'PrintHash Development License',
            'url': 'http://printhash.com/project/license'
        }
    }

    for path in swag['paths'].values():
        for method in path.values():
            if method.get('parameters') and 'files' in method['parameters']:
                method['parameters'][0]['type'] = 'array'
                method['parameters'][0]['items'] = {
                    'type': 'file',
                    'format': 'binary'
                }
    return jsonify(swag)


if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0')

