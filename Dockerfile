FROM ubuntu:24.04

# Install system dependencies and OCRmyPDF
RUN apt-get update

RUN apt-get install -y \
    python3-pip \
    ocrmypdf

RUN apt-get install -y python3-venv

RUN apt-get install -y tesseract-ocr-chi-sim

RUN apt-get install -y libgl1 libgl1-mesa-dev 

RUN apt-get install -y poppler-utils

RUN rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv

RUN python3 -m venv $VIRTUAL_ENV

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt .

RUN pip3 install -i https://mirrors.sustech.edu.cn/pypi/web/simple/ --no-cache-dir -r requirements.txt

COPY src/ .

# Create uploads directory
RUN mkdir -p uploads

ENV FLASK_APP=webservice.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python3", "webservice.py"]
