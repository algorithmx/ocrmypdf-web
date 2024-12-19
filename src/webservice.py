"""This is a simple web service/HTTP wrapper for OCRmyPDF.

Data Flow
=========

Client (upload.html)
  → Form submission with PDF + enhancement settings
    → Flask Server (webservice.py)
      → File validation & caching check
        → PDFImageEnhancer (if enhancement enabled)
          → OCRmyPDF processing
            → Return processed PDF
"""

from __future__ import annotations

import os
import shlex
import logging
from subprocess import run
from tempfile import TemporaryDirectory
from datetime import datetime
import hashlib
import json
from pathlib import Path

from flask import Flask, Response, request, send_from_directory, render_template
from werkzeug.utils import secure_filename

base_dir = os.environ.get('BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

# Create log directory if it doesn't exist
log_dir = Path(base_dir) / 'logs'
log_dir.mkdir(exist_ok=True)

# Update logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'ocrmypdf_webservice.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from enhancer import PDFImageEnhancer

app = Flask(__name__)

app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    logger.warning("No SECRET_KEY set! Using an insecure default.")
    app.secret_key = 'dev'

app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 50_000_000))
app.config['BASE_DIR'] = os.environ.get('BASE_DIR', base_dir)
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'uploads')
app.config['CACHE_INDEX'] = os.path.join(app.config['UPLOAD_FOLDER'], 'cache_index.json')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def compute_file_hash(file_path):
    """Compute SHA-256 hash of file content."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_cache_index():
    """Load or create cache index."""
    if os.path.exists(app.config['CACHE_INDEX']):
        with open(app.config['CACHE_INDEX'], 'r') as f:
            return json.load(f)
    return {}


def update_cache_index(cache_index):
    """Save cache index to file."""
    with open(app.config['CACHE_INDEX'], 'w') as f:
        json.dump(cache_index, f)


def create_enhancer_config(form_data):
    """Convert form data to enhancer configuration."""
    return {
        "denoising": {
            "enabled": "denoising_enabled" in form_data,
            "h": int(form_data.get("denoising_h", 10)),
            "template_window_size": int(form_data.get("denoising_template_window_size", 9)),
            "search_window_size": int(form_data.get("denoising_search_window_size", 21))
        },
        "clahe": {
            "enabled": "clahe_enabled" in form_data,
            "clip_limit": float(form_data.get("clahe_clip_limit", 3.0)),
            "tile_grid_size": [
                int(form_data.get("clahe_grid_size_x", 24)),
                int(form_data.get("clahe_grid_size_y", 24))
            ]
        },
        "contrast": {
            "enabled": "contrast_enabled" in form_data,
            "alpha": float(form_data.get("contrast_alpha", 1.5)),
            "beta": float(form_data.get("contrast_beta", 0))
        },
        "sharpening": {
            "enabled": "sharpening_enabled" in form_data,
            "sigma": float(form_data.get("sharpening_sigma", 0.8)),
            "amount": float(form_data.get("sharpening_amount", 1.0)),
            "gaussian_weight": float(form_data.get("sharpening_gaussian_weight", -0.1))
        },
        "binarization": {
            "enabled": "binarization_enabled" in form_data,
            "block_size": int(form_data.get("binarization_block_size", 11)),
            "c": int(form_data.get("binarization_c", 2))
        },
        "base_dir": app.config['BASE_DIR'],
        "upload_dir": app.config['UPLOAD_FOLDER'],
        "resolution": int(form_data.get("resolution", 400))
    }


def enhance_pdf(input_path, output_path, form_data):
    """Apply image enhancement to PDF if requested."""
    if any(key.endswith('_enabled') for key in form_data):
        logger.info("Applying image enhancement preprocessing")
        try:
            config = create_enhancer_config(form_data)
            enhancer = PDFImageEnhancer(config)
            assert os.path.isfile(input_path)
            enhancer.process_pdf(input_path, output_path, config['resolution'])
            logger.info(f"Enhanced PDF saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error during PDF enhancement: {str(e)}")
            raise
    return False


def do_ocrmypdf(file, request_form):
    logger.info(f"Starting OCR process for file: {file.filename}")

    filename = secure_filename(file.filename)
    cache_input = os.path.join(app.config['UPLOAD_FOLDER'], f"input_{filename}")
    file.save(cache_input)

    # Modify the output filename to include .ocr before the extension
    base_name, ext = os.path.splitext(filename)
    output_filename = f"{base_name}.ocr{ext}"
    down_file = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
    
    # Update the cache handling to use the new output filename
    file_hash = compute_file_hash(cache_input)
    cache_index = get_cache_index()
    
    # Check cache with new filename format
    if file_hash in cache_index:
        cached_filename = cache_index[file_hash]
        cached_file = os.path.join(app.config['UPLOAD_FOLDER'], cached_filename)
        if os.path.exists(cached_file):
            logger.info(f"Cache hit for {output_filename} with hash {file_hash}")
            os.remove(cache_input)  # Clean up input file
            return send_from_directory(app.config['UPLOAD_FOLDER'], cached_filename)
    
    # Apply enhancement if requested
    enhanced_input = os.path.join(app.config['UPLOAD_FOLDER'], f"enhanced_{filename}")
    try:
        if enhance_pdf(cache_input, enhanced_input, request_form):
            os.remove(cache_input)  # Clean up original input after enhancement
            cache_input = enhanced_input
    except Exception as e:
        if os.path.exists(cache_input):
            os.remove(cache_input)  # Clean up on enhancement failure
        if os.path.exists(enhanced_input):
            os.remove(enhanced_input)
        logger.error(f"Enhancement failed: {str(e)}")
        return Response(f"Image enhancement failed: {str(e)}", 400, mimetype='text/plain')

    # Continue with OCR processing
    cmd_args = [arg for arg in shlex.split(request_form["params"])]
    if "--sidecar" in cmd_args:
        if os.path.exists(cache_input):
            os.remove(cache_input)  # Clean up before returning error
        logger.warning("Sidecar option requested but not supported")
        return Response("--sidecar not supported", 501, mimetype='text/plain')

    selected_language = request_form.get("language", "eng")
    if selected_language:
        cmd_args.extend(["-l", selected_language])

    ocrmypdf_args = ["ocrmypdf", *cmd_args, cache_input, down_file]
    logger.debug(f"Executing command: {' '.join(ocrmypdf_args)}")
    
    proc = run(ocrmypdf_args, capture_output=True, encoding="utf-8", check=False)
    
    if proc.returncode == 0:
        cache_index[file_hash] = output_filename  # Store new filename format in cache
        update_cache_index(cache_index)
        logger.info(f"Added file to cache with hash {file_hash}")
        if os.path.exists(cache_input):
            os.remove(cache_input)  # Clean up input file
        return send_from_directory(app.config['UPLOAD_FOLDER'], output_filename)
    
    # Handle errors
    error_msg = proc.stderr
    if "PriorOcrFoundError" in proc.stderr or "page already has text!" in proc.stderr:
        error_msg = ("Document already contains text. Use --force-ocr to force OCR, "
                    "or --skip-text to skip pages with existing text, "
                    "or --redo-ocr to reprocess all pages.")
    
    logger.error(f"OCR process failed with error: {error_msg}")
    if os.path.exists(cache_input):
        os.remove(cache_input)  # Clean up input file
    return Response(error_msg, 400, mimetype='text/plain')



def process_upload_request(request):
    """Handle POST request for file upload and processing."""
    if "file" not in request.files:
        logger.warning("No file part in request")
        return {"error": "No file in POST"}, 400
    
    file = request.files["file"]
    if file.filename == "":
        logger.warning("Empty filename received")
        return {"error": "Empty filename"}, 400
    
    if not allowed_file(file.filename):
        logger.warning(f"Invalid file type attempted: {file.filename}")
        return {"error": "Invalid filename"}, 400
    
    if file and allowed_file(file.filename):
        logger.info(f"Processing valid file: {file.filename}")
        result = do_ocrmypdf(file, request.form)
        
        # Handle error responses from do_ocrmypdf
        if isinstance(result, Response) and result.status_code != 200:
            return {"error": result.get_data(as_text=True)}, 400
            
        # Success case
        return {"filename": secure_filename(file.filename)}, 200
    
    logger.error("Unexpected error in file processing")
    return {"error": "Some other problem"}, 400


@app.route("/", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        logger.info(f"Received POST request from {request.remote_addr}")
        return process_upload_request(request)

    logger.debug("Serving GET request - upload form")
    return render_template('upload.html')


@app.route("/download/<filename>")
def download_file(filename):
    """Handle file downloads from the upload folder."""
    if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        logger.error(f"Requested file not found: {filename}")
        return "File not found", 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == "__main__":
    logger.info("Starting OCRmyPDF webservice")
    app.run(host='0.0.0.0', port=5000)
