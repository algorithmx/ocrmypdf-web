import numpy as np
import cv2
import os
from PIL import Image
from pdf2image import pdfinfo_from_path, convert_from_path
import logging
logger = logging.getLogger(__name__)

class PDFImageEnhancer:
    def __init__(self, config: dict):
        """Initialize the enhancer with configuration."""
        logger.info("Initialize the enhancer with configuration.")
        self.config = config
        self.base_dir = config['base_dir']
        self.upload_dir = config['upload_dir']
        self.temp_dir = os.path.join(self.upload_dir, 'temp_images')
        self.enhanced_dir = os.path.join(self.upload_dir, 'enhanced_images')
        # Create temporary directories
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.enhanced_dir, exist_ok=True)

    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """Apply image preprocessing pipeline based on configuration."""
        logger.info("Preprocess image.")
        # 1. Convert to grayscale if not already
        if len(image.shape) > 2:
            processed = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            processed = image.copy()

        # 2. Denoising
        if self.config['denoising']['enabled']:
            processed = cv2.fastNlMeansDenoising(
                processed, 
                None, 
                h=self.config['denoising']['h'],
                templateWindowSize=self.config['denoising']['template_window_size'],
                searchWindowSize=self.config['denoising']['search_window_size']
            )
        
        # 3. Adaptive histogram equalization
        if self.config['clahe']['enabled']:
            clahe = cv2.createCLAHE(
                clipLimit=self.config['clahe']['clip_limit'],
                tileGridSize=tuple(self.config['clahe']['tile_grid_size'])
            )
            processed = clahe.apply(processed)

        # 4. Contrast enhancement
        if self.config['contrast']['enabled']:
            processed = cv2.convertScaleAbs(
                processed, 
                alpha=self.config['contrast']['alpha'],
                beta=self.config['contrast']['beta']
            )

        # 5. Unsharp masking for text sharpening
        if self.config['sharpening']['enabled']:
            gaussian_blur = cv2.GaussianBlur(
                processed, 
                (0, 0), 
                self.config['sharpening']['sigma']
            )
            processed = cv2.addWeighted(
                processed,
                self.config['sharpening']['amount'],
                gaussian_blur,
                self.config['sharpening']['gaussian_weight'],
                0
            )

        # 6. Binarization
        if self.config['binarization']['enabled']:
            processed = cv2.adaptiveThreshold(
                processed,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                self.config['binarization']['block_size'],
                self.config['binarization']['c']
            )
        
        return processed

    def get_pdf_page_count(self, pdf_path):
        """Get the number of pages in a PDF file using pdf2image."""
        try:
            assert os.path.isfile(pdf_path)
            pdf_info = pdfinfo_from_path(pdf_path)
            return pdf_info['Pages']
        except Exception as e:
            logger.error(f"Error counting PDF pages: {str(e)}")
            raise

    def process_pdf(
        self,
        input_pdf_path: str,
        output_pdf_path: str,
        resolution: int
    ) -> None:
        """Process PDF pages with enhancement."""
        logger.info(f"Start processing PDF {input_pdf_path} with resolution {resolution}.")
        # Convert PDF to images
        page_count = self.get_pdf_page_count(input_pdf_path)
        logger.info(f"Page count: {page_count}")
        # Process and save enhanced images
        enhanced_paths = []
        for i in range(1, page_count+1):
            try:
                pil_image = convert_from_path(input_pdf_path, dpi=resolution, first_page=i, last_page=i)[0]
                opencv_image = np.array(pil_image)
                enhanced_image = self.preprocess_image(opencv_image)
                enhanced_path = os.path.join(self.enhanced_dir, f'page_{i:03d}.png')
                cv2.imwrite(enhanced_path, enhanced_image)
                logger.info(f"Enhanced image saved to {enhanced_path}")
                enhanced_paths.append(enhanced_path)
            except Exception as e:
                logger.error(f"Error processing file {input_pdf_path} page {i}: {str(e)}")

        # Convert to PDF
        logger.info(f"Combine images to PDF.")
        images_to_pdf = [Image.open(path) for path in enhanced_paths]
        images_to_pdf[0].save(
            output_pdf_path, 
            save_all=True, 
            append_images=images_to_pdf[1:]
        )

        # Clean up temporary files
        for path in enhanced_paths:
            os.remove(path)
        
        # Remove temporary directories
        os.rmdir(self.temp_dir)
        os.rmdir(self.enhanced_dir)
